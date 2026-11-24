from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.repositories import agent_repository, borrower_repository, call_repository
from app.core.enums import AgentStatus, BorrowerStatus, CallStatus
from app.core.state_machines import is_terminal_call_state
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ReconciliationResult:
    agents_recovered: int = 0
    borrowers_recovered: int = 0
    calls_cancelled: int = 0
    calls_queried_provider: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class ReconciliationService:
    """
    Handles recovery after worker crashes, provider outages, and stale state.

    Key principle: a lease expiring does NOT mean a call has ended.
    We must check actual call state before releasing a reservation.
    """

    def reconcile_stale_agents(self, db: Session) -> int:
        """
        Find agents with RESERVED status whose lease has expired.
        Only release if they have no active call.
        """
        now = datetime.now(timezone.utc)
        stale_agents = agent_repository.get_stale_reservations(db, now)
        released = 0

        for agent in stale_agents:
            if not agent.current_call_id:
                # No call associated — safe to release
                agent_repository.release_agent(db, agent.id, AgentStatus.AVAILABLE)
                released += 1
                logger.info("Released stale agent %s (no call)", agent.id)
                continue

            # Check if the associated call is in a terminal state
            try:
                call = call_repository.get_call(db, agent.current_call_id)
                if is_terminal_call_state(call.status):
                    # Call finished, agent stuck — release
                    agent_repository.release_agent(db, agent.id, AgentStatus.AVAILABLE)
                    released += 1
                    logger.info(
                        "Released stale agent %s (call %s is %s)",
                        agent.id, call.id, call.status,
                    )
                else:
                    # Call is still active — extend lease to prevent premature release
                    from sqlalchemy import update
                    from app.models.agent import Agent
                    db.execute(
                        update(Agent)
                        .where(Agent.id == agent.id)
                        .values(
                            reservation_expires_at=now + timedelta(seconds=settings.lease_duration_seconds)
                        )
                    )
                    logger.debug(
                        "Extended lease for agent %s (call %s is %s)",
                        agent.id, call.id, call.status,
                    )
            except Exception as exc:
                logger.error("Error checking call for agent %s: %s", agent.id, exc)

        db.flush()
        return released

    def reconcile_stale_borrowers(self, db: Session) -> int:
        """
        Find borrowers stuck in RESERVED state with no active call.
        Return them to PENDING.
        """
        from app.repositories.campaign_repository import get_active_campaigns

        campaigns = get_active_campaigns(db)
        total_recovered = 0

        for campaign in campaigns:
            stuck = borrower_repository.get_reserved_without_active_call(db, campaign.id)
            for borrower in stuck:
                borrower_repository.release_borrower(db, borrower.id, BorrowerStatus.PENDING)
                total_recovered += 1
                logger.info("Returned stuck borrower %s to PENDING", borrower.id)

        db.flush()
        return total_recovered

    def reconcile_stale_calls(self, db: Session) -> ReconciliationResult:
        """
        Find calls in RESERVED or INITIATED states older than lease duration.
        RESERVED (pre-initiation): safe to cancel.
        INITIATED (post-initiation): query provider before cancelling.
        """
        result = ReconciliationResult()
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.lease_duration_seconds * 2)

        stale_calls = call_repository.get_calls_for_recovery(db, cutoff)

        for call in stale_calls:
            try:
                if call.status == CallStatus.RESERVED:
                    # Pre-initiation — safe to cancel and release
                    call_repository.update_call_status(
                        db, call.id, CallStatus.CANCELLED,
                        failure_reason="Worker crash recovery — pre-initiation cancel"
                    )
                    if call.agent_id:
                        try:
                            agent_repository.release_agent(db, call.agent_id, AgentStatus.AVAILABLE)
                        except Exception as agent_exc:
                            logger.error("Failed to release agent %s: %s", call.agent_id, agent_exc)
                    if call.borrower_id:
                        try:
                            borrower_repository.release_borrower(db, call.borrower_id, BorrowerStatus.PENDING)
                        except Exception as bor_exc:
                            logger.error("Failed to release borrower %s: %s", call.borrower_id, bor_exc)
                    result.calls_cancelled += 1
                    logger.info("Cancelled stale RESERVED call %s", call.id)

                elif call.status == CallStatus.INITIATED:
                    # Post-initiation — provider may have already connected
                    # Mark as FAILED with explanation rather than blindly retrying
                    # (safe policy: do not re-dial an uncertain call)
                    result.calls_queried_provider += 1
                    call_repository.update_call_status(
                        db, call.id, CallStatus.FAILED,
                        failure_reason="Worker crash recovery — initiated call timed out"
                    )
                    if call.agent_id:
                        try:
                            agent_repository.release_agent(db, call.agent_id, AgentStatus.AVAILABLE)
                        except Exception as agent_exc:
                            logger.error("Failed to release agent %s: %s", call.agent_id, agent_exc)
                    if call.borrower_id:
                        try:
                            borrower_repository.release_borrower(db, call.borrower_id, BorrowerStatus.FAILED)
                        except Exception as bor_exc:
                            logger.error("Failed to release borrower %s: %s", call.borrower_id, bor_exc)
                    logger.info("Marked stale INITIATED call %s as FAILED", call.id)

            except Exception as exc:
                result.errors.append(f"Error reconciling call {call.id}: {exc}")
                logger.error("Reconciliation error for call %s: %s", call.id, exc)

        db.flush()
        return result
