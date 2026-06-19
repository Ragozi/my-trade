"""Tests for the pure market-hours / session guard.

June 2026 is EDT (UTC-4), so 13:30 UTC == 09:30 ET (open) and 20:00 UTC ==
16:00 ET (close). 2026-06-17 is a Wednesday; 2026-06-20 is a Saturday.
"""

from __future__ import annotations

from datetime import UTC, datetime

from my_trade.core.market_calendar import (
    is_equity_regular_session,
    make_session_guard,
)


def _utc(y: int, mo: int, d: int, h: int, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


class TestEquityRegularSession:
    def test_open_midsession(self) -> None:
        assert is_equity_regular_session(_utc(2026, 6, 17, 17, 0)) is True  # 13:00 ET

    def test_open_at_open_boundary(self) -> None:
        assert is_equity_regular_session(_utc(2026, 6, 17, 13, 30)) is True  # 09:30 ET

    def test_closed_before_open(self) -> None:
        assert is_equity_regular_session(_utc(2026, 6, 17, 13, 0)) is False  # 09:00 ET

    def test_closed_at_close_boundary(self) -> None:
        assert is_equity_regular_session(_utc(2026, 6, 17, 20, 0)) is False  # 16:00 ET

    def test_closed_on_weekend(self) -> None:
        assert is_equity_regular_session(_utc(2026, 6, 20, 17, 0)) is False  # Saturday

    def test_naive_datetime_assumed_utc(self) -> None:
        naive = datetime(2026, 6, 17, 17, 0)  # noqa: DTZ001 - intentional
        assert is_equity_regular_session(naive) is True


class TestSessionGuard:
    def test_crypto_always_open(self) -> None:
        guard = make_session_guard("crypto")
        assert guard(_utc(2026, 6, 20, 3, 0)) is True  # Saturday 3am -> still open

    def test_equities_uses_session(self) -> None:
        guard = make_session_guard("equities")
        assert guard(_utc(2026, 6, 17, 17, 0)) is True
        assert guard(_utc(2026, 6, 20, 17, 0)) is False
