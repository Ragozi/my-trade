"""Tests for the monitoring/orchestration layer.

Focus: pure daily-state transitions, the risk-engine bridge, JSON persistence,
and orchestration decisions (halts, entries, exits, limits, restart-safety).
Trading math (indicators/risk) is already tested elsewhere and is faked here.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from my_trade.core.execution import (
    BrokerError,
    EntryIntent,
    ExecutionAdapter,
    ExecutionOutcome,
    ExecutionStatus,
    OrderRequest,
    OrderResult,
    OrderStatus,
)
from my_trade.core.monitoring import (
    AccountSnapshot,
    ActionKind,
    DailyState,
    DailyStateStore,
    HaltReason,
    Position,
    TradingOrchestrator,
    build_account_state,
    clear_position,
    record_entry,
    rollover_if_new_day,
    update_peak,
)
from my_trade.core.monitoring.state import entry_time_for
from my_trade.core.risk import AccountState, RiskLimits
from my_trade.core.strategy import OrderSide, ScanEvaluation, Signal
from my_trade.data import normalize_symbol

NOW = datetime(2026, 6, 18, 14, 7, tzinfo=UTC)
TODAY = NOW.date()
SYMBOL = "BTC/USD"
KEY = normalize_symbol(SYMBOL)


def limits(**overrides: float | int) -> RiskLimits:
    base: dict[str, float | int] = {
        "max_risk_per_trade_pct": 0.02,
        "max_total_open_risk_pct": 0.07,
        "daily_loss_limit_pct": 0.05,
        "max_drawdown_pct": 0.15,
        "max_concurrent_positions": 1,
    }
    base.update(overrides)
    return RiskLimits(**base)  # type: ignore[arg-type]


def signal(**overrides: object) -> Signal:
    base: dict[str, object] = {
        "symbol": SYMBOL,
        "side": OrderSide.BUY,
        "entry_price": 100_000.0,
        "stop_price": 99_350.0,
        "take_profit_price": 101_700.0,
        "confidence": 0.6,
    }
    base.update(overrides)
    return Signal(**base)  # type: ignore[arg-type]


def snapshot(equity: float = 12_000.0, positions: tuple[Position, ...] = ()) -> AccountSnapshot:
    return AccountSnapshot(equity=equity, cash=equity, last_equity=equity, positions=positions)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class FakeData:
    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
        return pd.DataFrame()

    def get_latest_price(self, symbol: str) -> float | None:
        return None


class FakeStrategy:
    def __init__(
        self, entry: Signal | None = None, exit_reason: str | None = None
    ) -> None:
        self._entry = entry
        self._exit_reason = exit_reason
        self.entry_calls = 0
        self.exit_calls = 0

    def detect_entry(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        now: datetime | None = None,
    ) -> tuple[Signal | None, ScanEvaluation]:
        self.entry_calls += 1
        evaluation = ScanEvaluation(
            eligible=self._entry is not None, summary="fake", near_signal=False
        )
        return self._entry, evaluation

    def detect_exit(
        self,
        df_1m: pd.DataFrame,
        entry_time: datetime,
        entry_price: float,
        now: datetime,
    ) -> str | None:
        self.exit_calls += 1
        return self._exit_reason


class FakeExecutor:
    def __init__(self, submitted: bool = True) -> None:
        self._submitted = submitted
        self.entries: list[EntryIntent] = []
        self.closes: list[str] = []

    def execute_entry(
        self, intent: EntryIntent, account: AccountState, *, now: datetime | None = None
    ) -> ExecutionOutcome:
        self.entries.append(intent)
        status = ExecutionStatus.SUBMITTED if self._submitted else ExecutionStatus.RISK_REJECTED
        return ExecutionOutcome(
            status=status,
            client_order_id="cid",
            submitted=self._submitted,
            detail="" if self._submitted else "risk rejected: max_positions",
        )

    def close_position(self, symbol: str, *, now: datetime | None = None) -> ExecutionOutcome:
        self.closes.append(symbol)
        return ExecutionOutcome(
            status=ExecutionStatus.SUBMITTED, client_order_id="cid", submitted=True
        )


class FakeAccount:
    def __init__(self, snap: AccountSnapshot) -> None:
        self._snap = snap

    def get_snapshot(self) -> AccountSnapshot:
        return self._snap


class RecordingBroker:
    """Minimal real BrokerClient for end-to-end risk-gate tests."""

    def __init__(self) -> None:
        self.submitted: list[OrderRequest] = []

    def submit_order(self, request: OrderRequest) -> OrderResult:
        self.submitted.append(request)
        return OrderResult(client_order_id=request.client_order_id, status=OrderStatus.ACCEPTED)

    def get_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        return None

    def cancel_order(self, order_id: str) -> None:  # pragma: no cover - unused
        pass

    def list_open_orders(self) -> list[OrderResult]:  # pragma: no cover - unused
        return []

    def close_position(self, symbol: str) -> OrderResult:  # pragma: no cover - unused
        raise BrokerError("not used")


def make_orchestrator(
    tmp_path: Path,
    *,
    snap: AccountSnapshot,
    strategy: FakeStrategy | None = None,
    executor: object | None = None,
    risk_limits: RiskLimits | None = None,
    max_entries: int = 10,
) -> TradingOrchestrator:
    return TradingOrchestrator(
        data=FakeData(),  # type: ignore[arg-type]
        strategy=strategy or FakeStrategy(),
        execution=executor or FakeExecutor(),  # type: ignore[arg-type]
        account=FakeAccount(snap),  # type: ignore[arg-type]
        store=DailyStateStore(tmp_path / "daily_state.json"),
        limits=risk_limits or limits(),
        symbols=(SYMBOL,),
        max_entries_per_symbol_per_day=max_entries,
        fallback_stop_pct=0.0065,
        clock=lambda: NOW,
    )


# --------------------------------------------------------------------------- #
# Pure daily-state transitions
# --------------------------------------------------------------------------- #
class TestDailyState:
    def test_rollover_resets_on_new_day(self) -> None:
        prev = DailyState(
            trading_day=date(2026, 6, 17),
            start_of_day_equity=11_000.0,
            peak_equity=13_000.0,
            entries_today={KEY: 5},
        )
        rolled = rollover_if_new_day(prev, TODAY, 12_000.0)
        assert rolled.trading_day == TODAY
        assert rolled.start_of_day_equity == 12_000.0
        assert rolled.peak_equity == 13_000.0  # lifetime high-water mark carried
        assert rolled.entries_today == {}

    def test_rollover_noop_same_day(self) -> None:
        state = DailyState(trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0)
        assert rollover_if_new_day(state, TODAY, 9_999.0) is state

    def test_update_peak(self) -> None:
        state = DailyState(trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0)
        assert update_peak(state, 11_000.0) is state
        assert update_peak(state, 12_500.0).peak_equity == 12_500.0

    def test_record_and_clear_position(self) -> None:
        state = DailyState.empty()
        state = record_entry(state, SYMBOL, 99_000.0, NOW)
        assert state.entries_for(SYMBOL) == 1
        assert state.position_stops[KEY] == 99_000.0
        assert entry_time_for(state, SYMBOL) == NOW

        state = record_entry(state, SYMBOL, 98_500.0, NOW)
        assert state.entries_for(SYMBOL) == 2

        state = clear_position(state, SYMBOL)
        assert KEY not in state.position_stops
        assert entry_time_for(state, SYMBOL) is None
        assert state.entries_for(SYMBOL) == 2  # count is NOT cleared


class TestBuildAccountState:
    def test_uses_recorded_stop_for_open_risk(self) -> None:
        state = DailyState(
            trading_day=TODAY,
            start_of_day_equity=11_800.0,
            peak_equity=12_500.0,
            position_stops={KEY: 99_000.0},
        )
        snap = snapshot(
            equity=12_000.0,
            positions=(Position(SYMBOL, qty=0.5, avg_entry_price=100_000.0),),
        )
        acct = build_account_state(snap, state, fallback_stop_pct=0.0065)
        assert acct.realized_day_pnl == 200.0
        assert acct.peak_equity == 12_500.0
        assert acct.open_positions == 1
        assert acct.open_risk_dollars == (100_000.0 - 99_000.0) * 0.5

    def test_falls_back_to_pct_stop_when_unknown(self) -> None:
        state = DailyState(trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0)
        snap = snapshot(
            equity=12_000.0,
            positions=(Position(SYMBOL, qty=0.5, avg_entry_price=100_000.0),),
        )
        acct = build_account_state(snap, state, fallback_stop_pct=0.0065)
        expected_stop = 100_000.0 * (1 - 0.0065)
        assert acct.open_risk_dollars == (100_000.0 - expected_stop) * 0.5

    def test_trading_capital_scales_equity_and_pnl(self) -> None:
        state = DailyState(
            trading_day=TODAY,
            start_of_day_equity=15_000.0,
            peak_equity=15_000.0,
            broker_sod_equity=94_868.0,
        )
        snap = snapshot(equity=93_868.0)  # -$1000 broker day
        acct = build_account_state(
            snap, state, fallback_stop_pct=0.0065, trading_capital=15_000.0
        )
        assert acct.equity == pytest.approx(15_000.0 - 1000 * (15_000 / 94_868))
        assert acct.start_of_day_equity == 15_000.0
        assert acct.realized_day_pnl == pytest.approx(acct.equity - 15_000.0)

    def test_trading_capital_rescales_stale_broker_peak(self) -> None:
        """Broker-era peak (~105k) must not trip R4 on a 15k virtual account."""
        state = DailyState(
            trading_day=TODAY,
            start_of_day_equity=15_000.0,
            peak_equity=105_263.48,
            broker_sod_equity=94_860.32,
        )
        snap = snapshot(equity=94_860.32)
        acct = build_account_state(
            snap, state, fallback_stop_pct=0.0065, trading_capital=15_000.0
        )
        assert acct.equity == pytest.approx(15_000.0)
        assert acct.peak_equity == pytest.approx(105_263.48 * (15_000 / 94_860.32))
        from my_trade.core.risk import RiskLimits, is_circuit_breaker_tripped

        limits = RiskLimits(
            max_risk_per_trade_pct=0.01,
            max_total_open_risk_pct=0.05,
            daily_loss_limit_pct=0.03,
            max_drawdown_pct=0.15,
            max_concurrent_positions=1,
            max_notional_pct=0.20,
        )
        assert is_circuit_breaker_tripped(acct, limits) is False


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
class TestStore:
    def test_round_trip(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "s.json")
        state = record_entry(
            DailyState(trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_300.0),
            SYMBOL,
            99_000.0,
            NOW,
        )
        store.save(state)
        loaded = store.load()
        assert loaded == state

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert DailyStateStore(tmp_path / "missing.json").load() is None

    def test_corrupt_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{ not json", encoding="utf-8")
        assert DailyStateStore(path).load() is None


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
class TestOrchestrator:
    def test_entry_happy_path(self, tmp_path: Path) -> None:
        executor = FakeExecutor(submitted=True)
        orch = make_orchestrator(
            tmp_path, snap=snapshot(), strategy=FakeStrategy(entry=signal()), executor=executor
        )
        result = orch.run_cycle(NOW)
        assert result.halted is False
        assert result.entries_submitted == 1
        assert len(executor.entries) == 1
        assert orch.state.entries_for(SYMBOL) == 1
        # state was persisted
        assert (tmp_path / "daily_state.json").exists()

    def test_no_signal_no_order(self, tmp_path: Path) -> None:
        executor = FakeExecutor()
        orch = make_orchestrator(
            tmp_path, snap=snapshot(), strategy=FakeStrategy(entry=None), executor=executor
        )
        result = orch.run_cycle(NOW)
        assert any(a.kind is ActionKind.NO_SIGNAL for a in result.actions)
        assert executor.entries == []

    def test_circuit_breaker_halts_entries(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "daily_state.json")
        store.save(
            DailyState(trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0)
        )
        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot(equity=10_000.0)),  # type: ignore[arg-type]
            store=store,
            limits=limits(),
            symbols=(SYMBOL,),
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.halted is True
        assert result.halt_reason is HaltReason.CIRCUIT_BREAKER
        assert executor.entries == []

    def test_daily_loss_halts_entries(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "daily_state.json")
        store.save(
            DailyState(trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0)
        )
        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot(equity=11_300.0)),  # type: ignore[arg-type]
            store=store,
            limits=limits(),
            symbols=(SYMBOL,),
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.halted is True
        assert result.halt_reason is HaltReason.DAILY_LOSS_LIMIT
        assert executor.entries == []

    def test_daily_profit_target_halts_entries(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "daily_state.json")
        store.save(
            DailyState(
                trading_day=TODAY,
                start_of_day_equity=15_000.0,
                peak_equity=15_150.0,
                broker_sod_equity=15_000.0,
            )
        )
        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot(equity=15_150.0)),  # type: ignore[arg-type]
            store=store,
            limits=RiskLimits(
                max_risk_per_trade_pct=0.02,
                max_total_open_risk_pct=0.07,
                daily_loss_limit_pct=0.01,
                daily_profit_target_pct=0.01,
                max_drawdown_pct=0.15,
                max_concurrent_positions=1,
                max_notional_pct=0.4,
            ),
            symbols=(SYMBOL,),
            trading_capital=15_000.0,
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.halted is True
        assert result.halt_reason is HaltReason.DAILY_PROFIT_TARGET
        assert executor.entries == []

    def test_exit_path_closes_position(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "daily_state.json")
        store.save(
            record_entry(
                DailyState(
                    trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0
                ),
                SYMBOL,
                99_350.0,
                NOW,
            )
        )
        executor = FakeExecutor()
        pos = (Position(SYMBOL, qty=0.5, avg_entry_price=100_000.0),)
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(exit_reason="time_stop"),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot(positions=pos)),  # type: ignore[arg-type]
            store=store,
            limits=limits(),
            symbols=(SYMBOL,),
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.exits_submitted == 1
        assert executor.closes == [SYMBOL]
        assert KEY not in orch.state.position_stops

    def test_max_entries_skips(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "daily_state.json")
        store.save(
            DailyState(
                trading_day=TODAY,
                start_of_day_equity=12_000.0,
                peak_equity=12_000.0,
                entries_today={KEY: 1},
            )
        )
        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot()),  # type: ignore[arg-type]
            store=store,
            limits=limits(),
            symbols=(SYMBOL,),
            max_entries_per_symbol_per_day=1,
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert any(a.kind is ActionKind.SKIP_MAX_ENTRIES for a in result.actions)
        assert executor.entries == []

    def test_restart_safety_preserves_entry_count(self, tmp_path: Path) -> None:
        path = tmp_path / "daily_state.json"

        first = make_orchestrator(
            tmp_path,
            snap=snapshot(),
            strategy=FakeStrategy(entry=signal()),
            executor=FakeExecutor(submitted=True),
            max_entries=1,
        )
        first.run_cycle(NOW)
        assert first.state.entries_for(SYMBOL) == 1
        assert path.exists()

        # Simulate a restart: a brand-new orchestrator reloads persisted state.
        second_exec = FakeExecutor(submitted=True)
        second = make_orchestrator(
            tmp_path,
            snap=snapshot(),
            strategy=FakeStrategy(entry=signal()),
            executor=second_exec,
            max_entries=1,
        )
        assert second.state.entries_for(SYMBOL) == 1  # recovered, not reset
        result = second.run_cycle(NOW)
        assert any(a.kind is ActionKind.SKIP_MAX_ENTRIES for a in result.actions)
        assert second_exec.entries == []  # no double entry after restart

    def test_account_error_is_fail_safe(self, tmp_path: Path) -> None:
        class BrokenAccount:
            def get_snapshot(self) -> AccountSnapshot:
                raise RuntimeError("api down")

        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=BrokenAccount(),  # type: ignore[arg-type]
            store=DailyStateStore(tmp_path / "s.json"),
            limits=limits(),
            symbols=(SYMBOL,),
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.halted is False
        assert any(a.kind is ActionKind.ERROR for a in result.actions)
        assert executor.entries == []

    def test_empty_watchlist_falls_back_to_static_symbols(self, tmp_path: Path) -> None:
        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot()),  # type: ignore[arg-type]
            store=DailyStateStore(tmp_path / "s.json"),
            limits=limits(),
            symbols=(SYMBOL, "MSFT"),
            watchlist=lambda: (),
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.halted is False
        assert len(executor.entries) == 1

    def test_session_closed_skips_entries(self, tmp_path: Path) -> None:
        executor = FakeExecutor()
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot()),  # type: ignore[arg-type]
            store=DailyStateStore(tmp_path / "s.json"),
            limits=limits(),
            symbols=(SYMBOL,),
            session_is_open=lambda _when: False,
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert result.halted is False
        assert any(a.kind is ActionKind.SESSION_CLOSED for a in result.actions)
        assert executor.entries == []

    def test_session_closed_still_manages_exits(self, tmp_path: Path) -> None:
        store = DailyStateStore(tmp_path / "daily_state.json")
        store.save(
            record_entry(
                DailyState(
                    trading_day=TODAY, start_of_day_equity=12_000.0, peak_equity=12_000.0
                ),
                SYMBOL,
                99_350.0,
                NOW,
            )
        )
        executor = FakeExecutor()
        pos = (Position(SYMBOL, qty=0.5, avg_entry_price=100_000.0),)
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(exit_reason="time_stop"),
            execution=executor,  # type: ignore[arg-type]
            account=FakeAccount(snapshot(positions=pos)),  # type: ignore[arg-type]
            store=store,
            limits=limits(),
            symbols=(SYMBOL,),
            session_is_open=lambda _when: False,
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert executor.closes == [SYMBOL]  # exits run even when market closed
        assert any(a.kind is ActionKind.SESSION_CLOSED for a in result.actions)

    def test_real_execution_adapter_enforces_risk_gate(self, tmp_path: Path) -> None:
        # An open position in another symbol pushes open_positions to the max,
        # so the REAL risk engine (inside ExecutionAdapter) must reject the BTC
        # entry — proving no order is sent when risk would be violated.
        broker = RecordingBroker()
        adapter = ExecutionAdapter(broker, limits(max_concurrent_positions=1))  # type: ignore[arg-type]
        other = (Position("ETH/USD", qty=1.0, avg_entry_price=3_000.0),)
        orch = TradingOrchestrator(
            data=FakeData(),  # type: ignore[arg-type]
            strategy=FakeStrategy(entry=signal()),
            execution=adapter,
            account=FakeAccount(snapshot(positions=other)),  # type: ignore[arg-type]
            store=DailyStateStore(tmp_path / "s.json"),
            limits=limits(max_concurrent_positions=1),
            symbols=(SYMBOL,),
            clock=lambda: NOW,
        )
        result = orch.run_cycle(NOW)
        assert any(a.kind is ActionKind.ENTRY_REJECTED for a in result.actions)
        assert broker.submitted == []  # nothing was sent to the broker
