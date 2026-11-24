from __future__ import annotations
import threading
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import *  # noqa: F401,F403
from app.repositories.agent_repository import create_agent
from app.repositories.campaign_repository import create_campaign, update_campaign_status
from app.repositories.borrower_repository import create_borrower
from app.services.call_allocator import CallAllocator
from app.core.enums import CampaignStatus, DialMode, AgentStatus
from app.providers.provider_factory import initialize_default_providers, reset_providers

TEST_DB_URL = "postgresql+psycopg2://postgres:Sharkesh%40%2310@localhost:5432/smartdialer_test"

# One engine shared across all test sessions — prevents connection exhaustion.
_TEST_ENGINE = create_engine(
    TEST_DB_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=15,
)
_TestSession = sessionmaker(bind=_TEST_ENGINE, autocommit=False, autoflush=False)


def make_session():
    """Return a Session backed by the single shared test engine."""
    return _TestSession()


class TestConcurrentAgentReservation:
    def setup_method(self):
        Base.metadata.drop_all(_TEST_ENGINE)
        Base.metadata.create_all(_TEST_ENGINE)

        reset_providers()
        initialize_default_providers()

        setup_db = make_session()
        c = create_campaign(setup_db, "Concurrency Test", DialMode.PROGRESSIVE, 50)
        update_campaign_status(setup_db, c.id, CampaignStatus.ACTIVE)
        setup_db.commit()
        self.campaign_id = c.id

        # Create only ONE agent and many borrowers
        create_agent(setup_db, "SingleAgent", campaign_id=c.id)
        for i in range(10):
            create_borrower(setup_db, campaign_id=c.id,
                            phone_number=f"+155500{i:04d}", name=f"B-{i}")
        setup_db.commit()
        setup_db.close()

    def teardown_method(self):
        Base.metadata.drop_all(_TEST_ENGINE)
        reset_providers()

    def test_only_one_worker_can_reserve_agent(self):
        """
        Two concurrent workers both try to reserve the SAME agent.
        Only one should succeed.
        """
        results = []
        errors = []

        def try_allocate():
            db = make_session()
            try:
                allocator = CallAllocator()
                result = allocator.allocate(db, self.campaign_id, DialMode.PROGRESSIVE)
                db.commit()
                results.append(result)
            except Exception as exc:
                errors.append(exc)
                db.rollback()
            finally:
                db.close()

        t1 = threading.Thread(target=try_allocate)
        t2 = threading.Thread(target=try_allocate)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one allocation should succeed (or zero if both failed due to contention)
        successful = [r for r in results if r is not None]
        assert len(successful) <= 1, (
            f"Two workers both reserved the same agent! successful={len(successful)}"
        )

        # Verify DB state: at most 1 RESERVED agent
        check_db = make_session()
        from sqlalchemy import select
        from app.models.agent import Agent
        reserved = check_db.execute(
            select(Agent).where(Agent.status == AgentStatus.RESERVED)
        ).scalars().all()
        assert len(reserved) <= 1
        check_db.close()

    def test_many_workers_one_agent(self):
        """10 concurrent workers, 1 agent. Only 1 allocation succeeds."""
        results = []

        def try_allocate():
            db = make_session()
            try:
                allocator = CallAllocator()
                result = allocator.allocate(db, self.campaign_id, DialMode.PROGRESSIVE)
                db.commit()
                results.append(result)
            except Exception:
                db.rollback()
                results.append(None)
            finally:
                db.close()

        threads = [threading.Thread(target=try_allocate) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successful = [r for r in results if r is not None]
        assert len(successful) == 1
