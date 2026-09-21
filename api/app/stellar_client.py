"""Cliente Stellar para liberar el escrow de un bounty.

Habla con Soroban RPC via stellar-sdk, nunca por la CLI ni por subprocess.
La cuenta verifier firma como source de la transaccion, que es lo que satisface
el `verifier.require_auth()` del contrato.
"""

from stellar_sdk import Keypair, TransactionBuilder, scval
from stellar_sdk.exceptions import Ed25519SecretSeedInvalidError
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus
from stellar_sdk.soroban_server import SorobanServer

from app.config import settings

RELEASE_FUNCTION_NAME = "release_bounty"

BASE_FEE = 100
TRANSACTION_TIMEOUT_SECONDS = 30

EVIDENCE_HASH_BYTES = 32
EVIDENCE_HASH_HEX_LENGTH = EVIDENCE_HASH_BYTES * 2

# Estados de envio desde los que todavia tiene sentido hacer polling.
ACCEPTED_SEND_STATUSES = (
    SendTransactionStatus.PENDING,
    SendTransactionStatus.DUPLICATE,
)


class StellarConfigurationError(Exception):
    """Falta configuracion de Stellar o el secreto del verifier no es valido."""


class StellarTransactionError(Exception):
    """La red rechazo la transaccion o no termino en SUCCESS."""


def _decode_evidence_hash(evidence_hash: str) -> bytes:
    """Convierte el hash hex en los 32 bytes que espera el contrato."""
    error = ValueError(
        "evidence_hash must be 64 hex characters representing 32 bytes"
    )

    if len(evidence_hash) != EVIDENCE_HASH_HEX_LENGTH:
        raise error

    try:
        evidence_bytes = bytes.fromhex(evidence_hash)
    except ValueError:
        raise error from None

    # bytes.fromhex ignora espacios, asi que la longitud se vuelve a comprobar.
    if len(evidence_bytes) != EVIDENCE_HASH_BYTES:
        raise error

    return evidence_bytes


class StellarClient:
    """Invoca `release_bounty` en el contrato de escrow."""

    def __init__(
        self,
        rpc_url: str,
        network_passphrase: str,
        contract_id: str,
        verifier_secret: str,
    ) -> None:
        try:
            self._verifier_keypair = Keypair.from_secret(verifier_secret)
        except Ed25519SecretSeedInvalidError:
            # El mensaje original lleva el secreto dentro, asi que se descarta
            # la excepcion entera en vez de encadenarla.
            raise StellarConfigurationError(
                "Invalid Stellar verifier secret"
            ) from None

        self._network_passphrase = network_passphrase
        self._contract_id = contract_id
        self._server = SorobanServer(rpc_url)

    @classmethod
    def from_settings(cls) -> "StellarClient":
        if not settings.stellar_contract_id:
            raise StellarConfigurationError("stellar_contract_id is not configured")

        if not settings.stellar_verifier_secret:
            raise StellarConfigurationError(
                "stellar_verifier_secret is not configured"
            )

        return cls(
            rpc_url=settings.stellar_rpc_url,
            network_passphrase=settings.stellar_network_passphrase,
            contract_id=settings.stellar_contract_id,
            verifier_secret=settings.stellar_verifier_secret,
        )

    @property
    def verifier_public_key(self) -> str:
        return self._verifier_keypair.public_key

    def release_bounty(self, bounty_id: int, evidence_hash: str) -> str:
        """Libera la recompensa y devuelve el hash hex de la transaccion."""
        if bounty_id <= 0:
            raise ValueError("bounty_id must be a positive integer")

        evidence_bytes = _decode_evidence_hash(evidence_hash)

        source_account = self._server.load_account(self.verifier_public_key)

        transaction = (
            TransactionBuilder(
                source_account=source_account,
                network_passphrase=self._network_passphrase,
                base_fee=BASE_FEE,
            )
            .set_timeout(TRANSACTION_TIMEOUT_SECONDS)
            .append_invoke_contract_function_op(
                contract_id=self._contract_id,
                function_name=RELEASE_FUNCTION_NAME,
                parameters=[
                    scval.to_uint64(bounty_id),
                    scval.to_bytes(evidence_bytes),
                ],
            )
            .build()
        )

        prepared_transaction = self._server.prepare_transaction(transaction)
        prepared_transaction.sign(self._verifier_keypair)

        transaction_hash = prepared_transaction.hash_hex()

        send_response = self._server.send_transaction(prepared_transaction)

        if send_response.status not in ACCEPTED_SEND_STATUSES:
            raise StellarTransactionError(
                f"Stellar rejected the release transaction with status "
                f"{send_response.status.value}"
            )

        get_response = self._server.poll_transaction(transaction_hash)

        if get_response.status is not GetTransactionStatus.SUCCESS:
            raise StellarTransactionError(
                f"Release transaction {transaction_hash} finished with status "
                f"{get_response.status.value}"
            )

        return transaction_hash
