from __future__ import annotations
import logging
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.services.reconciliation_service import ReconciliationService, ReconciliationResult

logger = logging.getLogger(__name__)


@dataclass
class RecoveryResult:
    agents_recovered: int = 0
    borrowers_recovered: int = 0
    calls_cancelled: int = 0
    calls_failed: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class RecoveryWorker:
    """
    Periodically scans for stale state and reconciles.

    Handles:
    - Agents stuck in RESERVED with expired leases
    - Borrowers stuck in RESERVED with no active call
    - Calls stuck in INITIATED/RESERVED from worker crashes
    """

    def run(self, db: Session) -> RecoveryResult:
        reconciler = ReconciliationService()
        result = RecoveryResult()

        try:
            result.agents_recovered = reconciler.reconcile_stale_agents(db)
        except Exception as exc:
            logger.error("Agent reconciliation error: %s", exc)
            result.errors.append(f"agents: {exc}")

        try:
            result.borrowers_recovered = reconciler.reconcile_stale_borrowers(db)
        except Exception as exc:
            logger.error("Borrower reconciliation error: %s", exc)
            result.errors.append(f"borrowers: {exc}")

        try:
            call_result: ReconciliationResult = reconciler.reconcile_stale_calls(db)
            result.calls_cancelled = call_result.calls_cancelled
            result.calls_failed = call_result.calls_queried_provider
            result.errors.extend(call_result.errors)
        except Exception as exc:
            logger.error("Call reconciliation error: %s", exc)
            result.errors.append(f"calls: {exc}")

        try:
            db.commit()
        except Exception as exc:
            logger.error("Recovery worker commit failed: %s", exc)
            db.rollback()
            result.errors.append(f"commit: {exc}")

        if result.agents_recovered or result.borrowers_recovered or result.calls_cancelled:
            logger.info(
                "Recovery: agents=%d borrowers=%d calls_cancelled=%d calls_failed=%d",
                result.agents_recovered,
                result.borrowers_recovered,
                result.calls_cancelled,
                result.calls_failed,
            )

        return result
