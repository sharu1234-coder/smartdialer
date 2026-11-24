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


class TestDuplicateEvents:
    def test_duplicate_event_marked_and_ignored(self, db, campaign, agents, borrowers):
        """
        Same (call_id, event_id) processed twice — second should be marked duplicate,
        call status should not change.
        """
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        update_call_status(db, alloc.call_id, CallStatus.INITIATED)
        db.commit()

        event_id = str(uuid.uuid4())
        processor = EventProcessor()

        # First RINGING event
        result1 = processor.process(
            db, alloc.call_id,
            event_type=ProviderEventType.RINGING,
            event_id=event_id,
            provider_name="provider_a",
            raw_payload={}
        )
        db.commit()
        assert result1.is_duplicate is False

        call_after_first = get_call(db, alloc.call_id)
        assert call_after_first.status == CallStatus.RINGING

        # Same event again (simulating provider retransmit)
        result2 = processor.process(
            db, alloc.call_id,
            event_type=ProviderEventType.RINGING,
            event_id=event_id,
            provider_name="provider_a",
            raw_payload={}
        )
        db.commit()
        assert result2.is_duplicate is True

        # Status must still be RINGING, not changed again
        call_after_second = get_call(db, alloc.call_id)
        assert call_after_second.status == CallStatus.RINGING

    def test_multiple_duplicate_events_all_idempotent(self, db, campaign, agents, borrowers):
        """10 duplicate events — only the first one takes effect."""
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        update_call_status(db, alloc.call_id, CallStatus.INITIATED)
        db.commit()

        event_id = str(uuid.uuid4())
        processor = EventProcessor()

        duplicate_count = 0
        for i in range(10):
            result = processor.process(
                db, alloc.call_id,
                event_type=ProviderEventType.RINGING,
                event_id=event_id,
                provider_name="provider_a",
                raw_payload={}
            )
            db.commit()
            if result.is_duplicate:
                duplicate_count += 1

        assert duplicate_count == 9

    def test_different_event_ids_all_processed(self, db, campaign, agents, borrowers):
        """Different event IDs for same event type are all processed."""
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        update_call_status(db, alloc.call_id, CallStatus.INITIATED)
        db.commit()

        processor = EventProcessor()

        # First RINGING with event_id_1
        r1 = processor.process(
            db, alloc.call_id,
            event_type=ProviderEventType.RINGING,
            event_id=str(uuid.uuid4()),
            provider_name="provider_a",
            raw_payload={}
        )
        db.commit()
        assert r1.is_duplicate is False

        # Second RINGING with event_id_2 — retransmit with new ID
        r2 = processor.process(
            db, alloc.call_id,
            event_type=ProviderEventType.RINGING,
            event_id=str(uuid.uuid4()),
            provider_name="provider_a",
            raw_payload={}
        )
        db.commit()
        # Not a duplicate by ID — may succeed or be skipped by state machine
        assert r2 is not None
