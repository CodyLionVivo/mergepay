from typing import Any

import pytest
from fastapi.testclient import TestClient
from stellar_sdk import Keypair

from app.models import Bounty, BountyStatus
from tests.conftest import sign_in

# La wallet que crea las tasks de este modulo. POST /bounties exige sesion, y
# el client del bounty sale de ella.
CLIENT_KEYPAIR = Keypair.random()


@pytest.fixture(autouse=True)
def authenticated(client: TestClient) -> None:
    sign_in(client, CLIENT_KEYPAIR)

AMOUNT_STROOPS = 100_000_000
DEADLINE_UNIX = 1_767_225_600


def payload(**overrides: Any) -> dict[str, Any]:
    """Request valido de POST /bounties, con campos sobreescribibles."""
    body: dict[str, Any] = {
        "title": "Arreglar el redirect tras el login",
        "description": "Tras iniciar sesion el usuario acaba en /home y no en /dashboard.",
        "repo_owner": "mergepay",
        "repo_name": "web",
        "amount_stroops": AMOUNT_STROOPS,
        "deadline_unix": DEADLINE_UNIX,
        "criteria": [
            {"description": "El redirect apunta a /dashboard"},
            {"description": "Hay un test de regresion", "required": False},
        ],
    }

    body.update(overrides)

    return body


# ─────────────────────────────────────────
# 3, 4, 5. Creacion valida.
# ─────────────────────────────────────────


def test_create_bounty_returns_201(client: TestClient) -> None:
    response = client.post("/bounties", json=payload())

    assert response.status_code == 201

    body = response.json()

    assert body["id"] > 0
    assert body["title"] == "Arreglar el redirect tras el login"
    assert body["repo_owner"] == "mergepay"
    assert body["repo_name"] == "web"
    assert body["base_branch"] == "main"


def test_created_bounty_is_draft(client: TestClient) -> None:
    response = client.post("/bounties", json=payload())

    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"


def test_created_bounty_ignores_status_from_request(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(status="PAID"))

    assert response.status_code == 201
    assert response.json()["status"] == "DRAFT"


def test_amount_stroops_is_preserved_exactly(client: TestClient) -> None:
    response = client.post("/bounties", json=payload())

    assert response.status_code == 201
    assert response.json()["amount_stroops"] == AMOUNT_STROOPS


# ─────────────────────────────────────────
# 6. Orden de los criterios.
# ─────────────────────────────────────────


def test_criteria_keep_request_order(client: TestClient) -> None:
    response = client.post("/bounties", json=payload())

    assert response.status_code == 201

    criteria = response.json()["criteria"]

    assert [criterion["position"] for criterion in criteria] == [0, 1]

    assert [criterion["description"] for criterion in criteria] == [
        "El redirect apunta a /dashboard",
        "Hay un test de regresion",
    ]

    assert [criterion["required"] for criterion in criteria] == [True, False]


# ─────────────────────────────────────────
# 7, 8, 9. Lectura.
# ─────────────────────────────────────────


def test_list_bounties_includes_a_funded_bounty(client: TestClient, session_factory) -> None:
    created = client.post("/bounties", json=payload()).json()

    # El marketplace solo lista tasks financiadas: el DRAFT recien creado
    # todavia es privado de su client.
    assert client.get("/bounties").json() == []

    with session_factory() as db:
        bounty = db.get(Bounty, created["id"])
        assert bounty is not None
        bounty.status = BountyStatus.OPEN_FUNDED
        db.commit()

    response = client.get("/bounties")

    assert response.status_code == 200

    body = response.json()

    assert len(body) == 1
    assert body[0]["id"] == created["id"]
    assert len(body[0]["criteria"]) == 2


def test_get_bounty_returns_the_bounty(client: TestClient) -> None:
    created = client.post("/bounties", json=payload()).json()

    response = client.get(f"/bounties/{created['id']}")

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == created["id"]
    assert body["title"] == created["title"]
    assert len(body["criteria"]) == 2


def test_get_unknown_bounty_returns_404(client: TestClient) -> None:
    response = client.get("/bounties/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}


# ─────────────────────────────────────────
# 10 a 14. Validacion del request.
# ─────────────────────────────────────────


def test_zero_amount_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(amount_stroops=0))

    assert response.status_code == 422


def test_negative_amount_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(amount_stroops=-1))

    assert response.status_code == 422


def test_empty_criteria_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(criteria=[]))

    assert response.status_code == 422


def test_empty_criterion_description_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(criteria=[{"description": ""}]))

    assert response.status_code == 422


def test_empty_title_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(title=""))

    assert response.status_code == 422


def test_empty_description_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(description=""))

    assert response.status_code == 422


def test_whitespace_only_description_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(description="   "))

    assert response.status_code == 422


def test_empty_base_branch_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(base_branch=""))

    assert response.status_code == 422


def test_whitespace_only_base_branch_is_rejected(client: TestClient) -> None:
    response = client.post("/bounties", json=payload(base_branch="   "))

    assert response.status_code == 422
