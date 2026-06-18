"""Risk management: fixed notional, daily loss cap (crypto 24/7)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from config import Settings
from models import Signal, TradePlan
from utils import get_logger


@dataclass
class DailyState:
    date: str
    starting_equity: float
    realized_pnl: float
    entries_per_symbol: Dict[str, int]


class RiskManager:
    """Fixed notional per trade; -2% daily loss cap."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._log = get_logger()
        self._entries_today: Dict[str, int] = {}
        self._starting_equity: Optional[float] = None
        self._load_daily_state()

    @property
    def fixed_notional(self) -> float:
        return self._s.notional_per_trade

    def _load_daily_state(self) -> None:
        path = Path(self._s.daily_state_file)
        today = date.today().isoformat()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("date") == today:
                self._entries_today = {
                    k: int(v) for k, v in data.get("entries_per_symbol", {}).items()
                }
                self._starting_equity = data.get("starting_equity")
        except (json.JSONDecodeError, OSError) as exc:
            self._log.warning("Could not load daily state: %s", exc)

    def save_daily_state(self, starting_equity: float, realized_pnl: float) -> None:
        path = Path(self._s.daily_state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = DailyState(
            date=date.today().isoformat(),
            starting_equity=starting_equity,
            realized_pnl=realized_pnl,
            entries_per_symbol=self._entries_today,
        )
        path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")

    def initialize_day(self, equity: float) -> None:
        today = date.today().isoformat()
        path = Path(self._s.daily_state_file)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self._entries_today = {}
        self._starting_equity = equity
        self.save_daily_state(equity, 0.0)

    def build_trade_plan(self, signal: Signal) -> Optional[TradePlan]:
        if signal.entry_price <= 0:
            return None
        notional = self.fixed_notional
        qty = round(notional / signal.entry_price, 8)
        return TradePlan(
            symbol=signal.symbol,
            qty=qty,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            take_profit_price=signal.take_profit_price,
            notional=notional,
            risk_dollars=round(notional * self._s.stop_loss_pct, 4),
        )

    def can_open_trade(
        self,
        symbol: str,
        buying_power: float,
        open_positions: Set[str],
        daily_pnl: float,
    ) -> Tuple[bool, str]:
        sym_key = symbol.replace("/", "").upper()
        normalized_open = {s.replace("/", "").upper() for s in open_positions}
        if sym_key in normalized_open:
            return False, f"SKIP - Already in position for {symbol}"

        if len(open_positions) >= self._s.max_open_positions:
            return False, "SKIP - Max open positions reached"

        if self._entries_today.get(symbol, 0) >= self._s.max_entries_per_symbol_per_day:
            return False, f"SKIP - Max daily entries for {symbol}"

        if self._starting_equity and self._starting_equity > 0:
            max_loss = self._starting_equity * self._s.max_daily_loss_pct
            if daily_pnl <= -max_loss:
                return (
                    False,
                    f"SKIP - Daily loss limit ({self._s.max_daily_loss_pct * 100:.1f}%)",
                )

        if buying_power < self.fixed_notional:
            return (
                False,
                f"SKIP - Insufficient buying power for ${self.fixed_notional:.2f} trade",
            )

        return True, "OK"

    def record_entry(self, symbol: str) -> None:
        self._entries_today[symbol] = self._entries_today.get(symbol, 0) + 1

    def pre_trade_checks(
        self,
        buying_power: float,
        open_positions: List[str],
        daily_pnl: float,
    ) -> Tuple[bool, str]:
        if len(open_positions) >= self._s.max_open_positions:
            return False, "SKIP - Max positions"
        if self._starting_equity and self._starting_equity > 0:
            max_loss = self._starting_equity * self._s.max_daily_loss_pct
            if daily_pnl <= -max_loss:
                return False, "SKIP - Daily loss limit (-2.0%)"
        if buying_power < self.fixed_notional:
            return False, "SKIP - Low buying power"
        return True, "OK"
