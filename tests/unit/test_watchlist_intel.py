"""Tests for watchlist research context."""

from __future__ import annotations

from my_trade.api.watchlist_intel import (
    build_watchlist_intel,
    latest_proposals_by_symbol,
    parse_proposal_detail,
)
from my_trade.observability.journal import JournalEvent


class TestWatchlistIntel:
    def test_parse_proposal_detail(self) -> None:
        detail = "[openai] hold conf=0.72 shares swing: Earnings volatility ahead."
        parsed = parse_proposal_detail(detail)
        assert parsed is not None
        assert parsed["action"] == "hold"
        assert parsed["confidence"] == 0.72
        assert parsed["thesis"] == "Earnings volatility ahead."

    def test_latest_proposal_per_symbol(self) -> None:
        events = [
            JournalEvent(
                "2026-06-29T13:00:00",
                "research_proposal",
                "AAPL",
                "[openai] avoid conf=0.80 shares swing: Skip ahead of earnings.",
                15000.0,
                0.0,
            ),
            JournalEvent(
                "2026-06-29T12:00:00",
                "research_proposal",
                "AAPL",
                "[openai] hold conf=0.55 shares swing: Old read.",
                15000.0,
                0.0,
            ),
        ]
        latest = latest_proposals_by_symbol(events)
        assert latest["AAPL"]["action"] == "avoid"

    def test_build_watchlist_intel_static(self) -> None:
        rows = build_watchlist_intel(
            ["AAPL"],
            universe_source="static_config",
            thesis_cache={"AAPL": "Resilience into earnings."},
            proposals={
                "AAPL": {
                    "action": "hold",
                    "confidence": 0.7,
                    "instrument": "shares",
                    "time_horizon": "swing",
                    "thesis": "Resilience into earnings.",
                    "provider": "openai",
                    "updated_at": "2026-06-29T13:00:00",
                }
            },
            lessons={"AAPL": "Prior loss on broker stop."},
        )
        assert rows[0]["symbol"] == "AAPL"
        assert "EQUITY_SYMBOLS" in rows[0]["why_watch"]
        assert rows[0]["action"] == "hold"
        assert rows[0]["recent_lesson"] == "Prior loss on broker stop."
