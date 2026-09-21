from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CriterionCreate(BaseModel):
    description: NonEmptyStr
    required: bool = True


class CriterionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bounty_id: int
    description: str
    required: bool
    position: int


class BountyCreate(BaseModel):
    title: NonEmptyStr
    description: NonEmptyStr
    repo_owner: NonEmptyStr
    repo_name: NonEmptyStr
    base_branch: NonEmptyStr = "main"
    amount_stroops: int = Field(gt=0)
    deadline_unix: int = Field(gt=0)
    criteria: list[CriterionCreate] = Field(min_length=1)


class BountyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int

    title: str
    description: str

    repo_owner: str
    repo_name: str
    base_branch: str
    base_sha: str | None

    client_wallet: str | None
    developer_wallet: str | None
    developer_github: str | None

    amount_stroops: int
    deadline_unix: int

    criteria_hash: str | None

    github_issue_number: int | None
    pull_request_number: int | None

    create_tx_hash: str | None
    release_tx_hash: str | None

    status: str

    created_at: datetime
    updated_at: datetime

    criteria: list[CriterionResponse]


# ─────────────────────────────────────────
# GitHub: lectura de pull requests.
# ─────────────────────────────────────────


class PullRequestRef(BaseModel):
    """Coordenadas de un PR, extraidas de su URL."""

    owner: str
    repo: str
    pull_number: int


class PullRequestFile(BaseModel):
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int

    # Solo lo rellena GitHub cuando status == "renamed". Hace falta para
    # detectar que un archivo protegido se movio de sitio.
    previous_filename: str | None = None


class PullRequestSummary(PullRequestRef):
    """Metadatos del PR que nos interesan, no el JSON completo de GitHub."""

    html_url: str
    state: str
    draft: bool
    author: str | None
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    head_repo_full_name: str | None


class PullRequestInspection(PullRequestSummary):
    files: list[PullRequestFile]


class GitHubCheckRun(BaseModel):
    name: str
    status: str
    conclusion: str | None
    head_sha: str
    html_url: str | None


# ─────────────────────────────────────────
# Verificacion determinista de un pull request.
# ─────────────────────────────────────────


class VerificationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class RequiredCheckResult(BaseModel):
    name: str
    # El status del check run, o "missing" si no existe ninguno con ese nombre.
    status: str
    conclusion: str | None
    passed: bool


class PullRequestVerificationResult(BaseModel):
    status: VerificationStatus
    eligible_for_payout: bool

    repository_valid: bool
    base_branch_valid: bool
    base_sha_valid: bool
    developer_valid: bool
    pr_open: bool
    pr_not_draft: bool
    protected_files_valid: bool

    protected_files_modified: list[str]

    checks: list[RequiredCheckResult]

    reasons: list[str]

    head_sha: str
