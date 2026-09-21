from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import verification_service
from app.database import get_db
from app.github_client import GitHubClient
from app.models import Bounty, BountyStatus, Criterion, Submission
from app.schemas import (
    BountyCreate,
    BountyResponse,
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


@router.post("", response_model=BountyResponse, status_code=status.HTTP_201_CREATED)
def create_bounty(payload: BountyCreate, db: Session = Depends(get_db)) -> Bounty:
    """Crea un bounty en DRAFT junto con sus criterios.

    El status nunca lo decide el request: en esta fase siempre es DRAFT.
    La posicion de cada criterio sale del orden en que llegaron.
    """
    bounty = Bounty(
        title=payload.title,
        description=payload.description,
        repo_owner=payload.repo_owner,
        repo_name=payload.repo_name,
        base_branch=payload.base_branch,
        amount_stroops=payload.amount_stroops,
        deadline_unix=payload.deadline_unix,
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
    return list(db.scalars(select(Bounty).order_by(Bounty.id)).all())


@router.get("/{bounty_id}", response_model=BountyResponse)
def get_bounty(bounty_id: int, db: Session = Depends(get_db)) -> Bounty:
    return _get_bounty_or_404(db, bounty_id)


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
) -> Submission:
    bounty = _get_bounty_or_404(db, bounty_id)

    return verification_service.register_submission(
        db, bounty, payload.pull_request_url, github
    )


@router.post("/{bounty_id}/verify", response_model=VerificationRecordResponse)
def verify_bounty(
    bounty_id: int,
    db: Session = Depends(get_db),
    github: GitHubClient = Depends(get_github_client),
) -> VerificationRecordResponse:
    bounty = _get_bounty_or_404(db, bounty_id)

    verification = verification_service.run_verification(db, bounty, github)

    return verification_service.to_verification_response(verification)


@router.get("/{bounty_id}/verification", response_model=VerificationRecordResponse)
def get_latest_verification(
    bounty_id: int, db: Session = Depends(get_db)
) -> VerificationRecordResponse:
    bounty = _get_bounty_or_404(db, bounty_id)

    verification = verification_service.get_latest_verification(db, bounty)

    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found"
        )

    return verification_service.to_verification_response(verification)
