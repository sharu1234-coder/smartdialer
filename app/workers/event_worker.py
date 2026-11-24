from __future__ import annotations
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.models.outbox import Outbox
from app.models.call import Call
from app.core.enums import OutboxStatus, CallStatus
from app.core.state_machines import ACTIVE_CALL_STATES
from app.services.event_processor import EventProcessor
from app.providers.provider_factory import get_provider, get_circuit_breaker
from app.repositories.call_repository import update_call_status
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class EventWorkerResult:
    outbox_processed: int = 0
    events_processed: int = 0
    events_duplicated: int = 0
    events_out_of_order: int = 0
    provider_failures: int = 0
    errors: int = 0


class EventWorker:
    """
    Processes pending outbox entries (dispatches calls to providers)
    and polls providers for new call events.
    """

    def __init__(self, provider_name: str = "provider_a"):
        self.provider_name = provider_name
        self._event_processor = EventProcessor()

    def run_tick(self, db: Session) -> EventWorkerResult:
        result = EventWorkerResult()
        self._process_outbox(db, result)
        self._poll_provider_events(db, result)
        return result

    def _process_outbox(self, db: Session, result: EventWorkerResult) -> None:
        """Dispatch pending outbox entries to provider."""
        # SELECT FOR UPDATE SKIP LOCKED ensures only one worker processes each entry
        stmt = (
            select(Outbox)
            .where(
                Outbox.status == OutboxStatus.PENDING,
                Outbox.provider_name == self.provider_name,
                (Outbox.next_retry_at <= datetime.now(timezone.utc))
                | (Outbox.next_retry_at.is_(None)),
            )
            .with_for_update(skip_locked=True)
            .limit(10)
        )
        entries = list(db.execute(stmt).scalars().all())

        for entry in entries:
            try:
                # Mark as processing
                db.execute(
                    update(Outbox)
                    .where(Outbox.id == entry.id)
                    .values(status=OutboxStatus.PROCESSING, attempts=Outbox.attempts + 1)
                )
                db.flush()

                provider = get_provider(self.provider_name)
                cb = get_circuit_breaker(self.provider_name)

                if not cb.can_proceed():
                    self._mark_outbox_retry(db, entry.id, "Circuit breaker open")
                    result.provider_failures += 1
                    continue

                call_data = entry.payload
                dispatch_result = provider.initiate_call(
                    call_id=call_data["call_id"],
                    phone_number=call_data["phone_number"],
                    idempotency_key=entry.idempotency_key,
                )

                if dispatch_result.success:
                    cb.record_success()
                    db.execute(
                        update(Outbox)
                        .where(Outbox.id == entry.id)
                        .values(
                            status=OutboxStatus.SENT,
                            sent_at=datetime.now(timezone.utc),
                        )
                    )
                    # Update call with provider_call_id and mark as INITIATED
                    update_call_status(
                        db,
                        call_data["call_id"],
                        CallStatus.INITIATED,
                        provider_call_id=dispatch_result.provider_call_id,
                    )
                    result.outbox_processed += 1
                    logger.info(
                        "Dispatched call %s -> provider_call_id=%s",
                        call_data["call_id"],
                        dispatch_result.provider_call_id,
                    )
                else:
                    cb.record_failure()
                    if entry.attempts >= settings.max_retry_attempts:
                        db.execute(
                            update(Outbox)
                            .where(Outbox.id == entry.id)
                            .values(
                                status=OutboxStatus.FAILED,
                                error_message=dispatch_result.error,
                            )
                        )
                        update_call_status(
                            db, call_data["call_id"], CallStatus.FAILED,
                            failure_reason=dispatch_result.error
                        )
                    else:
                        self._mark_outbox_retry(db, entry.id, dispatch_result.error)
                    result.provider_failures += 1

                db.flush()

            except Exception as exc:
                logger.exception("Error processing outbox entry %s: %s", entry.id, exc)
                result.errors += 1
                try:
                    self._mark_outbox_retry(db, entry.id, str(exc))
                    db.flush()
                except Exception:
                    pass

    def _poll_provider_events(self, db: Session, result: EventWorkerResult) -> None:
        """Poll provider for new events on active calls."""
        try:
            provider = get_provider(self.provider_name)
        except ValueError:
            return

        # Find active calls dispatched to this provider
        stmt = select(Call).where(
            Call.status.in_(list(ACTIVE_CALL_STATES)),
            Call.provider_id == self.provider_name,
            Call.provider_call_id.is_not(None),
            Call.status != CallStatus.RESERVED,  # not yet dispatched
        )
        active_calls = list(db.execute(stmt).scalars().all())

        for call in active_calls:
            if not call.provider_call_id:
                continue
            try:
                events = provider.get_pending_events(call.provider_call_id)
                for event in events:
                    proc_result = self._event_processor.process(
                        db=db,
                        call_id=call.id,
                        event_type=event.event_type,
                        event_id=event.event_id,
                        provider_name=event.provider_name,
                        raw_payload=event.raw_payload,
                        sequence_number=event.sequence_number,
                    )
                    result.events_processed += 1
                    if proc_result.is_duplicate:
                        result.events_duplicated += 1
                    if proc_result.is_out_of_order:
                        result.events_out_of_order += 1

                db.flush()

            except Exception as exc:
                logger.error("Error polling events for call %s: %s", call.id, exc)
                result.errors += 1

    @staticmethod
    def _mark_outbox_retry(db: Session, outbox_id: str, error: str) -> None:
        backoff = timedelta(seconds=5)
        db.execute(
            update(Outbox)
            .where(Outbox.id == outbox_id)
            .values(
                status=OutboxStatus.PENDING,
                error_message=error,
                next_retry_at=datetime.now(timezone.utc) + backoff,
            )
        )
