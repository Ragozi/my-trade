"""Shared data models for signals and trade plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: OrderSide
    entry_price: float
    stop_price: float
    take_profit_price: float
    confidence: float
    reasons: List[str] = field(default_factory=list)
    timestamp: Optional[datetime] = None


@dataclass
class TradePlan:
    symbol: str
    qty: float
    entry_price: float
    stop_price: float
    take_profit_price: float
    notional: float
    risk_dollars: float


@dataclass
class ScanEvaluation:
    """Structured result from one strategy evaluation."""

    eligible: bool
    summary: str
    failures: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    near_signal: bool = False


@dataclass
class BacktestResult:
    symbol: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_r: float
    max_drawdown: float
    equity_curve_path: str
