"""Symbol hygiene for universe construction — no I/O, fully testable."""

from __future__ import annotations

# Common 2x/3x and inverse ETFs that break pullback math (decay, gap risk).
# Mega/large caps — not the $2–20 AM momentum day-trade target.
DEFAULT_LARGE_CAP_SYMBOLS: frozenset[str] = frozenset(
    {
        "AAPL",
        "MSFT",
        "NVDA",
        "AMD",
        "AVGO",
        "QCOM",
        "MU",
        "AMAT",
        "LRCX",
        "KLAC",
        "MRVL",
        "ARM",
        "INTC",
        "GOOGL",
        "GOOG",
        "AMZN",
        "META",
        "TSLA",
        "NFLX",
        "JPM",
        "BAC",
        "XOM",
        "LLY",
        "UNH",
        "SPY",
        "QQQ",
        "IWM",
        "DIA",
    }
)

DEFAULT_LEVERAGED_ETF_SYMBOLS: frozenset[str] = frozenset(
    {
        "SOXS",
        "SOXL",
        "LABU",
        "LABD",
        "TQQQ",
        "SQQQ",
        "SPXL",
        "SPXS",
        "TECL",
        "TECS",
        "FNGU",
        "FNGD",
        "NVDL",
        "NVDX",
        "NVDU",
        "NVDD",
        "AMDL",
        "AMDS",
        "TSLZ",
        "TSLL",
        "MSTU",
        "MSTZ",
        "CONL",
        "YINN",
        "YANG",
        "UVXY",
        "SVXY",
        "VXX",
        "VIXY",
        "SARK",
        "BERZ",
        "BULZ",
    }
)


def normalize_symbol_key(symbol: str) -> str:
    return symbol.strip().upper()


def is_non_common_share(symbol: str) -> bool:
    """True for warrants, rights, units, and similar non-common tickers.

    Alpaca gainers lists are often dominated by these; they rarely have usable
    IEX bars and are poor AM scalp candidates.
    """
    key = normalize_symbol_key(symbol)
    if not key:
        return True
    if "." in key:  # e.g. VLN.WS, BRK.B preferred-style / warrant forms
        suffix = key.rsplit(".", 1)[-1]
        if suffix in {"WS", "W", "U", "R", "RT", "PW", "WT"}:
            return True
    # Common warrant/right/unit suffixes glued to the root ticker.
    for suffix in ("WW", "WS", "WT", "RW", "RT"):
        if key.endswith(suffix) and len(key) > len(suffix) + 1:
            return True
    if len(key) >= 5 and key[-1] in {"W", "U", "R"}:
        # e.g. QTEXW, CELUW, AENTW, QSEAR, ASPCR — keep 4-letter roots like MARA.
        return True
    return False


def is_blocked_symbol(symbol: str, *, exclude: frozenset[str]) -> bool:
    key = normalize_symbol_key(symbol)
    if not key:
        return True
    if is_non_common_share(key):
        return True
    return key in exclude


def merged_exclude_set(
    *,
    extra: frozenset[str] = frozenset(),
    exclude_leveraged_etfs: bool = True,
    exclude_large_caps: bool = False,
) -> frozenset[str]:
    base = DEFAULT_LEVERAGED_ETF_SYMBOLS if exclude_leveraged_etfs else frozenset()
    if exclude_large_caps:
        base = base | DEFAULT_LARGE_CAP_SYMBOLS
    return base | extra
