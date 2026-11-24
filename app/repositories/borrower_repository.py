from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from app.models.borrower import Borrower
from app.core.enums import BorrowerStatus
from app.core.exceptions import BorrowerNotAvailableError, BorrowerNotFoundError

logger = logging.getLogger(__name__)


def get_borrower(db: Session, borrower_id: str) -> Borrower:
    borrower = db.get(Borrower, borrower_id)
    if not borrower:
        raise BorrowerNotFoundError(f"Borrower {borrower_id} not found")
    return borrower


def get_next_borrower(db: Session, campaign_id: str) -> Optional[Borrower]:
    """
    Atomically fetch the next pending borrower using SELECT FOR UPDATE SKIP LOCKED.
    Returns None if no borrowers available.
    """
    stmt = (
        select(Borrower)
        .where(
            Borrower.campaign_id == campaign_id,
            Borrower.status == BorrowerStatus.PENDING,
        )
        .order_by(Borrower.priority.desc(), Borrower.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def reserve_borrower(db: Session, borrower_id: str) -> Borrower:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(Borrower)
        .where(Borrower.id == borrower_id, Borrower.status == BorrowerStatus.PENDING)
        .values(
            status=BorrowerStatus.RESERVED,
            last_attempt_at=now,
            attempt_count=Borrower.attempt_count + 1,
            updated_at=now,
        )
        .returning(Borrower)
    )
    db.flush()
    borrower = result.scalars().first()
    if not borrower:
        raise BorrowerNotAvailableError(
            f"Borrower {borrower_id} could not be reserved (already taken or status changed)"
        )
    return borrower


def release_borrower(
    db: Session, borrower_id: str, to_status: BorrowerStatus
) -> Borrower:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(Borrower)
        .where(Borrower.id == borrower_id)
        .values(status=to_status, updated_at=now)
        .returning(Borrower)
    )
    db.flush()
    borrower = result.scalars().first()
    if not borrower:
        raise BorrowerNotFoundError(f"Borrower {borrower_id} not found for release")
    return borrower


def count_pending(db: Session, campaign_id: str) -> int:
    stmt = select(func.count(Borrower.id)).where(
        Borrower.campaign_id == campaign_id,
        Borrower.status == BorrowerStatus.PENDING,
    )
    return db.execute(stmt).scalar() or 0


def create_borrower(
    db: Session,
    campaign_id: str,
    phone_number: str,
    name: str,
    priority: int = 0,
) -> Borrower:
    borrower = Borrower(
        campaign_id=campaign_id,
        phone_number=phone_number,
        name=name,
        priority=priority,
        status=BorrowerStatus.PENDING,
    )
    db.add(borrower)
    db.flush()
    return borrower


def bulk_create_borrowers(
    db: Session, campaign_id: str, borrowers_data: list[dict]
) -> list[Borrower]:
    borrowers = [
        Borrower(
            campaign_id=campaign_id,
            phone_number=b["phone_number"],
            name=b.get("name", "Unknown"),
            priority=b.get("priority", 0),
            status=BorrowerStatus.PENDING,
        )
        for b in borrowers_data
    ]
    db.add_all(borrowers)
    db.flush()
    return borrowers


def get_reserved_without_active_call(db: Session, campaign_id: str) -> list[Borrower]:
    """Find borrowers stuck in RESERVED state with no active call."""
    from sqlalchemy import not_, exists
    from app.models.call import Call
    from app.core.enums import CallStatus

    active_states = [
        CallStatus.RESERVED, CallStatus.INITIATED, CallStatus.RINGING,
        CallStatus.ANSWERED, CallStatus.CONNECTED,
    ]
    stmt = select(Borrower).where(
        Borrower.campaign_id == campaign_id,
        Borrower.status == BorrowerStatus.RESERVED,
        not_(
            exists(
                select(Call.id).where(
                    Call.borrower_id == Borrower.id,
                    Call.status.in_(active_states),
                )
            )
        ),
    )
    return list(db.execute(stmt).scalars().all())
