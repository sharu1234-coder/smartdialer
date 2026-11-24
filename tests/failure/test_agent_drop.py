from __future__ import annotations
import pytest
from sqlalchemy import update, select
from app.services.call_allocator import CallAllocator
from app.services.safety_controller import SafetyController
from app.services.reconciliation_service import ReconciliationService
from app.repositories.call_repository import get_call, update_call_status
from app.repositories.agent_repository import get_agent
from app.core.enums import DialMode, CallStatus, AgentStatus, ProviderStatus
from app.models.agent import Agent
from app.providers.provider_factory import initialize_default_providers, reset_providers
from datetime import datetime, timezone, timedelta


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


class TestAgentDrop:
    def test_40_percent_agents_disappear(self, db, campaign, agents, borrowers):
        """
        40% agents suddenly go OFFLINE (simulating disconnect).
        Safety controller re-evaluates and reduces approved calls.
        """
        total_agents = len(agents)
        to_drop = int(total_agents * 0.4)

        agent_ids_to_drop = [a.id for a in agents[:to_drop]]

        # Drop 40% of agents to OFFLINE
        db.execute(
            update(Agent)
            .where(Agent.id.in_(agent_ids_to_drop))
            .values(status=AgentStatus.OFFLINE)
        )
        db.commit()

        sc = SafetyController()
        evaluation = sc.evaluate(
            db, campaign.id,
            requested_calls=total_agents,
            provider_health=ProviderStatus.HEALTHY
        )

        remaining_available = total_agents - to_drop
        assert evaluation.approved <= remaining_available

    def test_all_agents_drop_causes_rejection(self, db, campaign, agents, borrowers):
        """All agents offline → Safety Controller rejects all calls."""
        db.execute(
            update(Agent)
            .where(Agent.campaign_id == campaign.id)
            .values(status=AgentStatus.OFFLINE)
        )
        db.commit()

        sc = SafetyController()
        evaluation = sc.evaluate(
            db, campaign.id,
            requested_calls=5,
            provider_health=ProviderStatus.HEALTHY
        )

        assert evaluation.approved == 0

    def test_agent_drop_during_active_call_recovered(self, db, campaign, agents, borrowers):
        """
        Agent drops OFFLINE during an active call.
        Reconciliation service must handle the stale RESERVED state.
        """
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        # Agent suddenly goes OFFLINE (simulate hardware crash)
        db.execute(
            update(Agent)
            .where(Agent.id == alloc.agent_id)
            .values(
                status=AgentStatus.OFFLINE,
                reservation_expires_at=datetime.now(timezone.utc) - timedelta(seconds=60)
            )
        )
        db.commit()

        # Mark call as old enough for reconciliation
        from sqlalchemy import update as sql_update
        from app.models.call import Call
        db.execute(
            sql_update(Call)
            .where(Call.id == alloc.call_id)
            .values(created_at=datetime.now(timezone.utc) - timedelta(seconds=120))
        )
        db.commit()

        reconciler = ReconciliationService()
        reconciler.reconcile_stale_calls(db)
        db.commit()

        # Call should be CANCELLED or FAILED — not stuck in RESERVED
        call = get_call(db, alloc.call_id)
        assert call.status in {CallStatus.CANCELLED, CallStatus.FAILED}

    def test_new_agents_come_online_pacing_adjusts(self, db, campaign, agents, borrowers):
        """
        Initially few agents, then more come online.
        Safety controller approves more calls after agent count increases.
        """
        # Drop all but 1 agent
        all_agent_ids = [a.id for a in agents]
        db.execute(
            update(Agent)
            .where(Agent.id.in_(all_agent_ids[1:]))
            .values(status=AgentStatus.OFFLINE)
        )
        db.commit()

        sc = SafetyController()
        eval_before = sc.evaluate(
            db, campaign.id, requested_calls=10, provider_health=ProviderStatus.HEALTHY
        )
        assert eval_before.approved <= 1

        # Bring all agents back online
        db.execute(
            update(Agent)
            .where(Agent.id.in_(all_agent_ids))
            .values(status=AgentStatus.AVAILABLE)
        )
        db.commit()

        eval_after = sc.evaluate(
            db, campaign.id, requested_calls=10, provider_health=ProviderStatus.HEALTHY
        )
        assert eval_after.approved > eval_before.approved
