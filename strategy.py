"""BTC/USD scalper v3 — VWAP + RSI + MACD + Bollinger (crypto-aware)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pandas_ta as ta

from config import Settings
from models import OrderSide, ScanEvaluation, Signal
from utils import get_logger, to_eastern


@dataclass
class _ConditionResult:
    passed: bool
    message: str


class BtcVwapRsiPullbackStrategy:
    """
    BTC/USD long scalper v3 (24/7).

    Optional: 5m + 15m EMA20 uptrend.
    1m: VWAP pullback, RSI oversold turning up, MACD hist expanding, BB lower zone.
    Volume spike skipped when CRYPTO_MODE (configurable override).
    Exit: +1.7% TP, RSI >= 68, -0.65% stop, 15m time stop.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._log = get_logger()

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        out = df.copy()
        out["ema_trend"] = ta.ema(out["close"], length=self._s.ema_trend)
        out["rsi"] = ta.rsi(out["close"], length=self._s.rsi_period)
        out["vol_sma"] = ta.sma(out["volume"], length=self._s.volume_sma_period)
        out["vwap"] = self._rolling_vwap(out)

        macd = ta.macd(
            out["close"],
            fast=self._s.macd_fast,
            slow=self._s.macd_slow,
            signal=self._s.macd_signal,
        )
        if macd is not None and not macd.empty:
            hist_col = [c for c in macd.columns if c.startswith("MACDh")]
            if hist_col:
                out["macd_hist"] = macd[hist_col[0]]

        bb = ta.bbands(
            out["close"],
            length=self._s.bollinger_period,
            std=self._s.bollinger_std,
        )
        if bb is not None and not bb.empty:
            lower_col = [c for c in bb.columns if c.startswith("BBL")]
            mid_col = [c for c in bb.columns if c.startswith("BBM")]
            upper_col = [c for c in bb.columns if c.startswith("BBU")]
            if lower_col:
                out["bb_lower"] = bb[lower_col[0]]
            if mid_col:
                out["bb_mid"] = bb[mid_col[0]]
            if upper_col:
                out["bb_upper"] = bb[upper_col[0]]

        return out

    @staticmethod
    def _rolling_vwap(df: pd.DataFrame) -> pd.Series:
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        cum_vol = df["volume"].cumsum()
        cum_tp_vol = (typical * df["volume"]).cumsum()
        return cum_tp_vol / cum_vol.replace(0, float("nan"))

    def snapshot_metrics(self, df_1m: pd.DataFrame) -> Dict[str, Any]:
        if df_1m.empty or len(df_1m) < 2:
            return {}
        df = self.add_indicators(df_1m)
        row = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(row["close"])
        vwap = float(row["vwap"]) if not pd.isna(row.get("vwap")) else None
        dist = abs(close - vwap) / vwap * 100 if vwap else None
        hist = float(row["macd_hist"]) if not pd.isna(row.get("macd_hist")) else None
        hist_prev = float(prev["macd_hist"]) if not pd.isna(prev.get("macd_hist")) else None
        return {
            "price": close,
            "vwap": vwap,
            "rsi": float(row["rsi"]) if not pd.isna(row.get("rsi")) else None,
            "rsi_prev": float(prev["rsi"]) if not pd.isna(prev.get("rsi")) else None,
            "vwap_dist_pct": dist,
            "macd_hist": hist,
            "macd_hist_prev": hist_prev,
            "bb_lower": float(row["bb_lower"]) if not pd.isna(row.get("bb_lower")) else None,
            "bb_mid": float(row["bb_mid"]) if not pd.isna(row.get("bb_mid")) else None,
        }

    def format_scan_line(self, metrics: Dict[str, Any], reason: str) -> str:
        p = metrics.get("price")
        r = metrics.get("rsi")
        dist = metrics.get("vwap_dist_pct")
        price_s = f"${p:,.2f}" if p is not None else "n/a"
        rsi_s = f"{r:.1f}" if r is not None else "n/a"
        dist_s = f"{dist:.2f}%" if dist is not None else "n/a"
        return f"BTC {price_s} | RSI={rsi_s} | VWAP dist={dist_s} | {reason}"

    def _trend_ok(self, df: pd.DataFrame, label: str) -> _ConditionResult:
        if len(df) < 2:
            return _ConditionResult(False, f"{label}: insufficient bars")
        row = df.iloc[-1]
        if pd.isna(row.get("ema_trend")):
            return _ConditionResult(False, f"{label}: EMA20 unavailable")
        close = float(row["close"])
        ema = float(row["ema_trend"])
        if close > ema:
            return _ConditionResult(True, f"{label} uptrend OK")
        return _ConditionResult(
            False,
            f"{label} close ${close:,.2f} <= EMA20 ${ema:,.2f}",
        )

    def _check_vwap(self, close: float, vwap: float) -> _ConditionResult:
        if vwap <= 0:
            return _ConditionResult(False, "VWAP unavailable")
        dist_pct = abs(close - vwap) / vwap
        if dist_pct <= self._s.vwap_pullback_pct:
            return _ConditionResult(
                True,
                f"VWAP OK ({dist_pct * 100:.2f}% away)",
            )
        return _ConditionResult(
            False,
            f"VWAP dist {dist_pct * 100:.2f}% > {self._s.vwap_pullback_pct * 100:.1f}%",
        )

    def _check_rsi(self, rsi_now: float, rsi_prev: float) -> _ConditionResult:
        if rsi_now > self._s.rsi_oversold:
            return _ConditionResult(
                False,
                f"RSI={rsi_now:.1f} > {self._s.rsi_oversold:.0f}",
            )
        if self._s.require_rsi_turning_up and rsi_now <= rsi_prev:
            return _ConditionResult(
                False,
                f"RSI not turning up ({rsi_prev:.1f} -> {rsi_now:.1f})",
            )
        return _ConditionResult(True, f"RSI OK ({rsi_prev:.1f} -> {rsi_now:.1f})")

    def _check_macd(self, hist: float, hist_prev: float) -> _ConditionResult:
        if hist <= 0:
            return _ConditionResult(False, f"MACD hist {hist:.6f} <= 0")
        if hist <= hist_prev:
            return _ConditionResult(
                False,
                f"MACD not expanding ({hist_prev:.6f} -> {hist:.6f})",
            )
        return _ConditionResult(True, "MACD hist > 0 expanding")

    def _check_bollinger(self, close: float, row: pd.Series) -> _ConditionResult:
        if not self._s.bollinger_lower_half_only:
            return _ConditionResult(True, "Bollinger filter off")

        lower = float(row["bb_lower"]) if not pd.isna(row.get("bb_lower")) else None
        mid = float(row["bb_mid"]) if not pd.isna(row.get("bb_mid")) else None
        if lower is None or mid is None:
            return _ConditionResult(False, "Bollinger bands unavailable")

        lower_half_top = (lower + mid) / 2.0
        touch_tol = lower * 0.001
        if close <= lower + touch_tol:
            return _ConditionResult(True, "At lower BB")
        if close <= lower_half_top:
            return _ConditionResult(True, "In lower BB half")
        return _ConditionResult(
            False,
            f"Price ${close:,.2f} above lower BB half (${lower_half_top:,.2f})",
        )

    def _check_volume(self, df: pd.DataFrame, row: pd.Series) -> _ConditionResult:
        if self._s.crypto_mode and not self._s.require_volume_spike:
            return _ConditionResult(True, "Volume skipped (crypto mode)")
        if not self._s.require_volume_spike:
            return _ConditionResult(True, "Volume filter off")

        vol = float(row["volume"])
        if vol <= 0 and len(df) >= 2:
            vol = float(df.iloc[-2]["volume"])
        vol_sma = float(row["vol_sma"]) if not pd.isna(row.get("vol_sma")) else 0.0
        if vol_sma > 0 and vol > vol_sma * self._s.volume_spike_mult:
            return _ConditionResult(True, "Volume spike OK")
        return _ConditionResult(False, "Volume spike failed")

    def detect_entry(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
    ) -> Tuple[Optional[Signal], ScanEvaluation]:
        failures: List[str] = []
        passes: List[str] = []

        if self._s.require_5m_uptrend:
            r5 = self._trend_ok(self.add_indicators(df_5m), "5m")
            if r5.passed:
                passes.append(r5.message)
            else:
                failures.append(r5.message)

        if self._s.require_15m_uptrend:
            r15 = self._trend_ok(self.add_indicators(df_15m), "15m")
            if r15.passed:
                passes.append(r15.message)
            else:
                failures.append(r15.message)

        if len(df_1m) < 3:
            failures.append("1m insufficient bars")
            ev = ScanEvaluation(
                eligible=False,
                summary="No -> " + "; ".join(failures),
                failures=failures,
                metrics=self.snapshot_metrics(df_1m),
            )
            return None, ev

        df = self.add_indicators(df_1m)
        row = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(row["close"])
        metrics = self.snapshot_metrics(df_1m)

        checks = [
            self._check_vwap(
                close,
                float(row["vwap"]) if not pd.isna(row.get("vwap")) else 0.0,
            ),
            self._check_rsi(
                float(row["rsi"]) if not pd.isna(row.get("rsi")) else 999.0,
                float(prev["rsi"]) if not pd.isna(prev.get("rsi")) else 999.0,
            ),
            self._check_macd(
                float(row["macd_hist"]) if not pd.isna(row.get("macd_hist")) else -1.0,
                float(prev["macd_hist"]) if not pd.isna(prev.get("macd_hist")) else -1.0,
            ),
            self._check_bollinger(close, row),
            self._check_volume(df, row),
        ]

        for c in checks:
            if c.passed:
                passes.append(c.message)
            else:
                failures.append(c.message)

        near_signal = len(failures) <= 2 and len(passes) >= 3

        if failures:
            summary = f"Eligible? No -> {'; '.join(failures)}"
            return (
                None,
                ScanEvaluation(
                    eligible=False,
                    summary=summary,
                    failures=failures,
                    metrics=metrics,
                    near_signal=near_signal,
                ),
            )

        entry_price = close
        stop_price = round(entry_price * (1.0 - self._s.stop_loss_pct), 2)
        take_profit_price = round(entry_price * (1.0 + self._s.take_profit_pct), 2)
        reasons = passes[:6]
        signal = Signal(
            symbol=symbol,
            side=OrderSide.BUY,
            entry_price=entry_price,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            confidence=min(1.0, len(reasons) / 6.0),
            reasons=reasons,
            timestamp=to_eastern(),
        )
        return (
            signal,
            ScanEvaluation(
                eligible=True,
                summary=f"Eligible? Yes -> {', '.join(reasons)}",
                failures=[],
                metrics=metrics,
                near_signal=True,
            ),
        )

    def detect_exit(
        self,
        df_1m: pd.DataFrame,
        entry_time: datetime,
        entry_price: float,
    ) -> Optional[str]:
        if df_1m.empty:
            return None

        df = self.add_indicators(df_1m)
        row = df.iloc[-1]
        now = to_eastern()

        hold_minutes = (now - to_eastern(entry_time)).total_seconds() / 60.0
        if hold_minutes >= self._s.max_hold_minutes:
            return "time_stop"

        rsi = float(row["rsi"]) if not pd.isna(row.get("rsi")) else 0.0
        if rsi >= self._s.rsi_overbought:
            return "rsi_overbought"

        low = float(row["low"])
        high = float(row["high"])
        stop_price = entry_price * (1.0 - self._s.stop_loss_pct)
        tp_price = entry_price * (1.0 + self._s.take_profit_pct)
        if low <= stop_price:
            return "stop_loss"
        if high >= tp_price:
            return "take_profit"

        return None

    def evaluate(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        *,
        verbose: bool = False,
    ) -> Tuple[Optional[Signal], ScanEvaluation]:
        """Evaluate entry; logging is handled by main.py unless verbose=True."""
        signal, evaluation = self.detect_entry(symbol, df_1m, df_5m, df_15m)
        if verbose:
            tag = "SIGNAL FIRED" if signal else evaluation.summary
            self._log.info(self.format_scan_line(evaluation.metrics, tag))
        return signal, evaluation


VwapRsiPullbackStrategy = BtcVwapRsiPullbackStrategy
PullbackScalperStrategy = BtcVwapRsiPullbackStrategy
