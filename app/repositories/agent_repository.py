from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session
from app.models.agent import Agent
from app.core.enums import AgentStatus
from app.core.exceptions import AgentNotAvailableError, AgentNotFoundError
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def get_agent(db: Session, agent_id: str) -> Agent:
    agent = db.get(Agent, agent_id)
    if not agent:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    return agent


def get_available_agents(
    db: Session, campaign_id: Optional[str] = None, limit: int = 50
) -> list[Agent]:
    stmt = (
        select(Agent)
        .where(Agent.status == AgentStatus.AVAILABLE)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    if campaign_id:
        stmt = stmt.where(Agent.campaign_id == campaign_id)
    return list(db.execute(stmt).scalars().all())


def count_available(db: Session, campaign_id: Optional[str] = None) -> int:
    stmt = select(func.count(Agent.id)).where(Agent.status == AgentStatus.AVAILABLE)
    if campaign_id:
        stmt = stmt.where(Agent.campaign_id == campaign_id)
    result = db.execute(stmt).scalar()
    return result or 0


def count_by_status(db: Session, status: AgentStatus, campaign_id: Optional[str] = None) -> int:
    stmt = select(func.count(Agent.id)).where(Agent.status == status)
    if campaign_id:
        stmt = stmt.where(Agent.campaign_id == campaign_id)
    return db.execute(stmt).scalar() or 0


def reserve_agent(
    db: Session,
    agent_id: str,
    call_id: str,
    expected_version: int,
    lease_seconds: int = 30,
) -> Agent:
    """
    Atomic agent reservation using optimistic locking.
    Only succeeds if status=AVAILABLE and state_version matches expected_version.
    Raises AgentNotAvailableError if another worker already reserved it.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=lease_seconds)

    result = db.execute(
        update(Agent)
        .where(
            Agent.id == agent_id,
            Agent.status == AgentStatus.AVAILABLE,
            Agent.state_version == expected_version,
        )
        .values(
            status=AgentStatus.RESERVED,
            current_call_id=call_id,
            reservation_expires_at=expires_at,
            state_version=Agent.state_version + 1,
            updated_at=now,
        )
        .returning(Agent)
    )
    db.flush()
    agent = result.scalars().first()
    if not agent:
        raise AgentNotAvailableError(
            f"Agent {agent_id} could not be reserved (already taken or state changed)"
        )
    return agent


def release_agent(
    db: Session,
    agent_id: str,
    to_status: AgentStatus = AgentStatus.AVAILABLE,
) -> Agent:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(
            status=to_status,
            current_call_id=None,
            reservation_expires_at=None,
            available_since=now if to_status == AgentStatus.AVAILABLE else None,
            state_version=Agent.state_version + 1,
            updated_at=now,
        )
        .returning(Agent)
    )
    db.flush()
    agent = result.scalars().first()
    if not agent:
        raise AgentNotFoundError(f"Agent {agent_id} not found for release")
    return agent


def update_agent_status(
    db: Session,
    agent_id: str,
    new_status: AgentStatus,
    call_id: Optional[str] = None,
) -> Agent:
    now = datetime.now(timezone.utc)
    values: dict = {
        "status": new_status,
        "state_version": Agent.state_version + 1,
        "updated_at": now,
    }
    if new_status == AgentStatus.AVAILABLE:
        values["current_call_id"] = None
        values["reservation_expires_at"] = None
        values["available_since"] = now
    elif call_id is not None:
        values["current_call_id"] = call_id
    result = db.execute(
        update(Agent).where(Agent.id == agent_id).values(**values).returning(Agent)
    )
    db.flush()
    agent = result.scalars().first()
    if not agent:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    return agent


def update_heartbeat(db: Session, agent_id: str) -> None:
    now = datetime.now(timezone.utc)
    db.execute(
        update(Agent)
        .where(Agent.id == agent_id)
        .values(last_heartbeat=now, updated_at=now)
    )
    db.flush()


def get_stale_reservations(db: Session, cutoff_time: datetime) -> list[Agent]:
    stmt = select(Agent).where(
        Agent.status == AgentStatus.RESERVED,
        Agent.reservation_expires_at < cutoff_time,
    )
    return list(db.execute(stmt).scalars().all())


def create_agent(db: Session, name: str, campaign_id: Optional[str] = None) -> Agent:
    agent = Agent(
        name=name,
        status=AgentStatus.AVAILABLE,
        campaign_id=campaign_id,
        available_since=datetime.now(timezone.utc),
        last_heartbeat=datetime.now(timezone.utc),
    )
    db.add(agent)
    db.flush()
    return agent


def set_agents_offline(db: Session, agent_ids: list[str]) -> int:
    result = db.execute(
        update(Agent)
        .where(Agent.id.in_(agent_ids), Agent.status == AgentStatus.AVAILABLE)
        .values(
            status=AgentStatus.OFFLINE,
            state_version=Agent.state_version + 1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return result.rowcount
