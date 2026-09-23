from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app import evidence_service, stellar_client
from app.config import settings
from app.evidence_service import get_stellar_client as real_get_stellar_client
from app.models import Bounty, BountyStatus, Submission, Verification
from app.stellar_client import (
    OnChainBounty,
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)
from tests.conftest import (
    BASE_BRANCH,
    BASE_SHA,
    DEVELOPER,
    OWNER,
    PULL_NUMBER,
    REPO,
    SENSITIVE_RPC_URL,
    DownSorobanServer,
    FakeGitHub,
    FakeStellar,
    sign_in,
)

CONTRACT_ID = StrKey.encode_contract(b"\x33" * 32)

# Lo que guarda MergePay. Los valores on-chain de abajo son distintos a
# proposito: asi cada test demuestra de donde sale cada campo.
DB_CLIENT_KEYPAIR = Keypair.random()
DB_CLIENT_WALLET = DB_CLIENT_KEYPAIR.public_key
DB_DEVELOPER_KEYPAIR = Keypair.random()
DB_DEVELOPER_WALLET = DB_DEVELOPER_KEYPAIR.public_key
DB_AMOUNT = 100_000_000
DB_CRITERIA_HASH = "c" * 64
DB_DEADLINE = 1_767_225_600

ON_CHAIN_CLIENT = Keypair.random().public_key
ON_CHAIN_DEVELOPER = Keypair.random().public_key
ON_CHAIN_AMOUNT = 123_456_789
ON_CHAIN_CRITERIA_HASH = "e" * 64
ON_CHAIN_EVIDENCE_HASH = "f0" * 32
ON_CHAIN_DEADLINE = 1_900_000_000

RESPONSE_FIELDS = {
    "network",
    "contract_id",
    "client_wallet",
    "developer_wallet",
    "amount_stroops",
    "criteria_hash",
    "evidence_hash",
    "deadline_unix",
    "contract_status",
}

LEAKED_SECRET = "SSECRETSEEDTHATMUSTNEVERREACHTHECLIENT00000000000000000"


@pytest.fixture(autouse=True)
def configured_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """contract_id sale de la configuracion; en los tests, de este valor."""
    monkeypatch.setattr(settings, "stellar_contract_id", CONTRACT_ID)


@pytest.fixture(autouse=True)
def authenticated(client: TestClient) -> None:
    """Las tasks privadas solo las lee quien participa: aqui, su client."""
    sign_in(client, DB_CLIENT_KEYPAIR)


def on_chain_bounty(**overrides: Any) -> OnChainBounty:
    fields: dict[str, Any] = {
        "client": ON_CHAIN_CLIENT,
        "developer": None,
        "amount": ON_CHAIN_AMOUNT,
        "criteria_hash": ON_CHAIN_CRITERIA_HASH,
        "evidence_hash": None,
        "deadline": ON_CHAIN_DEADLINE,
        "status": "Open",
    }

    fields.update(overrides)

    return OnChainBounty(**fields)


def create_bounty(session_factory: sessionmaker[Session], **overrides: Any) -> int:
    """Un bounty con el funding ya confirmado, saltandose la API."""
    fields: dict[str, Any] = {
        "title": "Arreglar el redirect tras el login",
        "description": "El usuario acaba en /home y no en /dashboard.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "criteria_hash": DB_CRITERIA_HASH,
        "client_wallet": DB_CLIENT_WALLET,
        "create_tx_hash": "ab" * 32,
        "status": BountyStatus.OPEN_FUNDED,
        "amount_stroops": DB_AMOUNT,
        "deadline_unix": DB_DEADLINE,
    }

    fields.update(overrides)

    with session_factory() as db:
        bounty = Bounty(**fields)
        db.add(bounty)
        db.commit()

        return bounty.id


def get_onchain(client: TestClient, bounty_id: int):
    return client.get(f"/bounties/{bounty_id}/onchain")


def read_ok(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    **on_chain_overrides: Any,
) -> dict[str, Any]:
    bounty_id = create_bounty(session_factory)
    stellar.on_chain = on_chain_bounty(**on_chain_overrides)

    response = get_onchain(client, bounty_id)

    assert response.status_code == 200

    return response.json()


# ─────────────────────────────────────────
# 1 a 3. Precondiciones.
# ─────────────────────────────────────────


def test_unknown_bounty_returns_404(client: TestClient, stellar: FakeStellar) -> None:
    response = get_onchain(client, 999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}
    assert stellar.builds == 0


