"""Confirmacion del funding on-chain de un bounty.

El navegador crea el escrow en Stellar y solo nos pasa el hash de la
transaccion. Nada de lo que envie el navegador se da por bueno: la wallet del
cliente, el monto y los terminos se leen del propio contrato, y el `base_sha`
se resuelve contra GitHub.
"""

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from stellar_sdk import StrKey

from app.github_client import BranchNotFoundError, GitHubClient, GitHubError
from app.models import Bounty, BountyStatus
from app.stellar_client import (
    OnChainBounty,
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)

ON_CHAIN_OPEN_STATUS = "Open"


def get_stellar_client() -> StellarClient:
    """Construye el cliente solo cuando hay un funding que comprobar.

    Separado del helper de verification_service para poder sustituirlo por
    su cuenta en los tests.
    """
    return StellarClient.from_settings()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def _matches_task(on_chain: OnChainBounty, bounty: Bounty) -> bool:
    """El escrow on-chain tiene que ser exactamente el que describe la task."""
    return (
        bounty.criteria_hash is not None
        and on_chain.amount == bounty.amount_stroops
        and on_chain.criteria_hash.lower() == bounty.criteria_hash.lower()
        and on_chain.deadline == bounty.deadline_unix
        and on_chain.developer is None
        and on_chain.status == ON_CHAIN_OPEN_STATUS
        and on_chain.evidence_hash is None
        # Una cuenta G..., no un contrato C...: el cliente tiene que ser alguien
        # que pueda recibir un refund.
        and StrKey.is_valid_ed25519_public_key(on_chain.client)
    )


def confirm_funding(
    db: Session,
    bounty: Bounty,
    transaction_hash: str,
    github: GitHubClient,
) -> Bounty:
    """Pasa un bounty DRAFT a OPEN_FUNDED tras comprobar su escrow on-chain.

    Todo se verifica antes de escribir, y la escritura es un unico commit: un
    fallo en cualquier paso deja la base de datos tal como estaba.
    """
    normalized_hash = transaction_hash.lower()

    # Idempotencia: reintentar con el mismo hash devuelve lo ya confirmado sin
    # volver a consultar Stellar. Es lo que permite al navegador recuperarse si
    # perdio la respuesta del primer intento.
    if bounty.status == BountyStatus.OPEN_FUNDED:
        if bounty.create_tx_hash == normalized_hash:
            return bounty

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is already funded",
        )

    if bounty.status != BountyStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty cannot be funded in its current state",
        )

    if bounty.criteria_hash is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is not ready for funding",
        )

    try:
        stellar = get_stellar_client()
    except StellarConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stellar funding verification is not configured",
        ) from error

    try:
        stellar.assert_transaction_success(normalized_hash)
        on_chain = stellar.get_bounty(bounty.id)
    except StellarTransactionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to verify funding on Stellar",
        ) from error

    if not _matches_task(on_chain, bounty):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="On-chain bounty does not match MergePay task",
        )

    try:
        base_sha = github.get_branch_head_sha(
            bounty.repo_owner, bounty.repo_name, bounty.base_branch
        )
    except BranchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Base branch not found on GitHub",
        ) from error
    except GitHubError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub service unavailable",
        ) from error

    bounty.client_wallet = on_chain.client
    bounty.base_sha = base_sha
    bounty.create_tx_hash = normalized_hash
    bounty.status = BountyStatus.OPEN_FUNDED

    _commit(db)
    db.refresh(bounty)

    return bounty
