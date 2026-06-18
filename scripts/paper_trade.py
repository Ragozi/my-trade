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
from datetime import UTC, datetime
from pathlib import Path

# Allow running without an editable install: put ``src`` on the path.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.config import Settings, load_settings  # noqa: E402
from my_trade.core.execution import ExecutionAdapter, ExecutionMode  # noqa: E402
from my_trade.core.execution.alpaca_client import AlpacaBrokerClient  # noqa: E402
from my_trade.core.monitoring import (  # noqa: E402
    CycleResult,
    DailyStateStore,
    TradingOrchestrator,
)
from my_trade.core.monitoring.alpaca_account import AlpacaAccountProvider  # noqa: E402
from my_trade.core.strategy import PullbackStrategy, StrategyParams  # noqa: E402
from my_trade.data.alpaca_data import AlpacaDataProvider  # noqa: E402
from my_trade.observability import Journal  # noqa: E402

ALLOW_LIVE = False  # HARD GUARD — never flip this on in the paper runner.

log = logging.getLogger("my_trade.paper")


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


def build_orchestrator(settings: Settings) -> TradingOrchestrator:
    data = AlpacaDataProvider.from_settings(settings)
    account = AlpacaAccountProvider(
        settings.alpaca.api_key, settings.alpaca.api_secret, paper=settings.alpaca.paper_trading
    )
    broker = AlpacaBrokerClient(
        settings.alpaca.api_key, settings.alpaca.api_secret, paper=settings.alpaca.paper_trading
    )
    execution = ExecutionAdapter(
        broker,
        settings.risk.to_limits(),
        mode=ExecutionMode.PAPER,
        allow_live=ALLOW_LIVE,
    )
    strategy = PullbackStrategy(StrategyParams.from_settings(settings))
    return TradingOrchestrator(
        data=data,
        strategy=strategy,
        execution=execution,
        account=account,
        store=DailyStateStore(settings.runtime.daily_state_file),
        limits=settings.risk.to_limits(),
        symbols=settings.symbols,
        entry_timeframe=settings.runtime.entry_timeframe,
        trend_timeframe=settings.runtime.trend_timeframe,
        trend_timeframe_15m=settings.runtime.trend_timeframe_15m,
        bar_limit=settings.runtime.bar_limit,
        max_entries_per_symbol_per_day=settings.risk.max_entries_per_symbol_per_day,
        fallback_stop_pct=settings.strategy.stop_loss_pct,
    )


def connectivity_check(settings: Settings) -> int:
    """Verify we can reach Alpaca (account + market data). Places NO orders."""
    log.info("Connectivity check (read-only, no trading)...")
    ok = True

    account = AlpacaAccountProvider(
        settings.alpaca.api_key, settings.alpaca.api_secret, paper=settings.alpaca.paper_trading
    )
    try:
        snap = account.get_snapshot()
        log.info(
            "Account API OK | equity=$%.2f cash=$%.2f open_positions=%d",
            snap.equity,
            snap.cash,
            len(snap.positions),
        )
    except Exception as exc:
        log.error("Account API unreachable: %s", exc)
        ok = False

    data = AlpacaDataProvider.from_settings(settings)
    symbol = settings.symbols[0]
    try:
        bars = data.get_bars(symbol, settings.runtime.entry_timeframe, limit=10)
        if bars.empty:
            log.warning("Data API reachable but returned no bars for %s", symbol)
        else:
            log.info(
                "Data API OK | %s %s: %d bars, last close=$%.2f",
                symbol,
                settings.runtime.entry_timeframe,
                len(bars),
                float(bars.iloc[-1]["close"]),
            )
    except Exception as exc:
        log.error("Data API unreachable: %s", exc)
        ok = False

    if ok:
        log.info("Connectivity check PASSED.")
        return 0
    log.error("Connectivity check FAILED.")
    return 1


def log_cycle(result: CycleResult) -> None:
    flag = "HALTED" if result.halted else "ok"
    log.info(
        "cycle %s | equity=$%.2f day_pnl=$%.2f peak=$%.2f open=%d [%s]",
        result.timestamp.strftime("%H:%M:%S"),
        result.equity,
        result.day_pnl,
        result.peak_equity,
        result.open_positions,
        flag,
    )
    for action in result.actions:
        log.info(
            "  - %-18s %-10s %s", action.kind.value, action.symbol, action.detail or action.status
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-only trading runner.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="connectivity check only (read-only; reaches Alpaca, places no orders)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="run a single trading cycle then exit (instead of looping)",
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
        return connectivity_check(settings)

    orchestrator = build_orchestrator(settings)
    journal = Journal(settings.runtime.journal_db)

    if args.once:
        log.info("Running a single PAPER cycle | symbols=%s", ",".join(settings.symbols))
        try:
            result = orchestrator.run_cycle(datetime.now(UTC))
            log_cycle(result)
            journal.log_cycle(result)
        finally:
            journal.close()
        return 0

    interval = max(settings.runtime.scan_interval_seconds, 5)
    log.info(
        "Starting PAPER trading | symbols=%s interval=%ds | LIVE DISABLED",
        ",".join(settings.symbols),
        interval,
    )
    last_day: datetime | None = None
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
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("Shutdown requested; exiting cleanly (open positions left intact).")
    finally:
        journal.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
