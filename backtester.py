"""Walk-forward backtester for BTC/USD v3 strategy."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

from broker import AlpacaBroker
from config import Settings
from models import BacktestResult
from risk import RiskManager
from strategy import BtcVwapRsiPullbackStrategy
from utils import get_logger, to_eastern


class SimpleBacktester:
    """Bar-by-bar backtest with 5m/15m trend filters (no lookahead)."""

    def __init__(
        self,
        settings: Settings,
        broker: AlpacaBroker,
        strategy: BtcVwapRsiPullbackStrategy,
        risk: RiskManager,
    ) -> None:
        self._s = settings
        self._broker = broker
        self._strategy = strategy
        self._risk = risk
        self._log = get_logger()

    def run(self, symbol: str, days: int = 30) -> BacktestResult:
        end = datetime.now(to_eastern().tzinfo)
        start = end - timedelta(days=days + 2)

        df_1m = self._broker.get_bars(
            symbol, self._s.entry_timeframe, limit=10000, start=start, end=end
        )
        df_5m = self._broker.get_bars(
            symbol, self._s.trend_timeframe, limit=5000, start=start, end=end
        )
        df_15m = self._broker.get_bars(
            symbol, self._s.trend_timeframe_15m, limit=3000, start=start, end=end
        )

        if df_1m.empty:
            raise ValueError(f"No crypto bars returned for {symbol}")

        df_1m = df_1m.reset_index()
        df_5m = df_5m.reset_index() if not df_5m.empty else pd.DataFrame()
        df_15m = df_15m.reset_index() if not df_15m.empty else pd.DataFrame()

        equity = 10_000.0
        initial_equity = equity
        in_position = False
        entry_price = 0.0
        entry_time: Optional[datetime] = None
        stop_price = 0.0
        tp_price = 0.0
        qty = 0.0

        trades: List[dict] = []
        equity_curve: List[dict] = []

        warmup = max(
            self._s.ema_trend,
            self._s.bollinger_period,
            self._s.volume_sma_period,
            self._s.macd_slow,
        ) + 5

        for i in range(warmup, len(df_1m) - 1):
            bar_time = df_1m.iloc[i]["timestamp"]
            window_1m = df_1m.iloc[: i + 1].copy()
            window_5m = (
                df_5m.loc[df_5m["timestamp"] <= bar_time].copy()
                if not df_5m.empty
                else pd.DataFrame()
            )
            window_15m = (
                df_15m.loc[df_15m["timestamp"] <= bar_time].copy()
                if not df_15m.empty
                else pd.DataFrame()
            )

            if in_position:
                exit_reason = self._strategy.detect_exit(
                    window_1m, entry_time, entry_price
                )
                next_open = float(df_1m.iloc[i + 1]["open"])
                exited = False
                pnl = 0.0

                if exit_reason == "stop_loss":
                    pnl = (stop_price - entry_price) * qty
                    exited = True
                elif exit_reason == "take_profit":
                    pnl = (tp_price - entry_price) * qty
                    exited = True
                elif exit_reason in ("rsi_overbought", "time_stop"):
                    pnl = (next_open - entry_price) * qty
                    exited = True

                if exited:
                    equity += pnl
                    trades.append(
                        {
                            "entry_time": entry_time,
                            "exit_time": bar_time,
                            "entry_price": entry_price,
                            "exit_price": entry_price + pnl / qty if qty else 0,
                            "pnl": pnl,
                            "reason": exit_reason,
                        }
                    )
                    in_position = False

            elif len(window_1m) >= 3:
                sig, _ev = self._strategy.evaluate(
                    symbol, window_1m, window_5m, window_15m, verbose=False
                )
                if sig:
                    plan = self._risk.build_trade_plan(sig)
                    if plan and plan.notional > 0:
                        entry_price = float(df_1m.iloc[i + 1]["open"])
                        stop_price = sig.stop_price
                        tp_price = sig.take_profit_price
                        qty = plan.notional / entry_price
                        entry_time = df_1m.iloc[i + 1]["timestamp"]
                        in_position = True

            equity_curve.append({"timestamp": bar_time, "equity": equity})

        wins = sum(1 for t in trades if t["pnl"] > 0)
        losses = sum(1 for t in trades if t["pnl"] <= 0)
        total = len(trades)
        win_rate = (wins / total * 100.0) if total else 0.0
        total_pnl = equity - initial_equity

        rs = []
        notional = self._risk.fixed_notional
        for t in trades:
            risk_dollars = t["entry_price"] * self._s.stop_loss_pct * (
                notional / t["entry_price"]
            )
            if risk_dollars > 0:
                rs.append(t["pnl"] / risk_dollars)
        avg_r = sum(rs) / len(rs) if rs else 0.0

        eq_series = pd.Series([e["equity"] for e in equity_curve])
        rolling_max = eq_series.cummax()
        drawdown = (eq_series - rolling_max) / rolling_max.replace(0, 1)
        max_dd = float(drawdown.min()) if len(drawdown) else 0.0

        log_dir = Path(self._s.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = to_eastern().strftime("%Y%m%d_%H%M%S")
        safe_sym = symbol.replace("/", "_")
        curve_path = log_dir / f"backtest_{safe_sym}_{stamp}.csv"
        pd.DataFrame(equity_curve).to_csv(curve_path, index=False)

        result = BacktestResult(
            symbol=symbol,
            total_trades=total,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_r=avg_r,
            max_drawdown=max_dd,
            equity_curve_path=str(curve_path),
        )
        self._log.info(
            "Backtest %s: trades=%d win_rate=%.1f%% pnl=$%.2f",
            symbol,
            total,
            win_rate,
            total_pnl,
        )
        return result
