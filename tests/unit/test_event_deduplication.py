from __future__ import annotations
import pytest
from app.services.event_processor import EventProcessor
from app.core.enums import ProviderEventType, CallStatus


class TestEventDeduplication:
    def test_duplicate_event_not_applied(self, db, campaign, agents, borrowers):
        """Same event_id processed twice — second is a no-op."""
        from app.services.call_allocator import CallAllocator
        from app.core.enums import DialMode
        from app.providers.provider_factory import initialize_default_providers, reset_providers

        reset_providers()
        initialize_default_providers()

        allocator = CallAllocator()
        result = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert result is not None
        db.commit()

        processor = EventProcessor()
        event_id = "unique-ringing-001"

        # First event: transitions RESERVED -> RINGING? Actually call starts at RESERVED
        # Let's first transition to INITIATED manually
        from app.repositories.call_repository import update_call_status, get_call
        update_call_status(db, result.call_id, CallStatus.INITIATED)
        db.commit()

        # First RINGING event
        r1 = processor.process(
            db, result.call_id, ProviderEventType.RINGING, event_id, "provider_a", {}
        )
        db.commit()
        assert not r1.is_duplicate
        assert r1.new_call_status == CallStatus.RINGING.value

        # Same event again
        r2 = processor.process(
            db, result.call_id, ProviderEventType.RINGING, event_id, "provider_a", {}
        )
        db.commit()
        assert r2.is_duplicate
        assert r2.skipped

        # Call should still be RINGING (not rolled back)
        call = get_call(db, result.call_id)
        assert call.status == CallStatus.RINGING

    def test_triple_answered_events(self, db, campaign, agents, borrowers):
        """ANSWERED + ANSWERED + ANSWERED: only first applies."""
        from app.services.call_allocator import CallAllocator
        from app.repositories.call_repository import update_call_status, get_call
        from app.core.enums import DialMode
        from app.providers.provider_factory import initialize_default_providers, reset_providers

        reset_providers()
        initialize_default_providers()

        allocator = CallAllocator()
        result = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert result is not None

        # Walk call through INITIATED -> RINGING
        update_call_status(db, result.call_id, CallStatus.INITIATED)
        update_call_status(db, result.call_id, CallStatus.RINGING)
        db.commit()

        processor = EventProcessor()
        answered_event_id = "answered-001"

        for i in range(3):
            r = processor.process(
                db, result.call_id, ProviderEventType.ANSWERED, answered_event_id, "provider_b", {}
            )
            if i == 0:
                assert not r.is_duplicate
            else:
                assert r.is_duplicate

        db.commit()
        call = get_call(db, result.call_id)
        assert call.status == CallStatus.ANSWERED

    def test_late_event_on_terminal_call(self, db, campaign, agents, borrowers):
        """RINGING arriving after COMPLETED is out-of-order, call stays COMPLETED."""
        from app.services.call_allocator import CallAllocator
        from app.repositories.call_repository import update_call_status, get_call
        from app.core.enums import DialMode
        from app.providers.provider_factory import initialize_default_providers, reset_providers

        reset_providers()
        initialize_default_providers()

        allocator = CallAllocator()
        result = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert result is not None

        # Walk to COMPLETED
        for status in [CallStatus.INITIATED, CallStatus.RINGING, CallStatus.ANSWERED, CallStatus.COMPLETED]:
            update_call_status(db, result.call_id, status)
        db.commit()

        processor = EventProcessor()
        r = processor.process(
            db, result.call_id, ProviderEventType.RINGING, "late-ringing-001", "provider_a", {}
        )
        db.commit()
        assert r.is_out_of_order
        assert r.skipped

        call = get_call(db, result.call_id)
        assert call.status == CallStatus.COMPLETED  # unchanged
