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
# Early overnight study window (≈3:00 AM CT) — research/screener warm-up; entries stay 9:30.
_RESEARCH_PREOPEN = time(4, 0)
_PREOPEN = time(8, 30)  # classic premarket hour before cash open
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
    """True from early overnight study through the opening range (4:00–11:30 ET).

    Used to refresh the screener faster while studying overnight/premarket movers.
    """
    parts = _ny_weekday_time(now)
    if parts is None:
        return False
    return _RESEARCH_PREOPEN <= parts[1] < time(11, 30)


def is_opening_scalp_window(
    now: datetime,
    *,
    end_hour: int = 10,
    end_minute: int = 0,
) -> bool:
    """True during the cash-open scalp window (default 9:30–10:00 ET).

    Classic gap-and-go: overnight gappers often pop hard in the first 30 minutes,
    then fade — this is the long-scalp entry window only.
    """
    parts = _ny_weekday_time(now)
    if parts is None:
        return False
    end = time(end_hour, end_minute)
    if end <= _OPEN:
        return False
    return _OPEN <= parts[1] < end


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
    """True from early overnight study through cash close (4:00–16:00 ET weekdays).

    Starts ~3:00 AM CT so the bot can study overnight gaps / news before
    premarket. Entries stay gated to the regular cash session (9:30 ET).
    """
    parts = _ny_weekday_time(now)
    if parts is None:
        return False
    return _RESEARCH_PREOPEN <= parts[1] < _CLOSE


def make_session_guard(asset_class: str) -> Callable[[datetime], bool]:
    """Return a ``now -> is_open`` guard for the given asset class.

    Crypto is always open; equities use the regular-session check.
    """
    if asset_class == ASSET_CLASS_EQUITIES:
        return is_equity_regular_session
    return lambda _now: True
