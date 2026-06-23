"""Minimal, runnable PAPER trading loop.

Run with:  python -m scripts.paper_trade   (or: poe paper)

Wires the live Alpaca I/O boundaries to the deterministic core:
    AlpacaDataProvider + AlpacaAccountProvider + ExecutionAdapter(AlpacaBroker)
    -> TradingOrchestrator -> Journal

Safety: a hard ``ALLOW_LIVE = False`` guard makes it impossible for this script
to place live orders. It refuses to start unless PAPER_TRADING is true and
ALLOW_LIVE_TRADING is false, and always constructs the execution adapter in
PAPER mode with allow_live=False.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Allow running without an editable install: put ``src`` on the path.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.api.bot_manager import record_cycle  # noqa: E402
from my_trade.config import Settings, load_settings  # noqa: E402
from my_trade.core.execution import (  # noqa: E402
    EntryIntent,
    ExecutionAdapter,
    ExecutionMode,
    ExecutionOutcome,
    TimeInForce,
)
from my_trade.core.execution.alpaca_client import AlpacaBrokerClient  # noqa: E402
from my_trade.core.market_calendar import make_session_guard  # noqa: E402
from my_trade.core.monitoring import (  # noqa: E402
    ActionKind,
    CycleResult,
    DailyStateStore,
    TradingOrchestrator,
)
from my_trade.core.monitoring.alpaca_account import AlpacaAccountProvider  # noqa: E402
from my_trade.core.risk import AccountState, RiskLimits  # noqa: E402
from my_trade.core.screening import (  # noqa: E402
    Screener,
    StaticUniverseSource,
    UniverseSource,
)
from my_trade.core.strategy import PullbackStrategy, StrategyParams  # noqa: E402
from my_trade.data import MarketDataProvider  # noqa: E402
from my_trade.data.alpaca_data import AlpacaDataProvider  # noqa: E402
from my_trade.data.alpaca_movers import AlpacaMoversUniverse  # noqa: E402
from my_trade.data.stock_data import StockHistoricalDataProvider  # noqa: E402
from my_trade.observability import Journal  # noqa: E402
from my_trade.research import (
    build_research_advisor,
    build_research_client,
    build_research_evaluation,
    build_research_memory,
    research_is_active,
)

ALLOW_LIVE = False  # HARD GUARD — never flip this on in the paper runner.
HEARTBEAT_EVERY_N_CYCLES = 10  # journal an equity pulse this often in the loop

log = logging.getLogger("my_trade.paper")

_RESEARCH_KINDS = frozenset(
    {
        ActionKind.RESEARCH_PROPOSAL,
        ActionKind.RESEARCH_SKIPPED,
        ActionKind.RESEARCH_NOT_APPROVED,
        ActionKind.RESEARCH_REFLECTION,
    }
)


def setup_logging() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):  # Windows consoles choke on non-ASCII otherwise
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def refuse_if_live(settings: Settings) -> None:
    if ALLOW_LIVE or settings.alpaca.allow_live_trading or not settings.alpaca.paper_trading:
        log.error(
            "Refusing to start: paper_trade.py is PAPER-only "
            "(require PAPER_TRADING=true and ALLOW_LIVE_TRADING=false)."
        )
        sys.exit(1)


@dataclass
class Providers:
    """The three live Alpaca I/O boundaries (data provider depends on asset class)."""

    data: MarketDataProvider
    account: AlpacaAccountProvider
    broker: AlpacaBrokerClient


def make_data_provider(settings: Settings) -> MarketDataProvider:
    """Crypto vs equities bars provider, selected by ASSET_CLASS."""
    if settings.is_equities:
        return StockHistoricalDataProvider.from_settings(settings)
    return AlpacaDataProvider.from_settings(settings)


def build_providers(settings: Settings) -> Providers:
    return Providers(
        data=make_data_provider(settings),
        account=AlpacaAccountProvider(
            settings.alpaca.api_key,
            settings.alpaca.api_secret,
            paper=settings.alpaca.paper_trading,
        ),
        broker=AlpacaBrokerClient(
            settings.alpaca.api_key,
            settings.alpaca.api_secret,
            paper=settings.alpaca.paper_trading,
        ),
    )


def build_execution(settings: Settings, broker: AlpacaBrokerClient) -> ExecutionAdapter:
    # Equities can't bracket fractional shares and use DAY orders; crypto is
    # fractional + GTC. The hard ALLOW_LIVE guard applies to both.
    return ExecutionAdapter(
        broker,
        settings.risk.to_limits(),
        mode=ExecutionMode.PAPER,
        allow_live=ALLOW_LIVE,
        whole_shares=settings.is_equities,
        default_time_in_force=TimeInForce.DAY if settings.is_equities else TimeInForce.GTC,
    )


def build_screener(settings: Settings, data: object) -> Screener | None:
    """Optional deterministic universe selection (off unless USE_SCREENER=true).

    Returns ``None`` when disabled, so the orchestrator falls back to the static
    ``symbols`` list exactly as before.
    """
    sc = settings.screener
    if not sc.enabled:
        return None

    universe: UniverseSource
    if settings.is_equities and sc.use_movers:
        universe = AlpacaMoversUniverse(
            settings.alpaca.api_key,
            settings.alpaca.api_secret,
            source=sc.movers_source,
            top=sc.movers_top,
            min_volume=sc.movers_min_volume,
        )
        source_desc = f"alpaca-movers({sc.movers_source}, top={sc.movers_top})"
    else:
        static_symbols = settings.symbols if settings.is_equities else sc.universe
        universe = StaticUniverseSource(static_symbols)
        source_desc = f"static({len(tuple(static_symbols))} symbols)"

    screener = Screener(
        data=data,  # type: ignore[arg-type]
        universe=universe,
        criteria=sc.to_criteria(),
        timeframe=sc.timeframe,
        bar_limit=sc.bar_limit,
        atr_period=sc.atr_period,
        lookback=sc.lookback,
        refresh_seconds=sc.refresh_seconds,
    )
    log.info(
        "Screener ENABLED | %s universe=%s top_n=%d refresh=%ds tf=%s",
        settings.asset_class,
        source_desc,
        sc.top_n,
        sc.refresh_seconds,
        sc.timeframe,
    )
    return screener


def log_research_status(settings: Settings, research: object | None) -> None:
    """Startup banner for Phase 4 — makes activation state obvious in console."""
    rc = settings.research
    if not rc.enabled:
        log.info(
            "Claude research DISABLED (ENABLE_CLAUDE=false) — deterministic-only mode"
        )
        return
    if research is None:
        log.error(
            "ENABLE_CLAUDE=true but research advisor failed to build — check ANTHROPIC_API_KEY"
        )
        return
    active = research_is_active(settings)
    if not active:
        log.warning(
            "Claude research ENABLED in config but INACTIVE for asset_class=%s "
            "(CLAUDE_EQUITIES_ONLY=%s). Switch ASSET_CLASS=equities to activate.",
            settings.asset_class,
            rc.equities_only,
        )
        return
    log.info(
        "Claude research ACTIVE | advisory mode | model=%s interval=%ds "
        "require_approval=%s postmortem=%s memory=%s",
        rc.model,
        rc.min_interval_seconds,
        rc.require_approval_for_entry,
        rc.postmortem_enabled,
        rc.memory_file,
    )


def build_research_stack(settings: Settings) -> tuple[object | None, object | None, object | None]:
    """Build advisor + memory + evaluation only when ENABLE_CLAUDE=true."""
    if not settings.research.enabled:
        return None, None, None
    client = build_research_client(settings)
    return (
        build_research_advisor(settings, client=client),
        build_research_memory(settings, client=client),
        build_research_evaluation(settings),
    )


def build_orchestrator(
    settings: Settings,
    *,
    data: object,
    account: object,
    execution: object,
    screener: Screener | None = None,
    research_advisor: object | None = None,
    research_memory: object | None = None,
    research_evaluation: object | None = None,
) -> TradingOrchestrator:
    strategy = PullbackStrategy(StrategyParams.from_settings(settings))
    return TradingOrchestrator(
        data=data,  # type: ignore[arg-type]
        strategy=strategy,
        execution=execution,  # type: ignore[arg-type]
        account=account,  # type: ignore[arg-type]
        store=DailyStateStore(settings.runtime.daily_state_file),
        limits=settings.risk.to_limits(),
        symbols=settings.symbols,
        asset_class=settings.asset_class,
        entry_timeframe=settings.runtime.entry_timeframe,
        trend_timeframe=settings.runtime.trend_timeframe,
        trend_timeframe_15m=settings.runtime.trend_timeframe_15m,
        bar_limit=settings.runtime.bar_limit,
        max_entries_per_symbol_per_day=settings.risk.max_entries_per_symbol_per_day,
        fallback_stop_pct=settings.strategy.stop_loss_pct,
        watchlist=screener.select if screener is not None else None,
        session_is_open=make_session_guard(settings.asset_class),
        research_advisor=research_advisor,  # type: ignore[arg-type]
        research_memory=research_memory,  # type: ignore[arg-type]
        research_evaluation=research_evaluation,  # type: ignore[arg-type]
        journal_path=settings.runtime.journal_db,
    )


# --------------------------------------------------------------------------- #
# Boundary-accounting wrappers: delegate to the real providers and tally calls
# so the smoke-test summary can report exactly which boundaries were exercised.
# --------------------------------------------------------------------------- #
class _CountingData:
    def __init__(self, inner: MarketDataProvider) -> None:
        self._inner = inner
        self.get_bars_calls = 0

    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None):  # type: ignore[no-untyped-def]
        self.get_bars_calls += 1
        return self._inner.get_bars(symbol, timeframe, limit)

    def get_latest_price(self, symbol: str) -> float | None:
        return self._inner.get_latest_price(symbol)


class _CountingAccount:
    def __init__(self, inner: AlpacaAccountProvider) -> None:
        self._inner = inner
        self.snapshot_calls = 0

    def get_snapshot(self):  # type: ignore[no-untyped-def]
        self.snapshot_calls += 1
        return self._inner.get_snapshot()


class _CountingExecution:
    def __init__(self, inner: ExecutionAdapter) -> None:
        self._inner = inner
        self.entry_attempts = 0
        self.entry_submitted = 0
        self.closes = 0

    def execute_entry(
        self, intent: EntryIntent, account: AccountState, *, now: datetime | None = None
    ) -> ExecutionOutcome:
        self.entry_attempts += 1
        outcome = self._inner.execute_entry(intent, account, now=now)
        if outcome.submitted:
            self.entry_submitted += 1
        return outcome

    def close_position(self, symbol: str, *, now: datetime | None = None) -> ExecutionOutcome:
        self.closes += 1
        return self._inner.close_position(symbol, now=now)


def describe_risk_limits(limits: RiskLimits) -> list[str]:
    return [
        f"R1 max risk / trade:   {limits.max_risk_per_trade_pct:.1%}",
        f"R2 max open risk:      {limits.max_total_open_risk_pct:.1%}",
        f"R3 daily loss limit:   {limits.daily_loss_limit_pct:.1%}",
        f"R4 drawdown breaker:   {limits.max_drawdown_pct:.1%}",
        f"max concurrent posns:  {limits.max_concurrent_positions}",
    ]


def run_health_checks(settings: Settings, providers: Providers) -> bool:
    """Exercise all three Alpaca boundaries (read-only) + confirm risk limits."""
    log.info("=== Health checks (read-only; no orders placed) ===")
    ok = True
    symbol = settings.symbols[0]

    try:
        snap = providers.account.get_snapshot()
        log.info(
            "[OK]   Account API     | equity=$%.2f cash=$%.2f open_positions=%d",
            snap.equity,
            snap.cash,
            len(snap.positions),
        )
    except Exception as exc:
        log.error("[FAIL] Account API     | %s", exc)
        ok = False

    try:
        bars = providers.data.get_bars(symbol, settings.runtime.entry_timeframe, limit=10)
        if bars.empty:
            log.warning("[WARN] Data API        | reachable but returned no bars for %s", symbol)
        else:
            log.info(
                "[OK]   Data API        | %s %s: %d bars, last close=$%.2f",
                symbol,
                settings.runtime.entry_timeframe,
                len(bars),
                float(bars.iloc[-1]["close"]),
            )
    except Exception as exc:
        log.error("[FAIL] Data API        | %s", exc)
        ok = False

    try:
        open_orders = providers.broker.list_open_orders()
        log.info("[OK]   Execution API   | reachable (open orders: %d)", len(open_orders))
    except Exception as exc:
        log.error("[FAIL] Execution API   | %s", exc)
        ok = False

    log.info("[OK]   Risk limits loaded:")
    for line in describe_risk_limits(settings.risk.to_limits()):
        log.info("           %s", line)

    log.info("=== Health checks %s ===", "PASSED" if ok else "FAILED")
    return ok


def _summary_label(result: CycleResult) -> str:
    if any(a.kind is ActionKind.ERROR for a in result.actions):
        return "FAIL (cycle error)"
    if result.halted and result.halt_reason is not None:
        return f"PASS (entries halted: {result.halt_reason.value})"
    if any(a.kind is ActionKind.ENTRY_REJECTED for a in result.actions):
        return "PASS (entry rejected by risk gate)"
    if any(a.kind is ActionKind.ENTRY_SUBMITTED for a in result.actions):
        return "PASS (entry submitted)"
    return "PASS (no action this cycle)"


def print_cycle_summary(
    settings: Settings,
    result: CycleResult,
    journaled: int,
    data: _CountingData,
    account: _CountingAccount,
    execution: _CountingExecution,
) -> None:
    log.info("================= SMOKE TEST SUMMARY =================")
    log.info("Cycle time (UTC):   %s", result.timestamp.isoformat())
    log.info("Equity:             $%.2f", result.equity)
    log.info("Day P&L:            $%.2f", result.day_pnl)
    log.info("Peak equity:        $%.2f", result.peak_equity)
    log.info("Open positions:     %d", result.open_positions)
    log.info(
        "Halted:             %s",
        result.halt_reason.value if (result.halted and result.halt_reason) else "no",
    )
    log.info("Actions (%d):", len(result.actions))
    for action in result.actions:
        log.info(
            "   - %-18s %-10s %s",
            action.kind.value,
            action.symbol,
            action.detail or action.status,
        )
    log.info("Boundaries exercised:")
    log.info("   data.get_bars:        %d", data.get_bars_calls)
    log.info("   account.get_snapshot: %d", account.snapshot_calls)
    log.info(
        "   orders attempted:     %d (submitted %d)",
        execution.entry_attempts,
        execution.entry_submitted,
    )
    log.info("   position closes:      %d", execution.closes)
    log.info("Journal:            wrote %d event(s) to %s", journaled, settings.runtime.journal_db)
    log.info("Result:             %s", _summary_label(result))
    log.info("=====================================================")


def run_once(settings: Settings) -> int:
    log.info(
        "Smoke test: single PAPER cycle (--once) | asset_class=%s symbols=%s",
        settings.asset_class,
        ",".join(settings.symbols),
    )
    providers = build_providers(settings)

    if not run_health_checks(settings, providers):
        log.error("Aborting --once: health checks failed (see above).")
        return 1

    data = _CountingData(providers.data)
    account = _CountingAccount(providers.account)
    execution = _CountingExecution(build_execution(settings, providers.broker))
    screener = build_screener(settings, data)
    research, memory, evaluation = build_research_stack(settings)
    log_research_status(settings, research)
    orchestrator = build_orchestrator(
        settings,
        data=data,
        account=account,
        execution=execution,
        screener=screener,
        research_advisor=research,
        research_memory=memory,
        research_evaluation=evaluation,
    )

    journal = Journal(settings.runtime.journal_db)
    try:
        result = orchestrator.run_cycle(datetime.now(UTC))
    except Exception as exc:
        log.exception("Cycle raised an exception: %s", exc)
        journal.record_event("error", detail=str(exc))
        journal.close()
        return 1

    journaled = journal.log_cycle(result)
    journal.record_heartbeat(result.equity, result.day_pnl, result.open_positions)
    record_cycle(
        settings.runtime.log_dir,
        timestamp=result.timestamp,
        halted=result.halted,
        halt_reason=result.halt_reason.value if result.halt_reason else None,
    )
    journal.close()
    if screener is not None:
        watchlist = ", ".join(
            f"{c.symbol}(atr={c.atr_pct:.2%},score={c.score:.3f})" for c in screener.ranked
        )
        log.info("Screener watchlist:  %s", watchlist or "(none passed filters)")
    print_cycle_summary(settings, result, journaled, data, account, execution)
    return 1 if any(a.kind is ActionKind.ERROR for a in result.actions) else 0


def log_cycle(result: CycleResult) -> None:
    flag = "HALTED" if result.halted else "ok"
    research_count = sum(1 for a in result.actions if a.kind in _RESEARCH_KINDS)
    log.info(
        "cycle %s | equity=$%.2f day_pnl=$%.2f peak=$%.2f open=%d [%s]"
        + (" | claude_events=%d" % research_count if research_count else ""),
        result.timestamp.strftime("%H:%M:%S"),
        result.equity,
        result.day_pnl,
        result.peak_equity,
        result.open_positions,
        flag,
    )
    for action in result.actions:
        if action.kind in _RESEARCH_KINDS:
            log.info(
                "  [CLAUDE] %-18s %-10s %s",
                action.kind.value,
                action.symbol,
                action.detail or action.status,
            )
        else:
            log.info(
                "  - %-18s %-10s %s",
                action.kind.value,
                action.symbol,
                action.detail or action.status,
            )


def run_loop(settings: Settings) -> int:
    providers = build_providers(settings)
    execution = build_execution(settings, providers.broker)
    screener = build_screener(settings, providers.data)
    research, memory, evaluation = build_research_stack(settings)
    log_research_status(settings, research)
    orchestrator = build_orchestrator(
        settings,
        data=providers.data,
        account=providers.account,
        execution=execution,
        screener=screener,
        research_advisor=research,
        research_memory=memory,
        research_evaluation=evaluation,
    )
    journal = Journal(settings.runtime.journal_db)

    interval = max(settings.runtime.scan_interval_seconds, 5)
    log.info(
        "Starting PAPER trading | asset_class=%s symbols=%s interval=%ds | LIVE DISABLED",
        settings.asset_class,
        ",".join(settings.symbols),
        interval,
    )
    last_day: datetime | None = None
    cycle_count = 0
    try:
        while True:
            now = datetime.now(UTC)
            try:
                result = orchestrator.run_cycle(now)
            except Exception as exc:  # one bad cycle must not kill the loop
                log.exception("cycle error: %s", exc)
                journal.record_event("error", detail=str(exc), ts=now)
                time.sleep(interval)
                continue

            if last_day is not None and result.timestamp.date() != last_day.date():
                journal.record_rollover(
                    result.timestamp.date().isoformat(), result.equity, ts=result.timestamp
                )
            last_day = result.timestamp

            log_cycle(result)
            journal.log_cycle(result)
            if cycle_count % HEARTBEAT_EVERY_N_CYCLES == 0:
                journal.record_heartbeat(
                    result.equity, result.day_pnl, result.open_positions, ts=result.timestamp
                )
            record_cycle(
                settings.runtime.log_dir,
                timestamp=result.timestamp,
                halted=result.halted,
                halt_reason=result.halt_reason.value if result.halt_reason else None,
            )
            cycle_count += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Shutdown requested; exiting cleanly (open positions left intact).")
    finally:
        journal.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-only trading runner.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="health checks only (read-only; reaches Alpaca, places no orders)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single trading cycle then exit (smoke test with summary)",
    )
    args = parser.parse_args(argv)

    setup_logging()
    settings = load_settings()
    try:
        settings.validate_for_trading()
    except ValueError as exc:
        log.error("Invalid settings: %s", exc)
        return 1
    refuse_if_live(settings)

    if args.check:
        return 0 if run_health_checks(settings, build_providers(settings)) else 1
    if args.once:
        return run_once(settings)
    return run_loop(settings)


if __name__ == "__main__":
    raise SystemExit(main())
