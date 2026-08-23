"""Circuit breaker (P4 §11): closed -> open on repeated failures; open -> half-open after a recovery
timeout; a half-open success closes it, a half-open failure re-opens it."""
from __future__ import annotations
import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0, clock=time.monotonic):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock
        self.state = "closed"
        self._failures = 0
        self._opened_at = 0.0

    def allow(self) -> bool:
        if self.state == "open":
            if self._clock() - self._opened_at >= self.recovery_timeout:
                self.state = "half_open"
                return True
            return False
        return True

    def on_success(self):
        self.state = "closed"
        self._failures = 0

    def on_failure(self):
        self._failures += 1
        if self.state == "half_open" or self._failures >= self.failure_threshold:
            self.state = "open"
            self._opened_at = self._clock()
