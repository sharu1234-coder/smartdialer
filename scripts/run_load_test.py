#!/usr/bin/env python3
"""
Load test: measure throughput and latency under concurrent allocation pressure.

Usage:
    # Burst mode — concurrent workers, no call completion (measures raw allocation speed)
    python scripts/run_load_test.py --workers 2  --duration 5  --agents 100
    python scripts/run_load_test.py --workers 5  --duration 10 --agents 100
    python scripts/run_load_test.py --workers 10 --duration 15 --agents 100

    # Sustained mode — tick loop that allocates AND processes events so agents recycle
    python scripts/run_load_test.py --mode sustained --ticks 120 --agents 20

Connection budget (per process):
    pool_size=10, max_overflow=5  =>  15 connections max from this script
    app/database.py uses pool_size=5, max_overflow=5 => 10 connections from API
    Total with API running: ~25 connections, well within PostgreSQL default of 100.
"""
from __future__ import annotations
import sys
import os
import argparse
import threading
import time
import statistics
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import *  # noqa: F401,F403 — registers all models with Base
from app.repositories.campaign_repository import create_campaign, update_campaign_status
from app.repositories.agent_repository import create_agent
from app.repositories.borrower_repository import create_borrower
from app.services.call_allocator import CallAllocator
from app.workers.dial_worker import DialWorker
from app.workers.event_worker import EventWorker
from app.core.enums import CampaignStatus, DialMode
from app.core.exceptions import AgentNotAvailableError, BorrowerNotAvailableError
from app.providers.provider_factory import initialize_default_providers, reset_providers
from app.config import get_settings

settings = get_settings()
logging.basicConfig(level=logging.WARNING)

# ── Single shared engine for the entire load-test process ─────────────────────
# All worker threads share this pool so we never exceed pool_size + max_overflow
# connections regardless of how many threads are running.
_load_test_engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=10,       # 10 persistent connections shared across all workers
    max_overflow=5,     # 5 overflow connections — 15 max total from this process
    pool_timeout=30,    # raise TimeoutError instead of hanging forever
    pool_recycle=1800,
)
_LoadTestSession = sessionmaker(
    bind=_load_test_engine, autocommit=False, autoflush=False
)


def make_session():
    """Return a Session backed by the single shared engine."""
    return _LoadTestSession()


# ── Error categories ──────────────────────────────────────────────────────────

class _ErrorKind:
    NO_AGENT     = "no_agent"
    NO_BORROWER  = "no_borrower"
    DB_CONN      = "db_connection"
    POOL_TIMEOUT = "pool_timeout"
    LOCK_TIMEOUT = "lock_timeout"
    OTHER        = "other"


def _classify_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if isinstance(exc, AgentNotAvailableError):
        return _ErrorKind.NO_AGENT
    if isinstance(exc, BorrowerNotAvailableError):
        return _ErrorKind.NO_BORROWER
    if "too many clients" in msg or "connection refused" in msg or "could not connect" in msg:
        return _ErrorKind.DB_CONN
    if "queuepool limit" in msg or "timeout" in msg and "pool" in msg:
        return _ErrorKind.POOL_TIMEOUT
    if "lock" in msg and ("timeout" in msg or "deadlock" in msg):
        return _ErrorKind.LOCK_TIMEOUT
    return _ErrorKind.OTHER


@dataclass
class LoadTestResult:
    worker_id: int
    success: bool          # True = allocation returned a non-None result
    no_resource: bool      # True = no agent/borrower available (expected)
    error_kind: str        # one of _ErrorKind constants, "" on success
    latency_ms: float
    error_detail: str = ""


# ── Worker task ───────────────────────────────────────────────────────────────

def worker_task(
    worker_id: int,
    campaign_id: str,
    duration: float,
    results: List[LoadTestResult],
    stop_event: threading.Event,
):
    allocator = CallAllocator()
    end_time = time.monotonic() + duration

    while time.monotonic() < end_time and not stop_event.is_set():
        db = make_session()
        start = time.monotonic()
        success = False
        no_resource = False
        error_kind = ""
        error_detail = ""
        try:
            result = allocator.allocate(db, campaign_id, DialMode.PROGRESSIVE)
            db.commit()
            if result is not None:
                success = True
            else:
                # allocate() returns None for contention (no agent / no borrower)
                no_resource = True
                error_kind = _ErrorKind.NO_AGENT
        except (AgentNotAvailableError, BorrowerNotAvailableError) as exc:
            db.rollback()
            no_resource = True
            error_kind = _classify_error(exc)
            error_detail = str(exc)
        except Exception as exc:
            db.rollback()
            error_kind = _classify_error(exc)
            error_detail = str(exc)
            logging.warning("Worker %d allocation error [%s]: %s", worker_id, error_kind, exc)
        finally:
            latency_ms = (time.monotonic() - start) * 1000
            results.append(LoadTestResult(
                worker_id=worker_id,
                success=success,
                no_resource=no_resource,
                error_kind=error_kind,
                latency_ms=latency_ms,
                error_detail=error_detail,
            ))
            try:
                db.close()
            except Exception:
                pass

        time.sleep(0.05)  # 50 ms between attempts per worker


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup_load_test(num_agents: int) -> str:
    """Drop/recreate schema and seed test data. Returns campaign_id."""
    Base.metadata.drop_all(_load_test_engine)
    Base.metadata.create_all(_load_test_engine)

    db = make_session()
    try:
        c = create_campaign(db, "Load Test Campaign", DialMode.PROGRESSIVE, 50)
        update_campaign_status(db, c.id, CampaignStatus.ACTIVE)

        for i in range(num_agents):
            create_agent(db, f"LoadAgent-{i:04d}", campaign_id=c.id)

        for i in range(num_agents * 50):
            create_borrower(
                db,
                campaign_id=c.id,
                phone_number=f"+1333{i:07d}",
                name=f"Lead {i}",
            )

        db.commit()
        return c.id
    finally:
        db.close()


