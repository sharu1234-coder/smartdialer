from __future__ import annotations
import uuid
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from app.models.call import Call
from app.models.outbox import Outbox
from app.models.reservation import Reservation
from app.repositories import agent_repository, borrower_repository, call_repository
from app.core.enums import DialMode, OutboxStatus
from app.core.exceptions import AgentNotAvailableError, BorrowerNotAvailableError
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class AllocationResult:
    call_id: str
    agent_id: str
    borrower_id: str
    campaign_id: str
    phone_number: str
    idempotency_key: str
    dial_mode: DialMode
    provider_name: str


class CallAllocator:
    """
    Atomically allocates one agent + one borrower + one call record + one outbox entry.
    All in a single database transaction so it cannot be half-committed.
    """

    def allocate(
        self,
        db: Session,
        campaign_id: str,
        dial_mode: DialMode,
        provider_name: str = "provider_a",
    ) -> Optional[AllocationResult]:
        """
        Returns AllocationResult on success, None if no resources available.
        Never raises on contention — just returns None.
        """
        try:
            # Step 1: Get next borrower with SKIP LOCKED — skips rows locked by other workers
            borrower = borrower_repository.get_next_borrower(db, campaign_id)
            if borrower is None:
                return None

            # Step 2: Get one available agent with SKIP LOCKED
            agents = agent_repository.get_available_agents(db, campaign_id=campaign_id, limit=1)
            if not agents:
                # Release the borrower lock by rolling back or returning without committing
                return None
            agent = agents[0]

            # Step 3: Reserve borrower (atomic update with status check)
            borrower = borrower_repository.reserve_borrower(db, borrower.id)

            # Step 4: Reserve agent using optimistic locking (state_version check)
            agent = agent_repository.reserve_agent(
                db,
                agent_id=agent.id,
                call_id="pending",  # placeholder, updated after call creation
                expected_version=agent.state_version,
                lease_seconds=settings.lease_duration_seconds,
            )

            # Step 5: Build idempotency key
            ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            idempotency_key = (
                f"{dial_mode.value[:4].lower()}-"
                f"{campaign_id[:8]}-"
                f"{borrower.id[:8]}-"
                f"{agent.id[:8]}-"
                f"{ts_ms}"
            )

            # Step 6: Create call record
            call = call_repository.create_call(
                db,
                campaign_id=campaign_id,
                borrower_id=borrower.id,
                agent_id=agent.id,
                dial_mode=dial_mode,
                idempotency_key=idempotency_key,
                provider_id=provider_name,
            )

            # Step 7: Update agent's current_call_id now that we have the call id
            from sqlalchemy import update as sa_update
            from app.models.agent import Agent
            db.execute(
                sa_update(Agent)
                .where(Agent.id == agent.id)
                .values(current_call_id=call.id)
            )

            # Step 8: Create outbox entry for async provider dispatch
            outbox = Outbox(
                call_id=call.id,
                provider_name=provider_name,
                status=OutboxStatus.PENDING,
                idempotency_key=idempotency_key,
                payload={
                    "call_id": call.id,
                    "phone_number": borrower.phone_number,
                    "agent_id": agent.id,
                    "campaign_id": campaign_id,
                    "idempotency_key": idempotency_key,
                },
                next_retry_at=datetime.now(timezone.utc),
            )
            db.add(outbox)

            # Step 9: Create reservation record for audit and recovery
            reservation = Reservation(
                agent_id=agent.id,
                borrower_id=borrower.id,
                call_id=call.id,
                worker_id=settings.worker_id,
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=settings.lease_duration_seconds),
            )
            db.add(reservation)

            db.flush()

            logger.info(
                "Allocated call=%s agent=%s borrower=%s mode=%s",
                call.id,
                agent.id,
                borrower.id,
                dial_mode.value,
            )

            return AllocationResult(
                call_id=call.id,
                agent_id=agent.id,
                borrower_id=borrower.id,
                campaign_id=campaign_id,
                phone_number=borrower.phone_number,
                idempotency_key=idempotency_key,
                dial_mode=dial_mode,
                provider_name=provider_name,
            )

        except (AgentNotAvailableError, BorrowerNotAvailableError) as exc:
            logger.debug("Allocation contention: %s", exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected allocation error: %s", exc)
            raise
