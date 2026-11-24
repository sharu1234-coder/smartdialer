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
from app.services.safety_controller import SafetyController
from app.services.call_allocator import CallAllocator
from app.core.enums import CampaignStatus, DialMode, AgentStatus, ProviderStatus
from app.providers.provider_factory import initialize_default_providers, reset_providers

TEST_DB_URL = "postgresql+psycopg2://postgres:Sharkesh%40%2310@localhost:5432/smartdialer_test"


def make_session():
    engine = create_engine(TEST_DB_URL)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


class TestCapacityLimits:
    def setup_method(self):
        engine = create_engine(TEST_DB_URL)
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        engine.dispose()
        reset_providers()
        initialize_default_providers()

        setup_db = make_session()
        c = create_campaign(setup_db, "Capacity Test", DialMode.PROGRESSIVE, 50)
        update_campaign_status(setup_db, c.id, CampaignStatus.ACTIVE)
        self.campaign_id = c.id

        # 5 agents, 50 borrowers
        for i in range(5):
            create_agent(setup_db, f"Agent-{i}", campaign_id=c.id)
        for i in range(50):
            create_borrower(setup_db, campaign_id=c.id,
                            phone_number=f"+155500{i:04d}", name=f"B-{i}")
        setup_db.commit()
        setup_db.close()

    def teardown_method(self):
        engine = create_engine(TEST_DB_URL)
        Base.metadata.drop_all(engine)
        engine.dispose()
        reset_providers()

    def test_concurrent_allocations_do_not_exceed_agents(self):
        """10 concurrent workers try to allocate. Total allocations <= 5 agents."""
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
        # Must never exceed 5 (number of agents)
        assert len(successful) <= 5

        # Verify agent IDs are unique across all allocations
        agent_ids = [r.agent_id for r in successful]
        assert len(set(agent_ids)) == len(agent_ids), "Same agent allocated to multiple calls!"

    def test_safety_controller_caps_to_available(self):
        """Safety controller caps requested calls to actual available agents."""
        db = make_session()
        try:
            sc = SafetyController()
            evaluation = sc.evaluate(db, self.campaign_id, requested_calls=100,
                                     provider_health=ProviderStatus.HEALTHY)
            assert evaluation.approved <= 5
        finally:
            db.close()
