from __future__ import annotations
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.repositories import agent_repository, call_repository
from app.repositories.campaign_repository import get_campaign
from app.core.enums import CallStatus, ProviderStatus

logger = logging.getLogger(__name__)

# In-flight states that consume agent capacity
IN_FLIGHT_STATES = [
    CallStatus.RESERVED,
    CallStatus.INITIATED,
    CallStatus.RINGING,
    CallStatus.ANSWERED,
    CallStatus.CONNECTED,
]


@dataclass
class PacingDecision:
    campaign_id: str
    estimated_answer_rate: float
    sample_size: int
    is_fallback: bool
    available_agents: int
    in_flight_calls: int
    capacity_buffer: int
    desired_calls: int
    requested_calls: int
    provider_health: str
    provider_health_adjustment: float
    reasoning: str
    timestamp: datetime


class PredictivePacingEngine:
    """
    Predictive pacing using EWMA (Exponentially Weighted Moving Average) for answer rate.

    Formula:
        ewma_rate = alpha * new_sample + (1 - alpha) * previous_ewma
        capacity_buffer = available_agents - in_flight_calls
        desired_calls = floor(capacity_buffer / estimated_answer_rate)

    The pacing engine REQUESTS calls — the Safety Controller APPROVES them.
    The engine never bypasses the Safety Controller.
    """

    EWMA_ALPHA = 0.2
    MIN_SAMPLE_SIZE = 5
    CONSERVATIVE_FALLBACK_RATE = 0.5
    MAX_DIAL_RATIO = 3.0  # never request more than 3x available agents

    def calculate_pacing(
        self,
        db: Session,
        campaign_id: str,
        provider_health: ProviderStatus = ProviderStatus.HEALTHY,
    ) -> PacingDecision:
        campaign = get_campaign(db, campaign_id)

        available_agents = agent_repository.count_available(db, campaign_id=campaign_id)
        in_flight = call_repository.count_calls_in_states(
            db, IN_FLIGHT_STATES, campaign_id=campaign_id
        )

        answer_rate, sample_size = self._estimate_answer_rate(db, campaign_id)
        is_fallback = sample_size < self.MIN_SAMPLE_SIZE

        provider_adjustment = self._provider_health_factor(provider_health)

        # Correct predictive formula:
        #   We want enough in-flight calls so that (answer_rate * in_flight) fills
        #   all available agents.  Target in-flight = available_agents / answer_rate.
        #   New dials needed = max(0, target_in_flight - current_in_flight).
        #
        # The old formula  capacity_buffer = available_agents - in_flight  was wrong:
        # available_agents already EXCLUDES agents occupied by in-flight calls, so
        # subtracting in_flight again double-counted that capacity and almost always
        # produced zero in a busy system.
        capacity_buffer = available_agents  # free agents right now

        # Correct predictive formula:
        #
        #   raw_desired = ceil(available_agents / effective_rate)
        #
        # In this model, every in-flight call has ALREADY reserved an agent.
        # Therefore in_flight calls do NOT compete with available_agents for capacity —
        # they are on separate agents.  Subtracting in_flight from the target was the
        # original double-subtraction bug: it produced 0 whenever in_flight >= available,
        # making predictive behave like progressive at zero throughput.
        #
        # The Safety Controller enforces the hard ceiling: approved ≤ available_agents.
        # So raw_desired can safely overshoot; the SC will clamp it.
        #
        # Fallback: use conservative rate (0.5) until MIN_SAMPLE_SIZE calls complete.
        effective_rate = answer_rate if not is_fallback else self.CONSERVATIVE_FALLBACK_RATE
        raw_desired = math.ceil(capacity_buffer / max(effective_rate, 0.05))

        # Apply provider health penalty
        adjusted = math.floor(raw_desired * provider_adjustment)

        # Hard cap: never request more than MAX_DIAL_RATIO * available
        hard_cap = math.floor(available_agents * self.MAX_DIAL_RATIO)
        # Also cap at campaign limit
        campaign_cap = campaign.max_concurrent_calls - in_flight
        requested = max(0, min(adjusted, hard_cap, max(0, campaign_cap)))

        reasoning = (
            f"available={available_agents} in_flight={in_flight} "
            f"capacity_buffer={capacity_buffer} "
            f"answer_rate={answer_rate:.3f} (n={sample_size}) "
            f"provider_adj={provider_adjustment:.2f} "
            f"raw_desired={raw_desired} adjusted={adjusted} "
            f"hard_cap={hard_cap} campaign_cap={campaign_cap} "
            f"→ requested={requested}"
        )

        logger.info("Pacing decision: %s", reasoning)

        return PacingDecision(
            campaign_id=campaign_id,
            estimated_answer_rate=answer_rate,
            sample_size=sample_size,
            is_fallback=is_fallback,
            available_agents=available_agents,
            in_flight_calls=in_flight,
            capacity_buffer=capacity_buffer,
            desired_calls=raw_desired,
            requested_calls=requested,
            provider_health=provider_health.value,
            provider_health_adjustment=provider_adjustment,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc),
        )

    def _estimate_answer_rate(self, db: Session, campaign_id: str) -> tuple[float, int]:
        """
        Compute EWMA answer rate from recent completed calls.
        Returns (rate, sample_count).
        """
        completed_calls = call_repository.get_completed_calls_for_rate(db, campaign_id, limit=100)
        if not completed_calls:
            return self.CONSERVATIVE_FALLBACK_RATE, 0

        # Build ordered sample: 1 if answered/connected/completed, 0 if failed
        samples = []
        for call in completed_calls:
            if call.status in (CallStatus.COMPLETED,) and call.answered_at is not None:
                samples.append(1.0)
            else:
                samples.append(0.0)

        if len(samples) < self.MIN_SAMPLE_SIZE:
            # Too few samples — use simple mean as conservative estimate
            rate = sum(samples) / len(samples)
            return max(0.05, min(0.95, rate)), len(samples)

        # EWMA: iterate oldest to newest
        ewma = sum(samples[:5]) / 5  # seed with first 5 samples
        for s in samples[5:]:
            ewma = self.EWMA_ALPHA * s + (1 - self.EWMA_ALPHA) * ewma

        # Clamp to avoid division by zero or extreme values
        return max(0.05, min(0.95, ewma)), len(samples)

    @staticmethod
    def _provider_health_factor(health: ProviderStatus) -> float:
        if health == ProviderStatus.HEALTHY:
            return 1.0
        elif health == ProviderStatus.DEGRADED:
            return 0.5
        else:  # UNHEALTHY
            return 0.0
