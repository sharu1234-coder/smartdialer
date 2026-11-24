from __future__ import annotations
import pytest
from app.services.call_allocator import CallAllocator
from app.services.event_processor import EventProcessor
from app.repositories.call_repository import get_call
from app.repositories.agent_repository import get_agent
from app.core.enums import CallStatus, AgentStatus, DialMode, ProviderEventType
from app.providers.provider_factory import initialize_default_providers, reset_providers


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


class TestCallLifecycle:
    def test_full_happy_path(self, db, campaign, agents, borrowers):
        """RESERVED -> INITIATED -> RINGING -> ANSWERED -> COMPLETED"""
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        processor = EventProcessor()

        # Walk through states
        from app.repositories.call_repository import update_call_status
        update_call_status(db, alloc.call_id, CallStatus.INITIATED)
        db.commit()

        for event_type, expected_status in [
            (ProviderEventType.RINGING, CallStatus.RINGING),
            (ProviderEventType.ANSWERED, CallStatus.ANSWERED),
            (ProviderEventType.COMPLETED, CallStatus.COMPLETED),
        ]:
            r = processor.process(
                db, alloc.call_id, event_type,
                f"evt-{event_type.value}", "provider_a", {}
            )
            db.commit()
            assert not r.is_duplicate
            assert r.new_call_status == expected_status.value

        call = get_call(db, alloc.call_id)
        assert call.status == CallStatus.COMPLETED
        assert call.answered_at is not None
        assert call.completed_at is not None

        # Agent should be AVAILABLE after completion
        agent = get_agent(db, alloc.agent_id)
        assert agent.status == AgentStatus.AVAILABLE

    def test_failed_call_releases_resources(self, db, campaign, agents, borrowers):
        allocator = CallAllocator()
        alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
        assert alloc is not None
        db.commit()

        from app.repositories.call_repository import update_call_status
        update_call_status(db, alloc.call_id, CallStatus.INITIATED)
        db.commit()

        processor = EventProcessor()
        r = processor.process(
            db, alloc.call_id, ProviderEventType.FAILED,
            "evt-failed-001", "provider_a", {}
        )
        db.commit()
        assert r.new_call_status == CallStatus.FAILED.value

        agent = get_agent(db, alloc.agent_id)
        assert agent.status == AgentStatus.AVAILABLE

    def test_agent_reserved_per_call(self, db, campaign, agents, borrowers):
        """Each call must have its own dedicated agent — no sharing."""
        allocator = CallAllocator()
        allocations = []
        for _ in range(3):
            alloc = allocator.allocate(db, campaign.id, DialMode.PROGRESSIVE)
            if alloc:
                allocations.append(alloc)
        db.commit()

        agent_ids = [a.agent_id for a in allocations]
        # All agent IDs must be unique
        assert len(set(agent_ids)) == len(agent_ids)
