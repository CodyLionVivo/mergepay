from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.github_verifier import (
    REQUIRED_CHECKS,
    find_protected_files,
    is_protected_path,
    select_latest_check_run,
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


STARTED_AT = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def make_check(
    name: str,
    status: str = "completed",
    conclusion: str | None = "success",
    run_id: int = 1,
    started_at: datetime | None = None,
    head_sha: str = HEAD_SHA,
) -> GitHubCheckRun:
    return GitHubCheckRun(
        id=run_id,
        name=name,
        status=status,
        conclusion=conclusion,
        head_sha=head_sha,
        html_url=None,
        started_at=started_at,
    )


def minutes(offset: int) -> datetime:
    """`STARTED_AT` desplazado, para escribir "mas nuevo" sin fechas literales."""
    return STARTED_AT + timedelta(minutes=offset)


def check_result(result: PullRequestVerificationResult, name: str) -> Any:
    """El RequiredCheckResult de ese nombre. Falla si no hay exactamente uno."""
    matches = [check for check in result.checks if check.name == name]

    assert len(matches) == 1, f"expected one entry for {name}, got {len(matches)}"

    return matches[0]


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
# 31. Nombres duplicados: se elige por check-run id.
# ─────────────────────────────────────────


def checks_with(name: str, *runs: GitHubCheckRun) -> list[GitHubCheckRun]:
    """Los obligatorios en PASS, con los de `name` sustituidos por `runs`."""
    others = [make_check(other) for other in REQUIRED_CHECKS if other != name]

    return others + list(runs)


# A. Lo que motiva usar el id: un run nuevo sin `started_at` tiene que ganar.
@pytest.mark.parametrize(
    "status", ["queued", "requested", "waiting", "pending", "in_progress"]
)
def test_a_newer_unstarted_run_wins_over_an_older_completed_one(status: str) -> None:
    """Un run recien creado no tiene `started_at`, y aun asi es el vigente.

    Ordenar por fecha elegiria el viejo completado y daria PASS a un commit cuyos
    checks todavia no han corrido.
    """
    older = make_check("build", run_id=100, started_at=minutes(0))
    newer = make_check(
        "build", status=status, conclusion=None, run_id=200, started_at=None
    )

    result = verify(check_runs=checks_with("build", older, newer))

    build = check_result(result, "build")

    assert build.status == status
    assert build.conclusion is None
    assert build.passed is False
    assert result.status is VerificationStatus.PENDING
    assert result.eligible_for_payout is False
    assert "Required check 'build' is still running" in result.reasons


# B. Mismo caso con `started_at` informado en ambos.
def test_newer_in_progress_over_older_success_is_pending() -> None:
    older = make_check("build", run_id=100, started_at=minutes(0))
    newer = make_check(
        "build",
        status="in_progress",
        conclusion=None,
        run_id=200,
        started_at=minutes(5),
    )

    result = verify(check_runs=checks_with("build", older, newer))

    assert check_result(result, "build").status == "in_progress"
    assert result.status is VerificationStatus.PENDING


# C. El run vigente decide, aunque el descartado hubiera fallado.
def test_newer_success_over_older_failure_passes() -> None:
    older = make_check("build", conclusion="failure", run_id=100, started_at=minutes(0))
    newer = make_check("build", run_id=200, started_at=minutes(5))

    result = verify(check_runs=checks_with("build", older, newer))

    build = check_result(result, "build")

    assert build.passed is True
    assert build.conclusion == "success"
    assert result.status is VerificationStatus.PASS
    assert result.eligible_for_payout is True


# D. Y tampoco se hereda un success viejo.
def test_newer_failure_over_older_success_fails() -> None:
    older = make_check("build", run_id=100, started_at=minutes(0))
    newer = make_check("build", conclusion="failure", run_id=200, started_at=minutes(5))

    result = verify(check_runs=checks_with("build", older, newer))

    build = check_result(result, "build")

    assert build.passed is False
    assert build.conclusion == "failure"
    assert result.status is VerificationStatus.FAIL
    assert result.eligible_for_payout is False
    assert "Required check 'build' failed with conclusion 'failure'" in result.reasons


# E. Sin ningun `started_at`, el id sigue resolviendolo.
def test_with_no_started_at_at_all_the_highest_id_wins() -> None:
    lower = make_check("build", conclusion="failure", run_id=100, started_at=None)
    higher = make_check("build", run_id=200, started_at=None)

    result = verify(check_runs=checks_with("build", lower, higher))

    assert check_result(result, "build").conclusion == "success"
    assert result.status is VerificationStatus.PASS


# F. Un `started_at` incoherente no puede darle la vuelta al id.
def test_a_later_started_at_on_the_lower_id_does_not_win() -> None:
    """Fechas raras no mandan: el selector es el id, no el reloj."""
    lower = make_check(
        "build", conclusion="failure", run_id=100, started_at=minutes(600)
    )
    higher = make_check("build", run_id=200, started_at=minutes(0))

    result = verify(check_runs=checks_with("build", lower, higher))

    assert check_result(result, "build").conclusion == "success"
    assert result.status is VerificationStatus.PASS


def test_started_at_never_changes_the_selection() -> None:
    """El mismo par de ids da el mismo resultado con cualquier `started_at`."""
    timestamps = [
        (None, None),
        (minutes(0), minutes(5)),
        (minutes(5), minutes(0)),
        (None, minutes(5)),
        (minutes(5), None),
    ]

    results = []

    for older_at, newer_at in timestamps:
        older = make_check(
            "build", conclusion="failure", run_id=100, started_at=older_at
        )
        newer = make_check("build", run_id=200, started_at=newer_at)

        results.append(verify(check_runs=checks_with("build", older, newer)))

    for result in results:
        assert check_result(result, "build").conclusion == "success"
        assert result.model_dump() == results[0].model_dump()


def test_three_duplicates_choose_the_highest_id() -> None:
    runs = [
        make_check("build", conclusion="failure", run_id=100, started_at=minutes(0)),
        make_check("build", conclusion="cancelled", run_id=300, started_at=None),
        make_check("build", conclusion="failure", run_id=200, started_at=minutes(20)),
    ]

    result = verify(check_runs=checks_with("build", *runs))

    build = check_result(result, "build")

    assert build.conclusion == "cancelled"
    assert result.status is VerificationStatus.FAIL


def test_duplicate_non_required_check_name_is_allowed() -> None:
    checks = [
        *passing_checks(),
        make_check("lint", run_id=1),
        make_check("lint", conclusion="failure", run_id=2),
    ]

    result = verify(check_runs=checks)

    assert result.status is VerificationStatus.PASS
    assert [check.name for check in result.checks] == list(REQUIRED_CHECKS)


def test_a_newer_duplicate_cannot_change_the_structural_rules() -> None:
    """Los duplicados solo tocan los required checks, nada mas."""
    runs = [
        make_check("build", conclusion="failure", run_id=100),
        make_check("build", run_id=200),
    ]

    result = verify(check_runs=checks_with("build", *runs))

    assert result.repository_valid is True
    assert result.base_branch_valid is True
    assert result.base_sha_valid is True
    assert result.developer_valid is True
    assert result.pr_open is True
    assert result.pr_not_draft is True
    assert result.protected_files_valid is True
    assert result.protected_files_modified == []


# ─────────────────────────────────────────
# 32. Solo cuentan los runs del head commit inspeccionado.
# ─────────────────────────────────────────


OTHER_HEAD_SHA = "z" * 40


def test_required_check_on_another_head_sha_is_ignored() -> None:
    stale = make_check(
        "build",
        conclusion="failure",
        run_id=999,
        started_at=minutes(60),
        head_sha=OTHER_HEAD_SHA,
    )
    current = make_check("build", run_id=1, started_at=minutes(0))

    result = verify(check_runs=checks_with("build", stale, current))

    # El run de otro commit tiene el id mas alto y habria fallado: se descarta
    # antes de seleccionar, asi que no es candidato.
    assert check_result(result, "build").conclusion == "success"
    assert result.status is VerificationStatus.PASS


def test_only_wrong_head_duplicates_leave_the_check_missing() -> None:
    runs = [
        make_check("build", run_id=100, head_sha=OTHER_HEAD_SHA),
        make_check("build", run_id=200, head_sha=OTHER_HEAD_SHA),
    ]

    result = verify(check_runs=checks_with("build", *runs))

    build = check_result(result, "build")

    assert build.status == "missing"
    assert build.conclusion is None
    assert build.passed is False
    assert result.status is VerificationStatus.PENDING
    assert "Required check 'build' is missing" in result.reasons


# ─────────────────────────────────────────
# 33. Forma y orden del resultado.
# ─────────────────────────────────────────


def test_result_holds_exactly_one_entry_per_required_check() -> None:
    checks = [
        *passing_checks(),
        make_check("build", run_id=200),
        make_check("regression-tests", run_id=300),
        make_check("acceptance-tests", run_id=400),
        make_check("lint", run_id=500),
    ]

    result = verify(check_runs=checks)

    assert len(result.checks) == len(REQUIRED_CHECKS)
    assert [check.name for check in result.checks] == [
        "build",
        "regression-tests",
        "acceptance-tests",
    ]


def test_required_check_order_is_fixed_regardless_of_input_order() -> None:
    checks = list(reversed(passing_checks()))

    result = verify(check_runs=checks)

    assert [check.name for check in result.checks] == [
        "build",
        "regression-tests",
        "acceptance-tests",
    ]


# ─────────────────────────────────────────
# 34. Determinismo: el orden de entrada no influye.
# ─────────────────────────────────────────


def duplicated_check_runs() -> list[GitHubCheckRun]:
    """Los tres obligatorios duplicados, cada par con una forma distinta.

    Los `started_at` estan puestos a proposito en contra del id, para que un
    resultado correcto solo pueda venir de ordenar por id.
    """
    return [
        # Fechas coherentes con el id.
        make_check("build", conclusion="failure", run_id=100, started_at=minutes(0)),
        make_check("build", run_id=200, started_at=minutes(10)),
        # Sin fechas en ninguno.
        make_check("regression-tests", conclusion="failure", run_id=300),
        make_check("regression-tests", run_id=400),
        # El id alto es el que no tiene fecha: el caso queued.
        make_check(
            "acceptance-tests", conclusion="failure", run_id=500, started_at=minutes(7)
        ),
        make_check("acceptance-tests", run_id=600, started_at=None),
        make_check("lint", conclusion="failure", run_id=700),
    ]


def test_selection_does_not_depend_on_input_order() -> None:
    runs = duplicated_check_runs()

    expected = {"build": 200, "regression-tests": 400, "acceptance-tests": 600}

    for name in REQUIRED_CHECKS:
        forward = select_latest_check_run(name, runs)
        backward = select_latest_check_run(name, list(reversed(runs)))

        assert forward is not None
        assert backward is not None
        assert forward.id == backward.id == expected[name]


@pytest.mark.parametrize(
    "reorder",
    [
        lambda runs: runs,
        lambda runs: list(reversed(runs)),
        lambda runs: runs[3:] + runs[:3],
        lambda runs: sorted(runs, key=lambda run: run.id, reverse=True),
        lambda runs: sorted(runs, key=lambda run: run.name),
    ],
)
def test_result_is_identical_for_any_input_order(reorder: Any) -> None:
    baseline = verify(check_runs=duplicated_check_runs())

    reordered = verify(check_runs=reorder(duplicated_check_runs()))

    assert reordered.model_dump() == baseline.model_dump()
    assert baseline.status is VerificationStatus.PASS


def test_the_selected_run_is_the_one_reported() -> None:
    runs = duplicated_check_runs()

    result = verify(check_runs=runs)

    for name in REQUIRED_CHECKS:
        selected = select_latest_check_run(name, runs)
        reported = check_result(result, name)

        assert selected is not None
        assert reported.status == selected.status
        assert reported.conclusion == selected.conclusion
