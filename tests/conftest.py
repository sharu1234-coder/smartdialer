from __future__ import annotations
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

TEST_DB_URL = "postgresql+psycopg2://postgres:Sharkesh%40%2310@localhost:5432/smartdialer_test"


def get_test_engine():
    # pool_size=1: each test uses at most 1+1 connections, preventing exhaustion
    # when the full suite runs (90 function-scoped fixtures would each own one engine).
    return create_engine(
        TEST_DB_URL,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=1,
        pool_timeout=15,
    )


@pytest.fixture(scope="function")
def db() -> Session:
    from app.database import Base
    import app.models  # noqa: F401 — registers all models with Base

    engine = get_test_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestSession()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def campaign(db):
    from app.repositories.campaign_repository import create_campaign
    from app.repositories.campaign_repository import update_campaign_status
    from app.core.enums import CampaignStatus, DialMode
    c = create_campaign(db, name="Test Campaign", dial_mode=DialMode.PROGRESSIVE, max_concurrent_calls=50)
    update_campaign_status(db, c.id, CampaignStatus.ACTIVE)
    db.commit()
    return db.get(type(c), c.id)


@pytest.fixture
def agents(db, campaign):
    from app.repositories.agent_repository import create_agent
    result = []
    for i in range(5):
        a = create_agent(db, name=f"Agent-{i}", campaign_id=campaign.id)
        result.append(a)
    db.commit()
    return result


@pytest.fixture
def borrowers(db, campaign):
    from app.repositories.borrower_repository import create_borrower
    result = []
    for i in range(10):
        b = create_borrower(db, campaign_id=campaign.id,
                            phone_number=f"+1555{i:07d}", name=f"Borrower-{i}")
        result.append(b)
    db.commit()
    return result
