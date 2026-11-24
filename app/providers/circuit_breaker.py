from __future__ import annotations
import time
import logging
from app.core.enums import ProviderStatus

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """
    Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED.

    CLOSED:    Normal operation, all requests allowed.
    OPEN:      Too many failures, requests rejected.
    HALF_OPEN: Timeout expired, one test request allowed.
    """

    def __init__(self, failure_threshold: int = 5, timeout_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count: int = 0
        self.last_failure_time: float | None = None
        self._state: str = "CLOSED"

    @property
    def state(self) -> str:
        return self._state

    def record_success(self) -> None:
        self.failure_count = 0
        if self._state != "CLOSED":
            logger.info("Circuit breaker closed after successful probe")
        self._state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold and self._state == "CLOSED":
            self._state = "OPEN"
            logger.warning(
                "Circuit breaker OPENED after %d failures", self.failure_count
            )

    def can_proceed(self) -> bool:
        if self._state == "CLOSED":
            return True
        if self._state == "OPEN":
            if (
                self.last_failure_time is not None
                and time.monotonic() - self.last_failure_time > self.timeout_seconds
            ):
                self._state = "HALF_OPEN"
                logger.info("Circuit breaker entering HALF_OPEN — allowing probe request")
                return True
            return False
        # HALF_OPEN: allow exactly one through
        return True

    def reset(self) -> None:
        self.failure_count = 0
        self.last_failure_time = None
        self._state = "CLOSED"

    @property
    def health(self) -> ProviderStatus:
        if self._state == "CLOSED":
            return ProviderStatus.HEALTHY
        if self._state == "HALF_OPEN":
            return ProviderStatus.DEGRADED
        return ProviderStatus.UNHEALTHY

    def __repr__(self) -> str:
        return (
            f"<CircuitBreaker state={self._state} "
            f"failures={self.failure_count}/{self.failure_threshold}>"
        )
