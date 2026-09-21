from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app import funding_service, stellar_client
from app.models import Bounty, BountyStatus
from app.stellar_client import (
    OnChainBounty,
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)
from tests.conftest import (
    BASE_BRANCH,
    BRANCH_HEAD_SHA,
    OWNER,
    REPO,
    SENSITIVE_RPC_URL,
    DownSorobanServer,
    FakeGitHub,
    FakeStellar,
)

CLIENT_WALLET = Keypair.random().public_key
CRITERIA_HASH = "c" * 64
AMOUNT_STROOPS = 100_000_000
DEADLINE_UNIX = 1_767_225_600

FUNDING_TX = "f1" * 32
OTHER_TX = "e2" * 32

FUNDING_COLUMNS = ("status", "client_wallet", "base_sha", "create_tx_hash")


def create_draft_bounty(
    session_factory: sessionmaker[Session], **overrides: Any
) -> int:
    fields: dict[str, Any] = {
        "title": "Add rate limiting to the webhook endpoint",
        "description": "The webhook endpoint accepts unbounded traffic.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": BASE_BRANCH,
        "criteria_hash": CRITERIA_HASH,
        "amount_stroops": AMOUNT_STROOPS,
        "deadline_unix": DEADLINE_UNIX,
        "status": BountyStatus.DRAFT,
    }

    fields.update(overrides)

    with session_factory() as db:
        bounty = Bounty(**fields)
        db.add(bounty)
        db.commit()

        return bounty.id


def matching_on_chain(**overrides: Any) -> OnChainBounty:
    """El escrow que corresponde exactamente al bounty de `create_draft_bounty`."""
    return replace(
        OnChainBounty(
            client=CLIENT_WALLET,
            developer=None,
            amount=AMOUNT_STROOPS,
            criteria_hash=CRITERIA_HASH,
            evidence_hash=None,
            deadline=DEADLINE_UNIX,
            status="Open",
        ),
        **overrides,
    )


def fund(client: TestClient, bounty_id: int, transaction_hash: str = FUNDING_TX):
    return client.post(
        f"/bounties/{bounty_id}/funded", json={"transaction_hash": transaction_hash}
    )


def funding_snapshot(
    session_factory: sessionmaker[Session], bounty_id: int
) -> dict[str, Any]:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        return {column: getattr(bounty, column) for column in FUNDING_COLUMNS}


@pytest.fixture
def funded_ready(stellar: FakeStellar) -> FakeStellar:
    """Stellar devuelve un escrow que coincide con la task."""
    stellar.on_chain = matching_on_chain()

    return stellar


# ─────────────────────────────────────────
# 1 a 3. Precondiciones y validacion del body.
# ─────────────────────────────────────────


def test_unknown_bounty_returns_404(client: TestClient, funded_ready: FakeStellar) -> None:
    response = fund(client, 999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}
    assert funded_ready.builds == 0


