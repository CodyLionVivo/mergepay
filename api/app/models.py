from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class BountyStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN_FUNDED = "OPEN_FUNDED"
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    NEEDS_CHANGES = "NEEDS_CHANGES"
    ELIGIBLE = "ELIGIBLE"
    PAID = "PAID"
    CANCELLED_REFUNDED = "CANCELLED_REFUNDED"
    EXPIRED_REFUNDED = "EXPIRED_REFUNDED"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Bounty(Base):
    __tablename__ = "bounties"

    __table_args__ = (
        CheckConstraint("amount_stroops > 0", name="ck_bounties_amount_positive"),
        CheckConstraint("deadline_unix > 0", name="ck_bounties_deadline_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    repo_owner: Mapped[str] = mapped_column(String, nullable=False)
    repo_name: Mapped[str] = mapped_column(String, nullable=False)
    base_branch: Mapped[str] = mapped_column(String, nullable=False, default="main")
    base_sha: Mapped[str | None] = mapped_column(String, nullable=True)

    client_wallet: Mapped[str | None] = mapped_column(String, nullable=True)
    developer_wallet: Mapped[str | None] = mapped_column(String, nullable=True)
    developer_github: Mapped[str | None] = mapped_column(String, nullable=True)

    amount_stroops: Mapped[int] = mapped_column(Integer, nullable=False)
    deadline_unix: Mapped[int] = mapped_column(Integer, nullable=False)

    criteria_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    github_issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    create_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    release_tx_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(
        String, nullable=False, default=BountyStatus.DRAFT
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    criteria: Mapped[list["Criterion"]] = relationship(
        back_populates="bounty",
        cascade="all, delete-orphan",
        order_by="Criterion.position",
    )

    # Uno a uno: la unicidad la garantiza el UNIQUE de Submission.bounty_id.
    submission: Mapped["Submission | None"] = relationship(
        back_populates="bounty",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Criterion(Base):
    __tablename__ = "criteria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    bounty_id: Mapped[int] = mapped_column(
        ForeignKey("bounties.id", ondelete="CASCADE"), nullable=False
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    bounty: Mapped["Bounty"] = relationship(back_populates="criteria")


class Submission(Base):
    """El pull request que un developer registro contra un bounty."""

    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    bounty_id: Mapped[int] = mapped_column(
        ForeignKey("bounties.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    pull_request_url: Mapped[str] = mapped_column(String, nullable=False)
    pull_request_number: Mapped[int] = mapped_column(Integer, nullable=False)

    author: Mapped[str | None] = mapped_column(String, nullable=True)

    # No esta congelado: cada verificacion vuelve a inspeccionar el PR y lo
    # actualiza si el developer hizo push.
    head_ref: Mapped[str] = mapped_column(String, nullable=False)
    head_sha: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    bounty: Mapped["Bounty"] = relationship(back_populates="submission")

    verifications: Mapped[list["Verification"]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="Verification.id",
    )


class Verification(Base):
    """Resultado de una pasada de verificacion. Se conserva el historial."""

    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )

    head_sha: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    eligible_for_payout: Mapped[bool] = mapped_column(Boolean, nullable=False)

    # PullRequestVerificationResult serializado, nunca el JSON de GitHub.
    result_json: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    submission: Mapped["Submission"] = relationship(back_populates="verifications")
