"""Tests for the pure market-hours / session guard.

June 2026 is EDT (UTC-4), so 13:30 UTC == 09:30 ET (open) and 20:00 UTC ==
16:00 ET (close). 2026-06-17 is a Wednesday; 2026-06-20 is a Saturday.
"""

from __future__ import annotations

from datetime import UTC, datetime

from my_trade.core.market_calendar import (
    is_am_momentum_window,
    is_equity_regular_session,
    is_equity_research_window,
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


class TestAmMomentumWindow:
    def test_premarket_warmup(self) -> None:
        # 12:30 UTC = 08:30 ET — one hour before cash open
        assert is_am_momentum_window(_utc(2026, 6, 17, 12, 30)) is True

    def test_inside_opening_range(self) -> None:
        # 14:00 UTC = 10:00 ET on a Wednesday
        assert is_am_momentum_window(_utc(2026, 6, 17, 14, 0)) is True

    def test_after_opening_range(self) -> None:
        # 16:00 UTC = 12:00 ET
        assert is_am_momentum_window(_utc(2026, 6, 17, 16, 0)) is False


class TestResearchWindow:
    def test_premarket_allowed(self) -> None:
        assert is_equity_research_window(_utc(2026, 6, 17, 12, 30)) is True  # 08:30 ET
        assert is_equity_regular_session(_utc(2026, 6, 17, 12, 30)) is False

    def test_cash_session_allowed(self) -> None:
        assert is_equity_research_window(_utc(2026, 6, 17, 17, 0)) is True  # 13:00 ET

    def test_overnight_blocked(self) -> None:
        assert is_equity_research_window(_utc(2026, 6, 17, 11, 0)) is False  # 07:00 ET


class TestSessionGuard:
    def test_crypto_always_open(self) -> None:
        guard = make_session_guard("crypto")
        assert guard(_utc(2026, 6, 20, 3, 0)) is True  # Saturday 3am -> still open

    def test_equities_uses_session(self) -> None:
        guard = make_session_guard("equities")
        assert guard(_utc(2026, 6, 17, 17, 0)) is True
        assert guard(_utc(2026, 6, 20, 17, 0)) is False
