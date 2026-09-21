from dataclasses import dataclass
from typing import Any

import pytest
import requests
from stellar_sdk import Account, Address, Keypair, TransactionEnvelope, scval
from stellar_sdk.exceptions import BadResponseError, SorobanRpcErrorResponse
from stellar_sdk.exceptions import Response as RpcResponse
from stellar_sdk.exceptions import ConnectionError as RpcConnectionError
from stellar_sdk.soroban_rpc import GetTransactionStatus, SendTransactionStatus
from stellar_sdk.strkey import StrKey
from stellar_sdk.xdr import SCVal

from app import stellar_client as stellar_module
from app.config import settings
from app.stellar_client import (
    OnChainBounty,
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


@dataclass
class FakeHostFunctionResult:
    xdr: str | None


@dataclass
class FakeSimulateResponse:
    error: str | None
    results: list[FakeHostFunctionResult] | None


class FakeSorobanServer:
    """Frontera RPC sustituida: registra lo enviado y no toca la red."""

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url

        self.loaded_accounts: list[str] = []
        self.prepared: list[TransactionEnvelope] = []
        self.sent: list[TransactionEnvelope] = []
        self.polled: list[str] = []
        self.simulated: list[TransactionEnvelope] = []
        self.looked_up: list[str] = []

        self.send_status = SendTransactionStatus.PENDING
        self.poll_status = GetTransactionStatus.SUCCESS

        # Lo que devuelve una simulacion de get_bounty.
        self.simulation_error: str | None = None
        self.simulation_results: list[FakeHostFunctionResult] | None = None

        # Lo que devuelve get_transaction.
        self.transaction_status = GetTransactionStatus.SUCCESS

        # Fallo de transporte: los metodos de `fail_on` lanzan `failure`.
        self.fail_on: set[str] = set()
        self.failure: Exception = RpcConnectionError("connection failed")

    def _maybe_fail(self, method: str) -> None:
        if method in self.fail_on:
            raise self.failure

    def simulate_transaction(
        self, transaction_envelope: TransactionEnvelope, **kwargs: Any
    ) -> FakeSimulateResponse:
        self._maybe_fail("simulate_transaction")

        self.simulated.append(transaction_envelope)

        return FakeSimulateResponse(self.simulation_error, self.simulation_results)

    def get_transaction(self, transaction_hash: str) -> FakeGetResponse:
        self._maybe_fail("get_transaction")

        self.looked_up.append(transaction_hash)

        return FakeGetResponse(self.transaction_status)

    def returns(self, value: SCVal) -> None:
        """Hace que la proxima simulacion devuelva este SCVal."""
        self.simulation_results = [FakeHostFunctionResult(value.to_xdr())]

    def load_account(self, account_id: str) -> Account:
        self._maybe_fail("load_account")

        self.loaded_accounts.append(account_id)

        return Account(account_id, 1)

    def prepare_transaction(
        self, transaction_envelope: TransactionEnvelope
    ) -> TransactionEnvelope:
        self._maybe_fail("prepare_transaction")

        self.prepared.append(transaction_envelope)

        return transaction_envelope

    def send_transaction(
        self, transaction_envelope: TransactionEnvelope
    ) -> FakeSendResponse:
        self._maybe_fail("send_transaction")

        self.sent.append(transaction_envelope)

        return FakeSendResponse(self.send_status)

    def poll_transaction(
        self, transaction_hash: str, **kwargs: Any
    ) -> FakeGetResponse:
        self._maybe_fail("poll_transaction")

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


# ─────────────────────────────────────────
# get_bounty: lectura on-chain por simulacion.
# ─────────────────────────────────────────

CLIENT_ADDRESS = Keypair.random().public_key
DEVELOPER_ADDRESS = Keypair.random().public_key
CRITERIA_HASH = "c1" * 32
ON_CHAIN_DEADLINE = 1_767_225_600


def bounty_scval(**overrides: SCVal) -> SCVal:
    """El struct `Bounty` tal como lo codifica el contrato: un mapa de simbolos."""
    fields: dict[str, SCVal] = {
        "amount": scval.to_int128(100_000_000),
        "client": scval.to_address(CLIENT_ADDRESS),
        "criteria_hash": scval.to_bytes(bytes.fromhex(CRITERIA_HASH)),
        "deadline": scval.to_uint64(ON_CHAIN_DEADLINE),
        "developer": scval.to_void(),
        "evidence_hash": scval.to_void(),
        "status": scval.to_vec([scval.to_symbol("Open")]),
    }

    fields.update(overrides)

    return scval.to_map({scval.to_symbol(key): value for key, value in fields.items()})


def test_get_bounty_decodes_an_open_bounty(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    server.returns(bounty_scval())

    bounty = stellar.get_bounty(BOUNTY_ID)

    assert bounty == OnChainBounty(
        client=CLIENT_ADDRESS,
        developer=None,
        amount=100_000_000,
        criteria_hash=CRITERIA_HASH,
        evidence_hash=None,
        deadline=ON_CHAIN_DEADLINE,
        status="Open",
    )


def test_get_bounty_decodes_optional_fields_when_present(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    server.returns(
        bounty_scval(
            developer=scval.to_address(DEVELOPER_ADDRESS),
            evidence_hash=scval.to_bytes(bytes.fromhex("EE" * 32)),
            status=scval.to_vec([scval.to_symbol("Assigned")]),
        )
    )

    bounty = stellar.get_bounty(BOUNTY_ID)

    assert bounty.developer == DEVELOPER_ADDRESS
    # Los bytes se normalizan a hex en minusculas.
    assert bounty.evidence_hash == "ee" * 32
    assert bounty.status == "Assigned"


def test_get_bounty_only_simulates(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    server.returns(bounty_scval())

    stellar.get_bounty(BOUNTY_ID)

    assert len(server.simulated) == 1

    # Solo lectura: nada se prepara, se firma ni se envia.
    assert server.prepared == []
    assert server.sent == []
    assert server.simulated[0].signatures == []


def test_get_bounty_invokes_get_bounty_with_the_u64_id(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    server.returns(bounty_scval())

    stellar.get_bounty(BOUNTY_ID)

    invoke = invoked_operation(server.simulated[0]).host_function.invoke_contract

    assert invoke.function_name.sc_symbol.decode() == "get_bounty"
    assert len(invoke.args) == 1
    assert scval.from_uint64(invoke.args[0]) == BOUNTY_ID


@pytest.mark.parametrize("bounty_id", [0, -1])
def test_get_bounty_rejects_invalid_ids_before_rpc(
    stellar: StellarClient, server: FakeSorobanServer, bounty_id: int
) -> None:
    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(bounty_id)

    assert server.loaded_accounts == []
    assert server.simulated == []


def test_get_bounty_raises_on_simulation_error(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    server.simulation_error = "HostError: Error(Contract, #3)"

    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(BOUNTY_ID)


@pytest.mark.parametrize(
    "results",
    [None, [], [FakeHostFunctionResult(None)]],
    ids=["none", "empty", "no-xdr"],
)
def test_get_bounty_raises_without_a_return_value(
    stellar: StellarClient,
    server: FakeSorobanServer,
    results: list[FakeHostFunctionResult] | None,
) -> None:
    server.simulation_results = results

    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(BOUNTY_ID)


def test_get_bounty_raises_on_corrupt_xdr(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    server.simulation_results = [FakeHostFunctionResult("%%%no-es-xdr%%%")]

    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(BOUNTY_ID)


@pytest.mark.parametrize(
    "payload",
    [
        scval.to_uint64(1),
        scval.to_vec([scval.to_symbol("Open")]),
        bounty_scval(amount=scval.to_bool(True)),
        bounty_scval(amount=scval.to_string("100")),
        bounty_scval(client=scval.to_string(CLIENT_ADDRESS)),
        bounty_scval(criteria_hash=scval.to_bytes(b"\x01" * 31)),
        bounty_scval(status=scval.to_symbol("Open")),
        bounty_scval(status=scval.to_vec([])),
        bounty_scval(extra=scval.to_uint64(1)),
    ],
    ids=[
        "not-a-map",
        "a-vector",
        "amount-bool",
        "amount-string",
        "client-string",
        "short-hash",
        "status-bare-symbol",
        "status-empty",
        "unknown-field",
    ],
)
def test_get_bounty_rejects_unexpected_payloads(
    stellar: StellarClient, server: FakeSorobanServer, payload: SCVal
) -> None:
    server.returns(payload)

    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(BOUNTY_ID)


def test_get_bounty_rejects_a_missing_field(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    fields = {
        scval.to_symbol("amount"): scval.to_int128(1),
        scval.to_symbol("client"): scval.to_address(CLIENT_ADDRESS),
    }

    server.returns(scval.to_map(fields))

    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(BOUNTY_ID)


# ─────────────────────────────────────────
# assert_transaction_success.
# ─────────────────────────────────────────

FUNDING_TX = "a1" * 32


def test_successful_transaction_passes(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    assert stellar.assert_transaction_success(FUNDING_TX) is None
    assert server.looked_up == [FUNDING_TX]


def test_transaction_hash_is_lowercased_for_rpc(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    stellar.assert_transaction_success(FUNDING_TX.upper())

    assert server.looked_up == [FUNDING_TX]


@pytest.mark.parametrize(
    "transaction_status",
    [GetTransactionStatus.FAILED, GetTransactionStatus.NOT_FOUND],
)
def test_non_success_transaction_raises(
    stellar: StellarClient,
    server: FakeSorobanServer,
    transaction_status: GetTransactionStatus,
) -> None:
    server.transaction_status = transaction_status

    with pytest.raises(StellarTransactionError) as raised:
        stellar.assert_transaction_success(FUNDING_TX)

    assert transaction_status.value in str(raised.value)

    # Sin polling: una sola consulta.
    assert server.looked_up == [FUNDING_TX]


@pytest.mark.parametrize(
    "transaction_hash",
    ["", "a1" * 31, "a1" * 33, "zz" * 32, " " + "a1" * 31 + "a"],
)
def test_invalid_transaction_hash_raises_before_rpc(
    stellar: StellarClient, server: FakeSorobanServer, transaction_hash: str
) -> None:
    with pytest.raises(StellarTransactionError):
        stellar.assert_transaction_success(transaction_hash)

    assert server.looked_up == []


def test_read_errors_never_leak_the_verifier_secret(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    messages: list[str] = []

    server.simulation_error = "boom"

    for call in (
        lambda: stellar.get_bounty(BOUNTY_ID),
        lambda: stellar.get_bounty(0),
        lambda: stellar.assert_transaction_success("nope"),
    ):
        try:
            call()
        except StellarTransactionError as error:
            messages.append(repr(error))

    server.transaction_status = GetTransactionStatus.FAILED

    try:
        stellar.assert_transaction_success(FUNDING_TX)
    except StellarTransactionError as error:
        messages.append(repr(error))

    assert len(messages) == 4
    assert all(VERIFIER_SECRET not in message for message in messages)


# ─────────────────────────────────────────
# Fallos de transporte del RPC.
# ─────────────────────────────────────────

SENSITIVE_RPC_URL = "https://rpc.example.invalid/?apiKey=PAID-PROVIDER-KEY"


def transport_failures() -> list[Exception]:
    """Lo que lanza el SDK cuando no hay respuesta RPC valida."""
    gateway_page = BadResponseError(
        RpcResponse(
            status_code=502,
            text="<html>bad gateway</html>",
            headers={},
            url=SENSITIVE_RPC_URL,
        )
    )

    return [
        RpcConnectionError(f"HTTPSConnectionPool: Max retries exceeded with url: {SENSITIVE_RPC_URL}"),
        gateway_page,
        requests.ConnectionError(f"connection refused for {SENSITIVE_RPC_URL}"),
    ]


TRANSPORT_IDS = ["sdk-connection", "non-json-5xx", "requests"]


@pytest.mark.parametrize("failure", transport_failures(), ids=TRANSPORT_IDS)
def test_assert_transaction_success_converts_transport_errors(
    stellar: StellarClient, server: FakeSorobanServer, failure: Exception
) -> None:
    server.fail_on = {"get_transaction"}
    server.failure = failure

    with pytest.raises(StellarTransactionError):
        stellar.assert_transaction_success(FUNDING_TX)


@pytest.mark.parametrize("method", ["load_account", "simulate_transaction"])
@pytest.mark.parametrize("failure", transport_failures(), ids=TRANSPORT_IDS)
def test_get_bounty_converts_transport_errors(
    stellar: StellarClient,
    server: FakeSorobanServer,
    method: str,
    failure: Exception,
) -> None:
    server.fail_on = {method}
    server.failure = failure

    with pytest.raises(StellarTransactionError):
        stellar.get_bounty(BOUNTY_ID)


@pytest.mark.parametrize(
    "method",
    ["load_account", "prepare_transaction", "send_transaction", "poll_transaction"],
)
@pytest.mark.parametrize("failure", transport_failures(), ids=TRANSPORT_IDS)
def test_release_bounty_converts_transport_errors(
    stellar: StellarClient,
    server: FakeSorobanServer,
    method: str,
    failure: Exception,
) -> None:
    server.fail_on = {method}
    server.failure = failure

    with pytest.raises(StellarTransactionError):
        stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH)


def test_local_validation_errors_are_not_converted(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    # Aunque el RPC este caido, una validacion local sigue siendo ValueError.
    server.fail_on = {"load_account", "get_transaction"}

    with pytest.raises(ValueError):
        stellar.release_bounty(0, EVIDENCE_HASH)

    with pytest.raises(ValueError):
        stellar.release_bounty(BOUNTY_ID, "no-es-hex")


def test_rpc_protocol_errors_are_not_treated_as_transport(
    stellar: StellarClient, server: FakeSorobanServer
) -> None:
    # Una respuesta JSON-RPC de error esta bien formada: no es transporte y
    # conserva su tipo, aunque herede de la misma base del SDK.
    server.fail_on = {"get_transaction"}
    server.failure = SorobanRpcErrorResponse(-32602, "invalid params")

    with pytest.raises(SorobanRpcErrorResponse):
        stellar.assert_transaction_success(FUNDING_TX)


@pytest.mark.parametrize("failure", transport_failures(), ids=TRANSPORT_IDS)
def test_transport_errors_never_leak_secret_or_rpc_url(
    stellar: StellarClient, server: FakeSorobanServer, failure: Exception
) -> None:
    server.fail_on = {
        "load_account",
        "prepare_transaction",
        "send_transaction",
        "poll_transaction",
        "simulate_transaction",
        "get_transaction",
    }
    server.failure = failure

    raised: list[StellarTransactionError] = []

    for call in (
        lambda: stellar.release_bounty(BOUNTY_ID, EVIDENCE_HASH),
        lambda: stellar.get_bounty(BOUNTY_ID),
        lambda: stellar.assert_transaction_success(FUNDING_TX),
    ):
        with pytest.raises(StellarTransactionError) as caught:
            call()

        raised.append(caught.value)

    for error in raised:
        text = repr(error)

        assert VERIFIER_SECRET not in text
        assert "PAID-PROVIDER-KEY" not in text
        assert "bad gateway" not in text

        # La excepcion original (con URL y cuerpo) no viaja encadenada.
        assert error.__cause__ is None
        assert error.__suppress_context__ is True
