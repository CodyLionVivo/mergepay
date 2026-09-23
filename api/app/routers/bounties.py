from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import (
    assignment_service,
    evidence_service,
    funding_service,
    verification_service,
)
from app.auth_dependencies import (
    AuthenticatedWallet,
    can_read_bounty,
    optional_auth,
    require_auth,
    require_client,
    require_developer,
    require_participant,
)
from app.database import get_db
from app.github_client import GitHubClient
from app.hashing import compute_criteria_hash
from app.models import Bounty, BountyStatus, Criterion, Submission
from app.schemas import (
    AssignmentConfirmationCreate,
    BountyCreate,
    BountyResponse,
    FundingConfirmationCreate,
    OnChainBountyResponse,
    SubmissionCreate,
    SubmissionResponse,
    VerificationRecordResponse,
)
from app.verification_service import get_github_client

router = APIRouter(prefix="/bounties", tags=["bounties"])


def _get_bounty_or_404(db: Session, bounty_id: int) -> Bounty:
    bounty = db.get(Bounty, bounty_id)

    if bounty is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bounty not found"
        )

    return bounty


def _get_visible_bounty_or_404(
    db: Session, bounty_id: int, auth: AuthenticatedWallet | None
) -> Bounty:
    """El bounty solo si quien pregunta puede verlo.

    Una task que existe pero no es visible responde exactamente igual que una
    que no existe: quien no participa en ella no puede ni confirmar que esta
    ahi, aunque conozca el id.
    """
    bounty = db.get(Bounty, bounty_id)

    if bounty is None or not can_read_bounty(bounty, auth):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bounty not found"
        )

    return bounty


@router.post("", response_model=BountyResponse, status_code=status.HTTP_201_CREATED)
def create_bounty(
    payload: BountyCreate,
    db: Session = Depends(get_db),
    auth: AuthenticatedWallet = Depends(require_auth),
) -> Bounty:
    """Crea un bounty en DRAFT junto con sus criterios.

    El status nunca lo decide el request: en esta fase siempre es DRAFT.
    El client sale de la sesion, nunca del body: quien crea la task es quien
    luego tendra que financiarla desde esa misma wallet.
    """
    bounty = Bounty(
        client_wallet=auth.wallet,
        title=payload.title,
        description=payload.description,
        repo_owner=payload.repo_owner,
        repo_name=payload.repo_name,
        base_branch=payload.base_branch,
        amount_stroops=payload.amount_stroops,
        deadline_unix=payload.deadline_unix,
        criteria_hash=compute_criteria_hash(payload.criteria),
        status=BountyStatus.DRAFT,
        criteria=[
            Criterion(
                description=criterion.description,
                required=criterion.required,
                position=position,
            )
            for position, criterion in enumerate(payload.criteria)
        ],
    )

    db.add(bounty)
    db.commit()
    db.refresh(bounty)

    return bounty


@router.get("", response_model=list[BountyResponse])
def list_bounties(db: Session = Depends(get_db)) -> list[Bounty]:
    """El marketplace: solo tasks financiadas y todavia sin developer.

    Es discovery publico, asi que no depende de la sesion. Las tasks de cada
    quien se abren por su enlace, no desde aqui.
    """
    return list(
        db.scalars(
            select(Bounty)
            .where(Bounty.status == BountyStatus.OPEN_FUNDED)
            .order_by(Bounty.id)
        ).all()
    )


@router.get("/{bounty_id}", response_model=BountyResponse)
def get_bounty(
    bounty_id: int,
    db: Session = Depends(get_db),
    auth: AuthenticatedWallet | None = Depends(optional_auth),
) -> Bounty:
    return _get_visible_bounty_or_404(db, bounty_id, auth)


