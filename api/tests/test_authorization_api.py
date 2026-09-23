"""Autorizacion por recurso: quien puede hacer que en cada bounty.

No hay roles globales. La misma wallet es client en una task y developer en
otra, asi que cada test monta la relacion real y comprueba solo eso.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app.assignment_service import build_assignment_message
from app.config import settings
from app.hashing import compute_evidence_hash
from app.models import Bounty, BountyStatus, Submission, Verification
from app.schemas import PullRequestVerificationResult
from app.stellar_client import OnChainBounty
from tests.conftest import (
    BRANCH_HEAD_SHA,
    DEVELOPER,
    OWNER,
    PULL_NUMBER,
    REPO,
    FakeGitHub,
    FakeStellar,
    auth_headers,
    sep53_signature,
)

CLIENT_KEYPAIR = Keypair.random()
CLIENT_WALLET = CLIENT_KEYPAIR.public_key

DEVELOPER_KEYPAIR = Keypair.random()
DEVELOPER_WALLET = DEVELOPER_KEYPAIR.public_key

# Una wallet cualquiera con sesion valida, pero ajena a la task.
OUTSIDER_KEYPAIR = Keypair.random()
OUTSIDER_WALLET = OUTSIDER_KEYPAIR.public_key

CONTRACT_ID = StrKey.encode_contract(b"\x55" * 32)

FUNDING_TX = "f1" * 32
ASSIGN_TX = "a2" * 32

PULL_REQUEST_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}"

AMOUNT_STROOPS = 100_000_000
DEADLINE_UNIX = 1_767_225_600


@pytest.fixture(autouse=True)
def configured_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stellar_contract_id", CONTRACT_ID)


def payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Arreglar el redirect tras el login",
        "description": "El usuario acaba en /home y no en /dashboard.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "amount_stroops": AMOUNT_STROOPS,
        "deadline_unix": DEADLINE_UNIX,
        "criteria": [{"description": "El redirect apunta a /dashboard"}],
    }

    body.update(overrides)

    return body


def create_task(
    client: TestClient, keypair: Keypair = CLIENT_KEYPAIR, **body_overrides: Any
) -> int:
    response = client.post(
        "/bounties",
        json=payload(**body_overrides),
        headers=auth_headers(client, keypair),
    )

    assert response.status_code == 201

    return response.json()["id"]


def draft_bounty(session_factory: sessionmaker[Session], **overrides: Any) -> int:
    """Un DRAFT insertado a mano, para los casos heredados sin client_wallet."""
    fields: dict[str, Any] = {
        "title": "Task antigua",
        "description": "Creada antes de que existiera la autenticacion.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": "main",
        "criteria_hash": "c" * 64,
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


def on_chain_for(
    session_factory: sessionmaker[Session], bounty_id: int, **overrides: Any
) -> OnChainBounty:
    """El escrow que corresponde exactamente a ese bounty."""
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        fields: dict[str, Any] = {
            "client": bounty.client_wallet or CLIENT_WALLET,
            "developer": None,
            "amount": bounty.amount_stroops,
            "criteria_hash": bounty.criteria_hash,
            "evidence_hash": None,
            "deadline": bounty.deadline_unix,
            "status": "Open",
        }

    fields.update(overrides)

    return OnChainBounty(**fields)


def fund(
    client: TestClient, bounty_id: int, keypair: Keypair | None = CLIENT_KEYPAIR
):
    headers = {} if keypair is None else auth_headers(client, keypair)

    return client.post(
        f"/bounties/{bounty_id}/funded",
        json={"transaction_hash": FUNDING_TX},
        headers=headers,
    )


def assign(
    client: TestClient,
    bounty_id: int,
    keypair: Keypair | None = DEVELOPER_KEYPAIR,
    *,
    signer: Keypair | None = None,
    developer_github: str = DEVELOPER,
):
    headers = {} if keypair is None else auth_headers(client, keypair)
    signing_keypair = signer or keypair or DEVELOPER_KEYPAIR

    message = build_assignment_message(
        bounty_id=bounty_id,
        transaction_hash=ASSIGN_TX,
        developer_wallet=signing_keypair.public_key,
        developer_github=developer_github,
        contract_id=CONTRACT_ID,
    )

    return client.post(
        f"/bounties/{bounty_id}/assigned",
        json={
            "transaction_hash": ASSIGN_TX,
            "developer_github": developer_github,
            "wallet_signature": sep53_signature(signing_keypair, message),
        },
        headers=headers,
    )


def submit(
    client: TestClient, bounty_id: int, keypair: Keypair | None = DEVELOPER_KEYPAIR
):
    headers = {} if keypair is None else auth_headers(client, keypair)

    return client.post(
        f"/bounties/{bounty_id}/submission",
        json={"pull_request_url": PULL_REQUEST_URL},
        headers=headers,
    )


def run_verification(
    client: TestClient, bounty_id: int, keypair: Keypair | None = DEVELOPER_KEYPAIR
):
    headers = {} if keypair is None else auth_headers(client, keypair)

    return client.post(f"/bounties/{bounty_id}/verify", headers=headers)


def bounty_row(session_factory: sessionmaker[Session], bounty_id: int) -> Bounty:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        db.expunge(bounty)

        return bounty


def count(session_factory: sessionmaker[Session], model: type) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def funded(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    github: FakeGitHub,
) -> int:
    """Task creada por el client y financiada desde su wallet."""
    bounty_id = create_task(client)
    stellar.on_chain = on_chain_for(session_factory, bounty_id)

    assert fund(client, bounty_id).status_code == 200

    # El PR saldra del head que el funding resolvio para la rama base.
    github.base_sha = BRANCH_HEAD_SHA

    return bounty_id


@pytest.fixture
def assigned(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    funded: int,
) -> int:
    stellar.on_chain = on_chain_for(
        session_factory, funded, developer=DEVELOPER_WALLET, status="Assigned"
    )

    assert assign(client, funded).status_code == 200

    return funded


@pytest.fixture
def submitted(client: TestClient, assigned: int) -> int:
    assert submit(client, assigned).status_code == 201

    return assigned


# ─────────────────────────────────────────
# 1 a 4. Creacion de tasks.
# ─────────────────────────────────────────


def test_create_without_session_returns_401(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    response = client.post("/bounties", json=payload())

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert count(session_factory, Bounty) == 0


def test_create_with_session_returns_201(client: TestClient) -> None:
    response = client.post(
        "/bounties", json=payload(), headers=auth_headers(client, CLIENT_KEYPAIR)
    )

    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"


def test_client_wallet_comes_from_the_session(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_task(client, OUTSIDER_KEYPAIR)

    assert bounty_row(session_factory, bounty_id).client_wallet == OUTSIDER_WALLET


def test_body_cannot_choose_the_client_wallet(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_task(client, CLIENT_KEYPAIR, client_wallet=OUTSIDER_WALLET)

    # Un DRAFT solo lo ve su client, asi que la lectura va con su sesion.
    body = client.get(
        f"/bounties/{bounty_id}", headers=auth_headers(client, CLIENT_KEYPAIR)
    ).json()

    assert body["client_wallet"] == CLIENT_WALLET
    assert bounty_row(session_factory, bounty_id).client_wallet == CLIENT_WALLET


# ─────────────────────────────────────────
# 5 a 9. Funding.
# ─────────────────────────────────────────


def test_funding_without_session_returns_401_without_touching_stellar(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_task(client)
    stellar.on_chain = on_chain_for(session_factory, bounty_id)

    response = fund(client, bounty_id, keypair=None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert stellar.builds == 0
    assert bounty_row(session_factory, bounty_id).status == BountyStatus.DRAFT


def test_funding_by_another_wallet_returns_403_without_touching_stellar(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_task(client)
    stellar.on_chain = on_chain_for(session_factory, bounty_id)

    response = fund(client, bounty_id, OUTSIDER_KEYPAIR)

    assert response.status_code == 403
    assert response.json() == {"detail": "Client wallet required for this task"}
    assert stellar.builds == 0
    assert bounty_row(session_factory, bounty_id).status == BountyStatus.DRAFT


def test_funding_by_the_client_keeps_working(
    client: TestClient, session_factory: sessionmaker[Session], funded: int
) -> None:
    bounty = bounty_row(session_factory, funded)

    assert bounty.status == BountyStatus.OPEN_FUNDED
    assert bounty.client_wallet == CLIENT_WALLET
    assert bounty.create_tx_hash == FUNDING_TX
    assert bounty.base_sha == BRANCH_HEAD_SHA


def test_on_chain_client_must_be_the_authenticated_wallet(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    # DRAFT heredado: pasa la comprobacion del router, pero on-chain financio otro.
    bounty_id = draft_bounty(session_factory)
    stellar.on_chain = on_chain_for(
        session_factory, bounty_id, client=OUTSIDER_WALLET
    )

    response = fund(client, bounty_id, CLIENT_KEYPAIR)

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Authenticated wallet does not match funding client"
    }

    # Nada se escribio.
    bounty = bounty_row(session_factory, bounty_id)

    assert bounty.status == BountyStatus.DRAFT
    assert bounty.client_wallet is None
    assert bounty.create_tx_hash is None


def test_legacy_draft_is_claimed_only_by_its_on_chain_funder(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = draft_bounty(session_factory)

    assert bounty_row(session_factory, bounty_id).client_wallet is None

    # El escrow lo creo OUTSIDER, asi que el client no puede reclamarlo.
    stellar.on_chain = on_chain_for(
        session_factory, bounty_id, client=OUTSIDER_WALLET
    )

    assert fund(client, bounty_id, CLIENT_KEYPAIR).status_code == 403

    # Quien financio de verdad si lo reclama, y pasa a ser su client.
    assert fund(client, bounty_id, OUTSIDER_KEYPAIR).status_code == 200

    bounty = bounty_row(session_factory, bounty_id)

    assert bounty.client_wallet == OUTSIDER_WALLET
    assert bounty.status == BountyStatus.OPEN_FUNDED


# ─────────────────────────────────────────
# 10 a 14. Aceptacion.
# ─────────────────────────────────────────


def test_assignment_without_session_returns_401(
    client: TestClient, session_factory: sessionmaker[Session], funded: int
) -> None:
    response = assign(client, funded, keypair=None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert bounty_row(session_factory, funded).status == BountyStatus.OPEN_FUNDED


def test_client_cannot_accept_its_own_task(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    funded: int,
) -> None:
    stellar.builds = 0

    response = assign(client, funded, CLIENT_KEYPAIR)

    assert response.status_code == 403
    assert response.json() == {"detail": "Client wallet cannot accept its own task"}

    # Ni se llego a construir el cliente de Stellar.
    assert stellar.builds == 0
    assert bounty_row(session_factory, funded).status == BountyStatus.OPEN_FUNDED


def test_session_must_match_the_on_chain_developer(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    funded: int,
) -> None:
    # El contrato dice que acepto DEVELOPER, pero firma y sesion son de otro.
    stellar.on_chain = on_chain_for(
        session_factory, funded, developer=DEVELOPER_WALLET, status="Assigned"
    )

    response = assign(client, funded, OUTSIDER_KEYPAIR)

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Authenticated wallet does not match assigned developer"
    }

    bounty = bounty_row(session_factory, funded)

    assert bounty.status == BountyStatus.OPEN_FUNDED
    assert bounty.developer_wallet is None


def test_developer_assignment_keeps_working(
    client: TestClient, session_factory: sessionmaker[Session], assigned: int
) -> None:
    bounty = bounty_row(session_factory, assigned)

    assert bounty.status == BountyStatus.ASSIGNED
    assert bounty.developer_wallet == DEVELOPER_WALLET
    assert bounty.developer_github == DEVELOPER


def test_idempotent_assignment_only_works_for_the_assigned_developer(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    assigned: int,
) -> None:
    reads_before = len(stellar.read_bounties)

    # El developer reintenta: recibe lo ya confirmado sin volver a Stellar.
    repeated = assign(client, assigned, DEVELOPER_KEYPAIR)

    assert repeated.status_code == 200
    assert repeated.json()["developer_wallet"] == DEVELOPER_WALLET
    assert len(stellar.read_bounties) == reads_before

    for intruder in (OUTSIDER_KEYPAIR, CLIENT_KEYPAIR):
        response = assign(client, assigned, intruder)

        assert response.status_code == 403
        assert response.json() == {
            "detail": "Developer wallet required for this task"
        }

    assert bounty_row(session_factory, assigned).developer_wallet == DEVELOPER_WALLET


# ─────────────────────────────────────────
# 15 a 18. Submission.
# ─────────────────────────────────────────


def test_submission_without_session_returns_401(
    client: TestClient, session_factory: sessionmaker[Session], assigned: int
) -> None:
    response = submit(client, assigned, keypair=None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}
    assert count(session_factory, Submission) == 0


@pytest.mark.parametrize("who", ["client", "outsider"])
def test_only_the_developer_can_submit(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    assigned: int,
    who: str,
) -> None:
    del github.requests[:]

    keypair = CLIENT_KEYPAIR if who == "client" else OUTSIDER_KEYPAIR

    response = submit(client, assigned, keypair)

    assert response.status_code == 403
    assert response.json() == {"detail": "Developer wallet required for this task"}

    # Ni se inspecciono el pull request.
    assert github.requests == []
    assert count(session_factory, Submission) == 0


def test_developer_submission_keeps_working(
    client: TestClient, session_factory: sessionmaker[Session], submitted: int
) -> None:
    bounty = bounty_row(session_factory, submitted)

    assert bounty.status == BountyStatus.SUBMITTED
    assert count(session_factory, Submission) == 1


# ─────────────────────────────────────────
# 19 a 25. Verificacion y payout.
# ─────────────────────────────────────────


def test_verification_without_session_returns_401_without_side_effects(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
    submitted: int,
) -> None:
    del github.requests[:]
    builds_before = stellar.builds

    response = run_verification(client, submitted, keypair=None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required"}

    assert github.requests == []
    assert stellar.builds == builds_before
    assert stellar.calls == []
    assert count(session_factory, Verification) == 0


def test_outsider_cannot_run_verification(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
    submitted: int,
) -> None:
    del github.requests[:]

    response = run_verification(client, submitted, OUTSIDER_KEYPAIR)

    assert response.status_code == 403
    assert response.json() == {"detail": "Task participant wallet required"}

    assert github.requests == []
    assert stellar.calls == []
    assert count(session_factory, Verification) == 0


@pytest.mark.parametrize("who", ["client", "developer"])
def test_both_participants_can_run_verification(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    submitted: int,
    who: str,
) -> None:
    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR

    response = run_verification(client, submitted, keypair)

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "PASS"

    # El PASS sigue liberando solo: no hay aprobacion manual de nadie.
    bounty = bounty_row(session_factory, submitted)

    assert bounty.status == BountyStatus.PAID
    assert bounty.release_tx_hash == stellar.transaction_hash
    assert len(stellar.calls) == 1


@pytest.mark.parametrize("who", ["client", "developer"])
def test_evidence_hash_does_not_depend_on_who_verified(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    submitted: int,
    who: str,
) -> None:
    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR

    body = run_verification(client, submitted, keypair).json()
    result = PullRequestVerificationResult.model_validate(body["result"])

    with session_factory() as db:
        bounty = db.get(Bounty, submitted)
        assert bounty is not None
        submission = db.scalars(select(Submission)).one()

        expected = compute_evidence_hash(
            bounty_id=bounty.id,
            repo_owner=bounty.repo_owner,
            repo_name=bounty.repo_name,
            base_branch=bounty.base_branch,
            base_sha=bounty.base_sha,
            criteria_hash=bounty.criteria_hash,
            developer_github=bounty.developer_github,
            pull_request_number=submission.pull_request_number,
            pull_request_url=submission.pull_request_url,
            verification=result,
        )

    called_bounty_id, evidence_hash = stellar.calls[0]

    # La wallet de la sesion no entra en la evidencia ni en la llamada.
    assert called_bounty_id == submitted
    assert evidence_hash == expected


@pytest.mark.parametrize("who", ["client", "developer"])
def test_payout_destination_never_depends_on_the_session(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    submitted: int,
    who: str,
) -> None:
    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR

    assert run_verification(client, submitted, keypair).status_code == 200

    bounty = bounty_row(session_factory, submitted)

    # El contrato paga a su developer; MergePay solo ancla la evidencia.
    assert bounty.developer_wallet == DEVELOPER_WALLET
    assert bounty.client_wallet == CLIENT_WALLET
    assert [call[0] for call in stellar.calls] == [submitted]


# ─────────────────────────────────────────
# 26 a 29. Lecturas publicas.
# ─────────────────────────────────────────


def test_reads_need_no_mutation_permissions(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    submitted: int,
) -> None:
    """Las cuatro lecturas de un participante, sin permisos de mutacion.

    Desde el parche de privacidad una task deja de ser publica al aceptarse,
    asi que aqui se leen con la sesion del developer. Que un tercero no pueda
    verlas lo cubre test_read_privacy_api.
    """
    assert run_verification(client, submitted, DEVELOPER_KEYPAIR).status_code == 200

    stellar.on_chain = on_chain_for(
        session_factory,
        submitted,
        developer=DEVELOPER_WALLET,
        evidence_hash="f0" * 32,
        status="Paid",
    )

    headers = auth_headers(client, DEVELOPER_KEYPAIR)

    assert client.get(f"/bounties/{submitted}", headers=headers).status_code == 200
    assert (
        client.get(f"/bounties/{submitted}/submission", headers=headers).status_code
        == 200
    )
    assert (
        client.get(f"/bounties/{submitted}/verification", headers=headers).status_code
        == 200
    )

    on_chain = client.get(f"/bounties/{submitted}/onchain", headers=headers)

    assert on_chain.status_code == 200
    assert on_chain.json()["contract_status"] == "Paid"

    assert client.get("/bounties").status_code == 200
    assert client.get("/health").status_code == 200


def test_funded_task_reads_stay_public(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    """Mientras espera developer, la oferta y su escrow son publicos."""
    bounty_id = draft_bounty(
        session_factory,
        status=BountyStatus.OPEN_FUNDED,
        client_wallet=CLIENT_WALLET,
        create_tx_hash=FUNDING_TX,
        base_sha="b" * 40,
    )
    stellar.on_chain = on_chain_for(session_factory, bounty_id)

    # Sin cabecera Authorization en ninguna de las dos.
    assert client.get(f"/bounties/{bounty_id}").status_code == 200
    assert client.get(f"/bounties/{bounty_id}/onchain").status_code == 200
    assert [item["id"] for item in client.get("/bounties").json()] == [bounty_id]
