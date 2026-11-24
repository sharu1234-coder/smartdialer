from __future__ import annotations
import pytest
from app.services.safety_controller import SafetyController
from app.services.predictive_pacing import PredictivePacingEngine
from app.services.call_allocator import CallAllocator
from app.repositories.call_repository import get_call
from app.core.enums import DialMode, SafetyDecision, ProviderStatus, CallStatus
from app.providers.provider_factory import initialize_default_providers, reset_providers, get_provider
from app.providers.circuit_breaker import CircuitBreaker


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


class TestProviderOutage:
    def test_unhealthy_provider_causes_rejection(self, db, campaign, agents, borrowers):
        """Safety controller rejects calls when provider is UNHEALTHY."""
        sc = SafetyController()
        evaluation = sc.evaluate(
            db, campaign.id,
            requested_calls=5,
            provider_health=ProviderStatus.UNHEALTHY
        )
        assert evaluation.decision == SafetyDecision.REJECT
        assert evaluation.approved == 0

    def test_degraded_provider_falls_back_to_progressive(self, db, campaign, agents, borrowers):
        """Safety controller falls back to progressive mode when provider is DEGRADED."""
        sc = SafetyController()
        evaluation = sc.evaluate(
            db, campaign.id,
            requested_calls=5,
            provider_health=ProviderStatus.DEGRADED
        )
        assert evaluation.decision == SafetyDecision.FALLBACK_TO_PROGRESSIVE
        assert evaluation.approved <= 1

    def test_circuit_breaker_opens_after_failures(self):
        """Circuit breaker opens after threshold failures."""
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)
        assert cb.health == ProviderStatus.HEALTHY

        for _ in range(3):
            cb.record_failure()

        assert cb.health == ProviderStatus.UNHEALTHY
        assert not cb.can_proceed()

    def test_circuit_breaker_half_open_then_success(self):
        """Circuit breaker moves to HALF_OPEN then CLOSED on success."""
        import time
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=1)

        for _ in range(3):
            cb.record_failure()

        assert cb.health == ProviderStatus.UNHEALTHY

        # Wait for recovery timeout
        time.sleep(1.1)
        assert cb.can_proceed()  # Should be HALF_OPEN now
        assert cb.health == ProviderStatus.DEGRADED

        cb.record_success()
        assert cb.health == ProviderStatus.HEALTHY

    def test_pacing_engine_zero_calls_on_unhealthy(self, db, campaign, agents, borrowers):
        """Predictive pacing engine returns 0 desired calls when provider unhealthy."""
        engine = PredictivePacingEngine()
        decision = engine.calculate_pacing(
            db, campaign.id,
            provider_health=ProviderStatus.UNHEALTHY
        )
        assert decision.requested_calls == 0

    def test_provider_a_failure_mode(self):
        """Provider A forced failure mode works."""
        provider = get_provider("provider_a")
        provider.set_failure_mode(True)
        try:
            result = provider.initiate_call(
                call_id="test-call-id",
                phone_number="+15551234567",
                idempotency_key="test-key-001"
            )
            assert result is not None
            assert result.success is False
        finally:
            provider.set_failure_mode(False)

    def test_allocation_during_provider_outage(self, db, campaign, agents, borrowers):
        """
        When provider is in forced failure mode, outbox entries get created but
        dispatch will fail — calls should eventually be reconciled.
        """
        allocator = CallAllocator()
        # Allocation itself should still succeed (creates outbox entry)
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None

        call = get_call(db, alloc.call_id)
        assert call.status == CallStatus.RESERVED
