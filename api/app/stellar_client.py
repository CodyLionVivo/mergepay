"""Cliente Stellar del escrow de MergePay.

Habla con Soroban RPC via stellar-sdk, nunca por la CLI ni por subprocess.
Libera recompensas (la cuenta verifier firma como source de la transaccion, que
es lo que satisface el `verifier.require_auth()` del contrato) y lee el estado
on-chain de un bounty para confirmar su funding.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import requests
from stellar_sdk import Address, Keypair, TransactionBuilder, scval
from stellar_sdk.exceptions import (
    BadRequestError,
    BadResponseError,
    Ed25519SecretSeedInvalidError,
    NotFoundError,
    UnknownRequestError,
)
from stellar_sdk.exceptions import ConnectionError as RpcConnectionError
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus
from stellar_sdk.soroban_server import SorobanServer
from stellar_sdk.xdr import SCVal

from app.config import settings

RELEASE_FUNCTION_NAME = "release_bounty"
GET_BOUNTY_FUNCTION_NAME = "get_bounty"

TRANSACTION_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}")

# Campos del struct `Bounty` del contrato. Un payload con otros campos se
# rechaza: si el contrato cambia, el backend no debe adivinar que significan.
ON_CHAIN_BOUNTY_FIELDS = frozenset(
    {
        "client",
        "developer",
        "amount",
        "criteria_hash",
        "evidence_hash",
        "deadline",
        "status",
    }
)

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


# Fallos de transporte del RPC: no hubo una respuesta RPC valida. El SDK
# envuelve los errores de `requests` (conexion, DNS, timeouts) en
# ConnectionError, y las respuestas HTTP que no son JSON en las otras cuatro.
# `SorobanRpcErrorResponse` hereda de la misma base pero queda fuera a
# proposito: es una respuesta RPC bien formada, no un fallo de transporte.
RPC_TRANSPORT_ERRORS = (
    RpcConnectionError,
    BadRequestError,
    BadResponseError,
    NotFoundError,
    UnknownRequestError,
    requests.RequestException,
)


@contextmanager
def _rpc_transport_errors() -> Iterator[None]:
    """Convierte un fallo de transporte del RPC en StellarTransactionError.

    Se corta la cadena: los mensajes de `requests` incluyen la URL del RPC, y
    con un proveedor de pago esa URL puede llevar una API key.
    """
    try:
        yield
    except RPC_TRANSPORT_ERRORS as error:
        raise StellarTransactionError(
            f"Stellar RPC request failed: {type(error).__name__}"
        ) from None


@dataclass(frozen=True)
class OnChainBounty:
    """El struct `Bounty` del contrato, ya normalizado a tipos Python.

    Uso interno: nunca se serializa hacia el cliente HTTP.
    """

    client: str
    developer: str | None
    amount: int
    criteria_hash: str
    evidence_hash: str | None
    deadline: int
    status: str


def _unexpected_payload() -> StellarTransactionError:
    return StellarTransactionError("Unexpected get_bounty payload")


def _as_address(value: Any) -> str:
    if not isinstance(value, Address):
        raise _unexpected_payload()

    return value.address


def _as_hash_hex(value: Any) -> str:
    if not isinstance(value, bytes) or len(value) != 32:
        raise _unexpected_payload()

    return value.hex()


def _as_integer(value: Any) -> int:
    # bool hereda de int, pero un bool aqui es un payload roto.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _unexpected_payload()

    return value


def _as_enum_variant(value: Any) -> str:
    """Un enum unitario de Soroban llega como vector de un solo simbolo."""
    if not (isinstance(value, list) and len(value) == 1 and isinstance(value[0], str)):
        raise _unexpected_payload()

    return value[0]


def _to_on_chain_bounty(native: Any) -> OnChainBounty:
    if not isinstance(native, dict) or set(native) != ON_CHAIN_BOUNTY_FIELDS:
        raise _unexpected_payload()

    developer = native["developer"]
    evidence_hash = native["evidence_hash"]

    return OnChainBounty(
        client=_as_address(native["client"]),
        developer=None if developer is None else _as_address(developer),
        amount=_as_integer(native["amount"]),
        criteria_hash=_as_hash_hex(native["criteria_hash"]),
        evidence_hash=None if evidence_hash is None else _as_hash_hex(evidence_hash),
        deadline=_as_integer(native["deadline"]),
        status=_as_enum_variant(native["status"]),
    )


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

        with _rpc_transport_errors():
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

        with _rpc_transport_errors():
            prepared_transaction = self._server.prepare_transaction(transaction)
        prepared_transaction.sign(self._verifier_keypair)

        transaction_hash = prepared_transaction.hash_hex()

        with _rpc_transport_errors():
            send_response = self._server.send_transaction(prepared_transaction)

        if send_response.status not in ACCEPTED_SEND_STATUSES:
            raise StellarTransactionError(
                f"Stellar rejected the release transaction with status "
                f"{send_response.status.value}"
            )

        with _rpc_transport_errors():
            get_response = self._server.poll_transaction(transaction_hash)

        if get_response.status is not GetTransactionStatus.SUCCESS:
            raise StellarTransactionError(
                f"Release transaction {transaction_hash} finished with status "
                f"{get_response.status.value}"
            )

        return transaction_hash

    def get_bounty(self, bounty_id: int) -> OnChainBounty:
        """Lee un bounty del contrato con una simulacion, sin enviar nada.

        La transaccion solo se construye para simularla: nunca se firma ni se
        envia, asi que leer no cuesta fees ni cambia estado.
        """
        if bounty_id <= 0:
            raise StellarTransactionError("bounty_id must be a positive integer")

        with _rpc_transport_errors():
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
                function_name=GET_BOUNTY_FUNCTION_NAME,
                parameters=[scval.to_uint64(bounty_id)],
            )
            .build()
        )

        with _rpc_transport_errors():
            simulation = self._server.simulate_transaction(transaction)

        # Un bounty que no existe llega aqui: el contrato devuelve
        # Error::BountyNotFound y la simulacion lo reporta como error.
        if simulation.error:
            raise StellarTransactionError(
                f"get_bounty simulation failed: {simulation.error}"
            )

        if not simulation.results or simulation.results[0].xdr is None:
            raise StellarTransactionError("get_bounty simulation returned no value")

        try:
            native = scval.to_native(SCVal.from_xdr(simulation.results[0].xdr))
        except (ValueError, EOFError) as error:
            raise _unexpected_payload() from error

        return _to_on_chain_bounty(native)

    def assert_transaction_success(self, transaction_hash: str) -> None:
        """Comprueba que una transaccion ya terminada acabo en SUCCESS.

        Sin polling: quien llama ya espero la confirmacion. Una transaccion que
        la red no conoce (NOT_FOUND) cuenta como fallida.
        """
        if not TRANSACTION_HASH_PATTERN.fullmatch(transaction_hash):
            raise StellarTransactionError(
                "transaction_hash must be 64 hex characters"
            )

        with _rpc_transport_errors():
            response = self._server.get_transaction(transaction_hash.lower())

        if response.status is not GetTransactionStatus.SUCCESS:
            raise StellarTransactionError(
                f"Transaction {transaction_hash.lower()} finished with status "
                f"{response.status.value}"
            )
