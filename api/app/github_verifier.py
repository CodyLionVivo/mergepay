"""Verificacion determinista de un pull request.

Esta capa no habla con GitHub ni con la base de datos: recibe lo que
`GitHubClient` ya trajo y lo evalua. Dadas las mismas entradas siempre produce
el mismo resultado, por eso un nombre de check duplicado es un error en vez de
una eleccion arbitraria.
"""

from collections.abc import Iterable, Sequence

from app.schemas import (
    GitHubCheckRun,
    PullRequestFile,
    PullRequestInspection,
    PullRequestVerificationResult,
    RequiredCheckResult,
    VerificationStatus,
)

REQUIRED_CHECKS = (
    "build",
    "regression-tests",
    "acceptance-tests",
)

PROTECTED_EXACT_PATHS = (
    ".github/workflows/mergepay-ci.yml",
    "requirements.txt",
)

PROTECTED_PATH_PREFIXES = (
    "tests/regression/",
    "tests/acceptance/",
)

# Status sintetico para un check obligatorio que no existe en el commit.
MISSING_CHECK_STATUS = "missing"

COMPLETED_STATUS = "completed"
SUCCESS_CONCLUSION = "success"


class DuplicateRequiredCheckError(Exception):
    """Dos check runs comparten el nombre de un check obligatorio."""


def is_protected_path(path: str) -> bool:
    """Una ruta esta protegida si coincide exacta o cuelga de un prefijo."""
    return path in PROTECTED_EXACT_PATHS or path.startswith(PROTECTED_PATH_PREFIXES)


def find_protected_files(files: Iterable[PullRequestFile]) -> list[str]:
    """Rutas protegidas tocadas por el PR, sin duplicados.

    Mira tanto `filename` como `previous_filename`, de modo que tanto mover un
    archivo protegido fuera de su sitio como traer uno nuevo a una ruta
    protegida quedan detectados.
    """
    protected: list[str] = []

    for file in files:
        for path in (file.filename, file.previous_filename):
            if path and is_protected_path(path) and path not in protected:
                protected.append(path)

    return protected


def _evaluate_check(
    name: str, check_runs: Sequence[GitHubCheckRun]
) -> tuple[RequiredCheckResult, str | None]:
    """Resultado de un check obligatorio y, si procede, su motivo de queja."""
    matches = [run for run in check_runs if run.name == name]

    if len(matches) > 1:
        raise DuplicateRequiredCheckError(
            f"Required check '{name}' appears {len(matches)} times"
        )

    if not matches:
        return (
            RequiredCheckResult(
                name=name,
                status=MISSING_CHECK_STATUS,
                conclusion=None,
                passed=False,
            ),
            f"Required check '{name}' is missing",
        )

    run = matches[0]

    if run.status != COMPLETED_STATUS:
        return (
            RequiredCheckResult(
                name=name,
                status=run.status,
                conclusion=run.conclusion,
                passed=False,
            ),
            f"Required check '{name}' is still running",
        )

    passed = run.conclusion == SUCCESS_CONCLUSION

    reason = (
        None
        if passed
        else f"Required check '{name}' failed with conclusion '{run.conclusion}'"
    )

    return (
        RequiredCheckResult(
            name=name,
            status=run.status,
            conclusion=run.conclusion,
            passed=passed,
        ),
        reason,
    )


def verify_pull_request(
    inspection: PullRequestInspection,
    check_runs: Sequence[GitHubCheckRun],
    *,
    expected_owner: str,
    expected_repo: str,
    expected_base_branch: str,
    expected_base_sha: str,
    expected_developer_github: str,
) -> PullRequestVerificationResult:
    """Evalua el PR contra lo que el bounty esperaba."""
    repository_valid = (
        inspection.owner.casefold() == expected_owner.casefold()
        and inspection.repo.casefold() == expected_repo.casefold()
    )

    base_branch_valid = inspection.base_ref == expected_base_branch
    base_sha_valid = inspection.base_sha == expected_base_sha

    developer_valid = (
        inspection.author is not None
        and inspection.author.casefold() == expected_developer_github.casefold()
    )

    pr_open = inspection.state == "open"
    pr_not_draft = not inspection.draft

    protected_files_modified = find_protected_files(inspection.files)
    protected_files_valid = not protected_files_modified

    reasons: list[str] = []

    if not repository_valid:
        reasons.append("Repository does not match bounty")

    if not base_branch_valid:
        reasons.append("Base branch does not match bounty")

    if not base_sha_valid:
        reasons.append("Base SHA does not match bounty")

    if not developer_valid:
        reasons.append("Pull request author does not match assigned developer")

    if not pr_open:
        reasons.append("Pull request is not open")

    if not pr_not_draft:
        reasons.append("Pull request is a draft")

    if not protected_files_valid:
        reasons.append("Protected files were modified")

    structural_valid = all(
        (
            repository_valid,
            base_branch_valid,
            base_sha_valid,
            developer_valid,
            pr_open,
            pr_not_draft,
            protected_files_valid,
        )
    )

    checks: list[RequiredCheckResult] = []

    for name in REQUIRED_CHECKS:
        result, reason = _evaluate_check(name, check_runs)

        checks.append(result)

        if reason is not None:
            reasons.append(reason)

    any_check_incomplete = any(
        result.status != COMPLETED_STATUS for result in checks
    )

    # Precedencia: lo estructural manda sobre lo pendiente, y lo pendiente
    # sobre un check completado que no fue success.
    if not structural_valid:
        status = VerificationStatus.FAIL
    elif any_check_incomplete:
        status = VerificationStatus.PENDING
    elif all(result.passed for result in checks):
        status = VerificationStatus.PASS
    else:
        status = VerificationStatus.FAIL

    return PullRequestVerificationResult(
        status=status,
        eligible_for_payout=status == VerificationStatus.PASS,
        repository_valid=repository_valid,
        base_branch_valid=base_branch_valid,
        base_sha_valid=base_sha_valid,
        developer_valid=developer_valid,
        pr_open=pr_open,
        pr_not_draft=pr_not_draft,
        protected_files_valid=protected_files_valid,
        protected_files_modified=protected_files_modified,
        checks=checks,
        reasons=reasons,
        head_sha=inspection.head_sha,
    )
