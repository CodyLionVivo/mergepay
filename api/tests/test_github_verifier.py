from typing import Any

import pytest

from app.github_verifier import (
    REQUIRED_CHECKS,
    DuplicateRequiredCheckError,
    find_protected_files,
    is_protected_path,
    verify_pull_request,
)
from app.schemas import (
    GitHubCheckRun,
    PullRequestFile,
    PullRequestInspection,
    PullRequestVerificationResult,
    VerificationStatus,
)

OWNER = "acme"
REPO = "demo"
PULL_NUMBER = 21
BASE_BRANCH = "main"
BASE_SHA = "b" * 40
HEAD_SHA = "h" * 40
DEVELOPER = "octodev"


def make_file(
    filename: str,
    status: str = "modified",
    previous_filename: str | None = None,
) -> PullRequestFile:
    return PullRequestFile(
        filename=filename,
        status=status,
        additions=1,
        deletions=0,
        changes=1,
        previous_filename=previous_filename,
    )


def make_inspection(**overrides: Any) -> PullRequestInspection:
    fields: dict[str, Any] = {
        "owner": OWNER,
        "repo": REPO,
        "pull_number": PULL_NUMBER,
        "html_url": f"https://github.com/{OWNER}/{REPO}/pull/{PULL_NUMBER}",
        "state": "open",
        "draft": False,
        "author": DEVELOPER,
        "base_ref": BASE_BRANCH,
        "base_sha": BASE_SHA,
        "head_ref": "feat/example",
        "head_sha": HEAD_SHA,
        "head_repo_full_name": f"{OWNER}/{REPO}",
        "files": [make_file("app/main.py"), make_file("README.md")],
    }

    fields.update(overrides)

    return PullRequestInspection(**fields)


def make_check(
    name: str, status: str = "completed", conclusion: str | None = "success"
) -> GitHubCheckRun:
    return GitHubCheckRun(
        name=name,
        status=status,
        conclusion=conclusion,
        head_sha=HEAD_SHA,
        html_url=None,
    )


def passing_checks() -> list[GitHubCheckRun]:
    return [make_check(name) for name in REQUIRED_CHECKS]


def verify(
    inspection: PullRequestInspection | None = None,
    check_runs: list[GitHubCheckRun] | None = None,
    **expected: str,
) -> PullRequestVerificationResult:
    values: dict[str, str] = {
        "expected_owner": OWNER,
        "expected_repo": REPO,
        "expected_base_branch": BASE_BRANCH,
        "expected_base_sha": BASE_SHA,
        "expected_developer_github": DEVELOPER,
    }

    values.update(expected)

    return verify_pull_request(
        inspection if inspection is not None else make_inspection(),
        passing_checks() if check_runs is None else check_runs,
        **values,
    )


# ─────────────────────────────────────────
# 7 a 14. Archivos protegidos.
# ─────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/mergepay-ci.yml",
        "requirements.txt",
        "tests/regression/test_login.py",
        "tests/regression/nested/deep/test_case.py",
        "tests/acceptance/test_checkout.py",
        "tests/acceptance/conftest.py",
    ],
)
def test_protected_paths_are_detected(path: str) -> None:
    assert is_protected_path(path) is True
    assert find_protected_files([make_file(path)]) == [path]


@pytest.mark.parametrize(
    "path",
    [
        "app/main.py",
        "README.md",
        "tests/test_main.py",
        "tests/regression.py",
        "docs/requirements.txt",
        ".github/workflows/other-ci.yml",
    ],
)
def test_unprotected_paths_are_ignored(path: str) -> None:
    assert is_protected_path(path) is False
    assert find_protected_files([make_file(path)]) == []


def test_rename_away_from_protected_path_is_detected() -> None:
    renamed = make_file(
        "tests/legacy/test_login.py",
        status="renamed",
        previous_filename="tests/regression/test_login.py",
    )

    assert find_protected_files([renamed]) == ["tests/regression/test_login.py"]


def test_rename_into_protected_path_is_detected() -> None:
    renamed = make_file(
        "tests/acceptance/test_login.py",
        status="renamed",
        previous_filename="tests/test_login.py",
    )

    assert find_protected_files([renamed]) == ["tests/acceptance/test_login.py"]


def test_protected_files_are_deduplicated() -> None:
    files = [
        make_file("requirements.txt"),
        make_file("requirements.txt"),
        make_file(
            "requirements.txt", status="renamed", previous_filename="requirements.txt"
        ),
    ]

    assert find_protected_files(files) == ["requirements.txt"]


# ─────────────────────────────────────────
# 15 y 32. Camino feliz.
# ─────────────────────────────────────────


def test_all_checks_success_gives_pass_and_eligible() -> None:
    result = verify()

    assert result.status is VerificationStatus.PASS
    assert result.eligible_for_payout is True
    assert result.head_sha == HEAD_SHA

    assert result.repository_valid is True
    assert result.base_branch_valid is True
    assert result.base_sha_valid is True
    assert result.developer_valid is True
    assert result.pr_open is True
    assert result.pr_not_draft is True
    assert result.protected_files_valid is True
    assert result.protected_files_modified == []

    assert [check.name for check in result.checks] == list(REQUIRED_CHECKS)
    assert all(check.passed for check in result.checks)


def test_pass_has_no_reasons() -> None:
    assert verify().reasons == []


def test_owner_and_developer_comparison_is_case_insensitive() -> None:
    inspection = make_inspection(owner="ACME", repo="DEMO", author="OctoDev")

    result = verify(inspection)

    assert result.status is VerificationStatus.PASS
    assert result.repository_valid is True
    assert result.developer_valid is True


# ─────────────────────────────────────────
# 16 a 18, 22, 23. Conclusiones que no son success.
# ─────────────────────────────────────────


