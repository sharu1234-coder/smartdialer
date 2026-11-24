from __future__ import annotations
import pytest
from app.services.safety_controller import SafetyController
from app.core.enums import SafetyDecision, ProviderStatus


class TestSafetyController:
    def test_approve_when_sufficient_agents(self, db, campaign, agents, borrowers):
        sc = SafetyController()
        evaluation = sc.evaluate(db, campaign.id, requested_calls=3, provider_health=ProviderStatus.HEALTHY)
        assert evaluation.decision == SafetyDecision.APPROVE
        assert evaluation.approved == 3

    def test_reduce_when_requested_exceeds_available(self, db, campaign, agents, borrowers):
        sc = SafetyController()
        # Request more than the 5 available agents
        evaluation = sc.evaluate(db, campaign.id, requested_calls=100, provider_health=ProviderStatus.HEALTHY)
        assert evaluation.decision == SafetyDecision.REDUCE
        assert evaluation.approved == evaluation.available_agents
        assert evaluation.approved < 100

    def test_reject_when_no_agents(self, db, campaign):
        # No agents registered
        sc = SafetyController()
        evaluation = sc.evaluate(db, campaign.id, requested_calls=5, provider_health=ProviderStatus.HEALTHY)
        assert evaluation.decision == SafetyDecision.REJECT
        assert evaluation.approved == 0

    def test_reject_when_provider_unhealthy(self, db, campaign, agents, borrowers):
        sc = SafetyController()
        evaluation = sc.evaluate(db, campaign.id, requested_calls=5, provider_health=ProviderStatus.UNHEALTHY)
        assert evaluation.decision == SafetyDecision.REJECT
        assert evaluation.approved == 0

    def test_fallback_when_provider_degraded(self, db, campaign, agents, borrowers):
        sc = SafetyController()
        evaluation = sc.evaluate(db, campaign.id, requested_calls=10, provider_health=ProviderStatus.DEGRADED)
        assert evaluation.decision in (SafetyDecision.FALLBACK_TO_PROGRESSIVE, SafetyDecision.REJECT)
        # At most 1 per available agent in degraded mode
        assert evaluation.approved <= 1

    def test_audit_trail_included(self, db, campaign, agents, borrowers):
        sc = SafetyController()
        evaluation = sc.evaluate(db, campaign.id, requested_calls=3, provider_health=ProviderStatus.HEALTHY)
        assert len(evaluation.checks_performed) > 0
        assert evaluation.timestamp is not None

    def test_independent_db_query(self, db, campaign, agents, borrowers):
        """Safety controller must NOT trust any external agent count — queries DB itself."""
        sc = SafetyController()
        # Even if we pass wrong requested count, it will clamp to actual available
        evaluation = sc.evaluate(db, campaign.id, requested_calls=999, provider_health=ProviderStatus.HEALTHY)
        # Should be clamped to actual DB count
        assert evaluation.approved <= 5  # only 5 agents created in fixture
