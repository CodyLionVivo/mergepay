"""Privacidad de lectura: quien puede ver cada task y su evidencia.

Una task financiada y sin developer es la oferta publica del marketplace. Un
borrador es privado de su client, y en cuanto se acepta solo la ven client y
developer. A quien no le corresponde, una task privada le responde igual que
una que no existe.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app.assignment_service import build_assignment_message
from app.config import settings
from app.models import Bounty, BountyStatus, Submission, Verification
from app.stellar_client import OnChainBounty
from tests.conftest import (
    BASE_BRANCH,
    BASE_SHA,
    DEVELOPER,
    OWNER,
    PULL_NUMBER,
    REPO,
    FakeStellar,
    auth_headers,
    sep53_signature,
)

CLIENT_KEYPAIR = Keypair.random()
CLIENT_WALLET = CLIENT_KEYPAIR.public_key

DEVELOPER_KEYPAIR = Keypair.random()
DEVELOPER_WALLET = DEVELOPER_KEYPAIR.public_key

# Sesion valida, pero ajena a la task.
VIEWER_KEYPAIR = Keypair.random()

CONTRACT_ID = StrKey.encode_contract(b"\x66" * 32)

CRITERIA_HASH = "c" * 64
CREATE_TX = "ab" * 32
ASSIGN_TX = "a2" * 32
AMOUNT_STROOPS = 100_000_000
DEADLINE_UNIX = 1_767_225_600

PULL_REQUEST_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}"

NOT_FOUND = {"detail": "Bounty not found"}

# Todo lo que deja de ser publico en cuanto la task se acepta.
PRIVATE_ASSIGNED_STATUSES = [
    BountyStatus.ASSIGNED,
    BountyStatus.SUBMITTED,
    BountyStatus.VERIFYING,
    BountyStatus.NEEDS_CHANGES,
    BountyStatus.ELIGIBLE,
    BountyStatus.PAID,
]

HIDDEN_FROM_MARKETPLACE = [
    BountyStatus.DRAFT,
    *PRIVATE_ASSIGNED_STATUSES,
    BountyStatus.CANCELLED_REFUNDED,
    BountyStatus.EXPIRED_REFUNDED,
]


@pytest.fixture(autouse=True)
def configured_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "stellar_contract_id", CONTRACT_ID)


def create_bounty(
    session_factory: sessionmaker[Session],
    status: BountyStatus = BountyStatus.OPEN_FUNDED,
    **overrides: Any,
) -> int:
    """Un bounty con el estado pedido, saltandose la API."""
    assigned = status not in (BountyStatus.DRAFT, BountyStatus.OPEN_FUNDED)

    fields: dict[str, Any] = {
        "title": "Arreglar el redirect tras el login",
        "description": "El usuario acaba en /home y no en /dashboard.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": BASE_BRANCH,
        "base_sha": None if status == BountyStatus.DRAFT else BASE_SHA,
        "criteria_hash": CRITERIA_HASH,
        "client_wallet": CLIENT_WALLET,
        "developer_wallet": DEVELOPER_WALLET if assigned else None,
        "developer_github": DEVELOPER if assigned else None,
        "create_tx_hash": None if status == BountyStatus.DRAFT else CREATE_TX,
        "status": status,
        "amount_stroops": AMOUNT_STROOPS,
        "deadline_unix": DEADLINE_UNIX,
    }

    fields.update(overrides)

    with session_factory() as db:
        bounty = Bounty(**fields)
        db.add(bounty)
        db.commit()

        return bounty.id


def add_submission(session_factory: sessionmaker[Session], bounty_id: int) -> None:
    with session_factory() as db:
        db.add(
            Submission(
                bounty_id=bounty_id,
                pull_request_url=PULL_REQUEST_URL,
                pull_request_number=PULL_NUMBER,
                author=DEVELOPER,
                head_ref="feat/example",
                head_sha="h" * 40,
            )
        )
        db.commit()


def add_verification(session_factory: sessionmaker[Session], bounty_id: int) -> None:
    add_submission(session_factory, bounty_id)

    with session_factory() as db:
        submission = db.query(Submission).filter_by(bounty_id=bounty_id).one()

        db.add(
            Verification(
                submission_id=submission.id,
                head_sha="h" * 40,
                status="PASS",
                eligible_for_payout=True,
                result_json=(
                    '{"status":"PASS","eligible_for_payout":true,'
                    '"repository_valid":true,"base_branch_valid":true,'
                    '"base_sha_valid":true,"developer_valid":true,"pr_open":true,'
                    '"pr_not_draft":true,"protected_files_valid":true,'
                    '"protected_files_modified":[],"checks":[],"reasons":[],'
                    '"head_sha":"' + "h" * 40 + '"}'
                ),
            )
        )
        db.commit()


def on_chain_for(
    session_factory: sessionmaker[Session], bounty_id: int, **overrides: Any
) -> OnChainBounty:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        fields: dict[str, Any] = {
            "client": bounty.client_wallet,
            "developer": bounty.developer_wallet,
            "amount": bounty.amount_stroops,
            "criteria_hash": bounty.criteria_hash,
            "evidence_hash": None,
            "deadline": bounty.deadline_unix,
            "status": "Open" if bounty.developer_wallet is None else "Assigned",
        }

    fields.update(overrides)

    return OnChainBounty(**fields)


def headers_for(client: TestClient, keypair: Keypair | None) -> dict[str, str]:
    return {} if keypair is None else auth_headers(client, keypair)


def read(
    client: TestClient,
    bounty_id: int,
    keypair: Keypair | None = None,
    suffix: str = "",
):
    return client.get(
        f"/bounties/{bounty_id}{suffix}", headers=headers_for(client, keypair)
    )


def listed_ids(client: TestClient, keypair: Keypair | None = None) -> list[int]:
    response = client.get("/bounties", headers=headers_for(client, keypair))

    assert response.status_code == 200

    return [item["id"] for item in response.json()]


# ─────────────────────────────────────────
# 1 a 10. Marketplace: solo OPEN_FUNDED.
# ─────────────────────────────────────────


@pytest.mark.parametrize("status", HIDDEN_FROM_MARKETPLACE)
def test_private_statuses_never_reach_the_marketplace(
    client: TestClient, session_factory: sessionmaker[Session], status: BountyStatus
) -> None:
    hidden = create_bounty(session_factory, status)
    public = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)

    assert listed_ids(client) == [public]
    assert hidden not in listed_ids(client)


def test_funded_task_is_listed(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)

    body = client.get("/bounties").json()

    assert [item["id"] for item in body] == [bounty_id]
    assert body[0]["status"] == BountyStatus.OPEN_FUNDED


@pytest.mark.parametrize("who", ["client", "developer", "viewer"])
def test_authentication_never_adds_private_tasks_to_the_marketplace(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    draft = create_bounty(session_factory, BountyStatus.DRAFT)
    assigned = create_bounty(session_factory, BountyStatus.ASSIGNED)
    public = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)

    keypair = {
        "client": CLIENT_KEYPAIR,
        "developer": DEVELOPER_KEYPAIR,
        "viewer": VIEWER_KEYPAIR,
    }[who]

    # Ni siquiera sus propias tasks privadas: el marketplace es discovery.
    assert listed_ids(client, keypair) == [public]
    assert draft not in listed_ids(client, keypair)
    assert assigned not in listed_ids(client, keypair)


def test_marketplace_keeps_the_id_order(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    first = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)
    create_bounty(session_factory, BountyStatus.DRAFT)
    third = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)

    assert listed_ids(client) == [first, third]


# ─────────────────────────────────────────
# 11 a 13. Detalle de un borrador.
# ─────────────────────────────────────────


def test_draft_is_hidden_from_anonymous_readers(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.DRAFT)

    response = read(client, bounty_id)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_draft_is_visible_to_its_client(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.DRAFT)

    response = read(client, bounty_id, CLIENT_KEYPAIR)

    assert response.status_code == 200
    assert response.json()["id"] == bounty_id


@pytest.mark.parametrize("who", ["viewer", "developer"])
def test_draft_is_hidden_from_other_wallets(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    # Ni siquiera quien sera developer de otras tasks ve un borrador ajeno.
    bounty_id = create_bounty(session_factory, BountyStatus.DRAFT)
    keypair = VIEWER_KEYPAIR if who == "viewer" else DEVELOPER_KEYPAIR

    response = read(client, bounty_id, keypair)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


# ─────────────────────────────────────────
# 14 a 16. Detalle de una task financiada.
# ─────────────────────────────────────────


@pytest.mark.parametrize("who", ["anonymous", "client", "viewer"])
def test_funded_task_is_public(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)
    keypair = {
        "anonymous": None,
        "client": CLIENT_KEYPAIR,
        "viewer": VIEWER_KEYPAIR,
    }[who]

    response = read(client, bounty_id, keypair)

    assert response.status_code == 200
    assert response.json()["id"] == bounty_id


# ─────────────────────────────────────────
# 17 a 20. Detalle desde ASSIGNED en adelante.
# ─────────────────────────────────────────


@pytest.mark.parametrize("status", PRIVATE_ASSIGNED_STATUSES)
def test_assigned_task_is_hidden_from_anonymous_readers(
    client: TestClient, session_factory: sessionmaker[Session], status: BountyStatus
) -> None:
    bounty_id = create_bounty(session_factory, status)

    response = read(client, bounty_id)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("status", PRIVATE_ASSIGNED_STATUSES)
def test_assigned_task_is_hidden_from_a_viewer(
    client: TestClient, session_factory: sessionmaker[Session], status: BountyStatus
) -> None:
    bounty_id = create_bounty(session_factory, status)

    response = read(client, bounty_id, VIEWER_KEYPAIR)

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("status", PRIVATE_ASSIGNED_STATUSES)
@pytest.mark.parametrize("who", ["client", "developer"])
def test_participants_still_see_the_task(
    client: TestClient,
    session_factory: sessionmaker[Session],
    status: BountyStatus,
    who: str,
) -> None:
    bounty_id = create_bounty(session_factory, status)
    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR

    response = read(client, bounty_id, keypair)

    assert response.status_code == 200
    assert response.json()["status"] == status


# ─────────────────────────────────────────
# 21 a 27. Submission y verification.
# ─────────────────────────────────────────


@pytest.mark.parametrize("who", ["anonymous", "viewer"])
def test_submission_of_a_private_task_is_hidden(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.SUBMITTED)
    add_submission(session_factory, bounty_id)

    keypair = None if who == "anonymous" else VIEWER_KEYPAIR
    response = read(client, bounty_id, keypair, "/submission")

    # El motivo es la task, no la submission: no se confirma que exista.
    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("who", ["client", "developer"])
def test_participants_read_the_submission(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.SUBMITTED)
    add_submission(session_factory, bounty_id)

    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR
    response = read(client, bounty_id, keypair, "/submission")

    assert response.status_code == 200
    assert response.json()["pull_request_url"] == PULL_REQUEST_URL


def test_participant_without_submission_still_gets_submission_not_found(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.ASSIGNED)

    response = read(client, bounty_id, CLIENT_KEYPAIR, "/submission")

    assert response.status_code == 404
    assert response.json() == {"detail": "Submission not found"}


@pytest.mark.parametrize("who", ["anonymous", "viewer"])
def test_verification_of_a_private_task_is_hidden(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.PAID)
    add_verification(session_factory, bounty_id)

    keypair = None if who == "anonymous" else VIEWER_KEYPAIR
    response = read(client, bounty_id, keypair, "/verification")

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


@pytest.mark.parametrize("who", ["client", "developer"])
def test_participants_read_the_verification(
    client: TestClient, session_factory: sessionmaker[Session], who: str
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.PAID)
    add_verification(session_factory, bounty_id)

    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR
    response = read(client, bounty_id, keypair, "/verification")

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "PASS"


def test_participant_without_verification_gets_verification_not_found(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.SUBMITTED)
    add_submission(session_factory, bounty_id)

    response = read(client, bounty_id, DEVELOPER_KEYPAIR, "/verification")

    assert response.status_code == 404
    assert response.json() == {"detail": "Verification not found"}


# ─────────────────────────────────────────
# 28 a 33. Evidencia on-chain.
# ─────────────────────────────────────────


@pytest.mark.parametrize("who", ["anonymous", "viewer"])
def test_onchain_of_a_private_task_is_hidden(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    who: str,
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.PAID)
    stellar.on_chain = on_chain_for(session_factory, bounty_id, status="Paid")

    keypair = None if who == "anonymous" else VIEWER_KEYPAIR
    response = read(client, bounty_id, keypair, "/onchain")

    assert response.status_code == 404
    assert response.json() == NOT_FOUND

    # Ni se construye el cliente ni se consulta el contrato.
    assert stellar.builds == 0
    assert stellar.read_bounties == []


@pytest.mark.parametrize("who", ["client", "developer"])
def test_participants_read_the_on_chain_evidence(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    who: str,
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.PAID)
    stellar.on_chain = on_chain_for(
        session_factory, bounty_id, evidence_hash="f0" * 32, status="Paid"
    )

    keypair = CLIENT_KEYPAIR if who == "client" else DEVELOPER_KEYPAIR
    response = read(client, bounty_id, keypair, "/onchain")

    assert response.status_code == 200

    body = response.json()

    assert body["contract_status"] == "Paid"
    assert body["evidence_hash"] == "f0" * 32
    assert body["contract_id"] == CONTRACT_ID
    assert stellar.read_bounties == [bounty_id]


def test_funded_task_on_chain_evidence_stays_public(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)
    stellar.on_chain = on_chain_for(session_factory, bounty_id)

    response = read(client, bounty_id, None, "/onchain")

    assert response.status_code == 200
    assert response.json()["contract_status"] == "Open"
    assert response.json()["client_wallet"] == CLIENT_WALLET


# ─────────────────────────────────────────
# 34 a 38. La transicion al aceptar la task.
# ─────────────────────────────────────────


def assign(client: TestClient, bounty_id: int):
    message = build_assignment_message(
        bounty_id=bounty_id,
        transaction_hash=ASSIGN_TX,
        developer_wallet=DEVELOPER_WALLET,
        developer_github=DEVELOPER,
        contract_id=CONTRACT_ID,
    )

    return client.post(
        f"/bounties/{bounty_id}/assigned",
        json={
            "transaction_hash": ASSIGN_TX,
            "developer_github": DEVELOPER,
            "wallet_signature": sep53_signature(DEVELOPER_KEYPAIR, message),
        },
        headers=auth_headers(client, DEVELOPER_KEYPAIR),
    )


def test_accepting_a_task_makes_it_private(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)

    # Antes: en el marketplace y visible para cualquiera.
    assert listed_ids(client) == [bounty_id]
    assert read(client, bounty_id).status_code == 200

    stellar.on_chain = on_chain_for(
        session_factory, bounty_id, developer=DEVELOPER_WALLET, status="Assigned"
    )

    assert assign(client, bounty_id).status_code == 200

    # Despues: fuera del marketplace y solo para quienes participan.
    assert listed_ids(client) == []
    assert read(client, bounty_id).status_code == 404
    assert read(client, bounty_id, VIEWER_KEYPAIR).status_code == 404
    assert read(client, bounty_id, CLIENT_KEYPAIR).status_code == 200
    assert read(client, bounty_id, DEVELOPER_KEYPAIR).status_code == 200


# ─────────────────────────────────────────
# 39. Una task privada y una inexistente son indistinguibles.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "suffix", ["", "/submission", "/verification", "/onchain"]
)
@pytest.mark.parametrize("status", [BountyStatus.DRAFT, BountyStatus.PAID])
def test_private_and_missing_tasks_answer_the_same(
    client: TestClient,
    session_factory: sessionmaker[Session],
    status: BountyStatus,
    suffix: str,
) -> None:
    bounty_id = create_bounty(session_factory, status)
    add_verification(session_factory, bounty_id)

    private = read(client, bounty_id, VIEWER_KEYPAIR, suffix)
    missing = read(client, 999_999, VIEWER_KEYPAIR, suffix)

    assert private.status_code == missing.status_code == 404
    assert private.json() == missing.json() == NOT_FOUND


def test_an_invalid_session_reads_like_an_anonymous_one(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, BountyStatus.ASSIGNED)

    # Token caducado, revocado o inventado: ninguno da acceso, y ninguno
    # convierte la lectura en un 401.
    for header in ({"Authorization": "Bearer nope"}, {"Authorization": "Basic x"}):
        response = client.get(f"/bounties/{bounty_id}", headers=header)

        assert response.status_code == 404
        assert response.json() == NOT_FOUND

    # Y una task publica se sigue leyendo con esa misma cabecera inservible.
    public = create_bounty(session_factory, BountyStatus.OPEN_FUNDED)

    assert (
        client.get(
            f"/bounties/{public}", headers={"Authorization": "Bearer nope"}
        ).status_code
        == 200
    )
