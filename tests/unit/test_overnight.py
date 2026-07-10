"""Tests for overnight / premarket gap study helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from my_trade.research.overnight import gather_overnight_moves, overnight_snapshot
from my_trade.research.prompts import SYSTEM_PROMPT, build_user_prompt
from my_trade.research.context import build_research_context
from my_trade.core.monitoring.account import AccountSnapshot


def test_overnight_snapshot_labels() -> None:
    up = overnight_snapshot(symbol="aaa", last_price=10.5, prior_close=10.0)
    assert up["gap_label"] == "gap_up"
    assert up["gap_pct"] == 0.05

    down = overnight_snapshot(symbol="bbb", last_price=9.5, prior_close=10.0)
    assert down["gap_label"] == "gap_down"

    flat = overnight_snapshot(symbol="ccc", last_price=10.1, prior_close=10.0)
    assert flat["gap_label"] == "flat_overnight"


def test_gather_overnight_moves_from_bars() -> None:
    daily = pd.DataFrame(
        {"close": [20.0]},
        index=pd.DatetimeIndex(["2026-07-07"]),
    )
    intraday = pd.DataFrame(
        {"close": [22.0]},
        index=pd.DatetimeIndex(["2026-07-08 13:00"], tz="UTC"),
    )

    def get_bars(symbol: str, timeframe: str, limit: int | None = None):
        if timeframe == "1Day":
            return daily
        return intraday

    rows = gather_overnight_moves(
        symbols=("XYZ",),
        get_bars=get_bars,
        as_of=datetime(2026, 7, 8, 13, 0, tzinfo=UTC),
    )
    assert len(rows) == 1
    assert rows[0]["symbol"] == "XYZ"
    assert rows[0]["prior_close"] == 20.0
    assert rows[0]["gap_pct"] == 0.1
    assert rows[0]["gap_label"] == "gap_up"


def test_gather_uses_ranked_meta_when_present() -> None:
    def get_bars(symbol: str, timeframe: str, limit: int | None = None):
        raise AssertionError("should not fetch when meta is complete")

    rows = gather_overnight_moves(
        symbols=("MARA",),
        get_bars=get_bars,
        as_of=datetime(2026, 7, 8, 13, 0, tzinfo=UTC),
        ranked_meta={
            "MARA": {
                "last_price": 12.0,
                "prior_close": 10.0,
                "change_pct": 0.05,
                "dollar_volume": 1_000_000.0,
            }
        },
    )
    assert rows[0]["gap_pct"] == 0.2
    assert rows[0]["intraday_change_pct"] == 0.05


def test_prompt_includes_overnight_moves() -> None:
    assert "overnight_moves" in SYSTEM_PROMPT
    ctx = build_research_context(
        snapshot=AccountSnapshot(equity=15_000.0),
        candidate_symbols=("MARA",),
        asset_class="equities",
        session_open=False,
        as_of=datetime(2026, 7, 8, 13, 0, tzinfo=UTC),
        equity=15_000.0,
        day_pnl=0.0,
        peak_equity=15_000.0,
        overnight_moves=(
            {
                "symbol": "MARA",
                "last_price": 12.0,
                "prior_close": 10.0,
                "gap_pct": 0.2,
                "gap_label": "gap_up",
            },
        ),
    )
    prompt = build_user_prompt(ctx, max_ideas=2)
    assert "overnight_moves" in prompt
    assert "gap_up" in prompt
    assert "MARA" in prompt
