"""Pure environment-variable parsing helpers.

Every function takes an explicit ``env`` mapping (no hidden ``os.environ``
access) so configuration parsing is fully deterministic and unit-testable.
Malformed values raise ``ValueError`` with the offending key — we fail fast
rather than silently fall back to a default that hides a typo.
"""

from __future__ import annotations

from collections.abc import Mapping

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f", ""}


def env_str(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key)
    return default if value is None else value


def env_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    value = env.get(key)
    if value is None:
        return default
    norm = value.strip().lower()
    if norm in _TRUE:
        return True
    if norm in _FALSE:
        return False
    raise ValueError(f"{key}: cannot parse {value!r} as a boolean")


def env_int(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{key}: cannot parse {value!r} as an int") from exc


def env_float(env: Mapping[str, str], key: str, default: float) -> float:
    value = env.get(key)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ValueError(f"{key}: cannot parse {value!r} as a float") from exc


def parse_symbols(raw: str) -> list[str]:
    """Split a comma-separated symbol list, upper-cased and de-duplicated."""
    seen: set[str] = set()
    out: list[str] = []
    for chunk in raw.split(","):
        sym = chunk.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out
