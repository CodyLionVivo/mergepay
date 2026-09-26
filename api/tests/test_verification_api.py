import re
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from stellar_sdk import Keypair, StrKey

from app import stellar_client, verification_service
from app.hashing import compute_evidence_hash
from app.models import Bounty, BountyStatus, Submission, Verification
from app.schemas import PullRequestVerificationResult, VerificationStatus
from app.stellar_client import (
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)
from app.verification_service import VERIFIABLE_STATUSES
from tests.conftest import (
    BASE_BRANCH,
    sign_in,
    BASE_SHA,
    DEVELOPER,
    HEAD_SHA,
    OWNER,
    PULL_NUMBER,
    REPO,
    SENSITIVE_RPC_URL,
    DownSorobanServer,
    FakeGitHub,
    FakeStellar,
    changed_file,
    check_run,
    passing_check_runs,
)

PULL_REQUEST_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}"

# Keypair real del developer asignado: abre la sesion de estos tests.
DEVELOPER_KEYPAIR = Keypair.random()
DEVELOPER_WALLET = DEVELOPER_KEYPAIR.public_key
CLIENT_WALLET = Keypair.random().public_key


@pytest.fixture(autouse=True)
def authenticated(client: TestClient) -> None:
    """Registrar el PR y verificar exigen sesion del developer asignado."""
    sign_in(client, DEVELOPER_KEYPAIR)

NEW_HEAD_SHA = "n" * 40
CRITERIA_HASH = "c" * 64


def create_bounty(session_factory: sessionmaker[Session], **overrides: Any) -> int:
    """Inserta un bounty listo para recibir submission, saltandose la API."""
    fields: dict[str, Any] = {
        "title": "Arreglar el redirect tras el login",
        "description": "El usuario acaba en /home y no en /dashboard.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "criteria_hash": CRITERIA_HASH,
        "developer_github": DEVELOPER,
        "developer_wallet": DEVELOPER_WALLET,
        "client_wallet": CLIENT_WALLET,
        "status": BountyStatus.ASSIGNED,
        "amount_stroops": 100_000_000,
        "deadline_unix": 1_767_225_600,
    }

    fields.update(overrides)

    with session_factory() as db:
        bounty = Bounty(**fields)
        db.add(bounty)
        db.commit()

        return bounty.id


def submit(client: TestClient, bounty_id: int, url: str = PULL_REQUEST_URL):
    return client.post(
        f"/bounties/{bounty_id}/submission", json={"pull_request_url": url}
    )


def count(session_factory: sessionmaker[Session], model: type) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


def bounty_status(session_factory: sessionmaker[Session], bounty_id: int) -> str:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        return bounty.status


# ─────────────────────────────────────────
# 1 a 4. Precondiciones del bounty.
# ─────────────────────────────────────────


def test_submission_on_unknown_bounty_returns_404(client: TestClient) -> None:
    response = submit(client, 999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}


