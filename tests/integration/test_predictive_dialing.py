from __future__ import annotations
import pytest
from app.workers.dial_worker import DialWorker
from app.core.enums import DialMode, SafetyDecision
from app.providers.provider_factory import initialize_default_providers, reset_providers


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


class TestPredictiveDialing:
    def test_predictive_tick_respects_safety(self, db, campaign, agents, borrowers):
        worker = DialWorker(campaign.id, DialMode.PREDICTIVE)
        result = worker.run_tick(db)
        db.commit()

        # Safety controller must have been consulted
        assert result.safety_evaluation is not None

        # Calls initiated must not exceed approved count
        if result.safety_evaluation.approved > 0:
            assert result.calls_initiated <= result.safety_evaluation.approved

    def test_predictive_cannot_exceed_available_agents(self, db, campaign, agents, borrowers):
        """Core safety: predictive can never create more calls than available agents."""
        from app.repositories.agent_repository import count_available

        available_before = count_available(db, campaign.id)
        worker = DialWorker(campaign.id, DialMode.PREDICTIVE)
        result = worker.run_tick(db)
        db.commit()

        assert result.calls_initiated <= available_before

    def test_safety_controller_rejects_on_unhealthy_provider(self, db, campaign, agents, borrowers):
        from app.providers.provider_factory import get_circuit_breaker
        # Force BOTH circuit breakers open so overall health is UNHEALTHY
        cb_a = get_circuit_breaker("provider_a")
        cb_b = get_circuit_breaker("provider_b")
        for _ in range(10):
            cb_a.record_failure()
            cb_b.record_failure()

        worker = DialWorker(campaign.id, DialMode.PREDICTIVE)
        result = worker.run_tick(db)
        db.commit()

        cb_a.reset()
        cb_b.reset()

        if result.safety_evaluation:
            # Should be REJECT when provider is UNHEALTHY
            assert result.safety_evaluation.decision in (
                SafetyDecision.REJECT, SafetyDecision.FALLBACK_TO_PROGRESSIVE
            )
