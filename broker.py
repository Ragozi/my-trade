"""Alpaca crypto trading and market data (BTC/USD)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
)

from config import Settings
from utils import get_logger, to_eastern


class AlpacaBroker:
    """Crypto broker wrapper: bars, notional bracket orders, positions."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._log = get_logger()
        self._trading = TradingClient(
            api_key=settings.api_key,
            secret_key=settings.api_secret,
            paper=settings.paper_trading,
        )
        self._data = CryptoHistoricalDataClient(
            api_key=settings.api_key,
            secret_key=settings.api_secret,
        )
        self._position_entry_times: Dict[str, datetime] = {}

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Alpaca may return BTCUSD; config uses BTC/USD."""
        return symbol.replace("/", "").upper()

    @staticmethod
    def symbols_match(a: str, b: str) -> bool:
        return AlpacaBroker.normalize_symbol(a) == AlpacaBroker.normalize_symbol(b)

    def _parse_timeframe(self, tf_str: str) -> TimeFrame:
        mapping = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "2Min": TimeFrame(2, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
            "1Day": TimeFrame(1, TimeFrameUnit.Day),
        }
        return mapping.get(tf_str, TimeFrame(1, TimeFrameUnit.Minute))

    def is_market_open(self) -> bool:
        """Crypto trades 24/7 — always True."""
        return True

    def get_account(self) -> dict:
        acct = self._trading.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
        }

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Fetch crypto OHLCV bars as a pandas DataFrame."""
        limit = limit or self._s.bar_limit
        tf = self._parse_timeframe(timeframe)

        if end is None:
            end = datetime.now(to_eastern().tzinfo)
        if start is None:
            minutes = 1
            if "5" in timeframe:
                minutes = 5
            elif "2" in timeframe:
                minutes = 2
            start = end - timedelta(minutes=minutes * limit * 2)

        request = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            limit=limit,
        )
        bars = self._data.get_crypto_bars(request)

        sym_key = symbol
        if symbol not in bars.data:
            for key in bars.data:
                if self.symbols_match(key, symbol):
                    sym_key = key
                    break

        if sym_key not in bars.data or not bars.data[sym_key]:
            return pd.DataFrame()

        records = []
        for bar in bars.data[sym_key]:
            records.append(
                {
                    "timestamp": bar.timestamp,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume),
                }
            )
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.set_index("timestamp").sort_index()
        return df

    def get_latest_price(self, symbol: str) -> Optional[float]:
        df = self.get_bars(symbol, self._s.entry_timeframe, limit=5)
        if df.empty:
            return None
        return float(df.iloc[-1]["close"])

    def get_open_positions(self) -> List[dict]:
        positions = self._trading.get_all_positions()
        result = []
        for pos in positions:
            result.append(
                {
                    "symbol": pos.symbol,
                    "qty": float(pos.qty),
                    "side": pos.side,
                    "avg_entry_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price),
                    "unrealized_pl": float(pos.unrealized_pl),
                    "market_value": float(pos.market_value),
                }
            )
        return result

    def has_position(self, symbol: str) -> bool:
        for pos in self.get_open_positions():
            if self.symbols_match(pos["symbol"], symbol):
                return True
        return False

    def _position_symbol(self, symbol: str) -> Optional[str]:
        """Return Alpaca position symbol matching our pair."""
        for pos in self.get_open_positions():
            if self.symbols_match(pos["symbol"], symbol):
                return pos["symbol"]
        return None

    def submit_bracket_order(
        self,
        symbol: str,
        notional: float,
        stop_price: float,
        take_profit_price: float,
    ) -> Optional[str]:
        """Submit a market bracket buy using fixed notional (e.g. $8)."""
        try:
            tp = round(take_profit_price, 2)
            sl = round(stop_price, 2)
            order = MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=tp),
                stop_loss=StopLossRequest(stop_price=sl),
            )
            submitted = self._trading.submit_order(order)
            self._position_entry_times[symbol] = to_eastern()
            self._log.info(
                "Bracket order submitted: %s notional=$%.2f sl=%.2f tp=%.2f id=%s",
                symbol,
                notional,
                sl,
                tp,
                submitted.id,
            )
            return str(submitted.id)
        except Exception as exc:
            self._log.error("Order failed for %s: %s", symbol, exc)
            return None

    def close_position(self, symbol: str) -> bool:
        pos_sym = self._position_symbol(symbol) or symbol
        try:
            self._trading.close_position(pos_sym)
            self._position_entry_times.pop(symbol, None)
            self._log.info("Closed position: %s", pos_sym)
            return True
        except Exception as exc:
            self._log.error("Failed to close %s: %s", symbol, exc)
            return False

    def close_all_positions(self) -> None:
        try:
            self._trading.close_all_positions(cancel_orders=True)
            self._position_entry_times.clear()
            self._log.info("All crypto positions closed")
        except Exception as exc:
            self._log.error("Failed to close all positions: %s", exc)

    def get_position_entry_time(self, symbol: str) -> Optional[datetime]:
        return self._position_entry_times.get(symbol)

    def set_position_entry_time(self, symbol: str, entry_time: datetime) -> None:
        self._position_entry_times[symbol] = entry_time

    def get_today_realized_pnl(self) -> float:
        try:
            from alpaca.trading.requests import GetPortfolioHistoryRequest

            request = GetPortfolioHistoryRequest(period="1D", timeframe="1Min")
            history = self._trading.get_portfolio_history(request)
            if history.equity and len(history.equity) >= 2:
                return float(history.equity[-1]) - float(history.equity[0])
        except Exception as exc:
            self._log.debug("Portfolio history P&L unavailable: %s", exc)
        return 0.0

    def manage_open_positions(
        self,
        strategy,
        get_bars_fn,
    ) -> List[tuple[str, str]]:
        """Soft exits: RSI overbought and time stop (bracket handles SL/TP)."""
        closed: List[tuple[str, str]] = []
        for pos in self.get_open_positions():
            symbol = pos["symbol"]
            config_sym = self._s.symbols[0] if self._s.symbols else symbol
            if not self.symbols_match(symbol, config_sym):
                continue

            entry_time = self._position_entry_times.get(config_sym)
            if entry_time is None:
                entry_time = to_eastern()

            df_1m = get_bars_fn(config_sym, self._s.entry_timeframe)
            if df_1m.empty:
                continue

            exit_reason = strategy.detect_exit(
                df_1m.reset_index(),
                entry_time,
                float(pos["avg_entry_price"]),
            )
            if exit_reason in ("rsi_overbought", "time_stop"):
                self._log.info("%s soft exit: %s", config_sym, exit_reason)
                if self.close_position(config_sym):
                    closed.append((config_sym, exit_reason))
        return closed

    def cancel_open_orders(self) -> None:
        try:
            self._trading.cancel_orders()
        except Exception as exc:
            self._log.warning("Cancel orders failed: %s", exc)