@pytest.mark.parametrize(
    "status",
    [
        BountyStatus.DRAFT,
        BountyStatus.OPEN_FUNDED,
        BountyStatus.SUBMITTED,
        BountyStatus.PAID,
    ],
)
def test_submission_requires_assigned_status(
    client: TestClient, session_factory: sessionmaker[Session], status: BountyStatus
) -> None:
    bounty_id = create_bounty(session_factory, status=status)

    response = submit(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not accepting submissions"}
    assert count(session_factory, Submission) == 0


def test_submission_requires_base_sha(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, base_sha=None)

    response = submit(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not ready for submission"}
    assert count(session_factory, Submission) == 0


def test_submission_requires_developer_github(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, developer_github=None)

    response = submit(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not ready for submission"}
    assert count(session_factory, Submission) == 0


# ─────────────────────────────────────────
# 5 a 9. Submission valida.
# ─────────────────────────────────────────


def test_valid_submission_returns_201(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    response = submit(client, bounty_id)

    assert response.status_code == 201

    body = response.json()

    assert body["bounty_id"] == bounty_id
    assert body["pull_request_url"] == PULL_REQUEST_URL
    assert body["author"] == DEVELOPER
    assert body["head_ref"] == "feat/example"


def test_submission_stores_pull_request_number(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    assert submit(client, bounty_id).json()["pull_request_number"] == PULL_NUMBER

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        assert bounty.pull_request_number == PULL_NUMBER
        assert bounty.submission is not None
        assert bounty.submission.pull_request_number == PULL_NUMBER


def test_submission_stores_head_sha(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    assert submit(client, bounty_id).json()["head_sha"] == HEAD_SHA

    with session_factory() as db:
        submission = db.scalars(select(Submission)).one()
        assert submission.head_sha == HEAD_SHA


def test_submission_moves_bounty_to_submitted(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    submit(client, bounty_id)

    assert bounty_status(session_factory, bounty_id) == BountyStatus.SUBMITTED


def test_second_submission_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    assert submit(client, bounty_id).status_code == 201

    # El bounty ya no esta ASSIGNED, asi que gana esa comprobacion.
    assert submit(client, bounty_id).status_code == 409

    # Con el bounty forzado de vuelta a ASSIGNED sale el conflicto de submission.
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        bounty.status = BountyStatus.ASSIGNED
        db.commit()

    response = submit(client, bounty_id)

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty already has a submission"}
    assert count(session_factory, Submission) == 1


# ─────────────────────────────────────────
# 10 a 15. Estructura del PR rechazada antes de persistir.
# ─────────────────────────────────────────


def assert_rejected_without_persisting(
    response: httpx.Response,
    session_factory: sessionmaker[Session],
    bounty_id: int,
    expected_reason: str,
) -> None:
    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail["message"] == "Pull request does not match bounty"
    assert expected_reason in detail["reasons"]

    # Los checks no se consultaron, asi que no deben aparecer como motivo.
    assert not any(
        reason.startswith("Required check") for reason in detail["reasons"]
    )

    assert count(session_factory, Submission) == 0
    assert bounty_status(session_factory, bounty_id) == BountyStatus.ASSIGNED


def test_wrong_repository_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    response = submit(
        client, bounty_id, f"https://github.com/someone-else/{REPO}/pull/{PULL_NUMBER}"
    )

    assert_rejected_without_persisting(
        response, session_factory, bounty_id, "Repository does not match bounty"
    )


def test_wrong_base_branch_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.base_ref = "develop"

    assert_rejected_without_persisting(
        submit(client, bounty_id),
        session_factory,
        bounty_id,
        "Base branch does not match bounty",
    )


def test_wrong_base_sha_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.base_sha = "c" * 40

    assert_rejected_without_persisting(
        submit(client, bounty_id),
        session_factory,
        bounty_id,
        "Base SHA does not match bounty",
    )


def test_wrong_developer_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.author = "someone-else"

    assert_rejected_without_persisting(
        submit(client, bounty_id),
        session_factory,
        bounty_id,
        "Pull request author does not match assigned developer",
    )


def test_protected_file_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.files = [changed_file("app/main.py"), changed_file("requirements.txt")]

    assert_rejected_without_persisting(
        submit(client, bounty_id),
        session_factory,
        bounty_id,
        "Protected files were modified",
    )


def test_draft_pull_request_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.draft = True

    assert_rejected_without_persisting(
        submit(client, bounty_id),
        session_factory,
        bounty_id,
        "Pull request is a draft",
    )


def test_closed_pull_request_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.state = "closed"

    assert_rejected_without_persisting(
        submit(client, bounty_id),
        session_factory,
        bounty_id,
        "Pull request is not open",
    )


# ─────────────────────────────────────────
# 16 y 17. Errores de GitHub durante la submission.
# ─────────────────────────────────────────


def test_invalid_url_is_rejected(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    response = submit(client, bounty_id, "https://example.com/acme/demo/pull/21")

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid GitHub pull request URL"}
    assert count(session_factory, Submission) == 0


def test_github_404_becomes_http_404(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)
    github.pull_response = httpx.Response(404, json={})

    response = submit(client, bounty_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Pull request not found on GitHub"}
    assert count(session_factory, Submission) == 0


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_github_outage_becomes_502(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    status_code: int,
) -> None:
    bounty_id = create_bounty(session_factory)
    github.pull_response = httpx.Response(status_code, json={})

    response = submit(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub verification service unavailable"}
    assert count(session_factory, Submission) == 0


# ─────────────────────────────────────────
# 18 a 25. Verificacion.
# ─────────────────────────────────────────


def submitted_bounty(
    client: TestClient, session_factory: sessionmaker[Session]
) -> int:
    bounty_id = create_bounty(session_factory)

    assert submit(client, bounty_id).status_code == 201

    return bounty_id


def test_verify_without_submission_returns_409(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory, status=BountyStatus.SUBMITTED)

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty has no submission"}


def test_verify_on_unknown_bounty_returns_404(client: TestClient) -> None:
    response = client.post("/bounties/999/verify")

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}


def test_verify_from_invalid_state_returns_409(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        bounty.status = BountyStatus.PAID
        db.commit()

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Bounty cannot be verified in its current state"
    }
    assert count(session_factory, Verification) == 0


@pytest.mark.parametrize(
    "status",
    [
        BountyStatus.SUBMITTED,
        BountyStatus.NEEDS_CHANGES,
        BountyStatus.VERIFYING,
        BountyStatus.ELIGIBLE,
    ],
)
def test_verify_is_allowed_from_every_verifiable_state(
    client: TestClient, session_factory: sessionmaker[Session], status: BountyStatus
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        bounty.status = status
        db.commit()

    assert client.post(f"/bounties/{bounty_id}/verify").status_code == 200


def test_failing_check_creates_verification_and_needs_changes(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 200

    body = response.json()

    assert body["result"]["status"] == VerificationStatus.FAIL
    assert body["result"]["eligible_for_payout"] is False
    assert body["bounty_id"] == bounty_id

    assert count(session_factory, Verification) == 1
    assert bounty_status(session_factory, bounty_id) == BountyStatus.NEEDS_CHANGES


def test_pending_check_moves_bounty_to_verifying(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", status="in_progress", conclusion=None),
    ]

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.json()["result"]["status"] == VerificationStatus.PENDING
    assert bounty_status(session_factory, bounty_id) == BountyStatus.VERIFYING


def test_missing_check_moves_bounty_to_verifying(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = []

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.json()["result"]["status"] == VerificationStatus.PENDING
    assert bounty_status(session_factory, bounty_id) == BountyStatus.VERIFYING


def test_passing_checks_pay_the_bounty(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    response = client.post(f"/bounties/{bounty_id}/verify")

    body = response.json()

    assert body["result"]["status"] == VerificationStatus.PASS
    assert body["result"]["eligible_for_payout"] is True
    assert body["result"]["reasons"] == []

    # ELIGIBLE es solo el paso intermedio: el payout deja el bounty en PAID.
    assert bounty_status(session_factory, bounty_id) == BountyStatus.PAID

    with session_factory() as db:
        verification = db.scalars(select(Verification)).one()
        assert verification.status == VerificationStatus.PASS
        assert verification.eligible_for_payout is True


# ─────────────────────────────────────────
# 26 y 27. result_json.
# ─────────────────────────────────────────


def test_result_json_stores_the_whole_result(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    client.post(f"/bounties/{bounty_id}/verify")

    with session_factory() as db:
        verification = db.scalars(select(Verification)).one()

        stored = PullRequestVerificationResult.model_validate_json(
            verification.result_json
        )

    assert stored.status is VerificationStatus.PASS
    assert stored.head_sha == HEAD_SHA
    assert [check.name for check in stored.checks] == [
        "build",
        "regression-tests",
        "acceptance-tests",
    ]
    assert all(check.passed for check in stored.checks)
    assert stored.protected_files_modified == []


def test_response_rebuilds_the_verification_result(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    # El cliente recibe el resultado tipado, no el result_json en crudo.
    assert "result_json" not in body

    result = PullRequestVerificationResult.model_validate(body["result"])

    assert result.status is VerificationStatus.PASS
    assert result.head_sha == HEAD_SHA
    assert len(result.checks) == 3


# ─────────────────────────────────────────
# 28 a 32. Reintentos y head SHA.
# ─────────────────────────────────────────


def test_second_verification_adds_a_row_instead_of_overwriting(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]

    first = client.post(f"/bounties/{bounty_id}/verify").json()

    github.check_runs = passing_check_runs()

    second = client.post(f"/bounties/{bounty_id}/verify").json()

    assert first["id"] != second["id"]
    assert first["result"]["status"] == VerificationStatus.FAIL
    assert second["result"]["status"] == VerificationStatus.PASS

    assert count(session_factory, Verification) == 2


def test_new_head_sha_updates_submission_and_keeps_history(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]

    client.post(f"/bounties/{bounty_id}/verify")

    # El developer hace push: commit nuevo y checks nuevos en verde.
    github.set_head_sha(NEW_HEAD_SHA)

    client.post(f"/bounties/{bounty_id}/verify")

    with session_factory() as db:
        submission = db.scalars(select(Submission)).one()

        assert submission.head_sha == NEW_HEAD_SHA

        verifications = submission.verifications

        assert len(verifications) == 2

        # Cada verificacion conserva su propio head SHA.
        assert verifications[0].head_sha == HEAD_SHA
        assert verifications[0].status == VerificationStatus.FAIL

        assert verifications[1].head_sha == NEW_HEAD_SHA
        assert verifications[1].status == VerificationStatus.PASS

    assert bounty_status(session_factory, bounty_id) == BountyStatus.PAID


def test_verify_inspects_the_pull_request_on_every_call(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    pull_path = f"/repos/{OWNER}/{REPO}/pulls/{PULL_NUMBER}"

    # Se mantiene en FAIL para que el bounty siga siendo verificable: un PASS
    # lo dejaria en PAID y la segunda llamada seria 409.
    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]

    del github.requests[:]

    client.post(f"/bounties/{bounty_id}/verify")
    client.post(f"/bounties/{bounty_id}/verify")

    assert github.paths().count(pull_path) == 2


def test_check_runs_use_the_freshly_inspected_head_sha(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.set_head_sha(NEW_HEAD_SHA)

    del github.requests[:]

    client.post(f"/bounties/{bounty_id}/verify")

    check_run_paths = [path for path in github.paths() if path.endswith("/check-runs")]

    assert check_run_paths == [
        f"/repos/{OWNER}/{REPO}/commits/{NEW_HEAD_SHA}/check-runs"
    ]


# ─────────────────────────────────────────
# 33 y 34. Errores durante verify.
# ─────────────────────────────────────────


def test_github_failure_during_verify_creates_no_verification(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs_response = httpx.Response(500, json={})

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 502
    assert count(session_factory, Verification) == 0

    # El bounty tampoco se movio.
    assert bounty_status(session_factory, bounty_id) == BountyStatus.SUBMITTED


def duplicated_runs(
    name: str,
    older: dict[str, Any],
    newer: dict[str, Any],
) -> list[dict[str, Any]]:
    """Los obligatorios en verde, con los de `name` sustituidos por dos runs."""
    others = [
        check_run(other) for other in ("build", "regression-tests", "acceptance-tests")
        if other != name
    ]

    return others + [older, newer]


def test_duplicate_required_checks_no_longer_return_409(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [*passing_check_runs(), check_run("build", run_id=2)]

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 200
    assert "Duplicate" not in response.text

    assert count(session_factory, Verification) == 1


def test_duplicate_checks_with_the_newest_passing_verify_pass(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = duplicated_runs(
        "build",
        check_run(
            "build",
            conclusion="failure",
            run_id=1,
            started_at="2026-03-10T12:00:00Z",
        ),
        check_run("build", run_id=2, started_at="2026-03-10T12:10:00Z"),
    )

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    assert body["result"]["status"] == VerificationStatus.PASS
    assert body["result"]["eligible_for_payout"] is True

    build = [check for check in body["result"]["checks"] if check["name"] == "build"]

    assert len(build) == 1
    assert build[0]["conclusion"] == "success"

    assert bounty_status(session_factory, bounty_id) == BountyStatus.PAID


def test_duplicate_checks_with_the_newest_failing_need_changes(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = duplicated_runs(
        "build",
        check_run("build", run_id=1, started_at="2026-03-10T12:00:00Z"),
        check_run(
            "build",
            conclusion="failure",
            run_id=2,
            started_at="2026-03-10T12:10:00Z",
        ),
    )

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    assert body["result"]["status"] == VerificationStatus.FAIL

    assert bounty_status(session_factory, bounty_id) == BountyStatus.NEEDS_CHANGES

    # Un FAIL no paga.
    assert stellar.calls == []


def test_duplicate_checks_with_the_newest_in_progress_are_verifying(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = duplicated_runs(
        "build",
        check_run("build", run_id=1, started_at="2026-03-10T12:00:00Z"),
        check_run(
            "build",
            status="in_progress",
            conclusion=None,
            run_id=2,
            started_at="2026-03-10T12:10:00Z",
        ),
    )

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    assert body["result"]["status"] == VerificationStatus.PENDING

    assert bounty_status(session_factory, bounty_id) == BountyStatus.VERIFYING

    assert stellar.calls == []


def test_duplicate_checks_release_the_payout_exactly_once(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = duplicated_runs(
        "build",
        check_run(
            "build",
            conclusion="failure",
            run_id=1,
            started_at="2026-03-10T12:00:00Z",
        ),
        check_run("build", run_id=2, started_at="2026-03-10T12:10:00Z"),
    )

    client.post(f"/bounties/{bounty_id}/verify")

    assert len(stellar.calls) == 1
    assert stellar.calls[0][0] == bounty_id


def test_duplicate_checks_write_a_single_verification_row(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = duplicated_runs(
        "build",
        check_run(
            "build",
            conclusion="failure",
            run_id=1,
            started_at="2026-03-10T12:00:00Z",
        ),
        check_run("build", run_id=2, started_at="2026-03-10T12:10:00Z"),
    )

    client.post(f"/bounties/{bounty_id}/verify")

    with session_factory() as db:
        verification = db.scalars(select(Verification)).one()

        result = PullRequestVerificationResult.model_validate_json(
            verification.result_json
        )

    # Una sola fila, y con el resultado del run seleccionado.
    assert result.status is VerificationStatus.PASS
    assert len(result.checks) == 3


def test_evidence_hash_uses_the_selected_duplicate_result(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = duplicated_runs(
        "build",
        check_run(
            "build",
            conclusion="failure",
            run_id=1,
            started_at="2026-03-10T12:00:00Z",
        ),
        check_run("build", run_id=2, started_at="2026-03-10T12:10:00Z"),
    )

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    result = PullRequestVerificationResult.model_validate(body["result"])

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
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

    # El hash ancla el resultado del run elegido, no el del descartado.
    assert stellar.calls[0][1] == expected


def test_check_runs_from_another_commit_do_not_count(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [
        *passing_check_runs(),
        # Mas nuevo y en rojo, pero de otro commit: no es candidato.
        check_run(
            "build",
            conclusion="failure",
            run_id=99,
            started_at="2026-03-10T23:00:00Z",
            head_sha="w" * 40,
        ),
    ]

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    assert body["result"]["status"] == VerificationStatus.PASS
    assert bounty_status(session_factory, bounty_id) == BountyStatus.PAID


def test_too_many_check_runs_returns_422(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs_response = httpx.Response(
        200, json={"total_count": 101, "check_runs": []}
    )

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Pull request exceeds MergePay MVP check run limit"
    }
    assert count(session_factory, Verification) == 0


# ─────────────────────────────────────────
# 35 a 37. Ultima verificacion.
# ─────────────────────────────────────────


def test_latest_verification_on_unknown_bounty_returns_404(
    client: TestClient,
) -> None:
    response = client.get("/bounties/999/verification")

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}


def test_latest_verification_without_any_returns_404(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    response = client.get(f"/bounties/{bounty_id}/verification")

    assert response.status_code == 404
    assert response.json() == {"detail": "Verification not found"}


def test_latest_verification_returns_the_only_one(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    created = client.post(f"/bounties/{bounty_id}/verify").json()

    response = client.get(f"/bounties/{bounty_id}/verification")

    assert response.status_code == 200

    body = response.json()

    assert body["id"] == created["id"]
    assert body["bounty_id"] == bounty_id
    assert body["result"]["status"] == VerificationStatus.PASS


def test_latest_verification_returns_the_most_recent(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]

    client.post(f"/bounties/{bounty_id}/verify")

    github.set_head_sha(NEW_HEAD_SHA)

    second = client.post(f"/bounties/{bounty_id}/verify").json()

    body = client.get(f"/bounties/{bounty_id}/verification").json()

    assert body["id"] == second["id"]
    assert body["result"]["status"] == VerificationStatus.PASS
    assert body["result"]["head_sha"] == NEW_HEAD_SHA


# ─────────────────────────────────────────
# 38 y 39. Relaciones persistidas.
# ─────────────────────────────────────────


def test_bounty_to_submission_is_one_to_one(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    with session_factory() as db:
        db.add(
            Submission(
                bounty_id=bounty_id,
                pull_request_url=PULL_REQUEST_URL,
                pull_request_number=99,
                author=DEVELOPER,
                head_ref="feat/other",
                head_sha="z" * 40,
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    assert count(session_factory, Submission) == 1


def test_submission_to_verification_is_one_to_many(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    # La primera pasada falla para que el bounty siga siendo verificable.
    github.check_runs = [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]

    client.post(f"/bounties/{bounty_id}/verify")

    github.set_head_sha(NEW_HEAD_SHA)

    client.post(f"/bounties/{bounty_id}/verify")

    with session_factory() as db:
        submission = db.scalars(select(Submission)).one()

        assert len(submission.verifications) == 2

        # Ordenadas cronologicamente por id.
        ids = [verification.id for verification in submission.verifications]
        assert ids == sorted(ids)

        assert all(
            verification.submission_id == submission.id
            for verification in submission.verifications
        )


# ─────────────────────────────────────────
# Payout: Stellar solo en PASS.
# ─────────────────────────────────────────


def failing_checks() -> list[dict[str, Any]]:
    return [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", conclusion="failure"),
    ]


def pending_checks() -> list[dict[str, Any]]:
    return [
        check_run("build"),
        check_run("regression-tests"),
        check_run("acceptance-tests", status="in_progress", conclusion=None),
    ]


def read_bounty_payout(
    session_factory: sessionmaker[Session], bounty_id: int
) -> tuple[str, str | None]:
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        return bounty.status, bounty.release_tx_hash


# ─────────────────────────────────────────
# 1 a 4. FAIL y PENDING no tocan Stellar.
# ─────────────────────────────────────────


@pytest.mark.parametrize("checks", ["failing", "pending"])
def test_non_passing_result_never_touches_stellar(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
    checks: str,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = failing_checks() if checks == "failing" else pending_checks()

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 200

    # Ni se construye el cliente ni se llama al contrato.
    assert stellar.builds == 0
    assert stellar.calls == []

    expected = (
        BountyStatus.NEEDS_CHANGES if checks == "failing" else BountyStatus.VERIFYING
    )

    status, release_tx_hash = read_bounty_payout(session_factory, bounty_id)

    assert status == expected
    assert release_tx_hash is None


def test_non_passing_result_works_without_stellar_configuration(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = failing_checks()
    stellar.configuration_error = StellarConfigurationError("no configurado")

    assert client.post(f"/bounties/{bounty_id}/verify").status_code == 200
    assert stellar.builds == 0


# ─────────────────────────────────────────
# 5 a 9. PASS llega a Stellar con la evidencia correcta.
# ─────────────────────────────────────────


def test_pass_builds_the_client_and_releases_once(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    client.post(f"/bounties/{bounty_id}/verify")

    assert stellar.builds == 1
    assert len(stellar.calls) == 1

    called_bounty_id, evidence_hash = stellar.calls[0]

    assert called_bounty_id == bounty_id
    assert len(evidence_hash) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", evidence_hash)


def test_evidence_hash_matches_compute_evidence_hash(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    result = PullRequestVerificationResult.model_validate(body["result"])

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
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

    assert stellar.calls[0][1] == expected


# ─────────────────────────────────────────
# 10 a 13 y 31. Payout con exito.
# ─────────────────────────────────────────


def test_successful_payout_marks_the_bounty_paid(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    stellar.transaction_hash = "5d" * 32

    bounty_id = submitted_bounty(client, session_factory)

    body = client.post(f"/bounties/{bounty_id}/verify").json()

    status, release_tx_hash = read_bounty_payout(session_factory, bounty_id)

    assert status == BountyStatus.PAID
    assert release_tx_hash == "5d" * 32

    # El payout no toca la Verification.
    assert body["result"]["status"] == VerificationStatus.PASS
    assert body["result"]["eligible_for_payout"] is True

    with session_factory() as db:
        verification = db.scalars(select(Verification)).one()

        assert verification.status == VerificationStatus.PASS
        assert verification.eligible_for_payout is True


def test_release_tx_hash_is_visible_through_get_bounty(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    client.post(f"/bounties/{bounty_id}/verify")

    body = client.get(f"/bounties/{bounty_id}").json()

    assert body["release_tx_hash"] == stellar.transaction_hash
    assert body["status"] == BountyStatus.PAID


# ─────────────────────────────────────────
# 14 a 16 y 30. Precondiciones de payout.
# ─────────────────────────────────────────


@pytest.mark.parametrize("missing", ["criteria_hash", "base_sha", "developer_github"])
def test_missing_payout_field_returns_409_without_calling_stellar(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    missing: str,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        setattr(bounty, missing, None)
        db.commit()

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not ready for payout"}

    assert stellar.builds == 0
    assert stellar.calls == []

    # Tampoco se registro la Verification.
    assert count(session_factory, Verification) == 0


def test_existing_release_tx_hash_returns_409_without_calling_stellar(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        bounty.release_tx_hash = "ff" * 32
        db.commit()

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty already has a payout transaction"}

    assert stellar.builds == 0
    assert stellar.calls == []
    assert count(session_factory, Verification) == 0


# ─────────────────────────────────────────
# 17 a 24. Stellar falla, el PASS de GitHub sobrevive.
# ─────────────────────────────────────────


def assert_pass_survived_stellar_failure(
    session_factory: sessionmaker[Session], bounty_id: int
) -> None:
    status, release_tx_hash = read_bounty_payout(session_factory, bounty_id)

    assert status == BountyStatus.ELIGIBLE
    assert release_tx_hash is None

    with session_factory() as db:
        verification = db.scalars(select(Verification)).one()

        assert verification.status == VerificationStatus.PASS
        assert verification.eligible_for_payout is True


def test_stellar_configuration_error_returns_503(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    stellar.configuration_error = StellarConfigurationError("falta el contract id")

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 503
    assert response.json() == {"detail": "Stellar payout service is not configured"}

    # No se llego a invocar el contrato.
    assert stellar.calls == []

    assert_pass_survived_stellar_failure(session_factory, bounty_id)


def test_stellar_transaction_error_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    stellar.transaction_error = StellarTransactionError("la red la rechazo")

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 502
    assert response.json() == {"detail": "Stellar payout failed"}

    # Se intento el pago, pero no hubo hash que guardar.
    assert len(stellar.calls) == 1

    assert_pass_survived_stellar_failure(session_factory, bounty_id)


# ─────────────────────────────────────────
# 25 a 27. Reintento desde ELIGIBLE.
# ─────────────────────────────────────────


def test_retry_from_eligible_pays_and_keeps_history(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    stellar.transaction_error = StellarTransactionError("caida temporal")

    assert client.post(f"/bounties/{bounty_id}/verify").status_code == 502
    assert bounty_status(session_factory, bounty_id) == BountyStatus.ELIGIBLE

    # Stellar se recupera y se vuelve a pedir verificacion.
    stellar.transaction_error = None

    assert client.post(f"/bounties/{bounty_id}/verify").status_code == 200

    assert len(stellar.calls) == 2

    status, release_tx_hash = read_bounty_payout(session_factory, bounty_id)

    assert status == BountyStatus.PAID
    assert release_tx_hash == stellar.transaction_hash

    # Dos Verification PASS: la segunda no piso a la primera.
    with session_factory() as db:
        verifications = db.scalars(
            select(Verification).order_by(Verification.id)
        ).all()

        assert len(verifications) == 2
        assert [record.status for record in verifications] == [
            VerificationStatus.PASS,
            VerificationStatus.PASS,
        ]
        assert verifications[0].id != verifications[1].id


def test_retry_reinspects_the_pull_request(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    stellar.transaction_error = StellarTransactionError("caida temporal")

    client.post(f"/bounties/{bounty_id}/verify")

    stellar.transaction_error = None
    github.set_head_sha(NEW_HEAD_SHA)

    client.post(f"/bounties/{bounty_id}/verify")

    # El segundo evidence hash se calcula sobre el commit nuevo.
    assert stellar.calls[0][1] != stellar.calls[1][1]

    with session_factory() as db:
        submission = db.scalars(select(Submission)).one()

        assert submission.head_sha == NEW_HEAD_SHA


# ─────────────────────────────────────────
# 28 y 29. PAID no se reverifica.
# ─────────────────────────────────────────


def test_paid_bounty_cannot_be_verified_again(
    client: TestClient, session_factory: sessionmaker[Session], stellar: FakeStellar
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    assert client.post(f"/bounties/{bounty_id}/verify").status_code == 200
    assert bounty_status(session_factory, bounty_id) == BountyStatus.PAID

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Bounty cannot be verified in its current state"
    }

    # Un solo payout: no se pago dos veces.
    assert len(stellar.calls) == 1
    assert stellar.builds == 1


def test_paid_is_not_a_verifiable_status() -> None:
    assert BountyStatus.PAID.value not in VERIFIABLE_STATUSES


# ─────────────────────────────────────────
# 32. Los errores HTTP no filtran el secreto del verifier.
# ─────────────────────────────────────────


@pytest.mark.parametrize("failure", ["configuration", "transaction"])
def test_payout_errors_never_leak_the_verifier_secret(
    client: TestClient,
    session_factory: sessionmaker[Session],
    stellar: FakeStellar,
    failure: str,
) -> None:
    leaked_secret = "SSECRETSEEDTHATMUSTNEVERREACHTHECLIENT00000000000000000"

    bounty_id = submitted_bounty(client, session_factory)

    if failure == "configuration":
        stellar.configuration_error = StellarConfigurationError(
            f"boom {leaked_secret}"
        )
    else:
        stellar.transaction_error = StellarTransactionError(f"boom {leaked_secret}")

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code in (502, 503)

    # Ni el secreto ni el mensaje original llegan al cliente.
    assert leaked_secret not in response.text
    assert "boom" not in response.text


def test_unpayable_bounty_is_rejected_even_when_the_result_would_not_pass(
    client, session_factory, github, stellar
) -> None:
    """La guarda corre antes de verificar, no solo antes de pagar.

    Es una desviacion deliberada del orden literal de la spec: con
    `developer_github` nulo el verifier ni siquiera termina, asi que un bounty
    impagable se rechaza antes de inspeccionar el PR.
    """
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = failing_checks()

    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None
        bounty.criteria_hash = None
        db.commit()

    del github.requests[:]

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {"detail": "Bounty is not ready for payout"}

    # Ni GitHub ni Stellar llegan a consultarse.
    assert github.requests == []
    assert stellar.builds == 0
    assert count(session_factory, Verification) == 0


# ─────────────────────────────────────────
# Fallos de transporte.
# ─────────────────────────────────────────


def test_github_transport_error_during_verify_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.transport_error = httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub verification service unavailable"}

    # Fallo antes de persistir: ni Verification ni cambio de estado.
    assert count(session_factory, Verification) == 0
    assert bounty_status(session_factory, bounty_id) == BountyStatus.SUBMITTED


def test_github_transport_error_during_submission_returns_502(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = create_bounty(session_factory)

    github.transport_error = httpx.ReadTimeout("timed out")

    response = submit(client, bounty_id)

    assert response.status_code == 502
    assert response.json() == {"detail": "GitHub verification service unavailable"}
    assert count(session_factory, Submission) == 0


def test_stellar_rpc_transport_error_during_payout_returns_502(
    client: TestClient,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    verifier = Keypair.random()

    # StellarClient real con el RPC caido, en lugar del FakeStellar.
    monkeypatch.setattr(stellar_client, "SorobanServer", DownSorobanServer)
    monkeypatch.setattr(
        verification_service,
        "get_stellar_client",
        lambda: StellarClient(
            rpc_url=SENSITIVE_RPC_URL,
            network_passphrase="Test SDF Network ; September 2015",
            contract_id=StrKey.encode_contract(b"\x11" * 32),
            verifier_secret=verifier.secret,
        ),
    )

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 502
    assert response.json() == {"detail": "Stellar payout failed"}

    assert verifier.secret not in response.text
    assert "PAID-PROVIDER-KEY" not in response.text

    # El PASS de GitHub sobrevive a la caida de Stellar, como antes.
    assert bounty_status(session_factory, bounty_id) == BountyStatus.ELIGIBLE

    with session_factory() as db:
        verification = db.scalars(select(Verification)).one()
        assert verification.status == VerificationStatus.PASS


# ─────────────────────────────────────────
# GET /submission: lectura de lo guardado.
# ─────────────────────────────────────────


def get_submission(client: TestClient, bounty_id: int):
    return client.get(f"/bounties/{bounty_id}/submission")


def stored_rows(
    session_factory: sessionmaker[Session], bounty_id: int
) -> tuple[tuple[Any, ...], tuple[Any, ...] | None, int]:
    """Bounty y submission columna a columna, mas el numero de Verification."""
    with session_factory() as db:
        bounty = db.get(Bounty, bounty_id)
        assert bounty is not None

        bounty_row = tuple(
            getattr(bounty, column.key) for column in Bounty.__table__.columns
        )

        submission = bounty.submission
        submission_row = (
            None
            if submission is None
            else tuple(
                getattr(submission, column.key)
                for column in Submission.__table__.columns
            )
        )

    return bounty_row, submission_row, count(session_factory, Verification)


def test_get_submission_on_unknown_bounty_returns_404(client: TestClient) -> None:
    response = get_submission(client, 999)

    assert response.status_code == 404
    assert response.json() == {"detail": "Bounty not found"}


def test_get_submission_without_submission_returns_404(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    response = get_submission(client, bounty_id)

    assert response.status_code == 404
    assert response.json() == {"detail": "Submission not found"}


def test_get_submission_returns_200_with_the_stored_submission(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = create_bounty(session_factory)

    created = submit(client, bounty_id).json()

    response = get_submission(client, bounty_id)

    assert response.status_code == 200
    assert response.json() == created
    assert response.json()["bounty_id"] == bounty_id


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("pull_request_url", PULL_REQUEST_URL),
        ("pull_request_number", PULL_NUMBER),
        ("author", DEVELOPER),
        ("head_ref", "feat/example"),
        ("head_sha", HEAD_SHA),
    ],
)
def test_get_submission_returns_field(
    client: TestClient,
    session_factory: sessionmaker[Session],
    field: str,
    expected: Any,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    assert get_submission(client, bounty_id).json()[field] == expected


def test_get_submission_does_not_modify_the_database(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    # Una verificacion FAIL deja filas en las tres tablas y el bounty abierto.
    github.check_runs = failing_checks()
    client.post(f"/bounties/{bounty_id}/verify")

    before = stored_rows(session_factory, bounty_id)

    # GitHub cambia por debajo: un GET no debe reflejarlo ni persistirlo.
    github.set_head_sha(NEW_HEAD_SHA)

    for _ in range(3):
        assert get_submission(client, bounty_id).status_code == 200

    assert stored_rows(session_factory, bounty_id) == before
    assert bounty_status(session_factory, bounty_id) == BountyStatus.NEEDS_CHANGES


def test_get_submission_never_calls_github_or_stellar(
    client: TestClient,
    session_factory: sessionmaker[Session],
    github: FakeGitHub,
    stellar: FakeStellar,
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    del github.requests[:]

    response = get_submission(client, bounty_id)

    assert response.status_code == 200
    assert response.json()["head_sha"] == HEAD_SHA

    # Ni una peticion al transporte de GitHub, ni construccion del cliente Stellar.
    assert github.requests == []
    assert stellar.builds == 0


def test_get_submission_reflects_the_head_of_the_last_verification(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = failing_checks()
    client.post(f"/bounties/{bounty_id}/verify")

    # Push nuevo y verificacion PASS: el bounty acaba en PAID.
    github.set_head_sha(NEW_HEAD_SHA)
    client.post(f"/bounties/{bounty_id}/verify")

    assert bounty_status(session_factory, bounty_id) == BountyStatus.PAID

    response = get_submission(client, bounty_id)

    assert response.status_code == 200
    assert response.json()["head_sha"] == NEW_HEAD_SHA
