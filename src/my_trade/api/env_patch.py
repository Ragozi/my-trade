"""Safe, whitelisted .env patching for settings changes from the operator UI.

Only non-secret trading knobs may be updated. API keys are never touched.
Pure logic for the key mapping; file I/O is isolated in ``apply_settings_patch``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# Frontend patch path → .env variable name.
_PATCH_MAP: dict[tuple[str, ...], str] = {
    ("asset_class",): "ASSET_CLASS",
    ("symbols",): "CRYPTO_SYMBOLS",  # resolved per asset class in apply
    ("screener", "enabled"): "USE_SCREENER",
    ("screener", "top_n"): "SCREENER_TOP_N",
    ("screener", "refresh_seconds"): "SCREENER_REFRESH_SECONDS",
    ("screener", "min_atr_pct"): "SCREENER_MIN_ATR_PCT",
    ("screener", "min_dollar_volume"): "SCREENER_MIN_DOLLAR_VOLUME",
    ("screener", "use_movers"): "SCREENER_USE_MOVERS",
    ("screener", "movers_source"): "SCREENER_MOVERS_SOURCE",
    ("strategy", "rsi_oversold"): "RSI_OVERSOLD",
    ("strategy", "rsi_overbought"): "RSI_OVERBOUGHT",
    ("strategy", "stop_loss_pct"): "STOP_LOSS_PCT",
    ("strategy", "take_profit_pct"): "TAKE_PROFIT_PCT",
    ("strategy", "max_hold_minutes"): "MAX_HOLD_MINUTES",
    ("strategy", "require_15m_uptrend"): "REQUIRE_15M_UPTREND",
    ("strategy", "require_volume_spike"): "REQUIRE_VOLUME_SPIKE",
    ("risk", "max_risk_per_trade_pct"): "MAX_RISK_PER_TRADE_PCT",
    ("risk", "max_open_risk_pct"): "MAX_TOTAL_OPEN_RISK_PCT",
    ("risk", "daily_loss_limit_pct"): "DAILY_LOSS_LIMIT_PCT",
    ("risk", "daily_profit_target_pct"): "DAILY_PROFIT_TARGET_PCT",
    ("risk", "max_drawdown_pct"): "MAX_DRAWDOWN_PCT",
    ("risk", "max_concurrent_positions"): "MAX_OPEN_POSITIONS",
    ("risk", "max_daily_entries"): "MAX_DAILY_ENTRIES",
    ("risk", "trading_capital"): "TRADING_CAPITAL",
    ("risk", "max_notional_pct"): "MAX_NOTIONAL_PCT",
    ("runtime", "scan_interval_seconds"): "SCAN_INTERVAL_SECONDS",
}

_BLOCKED_KEYS = frozenset({"APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALLOW_LIVE_TRADING"})


def _flatten_patch(
    patch: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> dict[tuple[str, ...], Any]:
    out: dict[tuple[str, ...], Any] = {}
    for key, value in patch.items():
        path = (*prefix, str(key))
        if isinstance(value, dict):
            out.update(_flatten_patch(value, path))
        else:
            out[path] = value
    return out


def patch_to_env_updates(patch: Mapping[str, Any]) -> dict[str, str]:
    """Convert a nested frontend settings patch into flat .env key→value updates."""
    flat = _flatten_patch(patch)
    updates: dict[str, str] = {}
    for path, value in flat.items():
        env_key = _PATCH_MAP.get(path)
        if env_key is None:
            continue
        if env_key in _BLOCKED_KEYS:
            continue
        if path == ("symbols",):
            # Caller resolves CRYPTO_SYMBOLS vs EQUITY_SYMBOLS using asset_class.
            updates["_SYMBOLS_LIST"] = ",".join(str(s) for s in value)
            continue
        if isinstance(value, bool):
            updates[env_key] = "true" if value else "false"
        else:
            updates[env_key] = str(value)
    return updates


def resolve_symbol_key(updates: dict[str, str], asset_class: str) -> dict[str, str]:
    """Map the internal _SYMBOLS_LIST placeholder to the correct env var."""
    out = {k: v for k, v in updates.items() if k != "_SYMBOLS_LIST"}
    if "_SYMBOLS_LIST" in updates:
        key = "EQUITY_SYMBOLS" if asset_class == "equities" else "CRYPTO_SYMBOLS"
        out[key] = updates["_SYMBOLS_LIST"]
    return out


_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def merge_env_lines(existing: str, updates: Mapping[str, str]) -> str:
    """Return new .env content with ``updates`` applied (add or replace lines)."""
    lines = existing.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ENV_LINE.match(line.strip())
        if m and m.group(1) in updates:
            key = m.group(1)
            if key in _BLOCKED_KEYS:
                out.append(line)
                continue
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen and key not in _BLOCKED_KEYS:
            out.append(f"{key}={value}")
    return "\n".join(out) + ("\n" if out else "")


def apply_env_patch(env_path: Path, updates: Mapping[str, str]) -> None:
    """Apply whitelisted updates to a .env file on disk."""
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    env_path.write_text(merge_env_lines(text, updates), encoding="utf-8")
