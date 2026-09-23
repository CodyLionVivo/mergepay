"""Confirmacion de la aceptacion on-chain de un bounty por un developer.

El developer acepta desde su wallet con `accept_bounty` y nos pasa el hash de
la transaccion, su usuario de GitHub y una firma SEP-53 que vincula ambos a su
wallet. La wallet del developer sale del contrato, y la firma se verifica contra
ella: el hash de la aceptacion es publico, asi que sin firma cualquiera podria
adelantarse y fijar otro GitHub. Que ese usuario de GitHub pertenezca de verdad
al developer sigue sin comprobarse; el verifier lo exigira como autor del PR.
"""

import base64
import hashlib

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from stellar_sdk import Keypair, StrKey
from stellar_sdk.exceptions import BadSignatureError

from app.config import settings
from app.models import Bounty, BountyStatus
from app.stellar_client import (
    OnChainBounty,
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)

ON_CHAIN_ASSIGNED_STATUS = "Assigned"

ASSIGNMENT_MESSAGE_HEADER = "MergePay assignment v1"

# Prefijo de SEP-53: lo que Freighter antepone al mensaje antes de firmar.
SEP53_PREFIX = b"Stellar Signed Message:\n"


def build_assignment_message(
    *,
    bounty_id: int,
    transaction_hash: str,
    developer_wallet: str,
    developer_github: str,
    contract_id: str,
) -> str:
    """Mensaje que firma el developer. Byte a byte igual que en el frontend.

    Una linea por campo y sin salto de linea final.
    """
    return "\n".join(
        [
            ASSIGNMENT_MESSAGE_HEADER,
            f"bounty_id={bounty_id}",
            f"transaction_hash={transaction_hash.lower()}",
            f"developer_wallet={developer_wallet}",
            f"developer_github={developer_github.strip()}",
            f"contract_id={contract_id}",
        ]
    )


def _sep53_digest(message: str) -> bytes:
    return hashlib.sha256(SEP53_PREFIX + message.encode("utf-8")).digest()


def _signature_is_valid(public_key: str, message: str, wallet_signature: str) -> bool:
    """Verifica una firma SEP-53 de `message` hecha por `public_key`."""
    try:
        signature = base64.b64decode(wallet_signature, validate=True)
    except ValueError:
        # El schema ya lo valido; esto solo cubre llamadas directas.
        return False

    try:
        Keypair.from_public_key(public_key).verify(_sep53_digest(message), signature)
    except BadSignatureError:
        return False

    return True


def get_stellar_client() -> StellarClient:
    """Construye el cliente solo cuando hay una aceptacion que comprobar.

    Separado de los helpers de funding y verification para poder sustituirlo
    por su cuenta en los tests.
    """
    return StellarClient.from_settings()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def _matches_assignment(on_chain: OnChainBounty, bounty: Bounty) -> bool:
    """El escrow on-chain tiene que ser el de la task, ya con developer."""
    return (
        bounty.criteria_hash is not None
        and on_chain.client == bounty.client_wallet
        and on_chain.developer is not None
        and StrKey.is_valid_ed25519_public_key(on_chain.developer)
        and on_chain.amount == bounty.amount_stroops
        and on_chain.criteria_hash.lower() == bounty.criteria_hash.lower()
        and on_chain.deadline == bounty.deadline_unix
        and on_chain.status == ON_CHAIN_ASSIGNED_STATUS
        and on_chain.evidence_hash is None
    )


def confirm_assignment(
    db: Session,
    bounty: Bounty,
    transaction_hash: str,
    developer_github: str,
    wallet_signature: str,
    authenticated_wallet: str,
) -> Bounty:
    """Pasa un bounty OPEN_FUNDED a ASSIGNED tras comprobar el contrato.

    Todo se verifica antes de escribir, y la escritura es un unico commit: un
    fallo en cualquier paso deja la base de datos tal como estaba.
    """
    normalized_hash = transaction_hash.lower()

    # Idempotencia: el mismo developer reintentando recibe lo ya confirmado
    # sin volver a consultar Stellar. El hash de la aceptacion no se guarda,
    # asi que la comparacion es por el usuario de GitHub.
    if bounty.status == BountyStatus.ASSIGNED:
        # Idempotente solo para el developer de la task: otra sesion no puede
        # usar este camino para leer nada ni para reclamarla.
        if bounty.developer_wallet != authenticated_wallet:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Developer wallet required for this task",
            )

        if (
            bounty.developer_github is not None
            and bounty.developer_github.casefold() == developer_github.casefold()
        ):
            return bounty

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is already assigned",
        )

    if bounty.status == BountyStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is not funded",
        )

    if bounty.status != BountyStatus.OPEN_FUNDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty cannot be assigned in its current state",
        )

    # El client no puede aceptar su propia task. Se comprueba antes de tocar
    # Stellar: ni siquiera se construye el cliente.
    if bounty.client_wallet == authenticated_wallet:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client wallet cannot accept its own task",
        )

    if (
        bounty.client_wallet is None
        or bounty.criteria_hash is None
        or bounty.base_sha is None
        or bounty.create_tx_hash is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is not ready for assignment",
        )

    try:
        stellar = get_stellar_client()
    except StellarConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stellar assignment verification is not configured",
        ) from error

    # El contrato del mensaje firmado es el que MergePay tiene configurado.
    # Con el cliente construido desde settings siempre existe; se comprueba
    # igual para no firmar nunca contra "None".
    contract_id = settings.stellar_contract_id

    if not contract_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stellar assignment verification is not configured",
        )

    try:
        stellar.assert_transaction_success(normalized_hash)
        on_chain = stellar.get_bounty(bounty.id)
    except StellarTransactionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to verify assignment on Stellar",
        ) from error

    if not _matches_assignment(on_chain, bounty):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="On-chain assignment does not match MergePay task",
        )

    # Quien acepto on-chain tiene que ser la misma wallet que abrio la sesion.
    if on_chain.developer != authenticated_wallet:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated wallet does not match assigned developer",
        )

    # Ademas de la sesion, la firma SEP-53 ata GitHub a esa wallet: sin ella,
    # el hash publico de la aceptacion bastaria para fijar otro usuario.
    message = build_assignment_message(
        bounty_id=bounty.id,
        transaction_hash=normalized_hash,
        developer_wallet=on_chain.developer,
        developer_github=developer_github,
        contract_id=contract_id,
    )

    if not _signature_is_valid(on_chain.developer, message, wallet_signature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Developer wallet signature is invalid",
        )

    # Solo lo que cambia con la aceptacion. client_wallet, base_sha,
    # criteria_hash y los hashes de transaccion quedan intactos.
    bounty.developer_wallet = on_chain.developer
    bounty.developer_github = developer_github
    bounty.status = BountyStatus.ASSIGNED

    _commit(db)
    db.refresh(bounty)

    return bounty
