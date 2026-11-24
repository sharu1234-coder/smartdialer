from __future__ import annotations
import pytest
from app.services.progressive_dialer import ProgressiveDialer
from app.repositories.agent_repository import count_available
from app.repositories.borrower_repository import count_pending
from app.core.enums import CallStatus, AgentStatus, BorrowerStatus
from app.providers.provider_factory import initialize_default_providers, reset_providers


@pytest.fixture(autouse=True)
def setup_providers():
    reset_providers()
    initialize_default_providers()
    yield
    reset_providers()


class TestProgressiveDialer:
    def test_tick_creates_calls(self, db, campaign, agents, borrowers):
        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        db.commit()
        assert result.calls_initiated > 0
        assert result.calls_initiated <= result.available_agents

    def test_never_exceeds_available_agents(self, db, campaign, agents, borrowers):
        """Core safety invariant: calls_initiated <= available_agents."""
        available_before = count_available(db, campaign.id)
        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        db.commit()
        assert result.calls_initiated <= available_before

    def test_agents_become_reserved_after_tick(self, db, campaign, agents, borrowers):
        from sqlalchemy import select
        from app.models.agent import Agent

        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        db.commit()

        if result.calls_initiated > 0:
            reserved = db.execute(
                select(Agent).where(Agent.status == AgentStatus.RESERVED)
            ).scalars().all()
            assert len(reserved) == result.calls_initiated

    def test_borrowers_become_reserved_after_tick(self, db, campaign, agents, borrowers):
        from sqlalchemy import select
        from app.models.borrower import Borrower

        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        db.commit()

        if result.calls_initiated > 0:
            reserved = db.execute(
                select(Borrower).where(Borrower.status == BorrowerStatus.RESERVED)
            ).scalars().all()
            assert len(reserved) == result.calls_initiated

    def test_no_calls_when_no_agents(self, db, campaign, borrowers):
        """With no agents registered, tick should produce zero calls."""
        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        assert result.calls_initiated == 0

    def test_no_calls_when_no_borrowers(self, db, campaign, agents):
        """With no borrowers, tick should produce zero calls."""
        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        assert result.calls_initiated == 0

    def test_outbox_entries_created(self, db, campaign, agents, borrowers):
        from sqlalchemy import select
        from app.models.outbox import Outbox
        from app.core.enums import OutboxStatus

        dialer = ProgressiveDialer(db, campaign.id)
        result = dialer.tick()
        db.commit()

        pending_outbox = db.execute(
            select(Outbox).where(Outbox.status == OutboxStatus.PENDING)
        ).scalars().all()
        assert len(pending_outbox) == result.calls_initiated
