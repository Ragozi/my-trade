"""Symbol hygiene for universe construction — no I/O, fully testable."""

from __future__ import annotations

# Common 2x/3x and inverse ETFs that break pullback math (decay, gap risk).
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


def is_blocked_symbol(symbol: str, *, exclude: frozenset[str]) -> bool:
    key = normalize_symbol_key(symbol)
    if not key:
        return True
    return key in exclude


def merged_exclude_set(
    *,
    extra: frozenset[str] = frozenset(),
    exclude_leveraged_etfs: bool = True,
) -> frozenset[str]:
    base = DEFAULT_LEVERAGED_ETF_SYMBOLS if exclude_leveraged_etfs else frozenset()
    return base | extra
