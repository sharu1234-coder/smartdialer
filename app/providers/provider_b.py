from __future__ import annotations
import uuid
import time
import logging
from typing import Optional
from app.providers.base import TelecomProvider, ProviderCallResult, NormalizedEvent
from app.core.enums import ProviderEventType, ProviderStatus

logger = logging.getLogger(__name__)


class ProviderB(TelecomProvider):
    """
    Provider B: Slower, unreliable, with chaos behaviors.
    - 70-80% initiation success
    - Higher failure rate
    - Duplicate events (15%)
    - Out-of-order events (20%)
    - Uses tick-based progression (like Provider A)
    """

    RINGING_TICKS = 4    # Slower than Provider A
    ANSWER_TICKS = 5     # Slower to answer

    def __init__(
        self,
        answer_rate: float = 0.5,
        avg_talk_duration: float = 10.0,
        failure_rate: float = 0.2,
        latency_ms: float = 300.0,
        timeout_rate: float = 0.1,
        duplicate_rate: float = 0.15,
        out_of_order_rate: float = 0.2,
        seed: Optional[int] = None,
    ):
        import random
        self._rng = random.Random(seed)
        self.answer_rate = answer_rate
        self.avg_talk_duration = avg_talk_duration
        self.failure_rate = failure_rate
        self.latency_ms = latency_ms
        self.timeout_rate = timeout_rate
        self.duplicate_rate = duplicate_rate
        self.out_of_order_rate = out_of_order_rate
        self._active_calls: dict[str, dict] = {}
        self._failure_mode: bool = False
        self._failure_count: int = 0
        self._success_count: int = 0
        self._completed_count: int = 0
        self._total_talk_ticks: int = 0

    @property
    def name(self) -> str:
        return "provider_b"

    def set_failure_mode(self, enabled: bool) -> None:
        self._failure_mode = enabled
        logger.info("Provider B failure mode: %s", enabled)

    def initiate_call(
        self, call_id: str, phone_number: str, idempotency_key: str
    ) -> ProviderCallResult:
        if self._failure_mode:
            self._failure_count += 1
            return ProviderCallResult(success=False, provider_call_id=None, error="Provider B outage")

        # Simulate latency (capped for simulation speed)
        time.sleep(min(self.latency_ms / 1000, 0.02))

        # Timeout scenario
        if self._rng.random() < self.timeout_rate:
            self._failure_count += 1
            return ProviderCallResult(success=False, provider_call_id=None, error="Timeout")

        # Random failure
        if self._rng.random() < self.failure_rate:
            self._failure_count += 1
            return ProviderCallResult(success=False, provider_call_id=None, error="Provider B error")

        provider_call_id = f"pB-{uuid.uuid4().hex[:8]}"
        will_answer = self._rng.random() < self.answer_rate
        talk_ticks = max(2, int(self._rng.gauss(self.avg_talk_duration, self.avg_talk_duration * 0.3)))

        self._active_calls[provider_call_id] = {
            "call_id": call_id,
            "phone": phone_number,
            "idempotency_key": idempotency_key,
            "will_answer": will_answer,
            "talk_ticks": talk_ticks,
            "poll_count": 0,
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

        call["poll_count"] += 1
        pc = call["poll_count"]
        events: list[NormalizedEvent] = []

        def make_event(etype: ProviderEventType, seq: int) -> NormalizedEvent:
            return NormalizedEvent(
                call_id=call["call_id"],
                event_id=f"pB-{provider_call_id}-{etype.value}-{seq}",
                event_type=etype,
                provider_name=self.name,
                sequence_number=seq,
                raw_payload={
                    "provider_call_id": provider_call_id,
                    "event": etype.value,
                    "phone": call["phone"],
                    "provider": "provider_b",
                },
            )

        # RINGING event (after RINGING_TICKS)
        if pc >= self.RINGING_TICKS and ProviderEventType.RINGING not in call["events_emitted"]:
            events.append(make_event(ProviderEventType.RINGING, 1))
            call["events_emitted"].add(ProviderEventType.RINGING)
            # Duplicates — chaos!
            if self._rng.random() < self.duplicate_rate:
                events.append(make_event(ProviderEventType.RINGING, 1))
            if self._rng.random() < self.duplicate_rate:
                events.append(make_event(ProviderEventType.RINGING, 1))

        # ANSWERED or FAILED
        if pc >= self.ANSWER_TICKS:
            if call["will_answer"]:
                if ProviderEventType.ANSWERED not in call["events_emitted"]:
                    answered_event = make_event(ProviderEventType.ANSWERED, 2)
                    call["events_emitted"].add(ProviderEventType.ANSWERED)
                    # Duplicate ANSWERED events
                    if self._rng.random() < self.duplicate_rate:
                        events.append(make_event(ProviderEventType.ANSWERED, 2))
                        events.append(make_event(ProviderEventType.ANSWERED, 2))
                    events.append(answered_event)

                # COMPLETED after talk_ticks
                if pc >= self.ANSWER_TICKS + call["talk_ticks"]:
                    if ProviderEventType.COMPLETED not in call["events_emitted"]:
                        completed_event = make_event(ProviderEventType.COMPLETED, 3)
                        call["events_emitted"].add(ProviderEventType.COMPLETED)
                        # Out-of-order: COMPLETED arrives before ANSWERED in the list
                        if self._rng.random() < self.out_of_order_rate:
                            events.insert(0, completed_event)
                        else:
                            events.append(completed_event)
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
