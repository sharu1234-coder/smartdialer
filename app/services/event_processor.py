from __future__ import annotations
import uuid
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.call import Call
from app.models.provider_event import ProviderEvent
from app.repositories import call_repository, agent_repository
from app.core.enums import ProviderEventType, CallStatus, AgentStatus
from app.core.state_machines import (
    PROVIDER_EVENT_TO_CALL_STATUS,
    is_terminal_call_state,
    validate_call_transition,
)
from app.core.exceptions import InvalidStateTransitionError

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    event_id: str
    call_id: str
    is_duplicate: bool
    is_out_of_order: bool
    new_call_status: Optional[str]
    skipped: bool
    reason: str


class EventProcessor:
    """
    Processes normalized telecom provider events.

    Guarantees:
    - Duplicate events (same call_id + event_id) are recorded but NOT applied.
    - Out-of-order events that would regress a terminal state are ignored.
    - Terminal states are never re-opened.
    - Each event is recorded exactly once per (call_id, event_id).
    """

    def process(
        self,
        db: Session,
        call_id: str,
        event_type: ProviderEventType,
        event_id: str,
        provider_name: str,
        raw_payload: dict,
        sequence_number: Optional[int] = None,
    ) -> ProcessResult:
        # Step 1: Check for duplicate using unique constraint (call_id, event_id)
        existing = db.execute(
            select(ProviderEvent).where(
                ProviderEvent.call_id == call_id,
                ProviderEvent.event_id == event_id,
            )
        ).scalars().first()

        if existing is not None:
            logger.debug("Duplicate event: call=%s event_id=%s", call_id, event_id)
            return ProcessResult(
                event_id=event_id,
                call_id=call_id,
                is_duplicate=True,
                is_out_of_order=False,
                new_call_status=None,
                skipped=True,
                reason="Duplicate event — already processed",
            )

        # Step 2: Get current call state
        try:
            call = call_repository.get_call(db, call_id)
        except Exception as exc:
            logger.error("Call %s not found for event processing: %s", call_id, exc)
            return ProcessResult(
                event_id=event_id,
                call_id=call_id,
                is_duplicate=False,
                is_out_of_order=False,
                new_call_status=None,
                skipped=True,
                reason=f"Call not found: {exc}",
            )

        # Step 3: Map event type to call status
        target_status = PROVIDER_EVENT_TO_CALL_STATUS.get(event_type)
        if target_status is None:
            # INITIATED is handled during dispatch, not as an incoming event
            self._record_event(
                db, call_id, event_type, event_id, provider_name,
                raw_payload, sequence_number, is_duplicate=False, is_out_of_order=True
            )
            return ProcessResult(
                event_id=event_id,
                call_id=call_id,
                is_duplicate=False,
                is_out_of_order=True,
                new_call_status=None,
                skipped=True,
                reason=f"No mapping for event type {event_type}",
            )

        # Step 4: Check if call is already terminal
        if is_terminal_call_state(call.status):
            self._record_event(
                db, call_id, event_type, event_id, provider_name,
                raw_payload, sequence_number, is_duplicate=False, is_out_of_order=True
            )
            logger.warning(
                "Out-of-order event: call=%s is %s, received %s — ignoring",
                call_id, call.status, event_type,
            )
            return ProcessResult(
                event_id=event_id,
                call_id=call_id,
                is_duplicate=False,
                is_out_of_order=True,
                new_call_status=call.status.value,
                skipped=True,
                reason=f"Call is terminal ({call.status}) — ignoring late {event_type}",
            )

        # Step 5: Validate the transition
        try:
            validate_call_transition(call.status, target_status)
        except InvalidStateTransitionError as exc:
            self._record_event(
                db, call_id, event_type, event_id, provider_name,
                raw_payload, sequence_number, is_duplicate=False, is_out_of_order=True
            )
            logger.warning("Invalid transition: %s", exc)
            return ProcessResult(
                event_id=event_id,
                call_id=call_id,
                is_duplicate=False,
                is_out_of_order=True,
                new_call_status=call.status.value,
                skipped=True,
                reason=str(exc),
            )

        # Step 6: Apply the transition
        updated_call = call_repository.update_call_status(db, call_id, target_status)

        # Step 7: Update agent state based on call event
        if call.agent_id:
            self._sync_agent_status(db, call.agent_id, target_status)

        # Step 8: Record the event as processed
        self._record_event(
            db, call_id, event_type, event_id, provider_name,
            raw_payload, sequence_number, is_duplicate=False, is_out_of_order=False,
            processed=True
        )

        logger.info(
            "Event processed: call=%s %s -> %s",
            call_id, call.status.value, target_status.value,
        )

        return ProcessResult(
            event_id=event_id,
            call_id=call_id,
            is_duplicate=False,
            is_out_of_order=False,
            new_call_status=target_status.value,
            skipped=False,
            reason=f"Applied transition {call.status.value} -> {target_status.value}",
        )

    def _sync_agent_status(
        self, db: Session, agent_id: str, call_status: CallStatus
    ) -> None:
        """Keep agent status in sync with call lifecycle."""
        try:
            if call_status == CallStatus.RINGING:
                agent_repository.update_agent_status(db, agent_id, AgentStatus.DIALING)
            elif call_status == CallStatus.CONNECTED:
                agent_repository.update_agent_status(db, agent_id, AgentStatus.CONNECTED)
            elif call_status in (CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.CANCELLED):
                agent_repository.update_agent_status(db, agent_id, AgentStatus.WRAP_UP)
                # After wrap-up, return to available
                agent_repository.release_agent(db, agent_id, AgentStatus.AVAILABLE)
        except Exception as exc:
            logger.error("Failed to sync agent %s status for call status %s: %s", agent_id, call_status, exc)

    @staticmethod
    def _record_event(
        db: Session,
        call_id: str,
        event_type: ProviderEventType,
        event_id: str,
        provider_name: str,
        raw_payload: dict,
        sequence_number: Optional[int],
        is_duplicate: bool,
        is_out_of_order: bool,
        processed: bool = False,
    ) -> ProviderEvent:
        now = datetime.now(timezone.utc)
        event = ProviderEvent(
            id=str(uuid.uuid4()),
            call_id=call_id,
            provider_name=provider_name,
            event_type=event_type.value,
            raw_payload=raw_payload,
            normalized_status=event_type.value,
            event_id=event_id,
            received_at=now,
            processed_at=now if processed else None,
            is_duplicate=is_duplicate,
            is_out_of_order=is_out_of_order,
            sequence_number=sequence_number,
        )
        db.add(event)
        db.flush()
        return event
