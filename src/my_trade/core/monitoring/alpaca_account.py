"""AccountProvider backed by alpaca-py's TradingClient (the read-only I/O boundary).

Uses the **Trading API** (``get_account`` + ``get_all_positions``) for equity and
open positions. Order placement lives in ``execution.AlpacaBrokerClient``. Both
are thin wrappers over the same Trading API; this one only reads.

Not unit-tested (network); exercised by the runnable paper-trading script.
"""

from __future__ import annotations

from typing import Any

from .account import AccountSnapshot, Position


def _f(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


class AlpacaAccountProvider:
    def __init__(self, api_key: str, api_secret: str, *, paper: bool = True) -> None:
        from alpaca.trading.client import TradingClient

        self._client: Any = TradingClient(api_key=api_key, secret_key=api_secret, paper=paper)

    def get_snapshot(self) -> AccountSnapshot:
        account = self._client.get_account()
        raw_positions = self._client.get_all_positions()
        positions = tuple(
            Position(
                symbol=str(p.symbol),
                qty=_f(p.qty),
                avg_entry_price=_f(p.avg_entry_price),
                market_value=_f(getattr(p, "market_value", 0.0)),
                unrealized_pl=_f(getattr(p, "unrealized_pl", 0.0)),
            )
            for p in raw_positions
        )
        return AccountSnapshot(
            equity=_f(account.equity),
            cash=_f(getattr(account, "cash", 0.0)),
            last_equity=_f(getattr(account, "last_equity", 0.0)),
            positions=positions,
        )