@pytest.mark.parametrize("status", [BountyStatus.DRAFT, BountyStatus.OPEN_FUNDED])
def test_bounty_without_funding_returns_409(
    client: TestClient,
    session_factory: sessionmaker[Session],
    status: BountyStatus,
) -> None:
    # Manda create_tx_hash, no el status: tambien un OPEN_FUNDED sin hash.
    bounty_id = create_bounty(session_factory, status=status, create_tx_hash=None)

    response = get_onchain(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty has not been confirmed on Stellar"}


def test_bounty_without_funding_never_builds_the_stellar_client(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(
        session_factory, status=BountyStatus.DRAFT, create_tx_hash=None
    )

    assert get_onchain(client, bounty_id).status_code == 409

    assert stellar.builds == 0
    assert stellar.read_bounties == []


# ─────────────────────────────────────────
# 4 y 5. Errores de Stellar.
# ─────────────────────────────────────────


def test_stellar_configuration_error_returns_503(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(session_factory)
    stellar.configuration_error = StellarConfigurationError("no configurado")

    response = get_onchain(client, bounty_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar evidence service is not configured"}
    assert stellar.read_bounties == []


@pytest.mark.parametrize("missing", ["stellar_contract_id", "stellar_verifier_secret"])
def test_missing_settings_return_503_through_the_real_client(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    """El StellarClient real, construido desde settings incompletos."""
    bounty_id = create_bounty(session_factory)

    monkeypatch.setattr(
        settings, "stellar_verifier_secret", Keypair.random().secret
    )
    monkeypatch.setattr(settings, missing, None)
    monkeypatch.setattr(evidence_service, "get_stellar_client", real_get_stellar_client)

    response = get_onchain(client, bounty_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar evidence service is not configured"}


def test_missing_contract_id_returns_503_even_with_a_client(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounty_id = create_bounty(session_factory)
    stellar.on_chain = on_chain_bounty()
    monkeypatch.setattr(settings, "stellar_contract_id", None)

    response = get_onchain(client, bounty_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar evidence service is not configured"}
    assert stellar.read_bounties == []


def test_stellar_read_failure_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(session_factory)
    stellar.read_error = StellarTransactionError("la simulacion fallo")

    response = get_onchain(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to read bounty evidence from Stellar"}
    assert stellar.read_bounties == [bounty_id]


def test_bounty_missing_on_chain_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    # Sin on_chain, el fake falla como el contrato con BountyNotFound.
    bounty_id = create_bounty(session_factory)

    response = get_onchain(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to read bounty evidence from Stellar"}


def test_rpc_transport_failure_returns_502_through_the_real_client(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """StellarClient real con el RPC caido, en lugar del FakeStellar."""
    bounty_id = create_bounty(session_factory)
    verifier = Keypair.random()

    monkeypatch.setattr(stellar_client, "SorobanServer", DownSorobanServer)
    monkeypatch.setattr(
        evidence_service,
        "get_stellar_client",
        lambda: StellarClient(
            rpc_url=SENSITIVE_RPC_URL,
            network_passphrase="Test SDF Network ; September 2015",
            contract_id=CONTRACT_ID,
            verifier_secret=verifier.secret,
        ),
    )

    response = get_onchain(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to read bounty evidence from Stellar"}
    assert verifier.secret not in response.text
    assert "PAID-PROVIDER-KEY" not in response.text


# ─────────────────────────────────────────
# 6 a 15. Respuesta correcta, campo a campo.
# ─────────────────────────────────────────


def test_valid_read_returns_200_with_exactly_the_public_fields(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(client, session_factory, stellar)

    assert set(body) == RESPONSE_FIELDS


def test_reads_the_requested_bounty_once(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    create_bounty(session_factory)
    bounty_id = create_bounty(session_factory)
    stellar.on_chain = on_chain_bounty()

    get_onchain(client, bounty_id)

    assert stellar.builds == 1
    assert stellar.read_bounties == [bounty_id]

    # Solo lectura: no se libero ni se comprobo ninguna transaccion.
    assert stellar.calls == []
    assert stellar.checked_transactions == []


def test_network_is_testnet(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    assert read_ok(client, session_factory, stellar)["network"] == "TESTNET"


def test_contract_id_comes_from_settings(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    assert read_ok(client, session_factory, stellar)["contract_id"] == CONTRACT_ID


def test_client_wallet_comes_from_on_chain(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(client, session_factory, stellar)

    assert body["client_wallet"] == ON_CHAIN_CLIENT
    assert body["client_wallet"] != DB_CLIENT_WALLET


def test_developer_wallet_comes_from_on_chain(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(
        session_factory,
        status=BountyStatus.ASSIGNED,
        developer_wallet=DB_DEVELOPER_WALLET,
    )
    stellar.on_chain = on_chain_bounty(developer=ON_CHAIN_DEVELOPER, status="Assigned")

    body = get_onchain(client, bounty_id).json()

    assert body["developer_wallet"] == ON_CHAIN_DEVELOPER
    assert body["developer_wallet"] != DB_DEVELOPER_WALLET


def test_unassigned_developer_wallet_is_null(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    assert read_ok(client, session_factory, stellar)["developer_wallet"] is None


def test_amount_comes_from_on_chain(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(client, session_factory, stellar)

    assert body["amount_stroops"] == ON_CHAIN_AMOUNT
    assert body["amount_stroops"] != DB_AMOUNT


def test_criteria_hash_comes_from_on_chain(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(client, session_factory, stellar)

    assert body["criteria_hash"] == ON_CHAIN_CRITERIA_HASH
    assert body["criteria_hash"] != DB_CRITERIA_HASH


def test_null_evidence_hash_is_preserved(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(client, session_factory, stellar)

    assert "evidence_hash" in body
    assert body["evidence_hash"] is None


def test_present_evidence_hash_is_returned(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(
        client, session_factory, stellar, evidence_hash=ON_CHAIN_EVIDENCE_HASH
    )

    assert body["evidence_hash"] == ON_CHAIN_EVIDENCE_HASH


def test_deadline_comes_from_on_chain(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    body = read_ok(client, session_factory, stellar)

    assert body["deadline_unix"] == ON_CHAIN_DEADLINE
    assert body["deadline_unix"] != DB_DEADLINE


# ─────────────────────────────────────────
# 16 a 18. contract_status tal cual lo da el contrato.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "contract_status", ["Open", "Assigned", "Paid", "Cancelled", "Refunded"]
)
def test_contract_status_is_returned_as_is(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    contract_status: str,
) -> None:
    body = read_ok(client, session_factory, stellar, status=contract_status)

    assert body["contract_status"] == contract_status


def test_contract_status_does_not_follow_the_database(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(session_factory, status=BountyStatus.PAID)
    stellar.on_chain = on_chain_bounty(status="Assigned")

    assert get_onchain(client, bounty_id).json()["contract_status"] == "Assigned"


# ─────────────────────────────────────────
# 19 a 21. El GET no escribe nada.
# ─────────────────────────────────────────


def row(instance: Any) -> tuple[Any, ...]:
    columns = type(instance).__table__.columns

    return tuple(getattr(instance, column.key) for column in columns)


def snapshot(
    session_factory: sessionmaker[Session], bounty_id: int
) -> dict[str, list[tuple[Any, ...]]]:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        return {
            "bounty": [row(bounty)],
            "submission": [row(item) for item in db.scalars(select(Submission))],
            "verification": [row(item) for item in db.scalars(select(Verification))],
        }


@pytest.fixture
def paid_bounty(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> int:
    """El happy path completo por la API: submission, verificacion y payout."""
    sign_in(client, DB_DEVELOPER_KEYPAIR)

    bounty_id = create_bounty(
        session_factory,
        status=BountyStatus.ASSIGNED,
        developer_wallet=DB_DEVELOPER_WALLET,
        developer_github=DEVELOPER,
    )

    pull_request_url = f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}"

    submitted = client.post(
        f"/bounties/{bounty_id}/submission",
        json={"pull_request_url": pull_request_url},
    )
    assert submitted.status_code == 201
    assert client.post(f"/bounties/{bounty_id}/verify").status_code == 200

    stellar.on_chain = on_chain_bounty(
        developer=ON_CHAIN_DEVELOPER,
        evidence_hash=ON_CHAIN_EVIDENCE_HASH,
        status="Paid",
    )

    return bounty_id


@pytest.mark.parametrize("table", ["bounty", "submission", "verification"])
def test_get_does_not_modify_the_database(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    paid_bounty: int,
    table: str,
) -> None:
    before = snapshot(session_factory, paid_bounty)

    assert before["submission"] and before["verification"]

    # GitHub cambia por debajo: la lectura on-chain no debe reflejarlo.
    github.set_head_sha("n" * 40)
    del github.requests[:]

    for _ in range(3):
        assert get_onchain(client, paid_bounty).status_code == 200

    assert snapshot(session_factory, paid_bounty)[table] == before[table]
    assert github.requests == []


# ─────────────────────────────────────────
# 22 y 23. Sin Stellar real y sin fugas.
# ─────────────────────────────────────────


def test_every_read_goes_through_the_fake(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    # El fixture `stellar` sustituye el helper del servicio en todos los tests:
    # la unica forma de llegar al StellarClient real es reponerlo a mano, y
    # los tests que lo hacen usan DownSorobanServer o fallan antes de la red.
    assert evidence_service.get_stellar_client == stellar.get_client

    read_ok(client, session_factory, stellar)

    assert stellar.builds == 1


@pytest.mark.parametrize("failure", ["configuration", "read"])
def test_errors_never_leak_secrets(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    failure: str,
) -> None:
    bounty_id = create_bounty(session_factory)
    leaked = f"boom {LEAKED_SECRET} {SENSITIVE_RPC_URL} AAAAAGXDRPAYLOAD=="

    if failure == "configuration":
        stellar.configuration_error = StellarConfigurationError(leaked)
    else:
        stellar.read_error = StellarTransactionError(leaked)

    response = get_onchain(client, bounty_id)

    assert response.status_code in (502, 503)

    for fragment in ("boom", LEAKED_SECRET, "PAID-PROVIDER-KEY", "AAAAAGXDRPAYLOAD"):
        assert fragment not in response.text


def test_successful_response_carries_no_secrets(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "stellar_verifier_secret", LEAKED_SECRET)
    monkeypatch.setattr(settings, "stellar_rpc_url", SENSITIVE_RPC_URL)

    bounty_id = create_bounty(session_factory)
    stellar.on_chain = on_chain_bounty()

    response = get_onchain(client, bounty_id)

    assert response.status_code == 200
    assert LEAKED_SECRET not in response.text
    assert "PAID-PROVIDER-KEY" not in response.text
    assert "rpc.example.invalid" not in response.text
