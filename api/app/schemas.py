import base64
import binascii
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from stellar_sdk import StrKey

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
    """Un check run del commit, tal como lo devuelve GitHub.

    `id` es lo que permite elegir de forma determinista entre varios runs
    legitimos con el mismo nombre. `started_at` es metadata: se parsea y se
    conserva, pero no interviene en esa eleccion.
    """

    id: int
    name: str
    status: str
    conclusion: str | None
    head_sha: str
    html_url: str | None

    # ISO 8601 en el JSON de GitHub. Falta mientras el run sigue encolado, que
    # es justamente por lo que no sirve para elegir el run mas reciente.
    started_at: datetime | None = None

    @field_validator("started_at")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        """Un timestamp naive se interpreta como UTC.

        GitHub manda Z, pero un naive dejaria dos runs sin instante comparable, y
        esta fecha se muestra y se compara como metadata.
        """
        if value is None or value.tzinfo is not None:
            return value

        return value.replace(tzinfo=timezone.utc)


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


# ─────────────────────────────────────────
# Submissions y verificaciones persistidas.
# ─────────────────────────────────────────


TransactionHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

# Letras, numeros y guion, de 1 a 39 caracteres. Solo formato: MergePay no
# comprueba que la cuenta exista ni que pertenezca a quien la declara.
GitHubUsername = Annotated[
    str,
    StringConstraints(min_length=1, max_length=39, pattern=r"^[A-Za-z0-9-]+$"),
]


WALLET_SIGNATURE_BYTES = 64


def validate_wallet_signature(value: str) -> str:
    """Solo el formato: base64 estandar de una firma ed25519 de 64 bytes.

    Que firme lo que debe se comprueba despues, contra la wallet que
    corresponda: la del contrato o la del challenge.
    """
    try:
        decoded = base64.b64decode(value, validate=True)
    except binascii.Error as error:
        raise ValueError("wallet_signature must be valid base64") from error

    if len(decoded) != WALLET_SIGNATURE_BYTES:
        raise ValueError("wallet_signature must decode to exactly 64 bytes")

    return value


def _normalize_transaction_hash(value: object) -> object:
    # Pydantic evalua `pattern` antes que strip/to_lower, asi que la
    # normalizacion tiene que ir en un validador previo.
    return value.strip().lower() if isinstance(value, str) else value


class FundingConfirmationCreate(BaseModel):
    """Solo el hash: wallet, montos y status los decide el backend on-chain.

    `extra="forbid"` rechaza cualquier otro campo en vez de ignorarlo, para que
    un cliente no pueda creer que su `client_wallet` o su `amount` cuentan.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_hash: TransactionHash

    @field_validator("transaction_hash", mode="before")
    @classmethod
    def _normalize_hash(cls, value: object) -> object:
        return _normalize_transaction_hash(value)


class AssignmentConfirmationCreate(BaseModel):
    """Hash de la aceptacion on-chain, el GitHub declarado y la prueba de wallet.

    La wallet del developer nunca viaja aqui: se lee del contrato. La firma
    SEP-53 prueba que quien envia el GitHub controla esa wallet; sin ella
    cualquiera podria reclamar la task con el hash publico de la aceptacion.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_hash: TransactionHash
    developer_github: GitHubUsername
    wallet_signature: str

    @field_validator("wallet_signature", mode="before")
    @classmethod
    def _strip_signature(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("wallet_signature")
    @classmethod
    def _check_signature(cls, value: str) -> str:
        return validate_wallet_signature(value)

    @field_validator("transaction_hash", mode="before")
    @classmethod
    def _normalize_hash(cls, value: object) -> object:
        return _normalize_transaction_hash(value)

    @field_validator("developer_github", mode="before")
    @classmethod
    def _strip_username(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class SubmissionCreate(BaseModel):
    pull_request_url: NonEmptyStr


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bounty_id: int

    pull_request_url: str
    pull_request_number: int

    author: str | None

    head_ref: str
    head_sha: str

    created_at: datetime
    updated_at: datetime


class OnChainBountyResponse(BaseModel):
    """Lo que el contrato dice de un bounty, leido en el momento de la peticion.

    Todo sale de `get_bounty` salvo `network` y `contract_id`, que son la
    configuracion del backend. Solo datos publicos: ni RPC URL, ni XDR, ni el
    secreto del verifier.
    """

    network: str
    contract_id: str

    client_wallet: str
    developer_wallet: str | None

    amount_stroops: int

    criteria_hash: str
    evidence_hash: str | None

    deadline_unix: int

    contract_status: str


class VerificationRecordResponse(BaseModel):
    id: int
    bounty_id: int
    submission_id: int

    created_at: datetime

    # El cliente recibe el resultado tipado, nunca el result_json en crudo.
    result: PullRequestVerificationResult


# ─────────────────────────────────────────
# Autenticacion por wallet.
# ─────────────────────────────────────────


class AuthChallengeCreate(BaseModel):
    """Solo la wallet que va a firmar. Que la controle se prueba despues."""

    wallet: str

    @field_validator("wallet", mode="before")
    @classmethod
    def _strip_wallet(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("wallet")
    @classmethod
    def _check_wallet(cls, value: str) -> str:
        if not StrKey.is_valid_ed25519_public_key(value):
            raise ValueError("wallet must be a valid Stellar public key")

        return value


class AuthChallengeResponse(BaseModel):
    challenge_id: str
    # El frontend firma exactamente esto, sin reconstruirlo.
    message: str
    expires_at_unix: int


class AuthVerifyCreate(BaseModel):
    challenge_id: str
    wallet_signature: str

    @field_validator("challenge_id", "wallet_signature", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("wallet_signature")
    @classmethod
    def _check_signature(cls, value: str) -> str:
        return validate_wallet_signature(value)


class AuthSessionResponse(BaseModel):
    """El token en crudo viaja aqui una sola vez: no se guarda ni se registra."""

    access_token: str
    token_type: str
    wallet: str
    expires_at_unix: int


class AuthMeResponse(BaseModel):
    wallet: str
    expires_at_unix: int
