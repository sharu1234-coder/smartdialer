from __future__ import annotations
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from app.models.call import Call
from app.core.enums import CallStatus, DialMode
from app.core.exceptions import CallNotFoundError
from app.core.state_machines import ACTIVE_CALL_STATES

logger = logging.getLogger(__name__)


def create_call(
    db: Session,
    campaign_id: str,
    borrower_id: str,
    agent_id: str,
    dial_mode: DialMode,
    idempotency_key: str,
    provider_id: str = "provider_a",
) -> Call:
    call = Call(
        id=str(uuid.uuid4()),
        campaign_id=campaign_id,
        borrower_id=borrower_id,
        agent_id=agent_id,
        dial_mode=dial_mode,
        idempotency_key=idempotency_key,
        status=CallStatus.RESERVED,
        provider_id=provider_id,
        state_version=0,
    )
    db.add(call)
    db.flush()
    return call


def get_call(db: Session, call_id: str) -> Call:
    call = db.get(Call, call_id)
    if not call:
        raise CallNotFoundError(f"Call {call_id} not found")
    return call


def get_call_by_idempotency_key(db: Session, key: str) -> Optional[Call]:
    stmt = select(Call).where(Call.idempotency_key == key)
    return db.execute(stmt).scalars().first()


def update_call_status(
    db: Session,
    call_id: str,
    new_status: CallStatus,
    provider_call_id: Optional[str] = None,
    failure_reason: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Call:
    now = datetime.now(timezone.utc)
    values: dict = {
        "status": new_status,
        "state_version": Call.state_version + 1,
        "updated_at": now,
    }
    if provider_call_id is not None:
        values["provider_call_id"] = provider_call_id
    if failure_reason is not None:
        values["failure_reason"] = failure_reason
    if agent_id is not None:
        values["agent_id"] = agent_id

    if new_status == CallStatus.INITIATED:
        values["initiated_at"] = now
    elif new_status == CallStatus.ANSWERED:
        values["answered_at"] = now
    elif new_status == CallStatus.CONNECTED:
        values["connected_at"] = now
    elif new_status == CallStatus.COMPLETED:
        values["completed_at"] = now
    elif new_status == CallStatus.FAILED:
        values["failed_at"] = now

    result = db.execute(
        update(Call).where(Call.id == call_id).values(**values).returning(Call)
    )
    db.flush()
    call = result.scalars().first()
    if not call:
        raise CallNotFoundError(f"Call {call_id} not found for update")
    return call


def get_active_calls(
    db: Session, campaign_id: Optional[str] = None
) -> list[Call]:
    stmt = select(Call).where(Call.status.in_(list(ACTIVE_CALL_STATES)))
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    return list(db.execute(stmt).scalars().all())


def get_calls_in_states(
    db: Session, states: list[CallStatus], campaign_id: Optional[str] = None
) -> list[Call]:
    stmt = select(Call).where(Call.status.in_(states))
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    return list(db.execute(stmt).scalars().all())


def count_active_calls(db: Session, campaign_id: Optional[str] = None) -> int:
    stmt = select(func.count(Call.id)).where(Call.status.in_(list(ACTIVE_CALL_STATES)))
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    return db.execute(stmt).scalar() or 0


def count_calls_in_states(
    db: Session, states: list[CallStatus], campaign_id: Optional[str] = None
) -> int:
    stmt = select(func.count(Call.id)).where(Call.status.in_(states))
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    return db.execute(stmt).scalar() or 0


def get_calls_for_recovery(
    db: Session, cutoff_time: datetime, campaign_id: Optional[str] = None
) -> list[Call]:
    """Find calls stuck in INITIATED state older than cutoff (worker crash scenario)."""
    stmt = select(Call).where(
        Call.status.in_([CallStatus.INITIATED, CallStatus.RESERVED]),
        Call.created_at < cutoff_time,
    )
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    return list(db.execute(stmt).scalars().all())


def get_completed_calls_for_rate(
    db: Session, campaign_id: str, limit: int = 100
) -> list[Call]:
    """Get recent completed/failed calls to estimate answer rate."""
    stmt = (
        select(Call)
        .where(
            Call.campaign_id == campaign_id,
            Call.status.in_([CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.CANCELLED]),
        )
        .order_by(Call.updated_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def count_calls_by_status(db: Session, campaign_id: str) -> dict[str, int]:
    stmt = (
        select(Call.status, func.count(Call.id))
        .where(Call.campaign_id == campaign_id)
        .group_by(Call.status)
    )
    rows = db.execute(stmt).all()
    return {row[0]: row[1] for row in rows}
