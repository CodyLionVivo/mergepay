"""Orquestacion de submissions y verificaciones.

Junta las tres piezas que ya existian: `GitHubClient` trae los datos,
`verify_pull_request` los evalua y aqui se decide que se persiste y como se
traduce un fallo a HTTP. Nada de esto habla con Stellar todavia.
"""

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.github_client import (
    CheckRunsTooLargeError,
    GitHubClient,
    GitHubForbiddenError,
    GitHubUnauthorizedError,
    GitHubUnexpectedStatusError,
    InvalidPullRequestUrlError,
    PullRequestNotFoundError,
    PullRequestTooLargeError,
)
from app.github_verifier import DuplicateRequiredCheckError, verify_pull_request
from app.hashing import compute_evidence_hash
from app.models import Bounty, BountyStatus, Submission, Verification, utcnow
from app.stellar_client import (
    StellarClient,
    StellarConfigurationError,
    StellarTransactionError,
)
from app.schemas import (
    PullRequestVerificationResult,
    VerificationRecordResponse,
    VerificationStatus,
)

# Estados del bounty desde los que se puede volver a verificar.
VERIFIABLE_STATUSES = frozenset(
    {
        BountyStatus.SUBMITTED.value,
        BountyStatus.NEEDS_CHANGES.value,
        BountyStatus.VERIFYING.value,
        BountyStatus.ELIGIBLE.value,
    }
)

BOUNTY_STATUS_BY_VERIFICATION = {
    VerificationStatus.PASS: BountyStatus.ELIGIBLE,
    VerificationStatus.FAIL: BountyStatus.NEEDS_CHANGES,
    VerificationStatus.PENDING: BountyStatus.VERIFYING,
}


def get_stellar_client() -> StellarClient:
    """Construye el cliente Stellar solo cuando hay algo que pagar.

    Es una funcion y no una dependencia global a proposito: asi un bounty que
    sale FAIL o PENDING se verifica igual aunque Stellar no este configurado.
    """
    return StellarClient.from_settings()


def get_github_client() -> Generator[GitHubClient, None, None]:
    """Dependencia de FastAPI: un cliente de GitHub por request."""
    client = GitHubClient()
    try:
        yield client
    finally:
        client.close()


@contextmanager
def github_errors_as_http() -> Iterator[None]:
    """Traduce los errores de GitHub y del verifier a respuestas HTTP.

    Nunca se propaga el cuerpo de la respuesta de GitHub ni el token: solo
    mensajes nuestros o el texto de nuestras propias excepciones.
    """
    try:
        yield
    except InvalidPullRequestUrlError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid GitHub pull request URL",
        ) from error
    except PullRequestNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pull request not found on GitHub",
        ) from error
    except (PullRequestTooLargeError, CheckRunsTooLargeError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except (
        GitHubUnauthorizedError,
        GitHubForbiddenError,
        GitHubUnexpectedStatusError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="GitHub verification service unavailable",
        ) from error
    except DuplicateRequiredCheckError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate required GitHub check detected",
        ) from error


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise


def _structural_reasons(result: PullRequestVerificationResult) -> list[str]:
    """Motivos de las reglas estructurales, sin los de los required checks.

    Al registrar una submission no se consultan check runs, asi que los tres
    obligatorios salen siempre como "missing". Esos motivos no explican el
    rechazo y solo confundirian al developer.
    """
    check_prefixes = tuple(f"Required check '{check.name}'" for check in result.checks)

    return [
        reason for reason in result.reasons if not reason.startswith(check_prefixes)
    ]


def _assert_ready_for_payout(bounty: Bounty, submission: Submission) -> None:
    """Comprueba lo que hace falta para pagar, antes de tocar nada.

    Se ejecuta antes de verificar y no solo antes de pagar: `base_sha` y
    `developer_github` son entradas del propio verifier, asi que sin ellos la
    verificacion no significa nada (y con `developer_github` nulo ni siquiera
    llega a terminar).
    """
    if bounty.release_tx_hash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty already has a payout transaction",
        )

    if (
        bounty.criteria_hash is None
        or bounty.base_sha is None
        or bounty.developer_github is None
        or submission.pull_request_number is None
        or submission.pull_request_url is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is not ready for payout",
        )


def _release_payout(
    db: Session,
    bounty: Bounty,
    submission: Submission,
    result: PullRequestVerificationResult,
) -> None:
    """Ancla la evidencia on-chain y marca el bounty como pagado.

    La Verification PASS y el estado ELIGIBLE ya estan comprometidos cuando
    esto se ejecuta: si Stellar falla no se revierten, porque GitHub si dio
    PASS y eso no deja de ser cierto.
    """
    evidence_hash = compute_evidence_hash(
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

    try:
        stellar = get_stellar_client()
    except StellarConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stellar payout service is not configured",
        ) from error

    try:
        transaction_hash = stellar.release_bounty(bounty.id, evidence_hash)
    except StellarTransactionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stellar payout failed",
        ) from error

    bounty.release_tx_hash = transaction_hash
    bounty.status = BountyStatus.PAID

    _commit(db)


