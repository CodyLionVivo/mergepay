import base64
import hashlib
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app import assignment_service, stellar_client
from app.config import settings
from app.models import Bounty, BountyStatus
from app.stellar_client import (
    OnChainBounty,
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)
from tests.conftest import (
    BASE_BRANCH,
    OWNER,
    REPO,
    SENSITIVE_RPC_URL,
    DownSorobanServer,
    FakeStellar,
)

CLIENT_WALLET = Keypair.random().public_key

# Keypair real del developer: firma la prueba de wallet de cada test.
DEVELOPER_KEYPAIR = Keypair.random()
DEVELOPER_WALLET = DEVELOPER_KEYPAIR.public_key
DEVELOPER_GITHUB = "CodyLionVivo"

# El contrato que MergePay tiene configurado, y que entra en el mensaje firmado.
CONTRACT_ID = StrKey.encode_contract(b"\x22" * 32)

CRITERIA_HASH = "c" * 64
BASE_SHA = "b" * 40
CREATE_TX = "f1" * 32
AMOUNT_STROOPS = 100_000_000
DEADLINE_UNIX = 1_767_225_600

ASSIGN_TX = "a2" * 32

# Todo lo que la aceptacion puede o no puede tocar.
TRACKED_COLUMNS = (
    "status",
    "developer_wallet",
    "developer_github",
    "client_wallet",
    "base_sha",
    "criteria_hash",
    "create_tx_hash",
    "release_tx_hash",
)


def create_funded_bounty(
    session_factory: sessionmaker[Session], **overrides: Any
) -> int:
    fields: dict[str, Any] = {
        "title": "Add rate limiting to the webhook endpoint",
        "description": "The webhook endpoint accepts unbounded traffic.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "criteria_hash": CRITERIA_HASH,
        "client_wallet": CLIENT_WALLET,
        "create_tx_hash": CREATE_TX,
        "amount_stroops": AMOUNT_STROOPS,
        "deadline_unix": DEADLINE_UNIX,
        "status": BountyStatus.OPEN_FUNDED,
    }

    fields.update(overrides)

    with session_factory() as db:
        bounty = Bounty(**fields)
        db.add(bounty)
        db.commit()

        return bounty.id


def matching_on_chain(**overrides: Any) -> OnChainBounty:
    """El escrow ya aceptado que corresponde a `create_funded_bounty`."""
    return replace(
        OnChainBounty(
            client=CLIENT_WALLET,
            developer=DEVELOPER_WALLET,
            amount=AMOUNT_STROOPS,
            criteria_hash=CRITERIA_HASH,
            evidence_hash=None,
            deadline=DEADLINE_UNIX,
            status="Assigned",
        ),
        **overrides,
    )


def canonical_message(
    *,
    bounty_id: int,
    transaction_hash: str,
    developer_wallet: str = DEVELOPER_WALLET,
    developer_github: str = DEVELOPER_GITHUB,
    contract_id: str = CONTRACT_ID,
) -> str:
    """El formato de la spec, reescrito aqui a mano a proposito.

    No reutiliza el helper del servicio: asi los tests comprueban el formato
    acordado, y no solo que el backend coincida consigo mismo.
    """
    return (
        "MergePay assignment v1\n"
        f"bounty_id={bounty_id}\n"
        f"transaction_hash={transaction_hash}\n"
        f"developer_wallet={developer_wallet}\n"
        f"developer_github={developer_github}\n"
        f"contract_id={contract_id}"
    )


def sep53_sign(keypair: Keypair, message: str) -> str:
    """Firma SEP-53, como Freighter: sha256 del prefijo mas el mensaje."""
    digest = hashlib.sha256(b"Stellar Signed Message:\n" + message.encode("utf-8")).digest()

    return base64.b64encode(keypair.sign(digest)).decode("ascii")


