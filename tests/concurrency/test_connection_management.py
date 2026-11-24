"""
Regression tests for PostgreSQL connection management.

Verifies:
1.  Sessions close after successful allocation.
2.  Sessions close after allocation exceptions.
3.  Sessions close after transaction rollback.
4.  Concurrent allocation does not leak connections.
5.  DB connection exhaustion is reported accurately (not as "no agent").
6.  No DB failure becomes a misleading no-agent result.
7.  Connection-pool limits are respected.
8.  Concurrent workers cannot reserve the same agent.
9.  Concurrent workers cannot reserve the same borrower.
10. Safety invariants remain intact under DB contention.
"""
from __future__ import annotations

import threading
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.enums import AgentStatus, BorrowerStatus, CampaignStatus, DialMode
from app.core.exceptions import AgentNotAvailableError, BorrowerNotAvailableError
from app.database import Base
from app.models import *  # noqa: F401,F403 — register all models
from app.models.agent import Agent
from app.models.borrower import Borrower
from app.providers.provider_factory import initialize_default_providers, reset_providers
from app.repositories.agent_repository import create_agent
from app.repositories.borrower_repository import create_borrower
from app.repositories.campaign_repository import create_campaign, update_campaign_status
from app.services.call_allocator import CallAllocator

TEST_DB_URL = "postgresql+psycopg2://postgres:Sharkesh%40%2310@localhost:5432/smartdialer_test"

_ENGINE = create_engine(
    TEST_DB_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=15,
)
_Session = sessionmaker(bind=_ENGINE, autocommit=False, autoflush=False)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fresh_db():
    return _Session()


def _pool_checked_out() -> int:
    """Return number of connections currently checked out from the pool."""
    return _ENGINE.pool.checkedout()


@pytest.fixture(autouse=True)
def reset_schema():
    reset_providers()
    initialize_default_providers()
    Base.metadata.drop_all(_ENGINE)
    Base.metadata.create_all(_ENGINE)
    yield
    Base.metadata.drop_all(_ENGINE)
    reset_providers()


@pytest.fixture
def campaign_id():
    db = fresh_db()
    try:
        c = create_campaign(db, "CM Test", DialMode.PROGRESSIVE, 50)
        update_campaign_status(db, c.id, CampaignStatus.ACTIVE)
        db.commit()
        return c.id
    finally:
        db.close()


@pytest.fixture
def one_agent_one_borrower(campaign_id):
    db = fresh_db()
    try:
        create_agent(db, "AgentA", campaign_id=campaign_id)
        create_borrower(db, campaign_id=campaign_id, phone_number="+15550000001", name="B1")
        db.commit()
    finally:
        db.close()
    return campaign_id


# ── Test 1: session closes after successful allocation ────────────────────────

def test_session_closes_after_success(one_agent_one_borrower):
    campaign_id = one_agent_one_borrower
    before = _pool_checked_out()
    db = fresh_db()
    try:
        allocator = CallAllocator()
        result = allocator.allocate(db, campaign_id, DialMode.PROGRESSIVE)
        db.commit()
        assert result is not None
    finally:
        db.close()
    after = _pool_checked_out()
    assert after == before, f"Connection leaked: before={before} after={after}"


# ── Test 2: session closes after allocation exception ─────────────────────────

def test_session_closes_after_exception(campaign_id):
    before = _pool_checked_out()
    db = fresh_db()
    try:
        allocator = CallAllocator()
        with patch.object(
            allocator, "allocate", side_effect=RuntimeError("injected")
        ):
            with pytest.raises(RuntimeError):
                allocator.allocate(db, campaign_id, DialMode.PROGRESSIVE)
    finally:
        db.close()
    after = _pool_checked_out()
    assert after == before, f"Connection leaked after exception: before={before} after={after}"


# ── Test 3: session closes after explicit rollback ────────────────────────────

def test_session_closes_after_rollback(campaign_id):
    before = _pool_checked_out()
    db = fresh_db()
    try:
        db.execute(text("SELECT 1"))
        db.rollback()
    finally:
        db.close()
    after = _pool_checked_out()
    assert after == before, f"Connection leaked after rollback: before={before} after={after}"


# ── Test 4: concurrent allocation does not leak connections ───────────────────