@router.get("/{bounty_id}/onchain", response_model=OnChainBountyResponse)
def get_onchain_bounty(
    bounty_id: int,
    db: Session = Depends(get_db),
    auth: AuthenticatedWallet | None = Depends(optional_auth),
) -> OnChainBountyResponse:
    """El escrow tal como lo guarda el contrato. Solo lee: ni firma ni escribe."""
    # La visibilidad se decide antes de construir el cliente: a quien no puede
    # ver la task no se le gasta ni una llamada a Stellar.
    bounty = _get_visible_bounty_or_404(db, bounty_id, auth)

    return evidence_service.read_onchain_bounty(bounty)


@router.post("/{bounty_id}/funded", response_model=BountyResponse)
def confirm_funding(
    bounty_id: int,
    payload: FundingConfirmationCreate,
    db: Session = Depends(get_db),
    github: GitHubClient = Depends(get_github_client),
    auth: AuthenticatedWallet = Depends(require_auth),
) -> Bounty:
    bounty = _get_bounty_or_404(db, bounty_id)

    # Un DRAFT antiguo puede no tener client todavia: entonces lo reclama
    # quien aparezca como client on-chain, que el servicio comprueba.
    if bounty.client_wallet is not None:
        require_client(bounty, auth.wallet)

    return funding_service.confirm_funding(
        db, bounty, payload.transaction_hash, github, auth.wallet
    )


@router.post("/{bounty_id}/assigned", response_model=BountyResponse)
def confirm_assignment(
    bounty_id: int,
    payload: AssignmentConfirmationCreate,
    db: Session = Depends(get_db),
    auth: AuthenticatedWallet = Depends(require_auth),
) -> Bounty:
    bounty = _get_bounty_or_404(db, bounty_id)

    return assignment_service.confirm_assignment(
        db,
        bounty,
        payload.transaction_hash,
        payload.developer_github,
        payload.wallet_signature,
        auth.wallet,
    )


@router.post(
    "/{bounty_id}/submission",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_submission(
    bounty_id: int,
    payload: SubmissionCreate,
    db: Session = Depends(get_db),
    github: GitHubClient = Depends(get_github_client),
    auth: AuthenticatedWallet = Depends(require_auth),
) -> Submission:
    bounty = _get_bounty_or_404(db, bounty_id)

    require_developer(bounty, auth.wallet)

    return verification_service.register_submission(
        db, bounty, payload.pull_request_url, github
    )


@router.get("/{bounty_id}/submission", response_model=SubmissionResponse)
def get_submission(
    bounty_id: int,
    db: Session = Depends(get_db),
    auth: AuthenticatedWallet | None = Depends(optional_auth),
) -> Submission:
    """La submission tal como esta guardada: no consulta GitHub ni escribe."""
    # Primero si la task se puede ver, y solo despues si tiene submission: asi
    # "privada sin PR" y "no existe" se responden igual.
    bounty = _get_visible_bounty_or_404(db, bounty_id, auth)

    if bounty.submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )

    return bounty.submission


@router.post("/{bounty_id}/verify", response_model=VerificationRecordResponse)
def verify_bounty(
    bounty_id: int,
    db: Session = Depends(get_db),
    github: GitHubClient = Depends(get_github_client),
    auth: AuthenticatedWallet = Depends(require_auth),
) -> VerificationRecordResponse:
    bounty = _get_bounty_or_404(db, bounty_id)

    # Client y developer pueden pedir verificacion; ninguno de los dos aprueba
    # el pago, que lo decide el verifier segun GitHub.
    require_participant(bounty, auth.wallet)

    verification = verification_service.run_verification(db, bounty, github)

    return verification_service.to_verification_response(verification)


@router.get("/{bounty_id}/verification", response_model=VerificationRecordResponse)
def get_latest_verification(
    bounty_id: int,
    db: Session = Depends(get_db),
    auth: AuthenticatedWallet | None = Depends(optional_auth),
) -> VerificationRecordResponse:
    bounty = _get_visible_bounty_or_404(db, bounty_id, auth)

    verification = verification_service.get_latest_verification(db, bounty)

    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found"
        )

    return verification_service.to_verification_response(verification)