def assign(
    client: TestClient,
    bounty_id: int,
    transaction_hash: str = ASSIGN_TX,
    developer_github: str = DEVELOPER_GITHUB,
    *,
    signer: Keypair = DEVELOPER_KEYPAIR,
    wallet_signature: str | None = None,
    signed_fields: dict[str, Any] | None = None,
):
    """POST /assigned con una firma valida del developer, salvo que se pida otra.

    Por defecto firma el mensaje que construira el backend (hash en minusculas,
    GitHub recortado). `signed_fields` altera campos del mensaje que se firma,
    sin tocar lo que se envia en el body.
    """
    if wallet_signature is None:
        fields: dict[str, Any] = {
            "bounty_id": bounty_id,
            "transaction_hash": transaction_hash.strip().lower(),
            "developer_github": developer_github.strip(),
        }
        fields.update(signed_fields or {})
        wallet_signature = sep53_sign(signer, canonical_message(**fields))

    return client.post(
        f"/bounties/{bounty_id}/assigned",
        json={
            "transaction_hash": transaction_hash,
            "developer_github": developer_github,
            "wallet_signature": wallet_signature,
        },
    )


def snapshot(session_factory: sessionmaker[Session], bounty_id: int) -> dict[str, Any]:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        return {column: getattr(bounty, column) for column in TRACKED_COLUMNS}


@pytest.fixture(autouse=True)
def configured_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """El FakeStellar no pasa por settings: el contract id se fija aqui."""
    monkeypatch.setattr(settings, "stellar_contract_id", CONTRACT_ID)


@pytest.fixture
def accepted(stellar: FakeStellar) -> FakeStellar:
    """Stellar devuelve un escrow aceptado que coincide con la task."""
    stellar.on_chain = matching_on_chain()

    return stellar


# ─────────────────────────────────────────
# 1 a 3. Bounty y estado.
# ─────────────────────────────────────────


def test_unknown_bounty_returns_404(client: TestClient, accepted: FakeStellar) -> None:
    response = assign(client, 999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}
    assert accepted.builds == 0


