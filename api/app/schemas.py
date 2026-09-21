from datetime import datetime
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
