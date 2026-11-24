from __future__ import annotations
import time
import pytest
from app.providers.circuit_breaker import CircuitBreaker
from app.core.enums import ProviderStatus


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == "CLOSED"
        assert cb.can_proceed()
        assert cb.health == ProviderStatus.HEALTHY

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, timeout_seconds=60)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "CLOSED"
        cb.record_failure()
        assert cb.state == "OPEN"
        assert not cb.can_proceed()
        assert cb.health == ProviderStatus.UNHEALTHY

    def test_success_resets(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        cb.record_success()
        assert cb.state == "CLOSED"
        assert cb.can_proceed()

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, timeout_seconds=0.01)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        time.sleep(0.05)
        assert cb.can_proceed()  # transitions to HALF_OPEN
        assert cb.state == "HALF_OPEN"
        assert cb.health == ProviderStatus.DEGRADED

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        cb.reset()
        assert cb.state == "CLOSED"
        assert cb.failure_count == 0
