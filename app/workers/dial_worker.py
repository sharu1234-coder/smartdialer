from __future__ import annotations
import logging
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from app.services.progressive_dialer import ProgressiveDialer, DialTickResult
from app.services.predictive_pacing import PredictivePacingEngine
from app.services.safety_controller import SafetyController, SafetyEvaluation
from app.services.call_allocator import CallAllocator, AllocationResult
from app.providers.provider_factory import get_overall_health
from app.core.enums import DialMode

logger = logging.getLogger(__name__)


@dataclass
class TickResult:
    dial_mode: str
    calls_initiated: int = 0
    calls_failed: int = 0
    available_agents: int = 0
    pending_borrowers: int = 0
    allocations: list[AllocationResult] = field(default_factory=list)
    pacing_decision: object = None
    safety_evaluation: object = None
    errors: list[str] = field(default_factory=list)


class DialWorker:
    """
    Runs dial ticks in either PROGRESSIVE or PREDICTIVE mode.

    Flow:
      Progressive: ProgressiveDialer → CallAllocator → Outbox
      Predictive:  PredictivePacingEngine → SafetyController → CallAllocator (N times) → Outbox
    """

    def __init__(
        self,
        campaign_id: str,
        mode: DialMode,
        worker_id: str = "worker-1",
        provider_name: str = "provider_a",
    ):
        self.campaign_id = campaign_id
        self.mode = mode
        self.worker_id = worker_id
        self.provider_name = provider_name
        self._pacing_engine = PredictivePacingEngine()
        self._safety_controller = SafetyController()
        self._allocator = CallAllocator()

    def run_tick(self, db: Session) -> TickResult:
        if self.mode == DialMode.PROGRESSIVE:
            return self._run_progressive_tick(db)
        else:
            return self._run_predictive_tick(db)

    def _run_progressive_tick(self, db: Session) -> TickResult:
        dialer = ProgressiveDialer(db, self.campaign_id, provider_name=self.provider_name)
        dial_result = dialer.tick()
        return TickResult(
            dial_mode=DialMode.PROGRESSIVE.value,
            calls_initiated=dial_result.calls_initiated,
            available_agents=dial_result.available_agents,
            pending_borrowers=dial_result.pending_borrowers,
            allocations=dial_result.allocations,
            errors=dial_result.errors,
        )

    def _run_predictive_tick(self, db: Session) -> TickResult:
        result = TickResult(dial_mode=DialMode.PREDICTIVE.value)

        # Step 1: Get provider health (independent of pacing)
        provider_health = get_overall_health()

        # Step 2: Pacing engine calculates desired calls
        pacing = self._pacing_engine.calculate_pacing(db, self.campaign_id, provider_health)
        result.pacing_decision = pacing
        result.available_agents = pacing.available_agents
        result.pending_borrowers = pacing.in_flight_calls  # approximate

        if pacing.requested_calls == 0:
            result.errors.append("Pacing engine: no calls requested")
            return result

        # Step 3: Safety Controller independently validates (uses its own DB query)
        evaluation = self._safety_controller.evaluate(
            db, self.campaign_id, pacing.requested_calls, provider_health
        )
        result.safety_evaluation = evaluation

        logger.info(
            "Safety decision: %s requested=%d approved=%d reason='%s'",
            evaluation.decision.value,
            evaluation.requested,
            evaluation.approved,
            evaluation.reason,
        )

        if evaluation.approved == 0:
            result.errors.append(f"Safety controller: {evaluation.reason}")
            return result

        # Step 4: Allocate approved number of calls
        for _ in range(evaluation.approved):
            allocation = self._allocator.allocate(
                db, self.campaign_id, DialMode.PREDICTIVE, provider_name=self.provider_name
            )
            if allocation is None:
                # Resources ran out mid-loop — stop
                break
            result.allocations.append(allocation)
            result.calls_initiated += 1

        return result
