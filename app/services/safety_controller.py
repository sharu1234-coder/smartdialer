from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.repositories import agent_repository, call_repository
from app.core.enums import SafetyDecision, ProviderStatus, CallStatus, AgentStatus

logger = logging.getLogger(__name__)

# States that are consuming agent capacity
CAPACITY_CONSUMING_STATES = [
    CallStatus.RESERVED,
    CallStatus.INITIATED,
    CallStatus.RINGING,
    CallStatus.ANSWERED,
    CallStatus.CONNECTED,
]


@dataclass
class SafetyEvaluation:
    decision: SafetyDecision
    requested: int
    approved: int
    reason: str
    available_agents: int
    reserved_agents: int
    active_calls: int
    provider_health: str
    checks_performed: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "requested": self.requested,
            "approved": self.approved,
            "reason": self.reason,
            "available_agents": self.available_agents,
            "reserved_agents": self.reserved_agents,
            "active_calls": self.active_calls,
            "provider_health": self.provider_health,
            "checks_performed": self.checks_performed,
            "timestamp": self.timestamp.isoformat(),
        }


class SafetyController:
    """
    Independent safety gate between pacing logic and telecom provider.

    NEVER trusts the pacing engine's claim about available capacity.
    Always queries authoritative DB state.

    Cannot be bypassed by the predictive engine — it owns the final approval.
    """

    def evaluate(
        self,
        db: Session,
        campaign_id: str,
        requested_calls: int,
        provider_health: ProviderStatus,
    ) -> SafetyEvaluation:
        checks: list[str] = []

        # 1. Authoritative agent count — independent DB query, not from pacing engine
        available_agents = agent_repository.count_available(db, campaign_id=campaign_id)
        checks.append(f"available_agents={available_agents}")

        # 2. Count agents already reserved (consuming capacity but not yet connected)
        reserved_agents = agent_repository.count_by_status(
            db, AgentStatus.RESERVED, campaign_id=campaign_id
        )
        checks.append(f"reserved_agents={reserved_agents}")

        # 3. Count active calls consuming capacity
        active_calls = call_repository.count_calls_in_states(
            db, CAPACITY_CONSUMING_STATES, campaign_id=campaign_id
        )
        checks.append(f"active_calls_in_flight={active_calls}")

        # 4. Provider health check
        checks.append(f"provider_health={provider_health.value}")

        # 5. Provider UNHEALTHY — reject everything
        if provider_health == ProviderStatus.UNHEALTHY:
            return SafetyEvaluation(
                decision=SafetyDecision.REJECT,
                requested=requested_calls,
                approved=0,
                reason="Provider is UNHEALTHY — no new calls allowed",
                available_agents=available_agents,
                reserved_agents=reserved_agents,
                active_calls=active_calls,
                provider_health=provider_health.value,
                checks_performed=checks,
            )

        # 6. Provider DEGRADED — fall back to progressive (at most 1 per available agent)
        if provider_health == ProviderStatus.DEGRADED:
            approved = min(requested_calls, available_agents, 1)
            decision = SafetyDecision.FALLBACK_TO_PROGRESSIVE if approved > 0 else SafetyDecision.REJECT
            return SafetyEvaluation(
                decision=decision,
                requested=requested_calls,
                approved=approved,
                reason=f"Provider DEGRADED — falling back to progressive ({approved} approved)",
                available_agents=available_agents,
                reserved_agents=reserved_agents,
                active_calls=active_calls,
                provider_health=provider_health.value,
                checks_performed=checks,
            )

        # 7. No available agents
        if available_agents == 0:
            return SafetyEvaluation(
                decision=SafetyDecision.REJECT,
                requested=requested_calls,
                approved=0,
                reason="No available agents",
                available_agents=available_agents,
                reserved_agents=reserved_agents,
                active_calls=active_calls,
                provider_health=provider_health.value,
                checks_performed=checks,
            )

        # 8. Clamp approved to actual available capacity
        # We can only safely start N calls where N = available_agents (they'll be reserved immediately)
        max_safe = available_agents
        checks.append(f"max_safe_calls={max_safe}")

        if requested_calls <= max_safe:
            decision = SafetyDecision.APPROVE
            approved = requested_calls
            reason = f"Approved {approved}/{requested_calls} requested"
        else:
            decision = SafetyDecision.REDUCE
            approved = max_safe
            reason = (
                f"Reduced from {requested_calls} to {approved} "
                f"(only {available_agents} agents available)"
            )

        return SafetyEvaluation(
            decision=decision,
            requested=requested_calls,
            approved=approved,
            reason=reason,
            available_agents=available_agents,
            reserved_agents=reserved_agents,
            active_calls=active_calls,
            provider_health=provider_health.value,
            checks_performed=checks,
        )