def register_submission(
    db: Session,
    bounty: Bounty,
    pull_request_url: str,
    github: GitHubClient,
) -> Submission:
    """Registra el PR de un bounty ASSIGNED, comprobandolo antes de persistir."""
    if bounty.status != BountyStatus.ASSIGNED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is not accepting submissions",
        )

    if not bounty.base_sha or not bounty.developer_github:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty is not ready for submission",
        )

    if bounty.submission is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty already has a submission",
        )

    # Sin check runs: aqui solo interesa la estructura del PR. Si todo encaja
    # el resultado sera PENDING porque faltan los obligatorios, y eso basta.
    with github_errors_as_http():
        inspection = github.inspect_pull_request(pull_request_url)

        result = verify_pull_request(
            inspection,
            [],
            expected_owner=bounty.repo_owner,
            expected_repo=bounty.repo_name,
            expected_base_branch=bounty.base_branch,
            expected_base_sha=bounty.base_sha,
            expected_developer_github=bounty.developer_github,
        )

    if result.status is VerificationStatus.FAIL:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Pull request does not match bounty",
                "reasons": _structural_reasons(result),
            },
        )

    submission = Submission(
        bounty=bounty,
        pull_request_url=pull_request_url,
        pull_request_number=inspection.pull_number,
        author=inspection.author,
        head_ref=inspection.head_ref,
        head_sha=inspection.head_sha,
    )

    db.add(submission)

    bounty.pull_request_number = inspection.pull_number
    bounty.status = BountyStatus.SUBMITTED

    _commit(db)
    db.refresh(submission)

    return submission


def run_verification(
    db: Session,
    bounty: Bounty,
    github: GitHubClient,
) -> Verification:
    """Vuelve a inspeccionar el PR y deja constancia del resultado."""
    submission = bounty.submission

    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty has no submission",
        )

    if bounty.status not in VERIFIABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bounty cannot be verified in its current state",
        )

    _assert_ready_for_payout(bounty, submission)

    # El developer puede haber hecho push desde la ultima pasada, asi que el
    # head SHA sale de esta inspeccion y los checks se piden para ese commit.
    with github_errors_as_http():
        inspection = github.inspect_pull_request(submission.pull_request_url)

        check_runs = github.list_check_runs(inspection, inspection.head_sha)

        result = verify_pull_request(
            inspection,
            check_runs,
            expected_owner=bounty.repo_owner,
            expected_repo=bounty.repo_name,
            expected_base_branch=bounty.base_branch,
            expected_base_sha=bounty.base_sha,
            expected_developer_github=bounty.developer_github,
        )

    verification = Verification(
        submission=submission,
        head_sha=result.head_sha,
        status=result.status.value,
        eligible_for_payout=result.eligible_for_payout,
        result_json=result.model_dump_json(),
    )

    db.add(verification)

    submission.pull_request_number = inspection.pull_number
    submission.author = inspection.author
    submission.head_ref = inspection.head_ref
    submission.head_sha = inspection.head_sha
    submission.updated_at = utcnow()

    bounty.pull_request_number = inspection.pull_number
    bounty.status = BOUNTY_STATUS_BY_VERIFICATION[result.status]

    # COMMIT #1: submission al dia, Verification creada y bounty en ELIGIBLE
    # si fue PASS. Ocurre antes de Stellar a proposito.
    _commit(db)
    db.refresh(verification)

    # COMMIT #2, solo en PASS: el payout y su hash de transaccion.
    if result.status is VerificationStatus.PASS:
        _release_payout(db, bounty, submission, result)

    return verification


def get_latest_verification(db: Session, bounty: Bounty) -> Verification | None:
    return db.scalars(
        select(Verification)
        .join(Submission)
        .where(Submission.bounty_id == bounty.id)
        .order_by(Verification.id.desc())
        .limit(1)
    ).first()


def to_verification_response(
    verification: Verification,
) -> VerificationRecordResponse:
    """Reconstruye el resultado tipado a partir del result_json guardado."""
    return VerificationRecordResponse(
        id=verification.id,
        bounty_id=verification.submission.bounty_id,
        submission_id=verification.submission_id,
        created_at=verification.created_at,
        result=PullRequestVerificationResult.model_validate_json(
            verification.result_json
        ),
    )
