from __future__ import annotations
import pytest
from app.services.call_allocator import CallAllocator
from app.services.reconciliation_service import ReconciliationService
from app.repositories.call_repository import update_call_status, get_call
from app.repositories.agent_repository import get_agent
from app.core.enums import DialMode, CallStatus, AgentStatus
from app.providers.provider_factory import initialize_default_providers, reset_providers
from datetime import datetime, timezone, timedelta
from sqlalchemy import update
from app.models.call import Call
from app.models.agent import Agent


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


class TestWorkerCrash:
    def test_stale_reserved_call_cancelled_on_recovery(self, db, campaign, agents, borrowers):
        """
        Worker crash scenario: agent RESERVED, call RESERVED, worker dies.
        RecoveryWorker must cancel the call and return agent to AVAILABLE.
        """
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        # Simulate old creation time (past lease duration)
        db.execute(
            update(Call)
            .where(Call.id == alloc.call_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        )
        db.commit()

        # Verify state before recovery
        call_before = get_call(db, alloc.call_id)
        assert call_before.status == CallStatus.RESERVED

        # Run reconciliation
        reconciler = ReconciliationService()
        result = reconciler.reconcile_stale_calls(db)
        db.commit()

        assert result.calls_cancelled >= 1

        call_after = get_call(db, alloc.call_id)
        assert call_after.status == CallStatus.CANCELLED

        # Agent must be released
        agent_after = get_agent(db, alloc.agent_id)
        assert agent_after.status == AgentStatus.AVAILABLE

    def test_stale_initiated_call_failed_on_recovery(self, db, campaign, agents, borrowers):
        """
        Worker crash scenario: call in INITIATED state (provider dispatched).
        Recovery marks it FAILED since we can't be sure of provider state.
        """
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None

        # Walk to INITIATED
        update_call_status(db, alloc.call_id, CallStatus.INITIATED)
        db.commit()

        # Age the call
        db.execute(
            update(Call)
            .where(Call.id == alloc.call_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        )
        db.commit()

        reconciler = ReconciliationService()
        result = reconciler.reconcile_stale_calls(db)
        db.commit()

        call_after = get_call(db, alloc.call_id)
        assert call_after.status == CallStatus.FAILED

        agent_after = get_agent(db, alloc.agent_id)
        assert agent_after.status == AgentStatus.AVAILABLE

    def test_stale_agent_reservation_recovered(self, db, campaign, agents, borrowers):
        """
        Agent with RESERVED status and expired lease but no active call gets released.
        """
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        # Expire the agent's reservation
        db.execute(
            update(Agent)
            .where(Agent.id == alloc.agent_id)
            .values(reservation_expires_at=datetime.now(timezone.utc) - timedelta(seconds=60))
        )
        # Cancel the call so agent has no active call
        update_call_status(db, alloc.call_id, CallStatus.CANCELLED)
        db.commit()

        reconciler = ReconciliationService()
        count = reconciler.reconcile_stale_agents(db)
        db.commit()

        assert count >= 1
        agent_after = get_agent(db, alloc.agent_id)
        assert agent_after.status == AgentStatus.AVAILABLE
