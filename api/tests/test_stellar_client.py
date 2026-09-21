from dataclasses import dataclass
from typing import Any

import pytest
from stellar_sdk import Account, Address, Keypair, TransactionEnvelope, scval
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus
from stellar_sdk.strkey import StrKey

from app import stellar_client as stellar_module
from app.config import settings
from app.stellar_client import (
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)

RPC_URL = "https://soroban-testnet.example.invalid"
NETWORK_PASSPHRASE = "Test SDF Network ; September 2015"
CONTRACT_ID = StrKey.encode_contract(b"\x11" * 32)

# Keypair desechable, generada en memoria. Nunca sale de estos tests.
VERIFIER_KEYPAIR = Keypair.random()
VERIFIER_SECRET = VERIFIER_KEYPAIR.secret

EVIDENCE_HASH = "ab" * 32
BOUNTY_ID = 7


@dataclass
class FakeSendResponse:
    status: SendTransactionStatus


@dataclass
class FakeGetResponse:
    status: GetTransactionStatus


class FakeSorobanServer:
    """Frontera RPC sustituida: registra lo enviado y no toca la red."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

        self.loaded_accounts: list[str] = []
        self.prepared: list[TransactionEnvelope] = []
        self.sent: list[TransactionEnvelope] = []
        self.polled: list[str] = []

        self.send_status = SendTransactionStatus.PENDING
        self.poll_status = GetTransactionStatus.SUCCESS

    def load_account(self, account_id: str) -> Account:
        self.loaded_accounts.append(account_id)

        return Account(account_id, 1)

    def prepare_transaction(
        self, transaction_envelope: TransactionEnvelope
    ) -> TransactionEnvelope:
        self.prepared.append(transaction_envelope)

        return transaction_envelope

    def send_transaction(
        self, transaction_envelope: TransactionEnvelope
    ) -> FakeSendResponse:
        self.sent.append(transaction_envelope)

        return FakeSendResponse(self.send_status)

    def poll_transaction(
        self, transaction_hash: str, **kwargs: Any
    ) -> FakeGetResponse:
        self.polled.append(transaction_hash)

        return FakeGetResponse(self.poll_status)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeSorobanServer:
    fake = FakeSorobanServer(RPC_URL)

    monkeypatch.setattr(stellar_module, "SorobanServer", lambda server_url: fake)

    return fake


@pytest.fixture
def stellar(server: FakeSorobanServer) -> StellarClient:
    return StellarClient(
        rpc_url=RPC_URL,
        network_passphrase=NETWORK_PASSPHRASE,
        contract_id=CONTRACT_ID,
        verifier_secret=VERIFIER_SECRET,
    )


def invoked_operation(envelope: TransactionEnvelope) -> Any:
    operations = envelope.transaction.operations

    assert len(operations) == 1

    return operations[0]


# ─────────────────────────────────────────
# 13 a 15. Configuracion.
# ─────────────────────────────────────────


def test_missing_contract_id_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "stellar_contract_id", None)
    monkeypatch.setattr(settings, "stellar_verifier_secret", VERIFIER_SECRET)

    with pytest.raises(StellarConfigurationError) as raised:
        StellarClient.from_settings()

    assert "stellar_contract_id" in str(raised.value)


def test_missing_verifier_secret_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "stellar_contract_id", CONTRACT_ID)
    monkeypatch.setattr(settings, "stellar_verifier_secret", None)

    with pytest.raises(StellarConfigurationError) as raised:
        StellarClient.from_settings()

    assert "stellar_verifier_secret" in str(raised.value)


def test_from_settings_builds_the_client(
    monkeypatch: pytest.MonkeyPatch, server: FakeSorobanServer
) -> None:
    monkeypatch.setattr(settings, "stellar_contract_id", CONTRACT_ID)
    monkeypatch.setattr(settings, "stellar_verifier_secret", VERIFIER_SECRET)

    client = StellarClient.from_settings()

    assert client.verifier_public_key == VERIFIER_KEYPAIR.public_key


def test_invalid_secret_does_not_leak_the_secret(
    server: FakeSorobanServer,
) -> None:
    leaked_secret = "SNOTAREALSECRETSEEDVALUE0000000000000000000000000000000"

    with pytest.raises(StellarConfigurationError) as raised:
        StellarClient(
            rpc_url=RPC_URL,
            network_passphrase=NETWORK_PASSPHRASE,
            contract_id=CONTRACT_ID,
            verifier_secret=leaked_secret,
        )

    # El SDK mete el secreto en su propio mensaje, asi que la cadena se corta.
    assert leaked_secret not in str(raised.value)
    assert raised.value.__cause__ is None


# ─────────────────────────────────────────
# 16 a 19. Validacion previa a cualquier RPC.
# ─────────────────────────────────────────


@pytest.mark.parametrize("bounty_id", [0, -1, -100])
def test_invalid_bounty_id_raises_before_rpc(
    stellar: StellarClient, server: FakeSorobanServer, bounty_id: int
) -> None:
    with pytest.raises(ValueError):
        stellar.release_bounty(bounty_id, EVIDENCE_HASH)

    assert server.loaded_accounts == []
    assert server.sent == []


@pytest.mark.parametrize(
    "evidence_hash",
    [
        "",
        "ab" * 31,
        "ab" * 33,
        "zz" * 32,
        "not hex at all",
        " " + "ab" * 31 + "a",
    ],
)
def test_invalid_evidence_hash_raises_before_rpc(
    stellar: StellarClient, server: FakeSorobanServer, evidence_hash: str
) -> None:
    with pytest.raises(ValueError):
        stellar.release_bounty(BOUNTY_ID, evidence_hash)

    assert server.loaded_accounts == []
    assert server.sent == []


# ─────────────────────────────────────────
# 20 a 24. Transaccion construida.
# ─────────────────────────────────────────


def test_release_loads_the_verifier_account(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    assert server.loaded_accounts == [VERIFIER_KEYPAIR.public_key]


def test_release_invokes_the_release_bounty_function(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    operation = invoked_operation(server.sent[0])
    invoke = operation.host_function.invoke_contract

    assert invoke.function_name.sc_symbol.decode() == "release_bounty"


def test_first_parameter_is_the_bounty_id_as_uint64(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    args = invoked_operation(server.sent[0]).host_function.invoke_contract.args

    assert len(args) == 2
    assert scval.from_uint64(args[0]) == BOUNTY_ID


def test_second_parameter_is_the_32_byte_evidence_hash(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    args = invoked_operation(server.sent[0]).host_function.invoke_contract.args

    evidence_bytes = scval.from_bytes(args[1])

    assert len(evidence_bytes) == 32
    assert evidence_bytes == bytes.fromhex(EVIDENCE_HASH)


def test_transaction_is_signed_by_the_verifier(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    envelope = server.sent[0]

    assert len(envelope.signatures) == 1

    signature = envelope.signatures[0]

    assert signature.signature_hint == VERIFIER_KEYPAIR.signature_hint()

    # verify() no devuelve nada; lanza si la firma no es del verifier.
    Keypair.from_public_key(VERIFIER_KEYPAIR.public_key).verify(
        envelope.hash(), signature.signature
    )


def test_transaction_uses_the_configured_network_and_contract(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    envelope = server.sent[0]

    assert envelope.network_passphrase == NETWORK_PASSPHRASE

    address = invoked_operation(envelope).host_function.invoke_contract.contract_address

    assert Address.from_xdr_sc_address(address).address == CONTRACT_ID


# ─────────────────────────────────────────
# 25 a 30. Estados de envio y de polling.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "send_status",
    [SendTransactionStatus.PENDING, SendTransactionStatus.DUPLICATE],
)
def test_accepted_send_status_with_successful_poll_returns_the_hash(
    stellar: StellarClient,
    server: FakeSorobanServer,
    send_status: SendTransactionStatus,
) -> None:
    server.send_status = send_status

    transaction_hash = stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    assert transaction_hash == server.sent[0].hash_hex()
    assert len(transaction_hash) == 64
    assert server.polled == [transaction_hash]


@pytest.mark.parametrize(
    "send_status",
    [SendTransactionStatus.ERROR, SendTransactionStatus.TRY_AGAIN_LATER],
)
def test_rejected_send_status_raises_transaction_error(
    stellar: StellarClient,
    server: FakeSorobanServer,
    send_status: SendTransactionStatus,
) -> None:
    server.send_status = send_status

    with pytest.raises(StellarTransactionError) as raised:
        stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    assert send_status.value in str(raised.value)

    # No se llega al polling.
    assert server.polled == []


@pytest.mark.parametrize(
    "poll_status",
    [GetTransactionStatus.FAILED, GetTransactionStatus.NOT_FOUND],
)
def test_non_success_poll_status_raises_transaction_error(
    stellar: StellarClient,
    server: FakeSorobanServer,
    poll_status: GetTransactionStatus,
) -> None:
    server.poll_status = poll_status

    with pytest.raises(StellarTransactionError) as raised:
        stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    assert poll_status.value in str(raised.value)


# ─────────────────────────────────────────
# 31. El secreto no se filtra por ningun camino de error.
# ─────────────────────────────────────────


def test_no_error_path_leaks_the_verifier_secret(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    raised_messages: list[str] = []

    def record(call) -> None:
        try:
            call()
        except (ValueError, StellarTransactionError) as error:
            raised_messages.append(repr(error))
        else:
            raise AssertionError("se esperaba una excepcion")

    record(lambda: stellar.release_bounty(0, EVIDENCE_HASH))
    record(lambda: stellar.release_bounty(BOUNTY_ID, "nope"))

    server.send_status = SendTransactionStatus.ERROR
    record(lambda: stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH))

    server.send_status = SendTransactionStatus.PENDING
    server.poll_status = GetTransactionStatus.FAILED
    record(lambda: stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH))

    assert len(raised_messages) == 4

    for message in raised_messages:
        assert VERIFIER_SECRET not in message


def test_successful_release_never_returns_sdk_objects(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    result = stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)

    assert isinstance(result, str)
    assert VERIFIER_SECRET not in result
