"""My-Trade: BTC/USD crypto scalper v3 — 24/7 entry point."""

from __future__ import annotations

import argparse
import signal
import sys
import time
from typing import List, Optional, Set, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from backtester import SimpleBacktester
from broker import AlpacaBroker
from config import Settings, get_settings
from journal import TradeJournal
from risk import RiskManager
from slack_notify import SlackEvent, SlackNotifier
from strategy import BtcVwapRsiPullbackStrategy
from utils import get_logger, send_alert, setup_logging, to_eastern

_scheduler: Optional[BackgroundScheduler] = None
_broker: Optional[AlpacaBroker] = None
_strategy: Optional[BtcVwapRsiPullbackStrategy] = None
_risk: Optional[RiskManager] = None
_settings: Optional[Settings] = None
_slack: Optional[SlackNotifier] = None
_journal: Optional[TradeJournal] = None
_scan_counter: int = 0


def _mode_label() -> str:
    assert _settings
    return "PAPER" if _settings.paper_trading else "LIVE"


def _primary_symbol() -> str:
    assert _settings
    return _settings.symbols[0]


def _should_log_scan(evaluation, has_signal: bool) -> bool:
    assert _settings
    if has_signal or _settings.verbose_debug or evaluation.near_signal:
        return True
    n = max(1, _settings.log_every_n_scans)
    return _scan_counter % n == 0


def scan_and_trade() -> None:
    """Scan BTC/USD every 60s — quiet logs, Slack on trades only."""
    global _scan_counter
    assert _broker and _strategy and _risk and _settings
    log = get_logger()
    slack = _slack
    symbol = _primary_symbol()
    _scan_counter += 1
    ts = to_eastern().strftime("%H:%M:%S")

    account = _broker.get_account()
    equity = account["equity"]
    buying_power = account["buying_power"]
    daily_pnl = _broker.get_today_realized_pnl()
    _risk.initialize_day(equity)

    positions = _broker.get_open_positions()
    open_symbols: Set[str] = {p["symbol"] for p in positions}

    ok, reason = _risk.pre_trade_checks(buying_power, list(open_symbols), daily_pnl)

    if not ok:
        log.info("SCAN [%s] HALTED | %s", ts, reason)
        return

    if _broker.has_position(symbol):
        log.debug("SCAN [%s] | %s | in position", ts, symbol)
        _broker.manage_open_positions(
            _strategy,
            lambda sym, tf: _broker.get_bars(sym, tf),
        )
        _risk.save_daily_state(equity, daily_pnl)
        return

    can_trade, trade_reason = _risk.can_open_trade(
        symbol, buying_power, open_symbols, daily_pnl
    )
    if not can_trade:
        if _scan_counter % max(1, _settings.log_every_n_scans) == 0:
            log.info("SCAN [%s] | %s | %s", ts, symbol, trade_reason)
        _risk.save_daily_state(equity, daily_pnl)
        return

    try:
        df_1m = _broker.get_bars(symbol, _settings.entry_timeframe)
        df_5m = _broker.get_bars(symbol, _settings.trend_timeframe)
        df_15m = _broker.get_bars(symbol, _settings.trend_timeframe_15m)
    except Exception as exc:
        log.warning("SCAN [%s] | bar fetch failed: %s", ts, exc)
        if slack and slack.enabled:
            slack.post(
                SlackEvent.ERROR,
                f"Bar fetch failed: {symbol}",
                str(exc)[:500],
            )
        return

    if df_1m.empty:
        log.warning("SCAN [%s] | %s | insufficient 1m bars", ts, symbol)
        return

    df_1m_r = df_1m.reset_index()
    df_5m_r = df_5m.reset_index() if not df_5m.empty else df_5m
    df_15m_r = df_15m.reset_index() if not df_15m.empty else df_15m

    sig, evaluation = _strategy.evaluate(
        symbol, df_1m_r, df_5m_r, df_15m_r, verbose=_settings.verbose_debug
    )

    if _should_log_scan(evaluation, sig is not None):
        line = _strategy.format_scan_line(evaluation.metrics, evaluation.summary)
        log.info("SCAN [%s] | %s", ts, line)
    else:
        log.debug("SCAN [%s] | %s", ts, evaluation.summary)

    if sig is None:
        _risk.save_daily_state(equity, daily_pnl)
        closed = _broker.manage_open_positions(
            _strategy,
            lambda sym, tf: _broker.get_bars(sym, tf),
        )
        for sym, exit_reason in closed:
            log.info("EXIT %s: %s", sym, exit_reason)
            if _journal:
                _journal.log_trade_exit(sym, exit_reason)
            if slack and slack.enabled:
                slack.post(
                    SlackEvent.EXIT,
                    f"Exit: {sym}",
                    f"Reason: {exit_reason}",
                    force=True,
                )
        return

    log.info("*** SIGNAL FIRED %s @ $%.2f ***", symbol, sig.entry_price)
    if _journal:
        _journal.log_event(
            "signal",
            f"SIGNAL {symbol} @ ${sig.entry_price:.2f}",
            symbol=symbol,
            metadata={
                "entry": sig.entry_price,
                "stop": sig.stop_price,
                "tp": sig.take_profit_price,
                "reasons": sig.reasons,
                "evaluation": evaluation.summary,
            },
        )

    if slack and slack.enabled:
        slack.post_signal(
            symbol,
            sig.entry_price,
            sig.stop_price,
            sig.take_profit_price,
            sig.reasons,
            evaluation.metrics.get("price") or sig.entry_price,
            0,
        )

    plan = _risk.build_trade_plan(sig)
    if plan is None:
        log.warning("Plan rejected for %s", symbol)
        return

    if slack and slack.enabled:
        slack.post(
            SlackEvent.PLAN,
            f"Trade plan: {symbol}",
            (
                f"Notional `${plan.notional:.2f}`\n"
                f"SL `${plan.stop_price:,.2f}` | TP `${plan.take_profit_price:,.2f}`"
            ),
            force=True,
        )

    order_id = _broker.submit_bracket_order(
        plan.symbol,
        plan.notional,
        plan.stop_price,
        plan.take_profit_price,
    )
    if order_id:
        _risk.record_entry(symbol)
        entry_msg = (
            f"{symbol} notional=${plan.notional:.2f} "
            f"SL=${plan.stop_price:,.2f} TP=${plan.take_profit_price:,.2f} order={order_id}"
        )
        log.info("ENTRY %s", entry_msg)
        if _journal:
            _journal.log_trade_entry(
                symbol,
                plan.qty,
                plan.entry_price,
                plan.notional,
                order_id,
                plan.stop_price,
                plan.take_profit_price,
            )
        if slack and slack.enabled:
            slack.post(
                SlackEvent.TRADE,
                f"Entry: {symbol}",
                entry_msg,
                force=True,
            )
        send_alert(_settings, f"ENTRY {symbol}", "TRADE")
    else:
        log.error("Order failed for %s", symbol)
        if slack and slack.enabled:
            slack.post(
                SlackEvent.ERROR,
                f"Order failed: {symbol}",
                "Bracket order rejected.",
                force=True,
            )

    closed = _broker.manage_open_positions(
        _strategy,
        lambda sym, tf: _broker.get_bars(sym, tf),
    )
    for sym, exit_reason in closed:
        log.info("EXIT %s: %s", sym, exit_reason)
        if _journal:
            _journal.log_trade_exit(sym, exit_reason)
        if slack and slack.enabled:
            slack.post(
                SlackEvent.EXIT,
                f"Exit: {sym}",
                f"Reason: {exit_reason}",
                force=True,
            )

    _risk.save_daily_state(equity, daily_pnl)


