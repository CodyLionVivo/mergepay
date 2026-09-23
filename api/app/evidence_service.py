"""Evidencia on-chain de un bounty, para mostrarla tal como la guarda Stellar.

Solo lectura: se reutiliza `StellarClient.get_bounty`, que simula la llamada
sin firmar ni enviar nada. Tampoco se escribe en la base de datos: lo que diga
el contrato se devuelve sin compararlo ni corregir la task.
"""

from fastapi import HTTPException, status

from app.config import settings
from app.models import Bounty
from app.schemas import OnChainBountyResponse
from app.stellar_client import (
    OnChainBounty,
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)

# El MVP solo despliega en Testnet.
NETWORK = "TESTNET"


def get_stellar_client() -> StellarClient:
    """Construye el cliente solo cuando hay un escrow que leer.

    Separado de los helpers de los otros servicios para poder sustituirlo por
    su cuenta en los tests.
    """
    return StellarClient.from_settings()


def _not_configured() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Stellar evidence service is not configured",
    )


def _to_response(on_chain: OnChainBounty, contract_id: str) -> OnChainBountyResponse:
    return OnChainBountyResponse(
        network=NETWORK,
        contract_id=contract_id,
        client_wallet=on_chain.client,
        developer_wallet=on_chain.developer,
        amount_stroops=on_chain.amount,
        criteria_hash=on_chain.criteria_hash,
        evidence_hash=on_chain.evidence_hash,
        deadline_unix=on_chain.deadline,
        contract_status=on_chain.status,
    )


def read_onchain_bounty(bounty: Bounty) -> OnChainBountyResponse:
    """Lee del contrato el escrow de un bounty ya confirmado en Stellar.

    Los errores de Stellar se traducen a mensajes propios: el original puede
    llevar la URL del RPC o detalles de la simulacion.
    """
    # Sin funding confirmado no hay escrow que leer, y ni siquiera se
    # construye el cliente.
    if bounty.create_tx_hash is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty has not been confirmed on Stellar",
        )

    try:
        stellar = get_stellar_client()
    except StellarConfigurationError as error:
        raise _not_configured() from error

    # from_settings ya lo exige; aqui solo se evita devolver un contract_id
    # vacio si el cliente llego por otro camino.
    contract_id = settings.stellar_contract_id

    if not contract_id:
        raise _not_configured()

    try:
        on_chain = stellar.get_bounty(bounty.id)
    except StellarTransactionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to read bounty evidence from Stellar",
        ) from error

    return _to_response(on_chain, contract_id)
