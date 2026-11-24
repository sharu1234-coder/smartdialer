from __future__ import annotations
import pytest
import uuid
from app.services.call_allocator import CallAllocator
from app.services.event_processor import EventProcessor
from app.repositories.call_repository import get_call, update_call_status
from app.core.enums import DialMode, CallStatus, ProviderEventType
from app.providers.provider_factory import initialize_default_providers, reset_providers


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


def _make_call(db, campaign, allocator):
    alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
    assert alloc is not None
    db.commit()
    update_call_status(db, alloc.call_id, CallStatus.INITIATED)
    db.commit()
    return alloc


class TestOutOfOrderEvents:
    def test_completed_before_answered_ignored(self, db, campaign, agents, borrowers):
        """
        Out-of-order scenario: Call reaches COMPLETED via happy path,
        then a late ANSWERED event arrives. It should be ignored (terminal state protection).
        """
        allocator = CallAllocator()
        alloc = _make_call(db, campaign, allocator)

        processor = EventProcessor()

        # Walk happy path: INITIATED → RINGING → ANSWERED → CONNECTED → COMPLETED
        for event_type in [
            ProviderEventType.RINGING,
            ProviderEventType.ANSWERED,
            ProviderEventType.CONNECTED,
            ProviderEventType.COMPLETED,
        ]:
            processor.process(db, alloc.call_id,
                              event_type=event_type,
                              event_id=str(uuid.uuid4()), provider_name="provider_a",
                              raw_payload={})
            db.commit()

        call = get_call(db, alloc.call_id)
        assert call.status == CallStatus.COMPLETED

        # Late ANSWERED event arrives (delayed delivery) — must be ignored
        r_answered = processor.process(db, alloc.call_id,
                                       event_type=ProviderEventType.ANSWERED,
                                       event_id=str(uuid.uuid4()), provider_name="provider_a",
                                       raw_payload={})
        db.commit()
        assert r_answered.is_out_of_order is True

        # Status must remain COMPLETED
        call_after = get_call(db, alloc.call_id)
        assert call_after.status == CallStatus.COMPLETED

    def test_failed_then_completed_ignored(self, db, campaign, agents, borrowers):
        """FAILED call cannot be transitioned to COMPLETED by a late event."""
        allocator = CallAllocator()
        alloc = _make_call(db, campaign, allocator)

        processor = EventProcessor()

        # Mark as FAILED directly
        update_call_status(db, alloc.call_id, CallStatus.FAILED)
        db.commit()

        # Late COMPLETED event
        result = processor.process(db, alloc.call_id,
                                   event_type=ProviderEventType.COMPLETED,
                                   event_id=str(uuid.uuid4()), provider_name="provider_a",
                                   raw_payload={})
        db.commit()
        assert result.is_out_of_order is True

        call = get_call(db, alloc.call_id)
        assert call.status == CallStatus.FAILED

    def test_cancelled_call_ignores_all_events(self, db, campaign, agents, borrowers):
        """Cancelled call ignores any subsequent provider events."""
        allocator = CallAllocator()
        alloc = _make_call(db, campaign, allocator)

        update_call_status(db, alloc.call_id, CallStatus.CANCELLED)
        db.commit()

        processor = EventProcessor()

        for event_type in [ProviderEventType.RINGING, ProviderEventType.ANSWERED,
                            ProviderEventType.COMPLETED]:
            result = processor.process(db, alloc.call_id,
                                       event_type=event_type,
                                       event_id=str(uuid.uuid4()), provider_name="provider_a",
                                       raw_payload={})
            db.commit()
            assert result.is_out_of_order is True

        call = get_call(db, alloc.call_id)
        assert call.status == CallStatus.CANCELLED

    def test_provider_b_out_of_order_handled(self, db, campaign, agents, borrowers):
        """
        Provider B emits events out-of-order. The event processor must handle
        this gracefully without raising exceptions.
        """
        from app.providers.provider_b import ProviderB
        provider = ProviderB()

        allocator = CallAllocator()
        alloc = _make_call(db, campaign, allocator)

        # Get events from Provider B — they may come out of order
        events = provider.get_pending_events(alloc.call_id)
        processor = EventProcessor()

        for event in events:
            try:
                processor.process(db, alloc.call_id,
                                   event_type=event.event_type,
                                   event_id=event.event_id,
                                   provider_id="provider_b")
                db.commit()
            except Exception as e:
                # Out-of-order handling must not crash
                db.rollback()
                pytest.fail(f"EventProcessor raised exception on out-of-order event: {e}")