@pytest.mark.parametrize("failing_check", REQUIRED_CHECKS)
def test_any_failing_required_check_gives_fail(failing_check: str) -> None:
    checks = [
        make_check(name, conclusion="failure" if name == failing_check else "success")
        for name in REQUIRED_CHECKS
    ]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.FAIL
    assert result.eligible_for_payout is False

    assert (
        f"Required check '{failing_check}' failed with conclusion 'failure'"
        in result.reasons
    )


@pytest.mark.parametrize(
    "conclusion",
    ["failure", "cancelled", "timed_out", "neutral", "skipped", "action_required", "stale"],
)
def test_non_success_conclusions_give_fail(conclusion: str) -> None:
    checks = [
        make_check("build"),
        make_check("regression-tests"),
        make_check("acceptance-tests", conclusion=conclusion),
    ]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.FAIL
    assert result.eligible_for_payout is False

    acceptance = result.checks[REQUIRED_CHECKS.index("acceptance-tests")]

    assert acceptance.passed is False
    assert acceptance.conclusion == conclusion


# ─────────────────────────────────────────
# 19 a 21. Checks ausentes o sin terminar.
# ─────────────────────────────────────────


def test_missing_required_check_gives_pending() -> None:
    checks = [make_check("build"), make_check("regression-tests")]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.PENDING
    assert result.eligible_for_payout is False

    acceptance = result.checks[REQUIRED_CHECKS.index("acceptance-tests")]

    assert acceptance.status == "missing"
    assert acceptance.conclusion is None
    assert acceptance.passed is False

    assert "Required check 'acceptance-tests' is missing" in result.reasons


@pytest.mark.parametrize("status", ["in_progress", "queued", "waiting"])
def test_incomplete_required_check_gives_pending(status: str) -> None:
    checks = [
        make_check("build"),
        make_check("regression-tests"),
        make_check("acceptance-tests", status=status, conclusion=None),
    ]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.PENDING
    assert result.eligible_for_payout is False

    acceptance = result.checks[REQUIRED_CHECKS.index("acceptance-tests")]

    assert acceptance.status == status
    assert acceptance.passed is False

    assert "Required check 'acceptance-tests' is still running" in result.reasons


def test_pending_takes_precedence_over_a_failed_check() -> None:
    checks = [
        make_check("build", conclusion="failure"),
        make_check("regression-tests"),
        make_check("acceptance-tests", status="queued", conclusion=None),
    ]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.PENDING


# ─────────────────────────────────────────
# 24 a 30. Reglas estructurales.
# ─────────────────────────────────────────


def test_protected_file_fails_even_with_every_check_green() -> None:
    inspection = make_inspection(
        files=[make_file("app/main.py"), make_file("requirements.txt")]
    )

    result = verify(inspection)

    assert result.status is VerificationStatus.FAIL
    assert result.eligible_for_payout is False
    assert result.protected_files_valid is False
    assert result.protected_files_modified == ["requirements.txt"]
    assert "Protected files were modified" in result.reasons

    # Los checks siguen estando verdes: lo que falla es la regla estructural.
    assert all(check.passed for check in result.checks)


def test_wrong_repository_gives_fail() -> None:
    result = verify(make_inspection(repo="other-repo"))

    assert result.status is VerificationStatus.FAIL
    assert result.repository_valid is False
    assert "Repository does not match bounty" in result.reasons


def test_wrong_owner_gives_fail() -> None:
    result = verify(make_inspection(owner="someone-else"))

    assert result.status is VerificationStatus.FAIL
    assert result.repository_valid is False


def test_wrong_base_branch_gives_fail() -> None:
    result = verify(make_inspection(base_ref="develop"))

    assert result.status is VerificationStatus.FAIL
    assert result.base_branch_valid is False
    assert "Base branch does not match bounty" in result.reasons


def test_wrong_base_sha_gives_fail() -> None:
    result = verify(make_inspection(base_sha="c" * 40))

    assert result.status is VerificationStatus.FAIL
    assert result.base_sha_valid is False
    assert "Base SHA does not match bounty" in result.reasons


def test_wrong_developer_gives_fail() -> None:
    result = verify(make_inspection(author="someone-else"))

    assert result.status is VerificationStatus.FAIL
    assert result.developer_valid is False
    assert "Pull request author does not match assigned developer" in result.reasons


def test_missing_author_gives_fail() -> None:
    result = verify(make_inspection(author=None))

    assert result.status is VerificationStatus.FAIL
    assert result.developer_valid is False


def test_closed_pull_request_gives_fail() -> None:
    result = verify(make_inspection(state="closed"))

    assert result.status is VerificationStatus.FAIL
    assert result.pr_open is False
    assert "Pull request is not open" in result.reasons


def test_draft_pull_request_gives_fail() -> None:
    result = verify(make_inspection(draft=True))

    assert result.status is VerificationStatus.FAIL
    assert result.pr_not_draft is False
    assert "Pull request is a draft" in result.reasons


def test_structural_failure_takes_precedence_over_pending() -> None:
    checks = [make_check("build"), make_check("regression-tests")]

    result = verify(make_inspection(draft=True), check_runs=checks)

    assert result.status is VerificationStatus.FAIL


# ─────────────────────────────────────────
# 31. Nombres duplicados.
# ─────────────────────────────────────────


def test_duplicate_required_check_name_raises() -> None:
    checks = [
        *passing_checks(),
        make_check("acceptance-tests", conclusion="failure"),
    ]

    with pytest.raises(DuplicateRequiredCheckError):
        verify(check_runs=checks)


def test_duplicate_non_required_check_name_is_allowed() -> None:
    checks = [
        *passing_checks(),
        make_check("lint"),
        make_check("lint", conclusion="failure"),
    ]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.PASS