def _pg_conn_count() -> int:
    """Return current PostgreSQL active connection count, or -1 on error."""
    try:
        with _load_test_engine.connect() as conn:
            row = conn.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state != 'idle'")
            ).fetchone()
            return int(row[0]) if row else -1
    except Exception:
        return -1


# ── Main ──────────────────────────────────────────────────────────────────────

def run_sustained_test(num_agents: int, num_ticks: int) -> None:
    """
    Sustained workload test: runs a tick loop that both allocates calls AND processes
    provider events so agents get released and can be reused.

    Unlike burst mode (which only measures raw allocation speed), this test verifies:
    - Agents recycle correctly through RESERVED → CONNECTED → AVAILABLE states.
    - The connection pool stays bounded across the full session lifecycle.
    - Successful allocations continue across many agent cycles.
    """
    print(f"\n{'='*55}")
    print(f"SUSTAINED LOAD TEST: {num_agents} agents, {num_ticks} ticks")
    print(f"Pool budget: pool_size=10 max_overflow=5 → 15 connections max")
    print(f"{'='*55}")

    reset_providers()
    # Provider with 50% answer rate and short 3-tick talk time for fast agent recycling
    initialize_default_providers(provider_a_kwargs={
        "answer_rate": 0.50,
        "avg_talk_duration": 3.0,
        "failure_rate": 0.05,
        "latency_ms": 10.0,
        "seed": 42,
    })

    Base.metadata.drop_all(_load_test_engine)
    Base.metadata.create_all(_load_test_engine)

    db = make_session()
    try:
        c = create_campaign(db, "Sustained Test Campaign", DialMode.PROGRESSIVE, num_agents * 2)
        update_campaign_status(db, c.id, CampaignStatus.ACTIVE)
        for i in range(num_agents):
            create_agent(db, f"SustAgent-{i:04d}", campaign_id=c.id)
        for i in range(num_agents * 50):
            create_borrower(db, campaign_id=c.id,
                            phone_number=f"+1444{i:07d}", name=f"Lead {i}")
        db.commit()
        campaign_id = c.id
    finally:
        db.close()

    dial_worker = DialWorker(campaign_id, DialMode.PROGRESSIVE, provider_name="provider_a")
    event_worker = EventWorker("provider_a")

    conn_before = _pg_conn_count()
    total_initiated = 0
    total_completed = 0

    wall_start = time.monotonic()
    for tick in range(num_ticks):
        db = make_session()
        try:
            tick_r = dial_worker.run_tick(db)
            db.commit()
            total_initiated += tick_r.calls_initiated
        except Exception as exc:
            db.rollback()
            logging.warning("Dial tick error at tick %d: %s", tick, exc)
        finally:
            db.close()

        db = make_session()
        try:
            event_r = event_worker.run_tick(db)
            db.commit()
        except Exception as exc:
            db.rollback()
            logging.warning("Event tick error at tick %d: %s", tick, exc)
        finally:
            db.close()

    wall_elapsed = time.monotonic() - wall_start
    conn_after = _pg_conn_count()

    # Count completed calls
    db = make_session()
    try:
        from app.repositories.call_repository import count_calls_by_status
        from app.core.enums import CallStatus
        counts = count_calls_by_status(db, campaign_id)
        total_completed = counts.get(CallStatus.COMPLETED, 0)
        total_failed = counts.get(CallStatus.FAILED, 0)
        still_active = sum(
            counts.get(s, 0)
            for s in [CallStatus.RESERVED, CallStatus.INITIATED, CallStatus.RINGING,
                      CallStatus.ANSWERED, CallStatus.CONNECTED]
        )
    finally:
        db.close()

    print(f"Duration:               {wall_elapsed:.1f}s wall-clock")
    print(f"Ticks:                  {num_ticks}")
    print(f"Total initiated:        {total_initiated}")
    print(f"Completed:              {total_completed}")
    print(f"Failed:                 {total_failed}")
    print(f"Still active (in-flight): {still_active}")
    print(f"PG active connections:  before={conn_before}  after={conn_after}")
    if total_initiated > 0:
        answer_rate = total_completed / (total_completed + total_failed) if (total_completed + total_failed) > 0 else 0
        print(f"Measured answer rate:   {answer_rate:.1%}")
    print()
    if conn_after <= 15:
        print("[OK] Connection count within budget (≤15).")
    else:
        print(f"[WARNING] Connection count {conn_after} exceeds budget — investigate pool config.")

    if total_completed > num_agents:
        print(f"[OK] Agents recycled — {total_completed} completions with only {num_agents} agents.")
    else:
        print(f"[INFO] {total_completed} completions — verify event processing progressed calls.")

    # Cleanup
    Base.metadata.drop_all(_load_test_engine)
    _load_test_engine.dispose()
    reset_providers()


