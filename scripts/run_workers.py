#!/usr/bin/env python3
"""
Run all background workers in a single process (dev convenience).
Production would run these as separate processes/containers.

Usage:
    python scripts/run_workers.py --campaign-id <uuid>
"""
from __future__ import annotations
import sys
import os
import argparse
import threading
import time
import signal
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_db, create_all_tables
from app.workers.dial_worker import DialWorker
from app.workers.event_worker import EventWorker
from app.workers.recovery_worker import RecoveryWorker
from app.providers.provider_factory import initialize_default_providers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("run_workers")

shutdown_event = threading.Event()


def run_dial_worker(campaign_id: str, interval: float = 1.0):
    logger.info("Dial worker starting")
    db = next(get_db())
    worker = DialWorker()
    while not shutdown_event.is_set():
        try:
            worker.tick(db, campaign_id)
            db.commit()
        except Exception as e:
            logger.error(f"Dial worker error: {e}")
            db.rollback()
        time.sleep(interval)
    db.close()
    logger.info("Dial worker stopped")


def run_event_worker(interval: float = 0.5):
    logger.info("Event worker starting")
    db = next(get_db())
    worker = EventWorker()
    while not shutdown_event.is_set():
        try:
            worker.tick(db)
            db.commit()
        except Exception as e:
            logger.error(f"Event worker error: {e}")
            db.rollback()
        time.sleep(interval)
    db.close()
    logger.info("Event worker stopped")


def run_recovery_worker(interval: float = 10.0):
    logger.info("Recovery worker starting")
    db = next(get_db())
    worker = RecoveryWorker()
    while not shutdown_event.is_set():
        try:
            worker.tick(db)
            db.commit()
        except Exception as e:
            logger.error(f"Recovery worker error: {e}")
            db.rollback()
        time.sleep(interval)
    db.close()
    logger.info("Recovery worker stopped")


def signal_handler(sig, frame):
    logger.info("Shutdown signal received")
    shutdown_event.set()


def main():
    p = argparse.ArgumentParser(description="Run SmartDialer workers")
    p.add_argument("--campaign-id", required=True)
    args = p.parse_args()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    create_all_tables()
    initialize_default_providers()

    threads = [
        threading.Thread(target=run_dial_worker, args=(args.campaign_id,), daemon=True),
        threading.Thread(target=run_event_worker, daemon=True),
        threading.Thread(target=run_recovery_worker, daemon=True),
    ]

    for t in threads:
        t.start()

    logger.info(f"All workers started for campaign {args.campaign_id}")
    logger.info("Press Ctrl+C to stop")

    while not shutdown_event.is_set():
        time.sleep(1)

    for t in threads:
        t.join(timeout=5)

    logger.info("All workers stopped")


if __name__ == "__main__":
    main()
