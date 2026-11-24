from __future__ import annotations
import uuid
import time
import logging
from datetime import datetime, timezone
from typing import Optional
from app.providers.base import TelecomProvider, ProviderCallResult, NormalizedEvent
from app.core.enums import ProviderEventType, ProviderStatus

logger = logging.getLogger(__name__)


class ProviderA(TelecomProvider):
    """
    Provider A: Fast, reliable, low failure rate.
    - 95% initiation success
    - Events tracked by poll ticks (tick-based for simulation)
    - 1% duplicate event rate
    """

    RINGING_TICKS = 2    # After 2 polls, RINGING fires
    ANSWER_TICKS = 3     # After 3 polls, ANSWERED fires (if will_answer)
    FAIL_TICKS = 3       # After 3 polls, FAILED fires (if not will_answer)

    def __init__(
        self,
        answer_rate: float = 0.5,
        avg_talk_duration: float = 10.0,
        failure_rate: float = 0.05,
        latency_ms: float = 100.0,
        duplicate_rate: float = 0.01,
        seed: Optional[int] = None,
    ):
        import random
        self._rng = random.Random(seed)
        self.answer_rate = answer_rate
        self.avg_talk_duration = avg_talk_duration
        self.failure_rate = failure_rate
        self.latency_ms = latency_ms
        self.duplicate_rate = duplicate_rate
        self._active_calls: dict[str, dict] = {}
        self._failure_mode: bool = False
        self._failure_count: int = 0
        self._success_count: int = 0
        self._completed_count: int = 0
        self._total_talk_ticks: int = 0

    @property
    def name(self) -> str:
        return "provider_a"

    def set_failure_mode(self, enabled: bool) -> None:
        self._failure_mode = enabled
        logger.info("Provider A failure mode: %s", enabled)

    def initiate_call(
        self, call_id: str, phone_number: str, idempotency_key: str
    ) -> ProviderCallResult:
        if self._failure_mode:
            self._failure_count += 1
            return ProviderCallResult(success=False, provider_call_id=None, error="Provider outage")

        # Minimal latency for simulation speed
        time.sleep(min(self.latency_ms / 1000, 0.01))

        if self._rng.random() < self.failure_rate:
            self._failure_count += 1
            return ProviderCallResult(
                success=False, provider_call_id=None, error="Initiation failed"
            )

        provider_call_id = f"pA-{uuid.uuid4().hex[:8]}"
        will_answer = self._rng.random() < self.answer_rate
        # Talk duration in ticks (1 tick ≈ 1 second in simulation)
        talk_ticks = max(2, int(self._rng.gauss(self.avg_talk_duration, self.avg_talk_duration * 0.2)))

        self._active_calls[provider_call_id] = {
            "call_id": call_id,
            "phone": phone_number,
            "idempotency_key": idempotency_key,
            "will_answer": will_answer,
            "talk_ticks": talk_ticks,
            "poll_count": 0,  # incremented each time get_pending_events is called
            "events_emitted": set(),
        }
        self._success_count += 1
        return ProviderCallResult(success=True, provider_call_id=provider_call_id)

    def get_call_status(self, provider_call_id: str) -> Optional[ProviderEventType]:
        call = self._active_calls.get(provider_call_id)
        if not call:
            return None
        pc = call["poll_count"]
        if pc < self.RINGING_TICKS:
            return ProviderEventType.RINGING
        if call["will_answer"]:
            if pc < self.ANSWER_TICKS + call["talk_ticks"]:
                return ProviderEventType.ANSWERED
            return ProviderEventType.COMPLETED
        return ProviderEventType.FAILED

    def get_pending_events(self, provider_call_id: str) -> list[NormalizedEvent]:
        call = self._active_calls.get(provider_call_id)
        if not call:
            return []

        # Advance the tick counter on each poll
        call["poll_count"] += 1
        pc = call["poll_count"]
        events: list[NormalizedEvent] = []

        def make_event(etype: ProviderEventType, seq: int) -> NormalizedEvent:
            return NormalizedEvent(
                call_id=call["call_id"],
                event_id=f"pA-{provider_call_id}-{etype.value}-{seq}",
                event_type=etype,
                provider_name=self.name,
                sequence_number=seq,
                raw_payload={
                    "provider_call_id": provider_call_id,
                    "event": etype.value,
                    "phone": call["phone"],
                },
            )

        # RINGING after RINGING_TICKS polls
        if pc >= self.RINGING_TICKS and ProviderEventType.RINGING not in call["events_emitted"]:
            events.append(make_event(ProviderEventType.RINGING, 1))
            call["events_emitted"].add(ProviderEventType.RINGING)
            # Occasional duplicate
            if self._rng.random() < self.duplicate_rate:
                events.append(make_event(ProviderEventType.RINGING, 1))

        # ANSWERED or FAILED after ANSWER_TICKS polls
        if pc >= self.ANSWER_TICKS:
            if call["will_answer"]:
                if ProviderEventType.ANSWERED not in call["events_emitted"]:
                    events.append(make_event(ProviderEventType.ANSWERED, 2))
                    call["events_emitted"].add(ProviderEventType.ANSWERED)
                # COMPLETED after talk_ticks more polls
                if pc >= self.ANSWER_TICKS + call["talk_ticks"]:
                    if ProviderEventType.COMPLETED not in call["events_emitted"]:
                        events.append(make_event(ProviderEventType.COMPLETED, 3))
                        call["events_emitted"].add(ProviderEventType.COMPLETED)
                        self._completed_count += 1
                        self._total_talk_ticks += call["talk_ticks"]
                        self._active_calls.pop(provider_call_id, None)
            else:
                if ProviderEventType.FAILED not in call["events_emitted"]:
                    events.append(make_event(ProviderEventType.FAILED, 2))
                    call["events_emitted"].add(ProviderEventType.FAILED)
                    self._active_calls.pop(provider_call_id, None)

        return events

    def get_avg_talk_ticks(self) -> float:
        if self._completed_count == 0:
            return 0.0
        return self._total_talk_ticks / self._completed_count

    def cancel_call(self, provider_call_id: str) -> bool:
        if provider_call_id in self._active_calls:
            del self._active_calls[provider_call_id]
            return True
        return False

    def health_check(self) -> ProviderStatus:
        if self._failure_mode:
            return ProviderStatus.UNHEALTHY
        total = self._failure_count + self._success_count
        if total == 0:
            return ProviderStatus.HEALTHY
        failure_rate = self._failure_count / total
        if failure_rate > 0.5:
            return ProviderStatus.UNHEALTHY
        elif failure_rate > 0.2:
            return ProviderStatus.DEGRADED
        return ProviderStatus.HEALTHY