def shutdown(signum=None, frame=None) -> None:
    log = get_logger()
    log.info("Shutting down...")
    if _slack and _slack.enabled:
        _slack.post(SlackEvent.BOT, "Bot stopped", "Shutdown.", force=True)
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    sys.exit(0)


def cmd_status() -> None:
    settings = get_settings()
    settings.validate_for_trading()
    setup_logging(settings)
    broker = AlpacaBroker(settings)
    strategy = BtcVwapRsiPullbackStrategy(settings)
    symbol = settings.symbols[0]

    account = broker.get_account()
    positions = broker.get_open_positions()
    pnl = broker.get_today_realized_pnl()

    print("\n=== My-Trade Status (BTC/USD v3) ===")
    print(f"Mode: {'PAPER' if settings.paper_trading else 'LIVE'}")
    print(f"Symbol: {symbol}")
    print(f"Notional: ${settings.notional_per_trade:.2f}")
    print(f"Crypto mode: {settings.crypto_mode} | Vol filter: {settings.require_volume_spike}")
    print(f"15m uptrend required: {settings.require_15m_uptrend}")
    print(f"Equity: ${account['equity']:,.2f} | Day P&L: ${pnl:,.2f}")

    df_1m = broker.get_bars(symbol, settings.entry_timeframe, limit=80)
    df_5m = broker.get_bars(symbol, settings.trend_timeframe, limit=50)
    df_15m = broker.get_bars(symbol, settings.trend_timeframe_15m, limit=50)
    if not df_1m.empty:
        sig, ev = strategy.evaluate(
            symbol,
            df_1m.reset_index(),
            df_5m.reset_index() if not df_5m.empty else df_5m,
            df_15m.reset_index() if not df_15m.empty else df_15m,
            verbose=False,
        )
        print(strategy.format_scan_line(ev.metrics, ev.summary))
        if sig:
            print(f"  -> Would enter @ ${sig.entry_price:,.2f}")

    print(f"Open positions: {len(positions)}")
    for pos in positions:
        print(
            f"  {pos['symbol']}: qty={pos['qty']:.8f} "
            f"entry=${pos['avg_entry_price']:,.2f} uPnL=${pos['unrealized_pl']:.2f}"
        )
    print()