def test_draft_bounty_returns_409(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory, status=BountyStatus.DRAFT)

    response = assign(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not funded"}
    assert accepted.builds == 0


@pytest.mark.parametrize(
    "status",
    [
        BountyStatus.SUBMITTED,
        BountyStatus.VERIFYING,
        BountyStatus.NEEDS_CHANGES,
        BountyStatus.ELIGIBLE,
        BountyStatus.PAID,
        BountyStatus.CANCELLED_REFUNDED,
        BountyStatus.EXPIRED_REFUNDED,
    ],
)
def test_other_states_return_409(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    status: BountyStatus,
) -> None:
    bounty_id = create_funded_bounty(session_factory, status=status)

    response = assign(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty cannot be assigned in its current state"}
    assert accepted.builds == 0


# ─────────────────────────────────────────
# 4 a 6. Validacion del body.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "transaction_hash",
    ["", "a2" * 31, "a2" * 33, "zz" * 32, "not-a-hash"],
)
def test_invalid_transaction_hash_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    transaction_hash: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assert assign(client, bounty_id, transaction_hash=transaction_hash).status_code == 422
    assert accepted.builds == 0


@pytest.mark.parametrize("developer_github", ["", "   "])
def test_empty_developer_github_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    developer_github: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assert assign(client, bounty_id, developer_github=developer_github).status_code == 422
    assert accepted.builds == 0


@pytest.mark.parametrize(
    "developer_github",
    ["octo_dev", "@octodev", "octo dev", "octo.dev", "a" * 40, "octó"],
)
def test_invalid_developer_github_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    developer_github: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assert assign(client, bounty_id, developer_github=developer_github).status_code == 422
    assert accepted.builds == 0


@pytest.mark.parametrize(
    "extra",
    ["developer_wallet", "client_wallet", "status", "amount", "criteria_hash"],
)
def test_backend_owned_fields_are_rejected(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    extra: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    response = client.post(
        f"/bounties/{bounty_id}/assigned",
        json={
            "transaction_hash": ASSIGN_TX,
            "developer_github": DEVELOPER_GITHUB,
            extra: "valor-del-navegador",
        },
    )

    assert response.status_code == 422
    assert accepted.builds == 0


# ─────────────────────────────────────────
# 7. Bounty financiado pero incompleto.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "missing", ["client_wallet", "criteria_hash", "base_sha", "create_tx_hash"]
)
def test_incomplete_funded_bounty_returns_409(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    missing: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory, **{missing: None})

    response = assign(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not ready for assignment"}
    assert accepted.builds == 0


# ─────────────────────────────────────────
# 8 a 16. El estado on-chain no encaja.
# ─────────────────────────────────────────


def test_unsuccessful_transaction_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    accepted.transaction_status_error = StellarTransactionError(
        "Transaction finished with status FAILED"
    )

    response = assign(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to verify assignment on Stellar"}

    # Sin transaccion confirmada no se llega a leer el contrato.
    assert accepted.read_bounties == []


@pytest.mark.parametrize(
    "mismatch",
    [
        {"client": Keypair.random().public_key},
        {"developer": None},
        {"developer": StrKey.encode_contract(b"\x11" * 32)},
        {"amount": AMOUNT_STROOPS + 1},
        {"criteria_hash": "d" * 64},
        {"deadline": DEADLINE_UNIX + 60},
        {"status": "Open"},
        {"status": "Paid"},
        {"evidence_hash": "e" * 64},
    ],
    ids=[
        "client",
        "developer-none",
        "developer-not-g-address",
        "amount",
        "criteria_hash",
        "deadline",
        "status-open",
        "status-paid",
        "evidence_hash",
    ],
)
def test_on_chain_mismatch_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    mismatch: dict[str, Any],
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    before = snapshot(session_factory, bounty_id)

    accepted.on_chain = matching_on_chain(**mismatch)

    response = assign(client, bounty_id)

    assert response.status_code == 422
    assert response.json() == {"detail": "On-chain assignment does not match MergePay task"}
    assert snapshot(session_factory, bounty_id) == before


def test_criteria_hash_comparison_ignores_case(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory, criteria_hash=CRITERIA_HASH.upper())

    assert assign(client, bounty_id).status_code == 200


# ─────────────────────────────────────────
# 17 a 24. Confirmacion valida.
# ─────────────────────────────────────────


def test_valid_confirmation_assigns_the_bounty(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    response = assign(client, bounty_id)

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == bounty_id
    assert body["status"] == BountyStatus.ASSIGNED
    assert body["developer_wallet"] == DEVELOPER_WALLET
    assert body["developer_github"] == DEVELOPER_GITHUB


def test_valid_confirmation_writes_only_the_assignment(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assign(client, bounty_id)

    assert snapshot(session_factory, bounty_id) == {
        "status": BountyStatus.ASSIGNED,
        # La wallet del developer sale de Stellar, no del navegador.
        "developer_wallet": DEVELOPER_WALLET,
        # El usuario de GitHub sale del payload, tal cual lo escribio.
        "developer_github": DEVELOPER_GITHUB,
        # Nada del funding se toca.
        "client_wallet": CLIENT_WALLET,
        "base_sha": BASE_SHA,
        "criteria_hash": CRITERIA_HASH,
        "create_tx_hash": CREATE_TX,
        "release_tx_hash": None,
    }


def test_confirmation_checks_the_transaction_and_reads_the_bounty(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assign(client, bounty_id, transaction_hash=f"  {ASSIGN_TX.upper()}  ")

    assert accepted.builds == 1
    assert accepted.checked_transactions == [ASSIGN_TX]
    assert accepted.read_bounties == [bounty_id]


def test_developer_github_is_stored_trimmed_with_its_case(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assign(client, bounty_id, developer_github="  Octo-Dev-42  ")

    assert snapshot(session_factory, bounty_id)["developer_github"] == "Octo-Dev-42"


# ─────────────────────────────────────────
# 25 a 27. Idempotencia.
# ─────────────────────────────────────────


@pytest.mark.parametrize("retry_github", [DEVELOPER_GITHUB, DEVELOPER_GITHUB.lower()])
def test_same_developer_on_assigned_bounty_is_idempotent(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    retry_github: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    first = assign(client, bounty_id)

    builds_before = accepted.builds
    before = snapshot(session_factory, bounty_id)

    second = assign(client, bounty_id, developer_github=retry_github)

    assert second.status_code == 200
    assert second.json() == first.json()

    # No se vuelve a consultar Stellar y nada cambia.
    assert accepted.builds == builds_before
    assert snapshot(session_factory, bounty_id) == before


def test_different_developer_on_assigned_bounty_returns_409(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assign(client, bounty_id)

    before = snapshot(session_factory, bounty_id)

    response = assign(client, bounty_id, developer_github="someone-else")

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is already assigned"}
    assert snapshot(session_factory, bounty_id) == before


# ─────────────────────────────────────────
# 28 y 29. Errores de Stellar.
# ─────────────────────────────────────────


def test_stellar_configuration_error_returns_503(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    accepted.configuration_error = StellarConfigurationError(
        "stellar_contract_id is not configured"
    )

    response = assign(client, bounty_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar assignment verification is not configured"}


def test_stellar_read_error_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    accepted.read_error = StellarTransactionError(
        "get_bounty simulation failed: HostError: Error(Contract, #3)"
    )

    response = assign(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to verify assignment on Stellar"}
    assert "HostError" not in response.text


def test_stellar_rpc_transport_error_returns_502(
    client: TestClient,
    session_factory: sessionmaker[Session],
    real_stellar_with_down_rpc: None,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    response = assign(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to verify assignment on Stellar"}


# ─────────────────────────────────────────
# 30. Ningun fallo parcial toca la base de datos.
# ─────────────────────────────────────────


def _break_configuration(stellar: FakeStellar) -> None:
    stellar.configuration_error = StellarConfigurationError("missing secret")


def _break_transaction(stellar: FakeStellar) -> None:
    stellar.transaction_status_error = StellarTransactionError("FAILED")


def _break_read(stellar: FakeStellar) -> None:
    stellar.read_error = StellarTransactionError("simulation failed")


def _break_match(stellar: FakeStellar) -> None:
    stellar.on_chain = matching_on_chain(status="Open")


@pytest.mark.parametrize(
    "break_step",
    [_break_configuration, _break_transaction, _break_read, _break_match],
    ids=["configuration", "transaction", "read", "match"],
)
def test_no_partial_failure_modifies_the_bounty(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    break_step,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    before = snapshot(session_factory, bounty_id)

    break_step(accepted)

    assert assign(client, bounty_id).status_code >= 400
    assert snapshot(session_factory, bounty_id) == before
    assert before["status"] == BountyStatus.OPEN_FUNDED
    assert before["developer_wallet"] is None
    assert before["developer_github"] is None


# ─────────────────────────────────────────
# 31. Ningun error filtra secretos.
# ─────────────────────────────────────────

VERIFIER_KEYPAIR = Keypair.random()


@pytest.fixture
def real_stellar_with_down_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    """El StellarClient real, con el RPC caido, en lugar del FakeStellar."""
    monkeypatch.setattr(stellar_client, "SorobanServer", DownSorobanServer)
    monkeypatch.setattr(
        assignment_service,
        "get_stellar_client",
        lambda: StellarClient(
            rpc_url=SENSITIVE_RPC_URL,
            network_passphrase="Test SDF Network ; September 2015",
            contract_id=StrKey.encode_contract(b"\x11" * 32),
            verifier_secret=VERIFIER_KEYPAIR.secret,
        ),
    )


def test_transport_errors_never_leak_secrets(
    client: TestClient,
    session_factory: sessionmaker[Session],
    real_stellar_with_down_rpc: None,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    response = assign(client, bounty_id)

    assert VERIFIER_KEYPAIR.secret not in response.text
    assert "PAID-PROVIDER-KEY" not in response.text
    assert "HTTPSConnectionPool" not in response.text


@pytest.mark.parametrize("failure", ["configuration", "transaction"])
def test_error_messages_never_leak_secrets(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    failure: str,
) -> None:
    leaked = "SSECRETSEEDTHATMUSTNEVERREACHTHECLIENT00000000000000000"

    bounty_id = create_funded_bounty(session_factory)

    if failure == "configuration":
        accepted.configuration_error = StellarConfigurationError(f"boom {leaked}")
    else:
        accepted.transaction_status_error = StellarTransactionError(f"boom {leaked}")

    response = assign(client, bounty_id)

    assert response.status_code in (502, 503)
    assert leaked not in response.text
    assert "boom" not in response.text


# ─────────────────────────────────────────
# Prueba de wallet (firma SEP-53).
# ─────────────────────────────────────────


def test_canonical_message_has_the_exact_format() -> None:
    message = assignment_service.build_assignment_message(
        bounty_id=7,
        transaction_hash=ASSIGN_TX.upper(),
        developer_wallet=DEVELOPER_WALLET,
        developer_github="  CodyLionVivo  ",
        contract_id=CONTRACT_ID,
    )

    assert message == (
        "MergePay assignment v1\n"
        "bounty_id=7\n"
        f"transaction_hash={ASSIGN_TX}\n"
        f"developer_wallet={DEVELOPER_WALLET}\n"
        "developer_github=CodyLionVivo\n"
        f"contract_id={CONTRACT_ID}"
    )
    assert not message.endswith("\n")


def test_missing_wallet_signature_returns_422(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    response = client.post(
        f"/bounties/{bounty_id}/assigned",
        json={"transaction_hash": ASSIGN_TX, "developer_github": DEVELOPER_GITHUB},
    )

    assert response.status_code == 422
    assert accepted.builds == 0


@pytest.mark.parametrize(
    "wallet_signature",
    ["", "   ", "not base64!!", "abc", "====", "ÿÿÿÿ"],
    ids=["empty", "blank", "symbols", "bad-padding", "only-padding", "non-ascii"],
)
def test_invalid_base64_signature_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    wallet_signature: str,
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    assert assign(client, bounty_id, wallet_signature=wallet_signature).status_code == 422
    assert accepted.builds == 0


@pytest.mark.parametrize("length", [32, 63, 65, 128])
def test_signature_of_wrong_length_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    length: int,
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    wrong_length = base64.b64encode(b"\x01" * length).decode("ascii")

    assert assign(client, bounty_id, wallet_signature=wrong_length).status_code == 422
    assert accepted.builds == 0


def test_valid_developer_signature_assigns_the_bounty(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    response = assign(client, bounty_id)

    assert response.status_code == 200
    assert response.json()["status"] == BountyStatus.ASSIGNED


def test_signature_from_the_sdk_sep53_implementation_is_accepted(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    # stellar_sdk trae su propia implementacion de SEP-53: si la acepta, el
    # backend habla el mismo protocolo que cualquier firmante SEP-53.
    bounty_id = create_funded_bounty(session_factory)
    message = canonical_message(bounty_id=bounty_id, transaction_hash=ASSIGN_TX)
    signature = base64.b64encode(DEVELOPER_KEYPAIR.sign_message(message)).decode("ascii")

    assert assign(client, bounty_id, wallet_signature=signature).status_code == 200


def test_signature_from_another_wallet_returns_403(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    # Firma correcta del mensaje correcto, pero hecha por otra wallet: es
    # justo lo que puede fabricar quien se adelanta con el hash publico.
    response = assign(client, bounty_id, signer=Keypair.random())

    assert response.status_code == 403
    assert response.json() == {"detail": "Developer wallet signature is invalid"}


@pytest.mark.parametrize(
    "tampered",
    [
        {"bounty_id": 999},
        {"transaction_hash": "b3" * 32},
        {"developer_github": "someone-else"},
        {"developer_wallet": Keypair.random().public_key},
        {"contract_id": StrKey.encode_contract(b"\x33" * 32)},
    ],
    ids=["bounty_id", "transaction_hash", "developer_github", "developer_wallet", "contract_id"],
)
def test_signature_over_an_altered_message_returns_403(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    tampered: dict[str, Any],
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    # Firmado por el developer real, pero sobre un mensaje con un campo cambiado.
    response = assign(client, bounty_id, signed_fields=tampered)

    assert response.status_code == 403
    assert response.json() == {"detail": "Developer wallet signature is invalid"}


def test_signature_over_a_message_with_trailing_newline_returns_403(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    message = canonical_message(bounty_id=bounty_id, transaction_hash=ASSIGN_TX) + "\n"

    response = assign(
        client, bounty_id, wallet_signature=sep53_sign(DEVELOPER_KEYPAIR, message)
    )

    assert response.status_code == 403


def test_github_case_is_part_of_the_signed_message(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    # El mensaje lleva el GitHub tal cual se envia: otra capitalizacion es otro
    # mensaje, aunque GitHub no distinga mayusculas.
    response = assign(client, bounty_id, developer_github="codylionvivo")

    assert response.status_code == 200

    other = create_funded_bounty(session_factory)
    signature = sep53_sign(
        DEVELOPER_KEYPAIR,
        canonical_message(bounty_id=other, transaction_hash=ASSIGN_TX),
    )

    response = assign(client, other, developer_github="codylionvivo", wallet_signature=signature)

    assert response.status_code == 403


def test_invalid_signature_does_not_modify_the_bounty(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    before = snapshot(session_factory, bounty_id)

    assert assign(client, bounty_id, signer=Keypair.random()).status_code == 403
    assert snapshot(session_factory, bounty_id) == before

    # Y el developer legitimo sigue pudiendo confirmar despues.
    assert assign(client, bounty_id).status_code == 200


def test_signature_is_checked_after_the_on_chain_state(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    accepted.on_chain = matching_on_chain(status="Open")

    # Con el contrato aun sin developer, gana el 422 aunque la firma sea mala.
    response = assign(client, bounty_id, signer=Keypair.random())

    assert response.status_code == 422


def test_signature_is_checked_after_the_transaction(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    accepted.transaction_status_error = StellarTransactionError("FAILED")

    response = assign(client, bounty_id, signer=Keypair.random())

    assert response.status_code == 502
    assert accepted.read_bounties == []


def test_missing_contract_id_keeps_the_configuration_error(
    client: TestClient,
    session_factory: sessionmaker[Session],
    accepted: FakeStellar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "stellar_contract_id", None)

    bounty_id = create_funded_bounty(session_factory)
    before = snapshot(session_factory, bounty_id)

    response = assign(client, bounty_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar assignment verification is not configured"}
    assert snapshot(session_factory, bounty_id) == before


def test_idempotent_retry_still_skips_stellar(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)

    first = assign(client, bounty_id)
    builds_before = accepted.builds

    second = assign(client, bounty_id)

    assert second.status_code == 200
    assert second.json() == first.json()
    assert accepted.builds == builds_before


def test_signature_errors_never_expose_secrets(
    client: TestClient, session_factory: sessionmaker[Session], accepted: FakeStellar
) -> None:
    bounty_id = create_funded_bounty(session_factory)
    attacker = Keypair.random()
    signature = sep53_sign(
        attacker, canonical_message(bounty_id=bounty_id, transaction_hash=ASSIGN_TX)
    )

    response = assign(client, bounty_id, wallet_signature=signature)

    assert response.status_code == 403
    assert response.json() == {"detail": "Developer wallet signature is invalid"}

    # Ni secretos, ni la firma, ni el mensaje, ni la wallet on-chain.
    assert attacker.secret not in response.text
    assert DEVELOPER_KEYPAIR.secret not in response.text
    assert signature not in response.text
    assert "MergePay assignment v1" not in response.text
    assert DEVELOPER_WALLET not in response.text
