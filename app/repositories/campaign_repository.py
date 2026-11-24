from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.models.campaign import Campaign
from app.core.enums import CampaignStatus, DialMode
from app.core.exceptions import CampaignNotFoundError

logger = logging.getLogger(__name__)


def create_campaign(
    db: Session,
    name: str,
    dial_mode: DialMode = DialMode.PROGRESSIVE,
    max_concurrent_calls: int = 50,
    priority: int = 0,
) -> Campaign:
    campaign = Campaign(
        name=name,
        dial_mode=dial_mode,
        max_concurrent_calls=max_concurrent_calls,
        priority=priority,
        status=CampaignStatus.DRAFT,
    )
    db.add(campaign)
    db.flush()
    return campaign


def get_campaign(db: Session, campaign_id: str) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
    return campaign


def get_active_campaigns(db: Session) -> list[Campaign]:
    stmt = select(Campaign).where(Campaign.status == CampaignStatus.ACTIVE)
    return list(db.execute(stmt).scalars().all())


def get_all_campaigns(db: Session) -> list[Campaign]:
    stmt = select(Campaign).order_by(Campaign.created_at.desc())
    return list(db.execute(stmt).scalars().all())


def update_campaign_status(
    db: Session, campaign_id: str, new_status: CampaignStatus
) -> Campaign:
    now = datetime.now(timezone.utc)
    values: dict = {"status": new_status, "updated_at": now}
    if new_status == CampaignStatus.ACTIVE:
        values["started_at"] = now
    elif new_status in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
        values["completed_at"] = now
    result = db.execute(
        update(Campaign).where(Campaign.id == campaign_id).values(**values).returning(Campaign)
    )
    db.flush()
    campaign = result.scalars().first()
    if not campaign:
        raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
    return campaign


def get_campaign_stats(db: Session, campaign_id: str) -> dict:
    from app.repositories.call_repository import count_calls_by_status
    from app.repositories.agent_repository import count_available, count_by_status
    from app.repositories.borrower_repository import count_pending
    from app.core.enums import AgentStatus

    call_counts = count_calls_by_status(db, campaign_id)
    return {
        "calls": call_counts,
        "agents_available": count_available(db, campaign_id),
        "agents_reserved": count_by_status(db, AgentStatus.RESERVED, campaign_id),
        "agents_connected": count_by_status(db, AgentStatus.CONNECTED, campaign_id),
        "borrowers_pending": count_pending(db, campaign_id),
    }
