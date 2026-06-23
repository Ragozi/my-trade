"""In-memory rate limiter for Claude research calls (deterministic, testable)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime


@dataclass
class RateLimitState:
    last_call_at: datetime | None = None
    calls_today: int = 0
    trading_day: date = field(default_factory=lambda: datetime.now(UTC).date())
    cooldown_until: datetime | None = None


class ResearchRateLimiter:
    """Enforces min interval between calls and a daily call budget."""

    def __init__(
        self,
        *,
        min_interval_seconds: int = 300,
        max_calls_per_day: int = 100,
    ) -> None:
        self._min_interval = max(min_interval_seconds, 0)
        self._max_calls = max(max_calls_per_day, 1)
        self._state = RateLimitState()

    @property
    def state(self) -> RateLimitState:
        return self._state

    def _roll_day(self, when: datetime) -> None:
        today = when.astimezone(UTC).date()
        if self._state.trading_day != today:
            self._state = RateLimitState(trading_day=today)

    def seconds_until_allowed(self, when: datetime) -> float:
        """Seconds until the next call is allowed (0 if ready now)."""
        self._roll_day(when)
        if self._state.calls_today >= self._max_calls:
            return float("inf")
        if self._state.cooldown_until is not None and when < self._state.cooldown_until:
            return (self._state.cooldown_until - when).total_seconds()
        if self._state.last_call_at is None:
            return 0.0
        elapsed = (when - self._state.last_call_at).total_seconds()
        remaining = self._min_interval - elapsed
        return max(0.0, remaining)

    def can_call(self, when: datetime) -> bool:
        return self.seconds_until_allowed(when) == 0.0

    def record_call(self, when: datetime) -> None:
        """Record a completed API attempt (success or failure) against limits."""
        self._roll_day(when)
        self._state.last_call_at = when
        self._state.calls_today += 1

    def record_billing_failure(self, when: datetime, *, cooldown_seconds: int = 3600) -> None:
        """After billing/credit errors, enforce a longer quiet period."""
        from datetime import timedelta

        self.record_call(when)
        self._state.cooldown_until = when + timedelta(seconds=max(cooldown_seconds, 0))

    def skip_reason(self, when: datetime) -> str:
        self._roll_day(when)
        if self._state.calls_today >= self._max_calls:
            return f"daily budget exhausted ({self._max_calls} calls)"
        if self._state.cooldown_until is not None and when < self._state.cooldown_until:
            wait = (self._state.cooldown_until - when).total_seconds()
            return f"billing cooldown ({wait:.0f}s remaining)"
        wait = self.seconds_until_allowed(when)
        if wait == float("inf"):
            return "daily budget exhausted"
        if wait > 0:
            return f"rate limited ({wait:.0f}s until next call)"
        return ""
