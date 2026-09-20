from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Bounty, BountyStatus, Criterion
from app.schemas import BountyCreate, BountyResponse

router = APIRouter(prefix="/bounties", tags=["bounties"])


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
    bounty = db.get(Bounty, bounty_id)

    if bounty is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Bounty not found"
        )

    return bounty