def main():
    p = argparse.ArgumentParser(description="SmartDialer load test")
    p.add_argument("--mode", choices=["burst", "sustained"], default="burst",
                   help="burst=concurrent allocation only; sustained=tick loop with event processing")
    p.add_argument("--workers",  type=int, default=10)
    p.add_argument("--duration", type=int, default=30, help="Seconds (burst mode)")
    p.add_argument("--agents",   type=int, default=50)
    p.add_argument("--ticks",    type=int, default=120, help="Ticks (sustained mode)")
    args = p.parse_args()

    if args.mode == "sustained":
        run_sustained_test(args.agents, args.ticks)
        return

    print(f"\nLoad test: {args.workers} workers, {args.duration}s, {args.agents} agents")
    print(f"Pool budget: pool_size=10 max_overflow=5 → 15 connections max (this process)")

    reset_providers()
    initialize_default_providers()

    conn_before = _pg_conn_count()
    campaign_id = setup_load_test(args.agents)
    print(f"PG active connections before test: {conn_before}")

    results: List[LoadTestResult] = []
    stop_event = threading.Event()

    threads = [
        threading.Thread(
            target=worker_task,
            args=(i, campaign_id, args.duration, results, stop_event),
        )
        for i in range(args.workers)
    ]

    start = time.monotonic()
    for t in threads:
        t.start()

    conn_during = -1
    # Sample connection count midway through
    time.sleep(args.duration / 2)
    conn_during = _pg_conn_count()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        stop_event.set()
        for t in threads:
            t.join(timeout=2)

    elapsed = time.monotonic() - start
    conn_after = _pg_conn_count()

    # ── Categorise results ────────────────────────────────────────────────────
    total      = len(results)
    successful = [r for r in results if r.success]
    no_res     = [r for r in results if r.no_resource]
    errors     = [r for r in results if not r.success and not r.no_resource]
    latencies  = [r.latency_ms for r in results]

    error_counts: Counter = Counter(r.error_kind for r in errors)
    no_res_counts: Counter = Counter(r.error_kind for r in no_res)

    print(f"\n{'='*55}")
    print("LOAD TEST RESULTS")
    print(f"{'='*55}")
    print(f"Duration:               {elapsed:.1f}s")
    print(f"Total attempts:         {total}")
    print(f"Successful allocations: {len(successful)}")
    print(f"No resource (expected): {len(no_res)}")
    print(f"  → no agent:           {no_res_counts.get(_ErrorKind.NO_AGENT, 0)}")
    print(f"  → no borrower:        {no_res_counts.get(_ErrorKind.NO_BORROWER, 0)}")
    print(f"Errors (unexpected):    {len(errors)}")
    if error_counts:
        for kind, count in error_counts.most_common():
            print(f"  → {kind:<18} {count}")
    print(f"Throughput:             {total / elapsed:.1f} attempts/sec")
    print(f"Success rate:           {len(successful)/total:.1%}" if total else "")

    if latencies:
        sorted_lat = sorted(latencies)
        print(f"\nLatency (ms):")
        print(f"  min:    {min(latencies):.1f}")
        print(f"  p50:    {statistics.median(latencies):.1f}")
        print(f"  p95:    {sorted_lat[int(len(sorted_lat)*0.95)]:.1f}")
        print(f"  p99:    {sorted_lat[int(len(sorted_lat)*0.99)]:.1f}")
        print(f"  max:    {max(latencies):.1f}")

    print(f"\nPostgreSQL active connections:")
    print(f"  before test:   {conn_before}")
    print(f"  during test:   {conn_during}")
    print(f"  after test:    {conn_after}")

    if error_counts.get(_ErrorKind.DB_CONN, 0) > 0:
        print("\n[WARNING] DB connection errors detected — pool may be under-sized or PostgreSQL max_connections too low.")
    elif len(errors) == 0:
        print("\n[OK] No unexpected errors.")

    # Cleanup
    Base.metadata.drop_all(_load_test_engine)
    _load_test_engine.dispose()
    reset_providers()


if __name__ == "__main__":
    main()
