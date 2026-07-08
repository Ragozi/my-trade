"""Pure session/market-hours guards (no I/O, deterministic given ``now``).

Crypto trades 24/7; US equities only during the regular cash session
(09:30-16:00 America/New_York, Mon-Fri). This is intentionally a *simple* guard:
it is DST-correct via ``zoneinfo`` but does NOT yet account for market holidays
or early closes — that is a documented follow-up. PDT enforcement is likewise a
later concern; see ``SCOPE.md``.

The orchestrator uses ``make_session_guard`` so it never *attempts* equity
entries outside the session (orders would queue/reject); crypto always
returns True.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)

ASSET_CLASS_CRYPTO = "crypto"
ASSET_CLASS_EQUITIES = "equities"


def is_am_momentum_window(now: datetime) -> bool:
    """True during the first ~2 hours of the US cash session (9:30–11:30 ET).

    Used to refresh the screener faster and bias toward opening-range movers.
    """
    aware = now if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo("UTC"))
    ny = aware.astimezone(_NY)
    if ny.weekday() >= 5:
        return False
    return _OPEN <= ny.time() < time(11, 30)


def is_equity_regular_session(now: datetime) -> bool:
    """True when ``now`` falls in the US equities regular cash session.

    Accepts tz-aware or naive datetimes; naive is assumed to be UTC. Weekends
    are closed. Holidays/early-closes are not yet modeled (treated as open).
    """
    aware = now if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo("UTC"))
    ny = aware.astimezone(_NY)
    if ny.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    return _OPEN <= ny.time() < _CLOSE


def make_session_guard(asset_class: str) -> Callable[[datetime], bool]:
    """Return a ``now -> is_open`` guard for the given asset class.

    Crypto is always open; equities use the regular-session check.
    """
    if asset_class == ASSET_CLASS_EQUITIES:
        return is_equity_regular_session
    return lambda _now: True
