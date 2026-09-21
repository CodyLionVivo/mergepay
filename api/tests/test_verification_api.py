from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Bounty, BountyStatus, Submission, Verification
from app.schemas import PullRequestVerificationResult, VerificationStatus
from tests.conftest import (
    BASE_BRANCH,
    BASE_SHA,
    DEVELOPER,
    HEAD_SHA,
    OWNER,
    PULL_NUMBER,
    REPO,
    FakeGitHub,
    changed_file,
    check_run,
    passing_check_runs,
)

PULL_REQUEST_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}"
NEW_HEAD_SHA = "n" * 40


def create_bounty(session_factory: sessionmaker[Session], **overrides: Any) -> int:
    """Inserta un bounty listo para recibir submission, saltandose la API."""
    fields: dict[str, Any] = {
        "title": "Arreglar el redirect tras el login",
        "description": "El usuario acaba en /home y no en /dashboard.",
        "repo_owner": OWNER,
        "repo_name": REPO,
        "base_branch": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "developer_github": DEVELOPER,
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


def test_passing_checks_move_bounty_to_eligible(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    response = client.post(f"/bounties/{bounty_id}/verify")

    body = response.json()

    assert body["result"]["status"] == VerificationStatus.PASS
    assert body["result"]["eligible_for_payout"] is True
    assert body["result"]["reasons"] == []

    assert bounty_status(session_factory, bounty_id) == BountyStatus.ELIGIBLE

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

    assert bounty_status(session_factory, bounty_id) == BountyStatus.ELIGIBLE


def test_verify_inspects_the_pull_request_on_every_call(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    pull_path = f"/repos/{OWNER}/{REPO}/pulls/{PULL_NUMBER}"

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


def test_duplicate_required_check_returns_409(
    client: TestClient, session_factory: sessionmaker[Session], github: FakeGitHub
) -> None:
    bounty_id = submitted_bounty(client, session_factory)

    github.check_runs = [*passing_check_runs(), check_run("build")]

    response = client.post(f"/bounties/{bounty_id}/verify")

    assert response.status_code == 409
    assert response.json() == {"detail": "Duplicate required GitHub check detected"}

    assert count(session_factory, Verification) == 0
    assert bounty_status(session_factory, bounty_id) == BountyStatus.SUBMITTED


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
