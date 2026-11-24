from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from app.repositories import agent_repository, borrower_repository
from app.services.call_allocator import CallAllocator, AllocationResult
from app.core.enums import DialMode
from app.core.exceptions import CampaignNotActiveError
from app.repositories.campaign_repository import get_campaign
from app.core.enums import CampaignStatus

logger = logging.getLogger(__name__)


@dataclass
class DialTickResult:
    calls_initiated: int = 0
    calls_failed: int = 0
    available_agents: int = 0
    pending_borrowers: int = 0
    allocations: list[AllocationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ProgressiveDialer:
    """
    Progressive dialing: exactly one outbound call per available agent.
    Never creates more calls than there are available agents.
    """

    def __init__(self, db: Session, campaign_id: str, provider_name: str = "provider_a"):
        self.db = db
        self.campaign_id = campaign_id
        self.provider_name = provider_name
        self._allocator = CallAllocator()

    def tick(self) -> DialTickResult:
        result = DialTickResult()

        # Verify campaign is active
        campaign = get_campaign(self.db, self.campaign_id)
        if campaign.status != CampaignStatus.ACTIVE:
            result.errors.append(f"Campaign {self.campaign_id} is not ACTIVE (status={campaign.status})")
            return result

        # Count available agents — this is our HARD CAP
        result.available_agents = agent_repository.count_available(
            self.db, campaign_id=self.campaign_id
        )
        result.pending_borrowers = borrower_repository.count_pending(
            self.db, campaign_id=self.campaign_id
        )

        if result.available_agents == 0:
            logger.debug("No available agents for campaign %s", self.campaign_id)
            return result

        if result.pending_borrowers == 0:
            logger.debug("No pending borrowers for campaign %s", self.campaign_id)
            return result

        # For each available agent, attempt one allocation
        slots = min(result.available_agents, result.pending_borrowers, campaign.max_concurrent_calls)

        for _ in range(slots):
            allocation = self._allocator.allocate(
                self.db,
                campaign_id=self.campaign_id,
                dial_mode=DialMode.PROGRESSIVE,
                provider_name=self.provider_name,
            )
            if allocation is None:
                # Contention or no more resources — stop trying
                break
            result.allocations.append(allocation)
            result.calls_initiated += 1

        logger.info(
            "Progressive tick: campaign=%s initiated=%d available=%d",
            self.campaign_id,
            result.calls_initiated,
            result.available_agents,
        )
        return result