@pytest.mark.parametrize(
    "status",
    [
        BountyStatus.ASSIGNED,
        BountyStatus.SUBMITTED,
        BountyStatus.ELIGIBLE,
        BountyStatus.PAID,
        BountyStatus.CANCELLED_REFUNDED,
    ],
)
def test_non_draft_bounty_returns_409(
    client: TestClient,
    session_factory: sessionmaker[Session],
    funded_ready: FakeStellar,
    status: BountyStatus,
) -> None:
    bounty_id = create_draft_bounty(session_factory, status=status)

    response = fund(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty cannot be funded in its current state"}
    assert funded_ready.builds == 0


@pytest.mark.parametrize(
    "transaction_hash",
    ["", "f1" * 31, "f1" * 33, "zz" * 32, "not-a-hash"],
)
def test_invalid_transaction_hash_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    funded_ready: FakeStellar,
    transaction_hash: str,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    response = fund(client, bounty_id, transaction_hash)

    assert response.status_code == 422

    # Rechazado por el schema: Stellar ni se construye.
    assert funded_ready.builds == 0


@pytest.mark.parametrize(
    "extra",
    ["client_wallet", "base_sha", "status", "amount", "criteria_hash"],
)
def test_backend_owned_fields_are_rejected(
    client: TestClient,
    session_factory: sessionmaker[Session],
    funded_ready: FakeStellar,
    extra: str,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    response = client.post(
        f"/bounties/{bounty_id}/funded",
        json={"transaction_hash": FUNDING_TX, extra: "valor-del-navegador"},
    )

    assert response.status_code == 422
    assert funded_ready.builds == 0


def test_missing_criteria_hash_returns_409(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory, criteria_hash=None)

    response = fund(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not ready for funding"}
    assert funded_ready.builds == 0


# ─────────────────────────────────────────
# 11 a 15. Confirmacion valida.
# ─────────────────────────────────────────


def test_valid_confirmation_funds_the_bounty(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    response = fund(client, bounty_id)

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == bounty_id
    assert body["status"] == BountyStatus.OPEN_FUNDED
    assert body["client_wallet"] == CLIENT_WALLET
    assert body["base_sha"] == BRANCH_HEAD_SHA
    assert body["create_tx_hash"] == FUNDING_TX


def test_valid_confirmation_persists_every_field(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    fund(client, bounty_id)

    assert funding_snapshot(session_factory, bounty_id) == {
        "status": BountyStatus.OPEN_FUNDED,
        # La wallet sale de Stellar, no del navegador.
        "client_wallet": CLIENT_WALLET,
        # El base_sha sale de GitHub.
        "base_sha": BRANCH_HEAD_SHA,
        "create_tx_hash": FUNDING_TX,
    }


def test_confirmation_checks_the_transaction_and_reads_the_right_bounty(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    fund(client, bounty_id)

    assert funded_ready.builds == 1
    assert funded_ready.checked_transactions == [FUNDING_TX]
    assert funded_ready.read_bounties == [bounty_id]


def test_uppercase_hash_is_stored_normalised(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    response = fund(client, bounty_id, f"  {FUNDING_TX.upper()}  ")

    assert response.status_code == 200
    assert response.json()["create_tx_hash"] == FUNDING_TX
    assert funded_ready.checked_transactions == [FUNDING_TX]


def test_base_sha_is_resolved_from_the_bounty_branch(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
) -> None:
    bounty_id = create_draft_bounty(session_factory, base_branch="release/2026")

    fund(client, bounty_id)

    # La rama con barra viaja como un unico segmento codificado.
    raw_paths = [request.url.raw_path.decode() for request in github.requests]

    assert raw_paths == [f"/repos/{OWNER}/{REPO}/commits/release%2F2026"]


# ─────────────────────────────────────────
# 16 y 17. Idempotencia.
# ─────────────────────────────────────────


def test_same_hash_twice_is_idempotent(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    first = fund(client, bounty_id)

    del github.requests[:]
    builds_before = funded_ready.builds
    snapshot_before = funding_snapshot(session_factory, bounty_id)

    second = fund(client, bounty_id)

    assert second.status_code == 200
    assert second.json() == first.json()

    # Ni Stellar ni GitHub se vuelven a consultar, y nada cambia.
    assert funded_ready.builds == builds_before
    assert github.requests == []
    assert funding_snapshot(session_factory, bounty_id) == snapshot_before


def test_different_hash_on_funded_bounty_returns_409(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    fund(client, bounty_id)

    snapshot_before = funding_snapshot(session_factory, bounty_id)

    response = fund(client, bounty_id, OTHER_TX)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is already funded"}
    assert funding_snapshot(session_factory, bounty_id) == snapshot_before


# ─────────────────────────────────────────
# 4 a 10. El escrow on-chain no encaja.
# ─────────────────────────────────────────


def test_unsuccessful_transaction_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    funded_ready.transaction_status_error = StellarTransactionError(
        "Transaction finished with status FAILED"
    )

    response = fund(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to verify funding on Stellar"}

    # Sin transaccion confirmada no se llega a leer el bounty.
    assert funded_ready.read_bounties == []


@pytest.mark.parametrize(
    "mismatch",
    [
        {"amount": AMOUNT_STROOPS + 1},
        {"criteria_hash": "d" * 64},
        {"deadline": DEADLINE_UNIX + 60},
        {"developer": Keypair.random().public_key},
        {"status": "Assigned"},
        {"evidence_hash": "e" * 64},
        # Un contrato no puede ser el cliente de un escrow.
        {"client": StrKey.encode_contract(b"\x11" * 32)},
    ],
    ids=[
        "amount",
        "criteria_hash",
        "deadline",
        "developer",
        "status",
        "evidence_hash",
        "client-is-contract",
    ],
)
def test_on_chain_mismatch_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
    mismatch: dict[str, Any],
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    funded_ready.on_chain = matching_on_chain(**mismatch)

    response = fund(client, bounty_id)

    assert response.status_code == 422
    assert response.json() == {"detail": "On-chain bounty does not match MergePay task"}

    # GitHub no se consulta si Stellar ya no encaja.
    assert github.requests == []


def test_criteria_hash_comparison_ignores_case(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory, criteria_hash=CRITERIA_HASH.upper())

    assert fund(client, bounty_id).status_code == 200


# ─────────────────────────────────────────
# 18 y 19. Errores de Stellar.
# ─────────────────────────────────────────


def test_stellar_configuration_error_returns_503(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    funded_ready.configuration_error = StellarConfigurationError(
        "stellar_contract_id is not configured"
    )

    response = fund(client, bounty_id)

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar funding verification is not configured"}


def test_stellar_read_error_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], funded_ready: FakeStellar
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    funded_ready.read_error = StellarTransactionError(
        "get_bounty simulation failed: HostError: Error(Contract, #3)"
    )

    response = fund(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to verify funding on Stellar"}

    # El mensaje del RPC no llega al cliente.
    assert "HostError" not in response.text


# ─────────────────────────────────────────
# 20 y 21. Errores de GitHub.
# ─────────────────────────────────────────


def test_missing_branch_returns_422(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    github.branch_response = httpx.Response(404, json={"message": "No commit found"})

    response = fund(client, bounty_id)

    assert response.status_code == 422
    assert response.json() == {"detail": "Base branch not found on GitHub"}


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_github_failure_returns_502(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
    status_code: int,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    github.branch_response = httpx.Response(status_code, json={"message": "secreto"})

    response = fund(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub service unavailable"}
    assert "secreto" not in response.text


# ─────────────────────────────────────────
# 22. Ningun fallo parcial toca la base de datos.
# ─────────────────────────────────────────


def _break_transaction(stellar: FakeStellar, github: FakeGitHub) -> None:
    stellar.transaction_status_error = StellarTransactionError("FAILED")


def _break_read(stellar: FakeStellar, github: FakeGitHub) -> None:
    stellar.read_error = StellarTransactionError("simulation failed")


def _break_configuration(stellar: FakeStellar, github: FakeGitHub) -> None:
    stellar.configuration_error = StellarConfigurationError("missing secret")


def _break_match(stellar: FakeStellar, github: FakeGitHub) -> None:
    stellar.on_chain = matching_on_chain(amount=1)


def _break_branch(stellar: FakeStellar, github: FakeGitHub) -> None:
    github.branch_response = httpx.Response(404, json={})


def _break_github(stellar: FakeStellar, github: FakeGitHub) -> None:
    github.branch_response = httpx.Response(500, json={})


@pytest.mark.parametrize(
    "break_step",
    [
        _break_configuration,
        _break_transaction,
        _break_read,
        _break_match,
        _break_branch,
        _break_github,
    ],
    ids=["configuration", "transaction", "read", "match", "branch", "github"],
)
def test_no_partial_failure_modifies_the_bounty(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
    break_step,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    before = funding_snapshot(session_factory, bounty_id)

    break_step(funded_ready, github)

    response = fund(client, bounty_id)

    assert response.status_code >= 400
    assert funding_snapshot(session_factory, bounty_id) == before
    assert before == {
        "status": BountyStatus.DRAFT,
        "client_wallet": None,
        "base_sha": None,
        "create_tx_hash": None,
    }


# ─────────────────────────────────────────
# Fallos de transporte.
# ─────────────────────────────────────────

VERIFIER_KEYPAIR = Keypair.random()


@pytest.fixture
def real_stellar_with_down_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    """El StellarClient real, con el RPC caido, en lugar del FakeStellar."""
    monkeypatch.setattr(stellar_client, "SorobanServer", DownSorobanServer)
    monkeypatch.setattr(
        funding_service,
        "get_stellar_client",
        lambda: StellarClient(
            rpc_url=SENSITIVE_RPC_URL,
            network_passphrase="Test SDF Network ; September 2015",
            contract_id=StrKey.encode_contract(b"\x11" * 32),
            verifier_secret=VERIFIER_KEYPAIR.secret,
        ),
    )


def test_github_transport_error_returns_502(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    funded_ready: FakeStellar,
) -> None:
    bounty_id = create_draft_bounty(session_factory)
    before = funding_snapshot(session_factory, bounty_id)

    github.transport_error = httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    response = fund(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub service unavailable"}
    assert funding_snapshot(session_factory, bounty_id) == before


def test_stellar_rpc_transport_error_returns_502(
    client: TestClient,
    session_factory: sessionmaker[Session],
    real_stellar_with_down_rpc: None,
) -> None:
    bounty_id = create_draft_bounty(session_factory)
    before = funding_snapshot(session_factory, bounty_id)

    response = fund(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "Unable to verify funding on Stellar"}
    assert funding_snapshot(session_factory, bounty_id) == before


def test_transport_errors_never_leak_secrets(
    client: TestClient,
    session_factory: sessionmaker[Session],
    real_stellar_with_down_rpc: None,
) -> None:
    bounty_id = create_draft_bounty(session_factory)

    response = fund(client, bounty_id)

    assert VERIFIER_KEYPAIR.secret not in response.text
    assert "PAID-PROVIDER-KEY" not in response.text
    assert "HTTPSConnectionPool" not in response.text
