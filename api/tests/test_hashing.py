import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from stellar_sdk import Keypair

from app.hashing import compute_criteria_hash, compute_evidence_hash
from app.models import Bounty
from app.schemas import (
    CriterionCreate,
    PullRequestVerificationResult,
    RequiredCheckResult,
    VerificationStatus,
)

from tests.conftest import sign_in

HEX_64 = re.compile(r"[0-9a-f]{64}")

# Crear tasks exige sesion; el hash de criterios no depende de ella.
CLIENT_KEYPAIR = Keypair.random()


@pytest.fixture(autouse=True)
def authenticated(client: TestClient) -> None:
    sign_in(client, CLIENT_KEYPAIR)

CRITERIA_HASH = "a" * 64


def criteria(*descriptions: str) -> list[CriterionCreate]:
    return [
        CriterionCreate(description=description) for description in descriptions
    ]


def verification_result(
    head_sha: str = "h" * 40,
    status: VerificationStatus = VerificationStatus.PASS,
) -> PullRequestVerificationResult:
    return PullRequestVerificationResult(
        status=status,
        eligible_for_payout=status is VerificationStatus.PASS,
        repository_valid=True,
        base_branch_valid=True,
        base_sha_valid=True,
        developer_valid=True,
        pr_open=True,
        pr_not_draft=True,
        protected_files_valid=True,
        protected_files_modified=[],
        checks=[
            RequiredCheckResult(
                name=name, status="completed", conclusion="success", passed=True
            )
            for name in ("build", "regression-tests", "acceptance-tests")
        ],
        reasons=[],
        head_sha=head_sha,
    )


def evidence_hash(**overrides: object) -> str:
    fields: dict[str, object] = {
        "bounty_id": 7,
        "repo_owner": "acme",
        "repo_name": "demo",
        "base_branch": "main",
        "base_sha": "b" * 40,
        "criteria_hash": CRITERIA_HASH,
        "developer_github": "octodev",
        "pull_request_number": 21,
        "pull_request_url": "https://github.com/acme/demo/pull/21",
        "verification": verification_result(),
    }

    fields.update(overrides)

    return compute_evidence_hash(**fields)  # type: ignore[arg-type]


# ─────────────────────────────────────────
# 1 a 5. Criteria hash.
# ─────────────────────────────────────────


def test_criteria_hash_is_64_lowercase_hex_chars() -> None:
    digest = compute_criteria_hash(criteria("uno", "dos"))

    assert len(digest) == 64
    assert HEX_64.fullmatch(digest)


def test_same_criteria_produce_the_same_hash() -> None:
    assert compute_criteria_hash(criteria("uno", "dos")) == compute_criteria_hash(
        criteria("uno", "dos")
    )


def test_changing_a_description_changes_the_hash() -> None:
    assert compute_criteria_hash(criteria("uno", "dos")) != compute_criteria_hash(
        criteria("uno", "DOS")
    )


def test_changing_required_changes_the_hash() -> None:
    required = [CriterionCreate(description="uno", required=True)]
    optional = [CriterionCreate(description="uno", required=False)]

    assert compute_criteria_hash(required) != compute_criteria_hash(optional)


def test_reordering_criteria_changes_the_hash() -> None:
    assert compute_criteria_hash(criteria("uno", "dos")) != compute_criteria_hash(
        criteria("dos", "uno")
    )


def test_criteria_hash_ignores_everything_but_criteria() -> None:
    # El mismo conjunto de criterios da el mismo hash venga de donde venga.
    digest = compute_criteria_hash(criteria("uno"))

    assert digest == compute_criteria_hash(
        [CriterionCreate(description="uno", required=True)]
    )


def test_non_ascii_descriptions_are_supported() -> None:
    digest = compute_criteria_hash(criteria("añadir año y ñ", "日本語"))

    assert HEX_64.fullmatch(digest)
    assert digest != compute_criteria_hash(criteria("anadir ano y n", "日本語"))


# ─────────────────────────────────────────
# 6 y 7. POST /bounties persiste el criteria_hash.
# ─────────────────────────────────────────


def bounty_payload() -> dict[str, object]:
    return {
        "title": "Arreglar el redirect",
        "description": "El usuario acaba en /home y no en /dashboard.",
        "repo_owner": "mergepay",
        "repo_name": "web",
        "amount_stroops": 100_000_000,
        "deadline_unix": 1_767_225_600,
        "criteria": [
            {"description": "El redirect apunta a /dashboard"},
            {"description": "Hay un test de regresion", "required": False},
        ],
    }


def test_create_bounty_returns_criteria_hash(client: TestClient) -> None:
    response = client.post("/bounties", json=bounty_payload())

    assert response.status_code == 201

    digest = response.json()["criteria_hash"]

    assert digest is not None
    assert HEX_64.fullmatch(digest)


def test_create_bounty_persists_criteria_hash(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    payload = bounty_payload()

    client.post("/bounties", json=payload)

    expected = compute_criteria_hash(
        [
            CriterionCreate(**criterion)  # type: ignore[arg-type]
            for criterion in payload["criteria"]  # type: ignore[union-attr]
        ]
    )

    with session_factory() as db:
        bounty = db.scalars(select(Bounty)).one()

        assert bounty.criteria_hash == expected


# ─────────────────────────────────────────
# 8 a 12. Evidence hash.
# ─────────────────────────────────────────


def test_evidence_hash_is_64_lowercase_hex_chars() -> None:
    digest = evidence_hash()

    assert len(digest) == 64
    assert HEX_64.fullmatch(digest)


def test_same_evidence_produces_the_same_hash() -> None:
    assert evidence_hash() == evidence_hash()


def test_changing_head_sha_changes_the_evidence_hash() -> None:
    assert evidence_hash() != evidence_hash(
        verification=verification_result(head_sha="n" * 40)
    )


def test_changing_criteria_hash_changes_the_evidence_hash() -> None:
    assert evidence_hash() != evidence_hash(criteria_hash="b" * 64)


def test_changing_the_verification_status_changes_the_evidence_hash() -> None:
    assert evidence_hash() != evidence_hash(
        verification=verification_result(status=VerificationStatus.FAIL)
    )


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "a" * 63,
        "a" * 65,
        "z" * 64,
        "not-a-hash",
        " " + "a" * 63,
    ],
)
def test_invalid_criteria_hash_raises_value_error(invalid: str) -> None:
    with pytest.raises(ValueError):
        evidence_hash(criteria_hash=invalid)


def test_uppercase_criteria_hash_is_normalised() -> None:
    # Se acepta en mayusculas, pero entra en el payload en minusculas, asi que
    # ambas formas producen el mismo digest.
    assert evidence_hash(criteria_hash=CRITERIA_HASH.upper()) == evidence_hash()