def cmd_backtest(symbol: Optional[str], days: int) -> None:
    settings = get_settings()
    settings.validate_for_trading()
    setup_logging(settings)
    slack = SlackNotifier(settings)

    broker = AlpacaBroker(settings)
    strategy = BtcVwapRsiPullbackStrategy(settings)
    risk = RiskManager(settings)
    bt = SimpleBacktester(settings, broker, strategy, risk)

    sym = symbol or settings.symbols[0]
    result = bt.run(sym, days)
    print("\n=== Backtest Results (BTC/USD v3) ===")
    print(f"Symbol: {result.symbol}")
    print(f"Trades: {result.total_trades}")
    print(f"Wins: {result.wins} | Losses: {result.losses}")
    print(f"Win rate: {result.win_rate:.1f}%")
    print(f"Total P&L: ${result.total_pnl:,.2f}")
    print(f"Max drawdown: {result.max_drawdown * 100:.2f}%")
    print(f"Equity curve: {result.equity_curve_path}")

    if slack.enabled:
        slack.post(
            SlackEvent.BACKTEST,
            f"Backtest: {result.symbol} ({days}d)",
            (
                f"Trades: *{result.total_trades}* | Win rate: *{result.win_rate:.1f}%*\n"
                f"P&L: `${result.total_pnl:+,.2f}`"
            ),
            force=True,
        )


def cmd_dashboard() -> None:
    from dashboard.server import main as run_dashboard

    run_dashboard()


def cmd_run() -> None:
    global _scheduler, _broker, _strategy, _risk, _settings, _slack, _journal, _scan_counter

    _settings = get_settings()
    _settings.validate_for_trading()
    setup_logging(_settings)
    log = get_logger()
    _slack = SlackNotifier(_settings)
    _journal = TradeJournal(_settings.journal_db)
    _scan_counter = 0

    mode = _mode_label()
    symbol = _primary_symbol()
    log.info(
        "BTC scalper v3 (%s) | %s | $%.2f/trade | scan %ds | "
        "vol=%s | 15m_trend=%s | log every %d scans",
        mode,
        symbol,
        _settings.notional_per_trade,
        _settings.scan_interval_seconds,
        _settings.require_volume_spike,
        _settings.require_15m_uptrend,
        _settings.log_every_n_scans,
    )

    _broker = AlpacaBroker(_settings)
    _strategy = BtcVwapRsiPullbackStrategy(_settings)
    _risk = RiskManager(_settings)

    if _slack.enabled:
        _slack.post(
            SlackEvent.BOT,
            f"BTC bot v3 started ({mode})",
            (
                f"`{symbol}` | `${_settings.notional_per_trade}`/trade | "
                f"Scans every {_settings.scan_interval_seconds}s (quiet)\n"
                f"Slack: signals/trades/exits only"
            ),
            force=True,
        )

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        scan_and_trade,
        IntervalTrigger(seconds=_settings.scan_interval_seconds),
        id="btc_scan",
        max_instances=1,
        coalesce=True,
    )

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    _scheduler.start()
    scan_and_trade()
    log.info("Scheduler running — scan every %ds", _settings.scan_interval_seconds)

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="My-Trade: BTC/USD Scalper v3 (24/7)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="Start paper/live BTC bot")
    sub.add_parser("status", help="Show account and entry eligibility")
    sub.add_parser("dashboard", help="Start localhost dashboard")

    bt_parser = sub.add_parser("backtest", help="Backtest BTC/USD v3")
    bt_parser.add_argument("--symbol", default=None)
    bt_parser.add_argument("--days", type=int, default=30)

    args = parser.parse_args()

    if args.command == "run":
        cmd_run()
    elif args.command == "status":
        cmd_status()
    elif args.command == "dashboard":
        cmd_dashboard()
    elif args.command == "backtest":
        cmd_backtest(args.symbol, args.days)


if __name__ == "__main__":
    main()
