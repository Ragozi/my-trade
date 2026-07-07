"""Tests for the deterministic screening / universe-selection layer.

Covers the pure metric math, the filter/rank policy, universe sources, the
Screener orchestrator (incl. refresh caching + fail-safe skipping), and the
orchestrator's dynamic-watchlist hook (incl. fail-safe fallback to static).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from my_trade.core.monitoring import (
    AccountSnapshot,
    ActionKind,
    DailyStateStore,
    TradingOrchestrator,
)
from my_trade.core.risk import AccountState, RiskLimits
from my_trade.core.screening import (
    DEFAULT_CRYPTO_UNIVERSE,
    Candidate,
    Screener,
    ScreenerCriteria,
    StaticUniverseSource,
    atr_pct,
    avg_dollar_volume,
    build_candidate,
    change_pct,
    passes,
    rank,
    select_watchlist,
)
from my_trade.core.strategy import ScanEvaluation, Signal

NOW = datetime(2026, 6, 18, 14, 0, tzinfo=UTC)


def make_frame(
    n: int = 16,
    *,
    close: float = 100.0,
    spread: float = 2.0,
    volume: float = 10.0,
) -> pd.DataFrame:
    """A flat OHLCV frame: each bar high/low = close +/- spread/2, constant volume.

    With a flat close, every true range equals ``spread``, so ATR is exactly
    ``spread`` and atr_pct == spread / close — handy for exact assertions.
    """
    idx = pd.date_range(end=NOW, periods=n, freq="15min")
    return pd.DataFrame(
        {
            "open": [close] * n,
            "high": [close + spread / 2] * n,
            "low": [close - spread / 2] * n,
            "close": [close] * n,
            "volume": [volume] * n,
        },
        index=idx,
    )


def candidate(
    symbol: str, *, atr: float, dv: float, price: float = 100.0, bars: int = 30
) -> Candidate:
    return Candidate(
        symbol=symbol,
        last_price=price,
        dollar_volume=dv,
        atr_pct=atr,
        change_pct=0.0,
        bars=bars,
    )


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
class TestMetrics:
    def test_atr_pct_flat_series(self) -> None:
        df = make_frame(close=100.0, spread=2.0)
        assert atr_pct(df, 14) == 2.0 / 100.0

    def test_atr_pct_none_when_too_few_bars(self) -> None:
        assert atr_pct(make_frame(n=10), 14) is None

    def test_avg_dollar_volume(self) -> None:
        df = make_frame(close=100.0, volume=10.0)
        assert avg_dollar_volume(df, 20) == 1000.0

    def test_change_pct(self) -> None:
        df = make_frame(close=100.0)
        df = df.copy()
        df.iloc[-1, df.columns.get_loc("close")] = 110.0
        # last close 110 vs close 'lookback' bars ago (100)
        assert change_pct(df, 5) == (110.0 - 100.0) / 100.0

    def test_build_candidate_happy(self) -> None:
        cand = build_candidate("BTC/USD", make_frame(), atr_period=14, lookback=20)
        assert cand is not None
        assert cand.symbol == "BTC/USD"
        assert cand.atr_pct == 0.02
        assert cand.dollar_volume == 1000.0
        assert cand.bars == 16

    def test_build_candidate_none_on_empty(self) -> None:
        assert build_candidate("X", pd.DataFrame(), atr_period=14) is None

    def test_build_candidate_none_on_insufficient(self) -> None:
        assert build_candidate("X", make_frame(n=5), atr_period=14) is None


# --------------------------------------------------------------------------- #
# Filters / ranking
# --------------------------------------------------------------------------- #
class TestFilters:
    def test_passes_all_gates(self) -> None:
        crit = ScreenerCriteria(
            min_price=10, max_price=200, min_dollar_volume=500,
            min_atr_pct=0.01, max_atr_pct=0.10, min_bars=20,
        )
        assert passes(candidate("A", atr=0.02, dv=1000), crit) is True

    def test_rejects_low_liquidity(self) -> None:
        crit = ScreenerCriteria(min_dollar_volume=2000)
        assert passes(candidate("A", atr=0.02, dv=1000), crit) is False

    def test_rejects_price_band(self) -> None:
        crit = ScreenerCriteria(min_price=50, max_price=80)
        assert passes(candidate("A", atr=0.02, dv=1000, price=100.0), crit) is False

    def test_rejects_volatility_band(self) -> None:
        crit = ScreenerCriteria(min_atr_pct=0.05)
        assert passes(candidate("A", atr=0.02, dv=1000), crit) is False

    def test_rejects_insufficient_bars(self) -> None:
        crit = ScreenerCriteria(min_bars=40)
        assert passes(candidate("A", atr=0.02, dv=1000, bars=30), crit) is False

    def test_rank_orders_by_score_and_caps_top_n(self) -> None:
        crit = ScreenerCriteria(top_n=2, weight_volatility=1.0, weight_liquidity=1.0)
        cands = [
            candidate("LOW", atr=0.01, dv=100),
            candidate("HIGH", atr=0.05, dv=10_000),
            candidate("MID", atr=0.03, dv=5_000),
        ]
        ranked = rank(cands, crit)
        assert [c.symbol for c in ranked] == ["HIGH", "MID"]
        assert ranked[0].score >= ranked[1].score

    def test_rank_ties_break_on_symbol(self) -> None:
        # Equal liquidity -> normalized 0; equal atr -> equal score -> sort by symbol.
        crit = ScreenerCriteria(top_n=3)
        cands = [candidate(s, atr=0.02, dv=1000) for s in ("C", "A", "B")]
        assert [c.symbol for c in rank(cands, crit)] == ["A", "B", "C"]

    def test_rank_empty_when_none_pass(self) -> None:
        crit = ScreenerCriteria(min_dollar_volume=1e9)
        assert rank([candidate("A", atr=0.02, dv=1000)], crit) == []

    def test_select_watchlist_returns_symbols(self) -> None:
        crit = ScreenerCriteria(top_n=2)
        cands = [
            candidate("A", atr=0.05, dv=10_000),
            candidate("B", atr=0.01, dv=100),
        ]
        assert select_watchlist(cands, crit) == ("A", "B")


class TestCriteriaValidation:
    def test_rejects_bad_values(self) -> None:
        for bad in (
            {"min_price": -1.0},
            {"max_price": 1.0, "min_price": 2.0},
            {"min_dollar_volume": -1.0},
            {"min_atr_pct": -0.1},
            {"max_atr_pct": 0.01, "min_atr_pct": 0.5},
            {"min_bars": 0},
            {"top_n": 0},
            {"weight_volatility": -1.0},
        ):
            try:
                ScreenerCriteria(**bad).validate()  # type: ignore[arg-type]
            except ValueError:
                continue
            raise AssertionError(f"expected ValueError for {bad}")


# --------------------------------------------------------------------------- #
# Universe sources
# --------------------------------------------------------------------------- #
class TestUniverse:
    def test_static_dedups_and_preserves_order(self) -> None:
        src = StaticUniverseSource([" BTC/USD ", "eth/usd", "BTC/USD", "ETH/USD", ""])
        assert list(src.symbols()) == ["BTC/USD", "eth/usd"]

    def test_default_crypto_universe_nonempty(self) -> None:
        assert "BTC/USD" in DEFAULT_CRYPTO_UNIVERSE
        assert len(DEFAULT_CRYPTO_UNIVERSE) >= 3


# --------------------------------------------------------------------------- #
# Screener orchestrator
# --------------------------------------------------------------------------- #
class FakeCountingData:
    """MarketDataProvider that serves per-symbol frames and counts calls."""

    def __init__(self, frames: dict[str, pd.DataFrame], *, raise_for: str | None = None) -> None:
        self._frames = frames
        self._raise_for = raise_for
        self.calls = 0

    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
        self.calls += 1
        if symbol == self._raise_for:
            raise RuntimeError("boom")
        return self._frames.get(symbol, pd.DataFrame())

    def get_latest_price(self, symbol: str) -> float | None:  # pragma: no cover - unused
        return None


class TestScreener:
    def _screener(
        self, data: FakeCountingData, *, clock_value: list[datetime], **kw: object
    ) -> Screener:
        crit = ScreenerCriteria(top_n=int(kw.pop("top_n", 5)), min_bars=10)
        return Screener(
            data=data,  # type: ignore[arg-type]
            universe=StaticUniverseSource(["AAA", "BBB", "CCC"]),
            criteria=crit,
            refresh_seconds=int(kw.pop("refresh_seconds", 100)),
            clock=lambda: clock_value[0],
        )

    def test_screen_ranks_candidates(self) -> None:
        frames = {
            "AAA": make_frame(close=100.0, spread=1.0, volume=10.0),   # atr 1%
            "BBB": make_frame(close=100.0, spread=4.0, volume=50.0),   # atr 4%, big dv
            "CCC": make_frame(close=100.0, spread=2.0, volume=10.0),   # atr 2%
        }
        data = FakeCountingData(frames)
        clock = [NOW]
        screener = self._screener(data, clock_value=clock)
        ranked = screener.screen()
        assert ranked[0].symbol == "BBB"  # highest volatility AND liquidity
        assert {c.symbol for c in ranked} == {"AAA", "BBB", "CCC"}

    def test_select_caches_until_stale(self) -> None:
        frames = {s: make_frame() for s in ("AAA", "BBB", "CCC")}
        data = FakeCountingData(frames)
        clock = [NOW]
        screener = self._screener(data, clock_value=clock, refresh_seconds=100)

        first = screener.select()
        calls_after_first = data.calls
        assert calls_after_first == 3  # one screen pass over the universe

        # Within the refresh window: cached, no new data calls.
        clock[0] = NOW + timedelta(seconds=50)
        assert screener.select() == first
        assert data.calls == calls_after_first

        # Past the refresh window: re-screens.
        clock[0] = NOW + timedelta(seconds=150)
        screener.select()
        assert data.calls == calls_after_first + 3

    def test_failsafe_skips_bad_symbol(self) -> None:
        frames = {"AAA": make_frame(), "CCC": make_frame()}
        data = FakeCountingData(frames, raise_for="BBB")
        clock = [NOW]
        screener = self._screener(data, clock_value=clock)
        ranked = screener.screen()
        symbols = {c.symbol for c in ranked}
        assert "BBB" not in symbols
        assert symbols == {"AAA", "CCC"}


# --------------------------------------------------------------------------- #
# Orchestrator dynamic-watchlist hook
# --------------------------------------------------------------------------- #
class _OrchData:
    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
        return pd.DataFrame()

    def get_latest_price(self, symbol: str) -> float | None:  # pragma: no cover
        return None


class _OrchStrategy:
    def __init__(self) -> None:
        self.scanned: list[str] = []

    def detect_entry(
        self, symbol: str, df_1m: pd.DataFrame, df_5m: pd.DataFrame,
        df_15m: pd.DataFrame, now: datetime | None = None,
    ) -> tuple[Signal | None, ScanEvaluation]:
        self.scanned.append(symbol)
        return None, ScanEvaluation(eligible=False, summary="x", near_signal=False)

    def detect_exit(
        self, df_1m: pd.DataFrame, entry_time: datetime, entry_price: float, now: datetime,
    ) -> str | None:  # pragma: no cover - no positions in these tests
        return None


class _OrchExec:
    def execute_entry(self, intent: object, account: AccountState, *, now: datetime | None = None):  # type: ignore[no-untyped-def]
        raise AssertionError("no entry expected")

    def close_position(self, symbol: str, *, now: datetime | None = None):  # type: ignore[no-untyped-def]
        raise AssertionError("no close expected")


def _orchestrator(
    tmp_path: Path, strategy: _OrchStrategy, watchlist: object
) -> TradingOrchestrator:
    snap = AccountSnapshot(equity=12_000.0, cash=12_000.0, last_equity=12_000.0, positions=())
    return TradingOrchestrator(
        data=_OrchData(),  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        execution=_OrchExec(),  # type: ignore[arg-type]
        account=_FixedAccount(snap),  # type: ignore[arg-type]
        store=DailyStateStore(tmp_path / "s.json"),
        limits=RiskLimits(
            max_risk_per_trade_pct=0.02, max_total_open_risk_pct=0.07,
            daily_loss_limit_pct=0.05, max_drawdown_pct=0.15, max_concurrent_positions=1,
        ),
        symbols=("BTC/USD",),
        watchlist=watchlist,  # type: ignore[arg-type]
        clock=lambda: NOW,
    )


class _FixedAccount:
    def __init__(self, snap: AccountSnapshot) -> None:
        self._snap = snap

    def get_snapshot(self) -> AccountSnapshot:
        return self._snap


class TestOrchestratorWatchlist:
    def test_uses_dynamic_watchlist(self, tmp_path: Path) -> None:
        strategy = _OrchStrategy()
        orch = _orchestrator(tmp_path, strategy, lambda: ("ETH/USD", "SOL/USD"))
        orch.run_cycle(NOW)
        assert strategy.scanned == ["ETH/USD", "SOL/USD"]  # not the static BTC/USD

    def test_failsafe_falls_back_to_static(self, tmp_path: Path) -> None:
        strategy = _OrchStrategy()

        def boom() -> list[str]:
            raise RuntimeError("screener down")

        orch = _orchestrator(tmp_path, strategy, boom)
        orch.run_cycle(NOW)
        assert strategy.scanned == ["BTC/USD"]  # fell back to configured symbols

    def test_empty_watchlist_falls_back_to_static_symbols(self, tmp_path: Path) -> None:
        strategy = _OrchStrategy()
        orch = _orchestrator(tmp_path, strategy, lambda: [])
        result = orch.run_cycle(NOW)
        assert strategy.scanned == ["BTC/USD"]
        assert any(a.kind is ActionKind.NO_SIGNAL for a in result.actions)