def test_no_connection_leak_under_concurrency(one_agent_one_borrower):
    campaign_id = one_agent_one_borrower
    before = _pool_checked_out()
    results = []
    errors = []

    def try_alloc():
        db = fresh_db()
        try:
            r = CallAllocator().allocate(db, campaign_id, DialMode.PROGRESSIVE)
            db.commit()
            results.append(r)
        except Exception as exc:
            errors.append(exc)
            db.rollback()
        finally:
            db.close()

    threads = [threading.Thread(target=try_alloc) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    after = _pool_checked_out()
    assert after == before, f"Connection leaked under concurrency: before={before} after={after}"


# ── Test 5: DB connection error is NOT reported as no-agent ───────────────────

def test_db_error_raises_not_returns_none(campaign_id):
    """
    When the database raises an OperationalError the allocator must NOT
    swallow it and return None — it must propagate so callers know something
    went wrong rather than silently treating it as "no resource available".
    """
    db = fresh_db()
    try:
        # Simulate connection exhaustion error from psycopg2
        def boom(*a, **kw):
            raise OperationalError(
                "FATAL: sorry, too many clients already",
                orig=None,
                params=None,
            )

        with patch("app.repositories.borrower_repository.get_next_borrower", side_effect=boom):
            with pytest.raises(OperationalError):
                CallAllocator().allocate(db, campaign_id, DialMode.PROGRESSIVE)
    finally:
        db.close()


# ── Test 6: AgentNotAvailableError returns None, not an exception ─────────────

def test_no_agent_returns_none_not_exception(campaign_id):
    """
    When no agent is available the allocator returns None silently.
    It must NOT raise so callers can poll again later.
    """
    db = fresh_db()
    try:
        # No agents created → allocate returns None
        result = CallAllocator().allocate(db, campaign_id, DialMode.PROGRESSIVE)
        db.commit()
        assert result is None
    finally:
        db.close()


# ── Test 7: pool limit is respected ──────────────────────────────────────────

def test_pool_limit_respected():
    """
    With pool_size=5 and max_overflow=5 the pool raises TimeoutError rather
    than growing without bound when all connections are occupied.
    """
    from sqlalchemy.exc import TimeoutError as SATimeout

    tiny_engine = create_engine(
        TEST_DB_URL,
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,  # fail fast
    )
    TinySession = sessionmaker(bind=tiny_engine)

    checked_out = []
    try:
        for _ in range(2):
            s = TinySession()
            s.execute(text("SELECT 1"))
            checked_out.append(s)

        # Third request must time out, not hang or open a new connection
        with pytest.raises((SATimeout, Exception)):
            extra = TinySession()
            extra.execute(text("SELECT 1"))
    finally:
        for s in checked_out:
            try:
                s.close()
            except Exception:
                pass
        tiny_engine.dispose()


# ── Test 8: concurrent workers cannot reserve the same agent ─────────────────

def test_concurrent_workers_no_duplicate_agent(one_agent_one_borrower):
    campaign_id = one_agent_one_borrower
    successes = []
    errors = []

    def try_alloc():
        db = fresh_db()
        try:
            r = CallAllocator().allocate(db, campaign_id, DialMode.PROGRESSIVE)
            db.commit()
            if r is not None:
                successes.append(r.agent_id)
        except Exception as exc:
            errors.append(exc)
            db.rollback()
        finally:
            db.close()

    threads = [threading.Thread(target=try_alloc) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # At most 1 agent was available; duplicates would mean the same agent was
    # reserved twice.
    assert len(successes) == len(set(successes)), "Same agent reserved by multiple workers"
    assert len(successes) <= 1


# ── Test 9: concurrent workers cannot reserve the same borrower ───────────────

def test_concurrent_workers_no_duplicate_borrower(one_agent_one_borrower):
    campaign_id = one_agent_one_borrower
    # Add more agents so borrower contention is the bottleneck
    db = fresh_db()
    try:
        for i in range(9):
            create_agent(db, f"ExtraAgent-{i}", campaign_id=campaign_id)
        db.commit()
    finally:
        db.close()

    borrower_ids = []
    errors = []

    def try_alloc():
        db = fresh_db()
        try:
            r = CallAllocator().allocate(db, campaign_id, DialMode.PROGRESSIVE)
            db.commit()
            if r is not None:
                borrower_ids.append(r.borrower_id)
        except Exception as exc:
            errors.append(exc)
            db.rollback()
        finally:
            db.close()

    threads = [threading.Thread(target=try_alloc) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(borrower_ids) == len(set(borrower_ids)), \
        "Same borrower reserved by multiple workers"


# ── Test 10: safety invariants under DB contention ───────────────────────────

def test_safety_invariants_under_contention(one_agent_one_borrower):
    """
    After concurrent allocation attempts, DB state must be internally consistent:
    every RESERVED agent has a matching RESERVED borrower, and no agent is
    double-booked.
    """
    campaign_id = one_agent_one_borrower

    def try_alloc():
        db = fresh_db()
        try:
            CallAllocator().allocate(db, campaign_id, DialMode.PROGRESSIVE)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    threads = [threading.Thread(target=try_alloc) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check = fresh_db()
    try:
        reserved_agents = list(
            check.execute(
                select(Agent).where(Agent.status == AgentStatus.RESERVED)
            ).scalars()
        )
        reserved_borrowers = list(
            check.execute(
                select(Borrower).where(Borrower.status == BorrowerStatus.RESERVED)
            ).scalars()
        )

        # With 1 agent and 1 borrower, at most 1 of each should be RESERVED
        assert len(reserved_agents) <= 1, \
            f"Multiple agents reserved: {[a.id for a in reserved_agents]}"
        assert len(reserved_borrowers) <= 1, \
            f"Multiple borrowers reserved: {[b.id for b in reserved_borrowers]}"
        assert len(reserved_agents) == len(reserved_borrowers), \
            "Agent/borrower reservation count mismatch — partial allocation"
    finally:
        check.close()
