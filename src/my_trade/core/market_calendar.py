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
_PREOPEN = time(8, 30)  # one hour before cash open — screener/research warmup
_OPEN = time(9, 30)
_CLOSE = time(16, 0)

ASSET_CLASS_CRYPTO = "crypto"
ASSET_CLASS_EQUITIES = "equities"


def _ny_weekday_time(now: datetime) -> tuple[int, time] | None:
    """Return (weekday, NY time) or None when weekend."""
    aware = now if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo("UTC"))
    ny = aware.astimezone(_NY)
    if ny.weekday() >= 5:  # 5=Sat, 6=Sun
        return None
    return ny.weekday(), ny.time()


def is_am_momentum_window(now: datetime) -> bool:
    """True from premarket warmup through the opening range (8:30–11:30 ET).

    Used to refresh the screener faster ahead of and into the cash open.
    """
    parts = _ny_weekday_time(now)
    if parts is None:
        return False
    return _PREOPEN <= parts[1] < time(11, 30)


def is_equity_regular_session(now: datetime) -> bool:
    """True when ``now`` falls in the US equities regular cash session.

    Accepts tz-aware or naive datetimes; naive is assumed to be UTC. Weekends
    are closed. Holidays/early-closes are not yet modeled (treated as open).
    """
    parts = _ny_weekday_time(now)
    if parts is None:
        return False
    return _OPEN <= parts[1] < _CLOSE


def is_equity_research_window(now: datetime) -> bool:
    """True during premarket warmup + cash session (8:30–16:00 ET weekdays).

    Entries stay gated to the regular session; research/screener may run here so
    the watchlist is warm before the open.
    """
    parts = _ny_weekday_time(now)
    if parts is None:
        return False
    return _PREOPEN <= parts[1] < _CLOSE


def make_session_guard(asset_class: str) -> Callable[[datetime], bool]:
    """Return a ``now -> is_open`` guard for the given asset class.

    Crypto is always open; equities use the regular-session check.
    """
    if asset_class == ASSET_CLASS_EQUITIES:
        return is_equity_regular_session
    return lambda _now: True
