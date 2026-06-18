"""Dynamic universe scanner: $3–$24.99, volume filter, Alpaca screener."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Set, TYPE_CHECKING

from config import Settings
from journal import TradeJournal, save_universe_snapshot
from utils import get_logger, to_eastern

if TYPE_CHECKING:
    from broker import AlpacaBroker
    from risk import RiskManager


@dataclass
class ScannedSymbol:
    """Symbol that passed universe filters."""

    symbol: str
    price: float
    avg_volume: float
    source: str = "seed"


@dataclass
class ScanResult:
    """Full scan output for Slack and dashboard."""

    eligible: List[ScannedSymbol]
    sources_used: List[str]
    candidates_checked: int
    rejected_price: int = 0
    rejected_volume: int = 0

    def to_dict(self) -> dict:
        return {
            "scanned_at": to_eastern().isoformat(),
            "eligible_count": len(self.eligible),
            "candidates_checked": self.candidates_checked,
            "sources": self.sources_used,
            "rejected_price": self.rejected_price,
            "rejected_volume": self.rejected_volume,
            "symbols": [asdict(s) for s in self.eligible],
        }


class UniverseScanner:
    """
    Build tradeable universe from:
      - Alpaca most-actives (volume)
      - Alpaca market movers (gainers + losers)
      - Configured seed list (fallback / always merged)

    Filters: price $3–$24.99, 20-day avg volume >= 1.2M.
    """

    def __init__(
        self,
        settings: Settings,
        broker: "AlpacaBroker",
        journal: Optional[TradeJournal] = None,
        risk: Optional["RiskManager"] = None,
    ) -> None:
        self._s = settings
        self._broker = broker
        self._journal = journal
        if risk is None:
            from risk import RiskManager

            risk = RiskManager(settings)
        self._risk = risk
        self._log = get_logger()
        self._eligible: List[str] = []
        self._last_result: Optional[ScanResult] = None

    @property
    def eligible_symbols(self) -> List[str]:
        return list(self._eligible)

    @property
    def last_result(self) -> Optional[ScanResult]:
        return self._last_result

    def _build_candidate_pool(self) -> Dict[str, Set[str]]:
        """Merge screener + seeds into tagged candidate sets."""
        pool: Dict[str, Set[str]] = {
            "seed": set(self._s.scanner_seed_symbols),
            "most_actives": set(),
            "gainers": set(),
            "losers": set(),
        }
        if self._s.use_alpaca_screener:
            screener = self._broker.get_screener_candidates()
            pool["most_actives"] = set(screener.get("most_actives", []))
            pool["gainers"] = set(screener.get("gainers", []))
            pool["losers"] = set(screener.get("losers", []))
        return pool

    def _symbol_source(self, symbol: str, pool: Dict[str, Set[str]]) -> str:
        tags = [k for k, syms in pool.items() if symbol in syms]
        return "+".join(tags) if tags else "unknown"

    def passes_filters(self, price: float, avg_volume: float) -> bool:
        return (
            self._s.price_min <= price <= self._s.price_max
            and avg_volume >= self._s.min_avg_volume
        )

    def check_symbol(self, symbol: str, source: str) -> tuple[Optional[ScannedSymbol], str]:
        """Evaluate one symbol; returns (result, reject_reason code)."""
        price = self._broker.get_latest_price(symbol)
        avg_vol = self._broker.get_avg_daily_volume(
            symbol, days=self._s.volume_lookback_days
        )

        ok, msg = self._risk.check_universe(symbol, price, avg_vol)
        if not ok:
            if "outside" in msg:
                return None, "price"
            if "volume" in msg.lower():
                return None, "volume"
            return None, "other"

        assert price is not None and avg_vol is not None
        return ScannedSymbol(symbol=symbol, price=price, avg_volume=avg_vol, source=source), ""

    def scan(self) -> List[str]:
        """Run full universe scan; persist to journal and JSON."""
        pool = self._build_candidate_pool()
        all_symbols: Set[str] = set()
        for syms in pool.values():
            all_symbols.update(syms)

        sources_used = [k for k, v in pool.items() if v]
        passed: List[ScannedSymbol] = []
        rejected_price = 0
        rejected_volume = 0

        self._log.info(
            "Scanner: %d candidates from %s | filter $%.2f–$%.2f vol≥%s",
            len(all_symbols),
            ", ".join(sources_used) or "seeds",
            self._s.price_min,
            self._s.price_max,
            f"{self._s.min_avg_volume:,}",
        )

        for symbol in sorted(all_symbols):
            source = self._symbol_source(symbol, pool)
            try:
                result, reason = self.check_symbol(symbol, source)
                if result:
                    passed.append(result)
                elif reason == "price":
                    rejected_price += 1
                elif reason == "volume":
                    rejected_volume += 1
            except Exception as exc:
                self._log.debug("Scanner skip %s: %s", symbol, exc)

        passed.sort(key=lambda x: x.avg_volume, reverse=True)
        top = passed[: self._s.max_scanner_results]
        self._eligible = [s.symbol for s in top]

        self._last_result = ScanResult(
            eligible=top,
            sources_used=sources_used,
            candidates_checked=len(all_symbols),
            rejected_price=rejected_price,
            rejected_volume=rejected_volume,
        )

        snapshot = self._last_result.to_dict()
        save_universe_snapshot("logs/last_universe.json", snapshot)

        if self._journal:
            self._journal.log_universe_scan(snapshot["symbols"], sources_used)
            self._journal.log_event(
                "universe_scan",
                f"{len(self._eligible)} eligible from {len(all_symbols)} candidates",
                metadata=snapshot,
            )

        if self._eligible:
            summary = ", ".join(f"{s.symbol}@${s.price:.2f}" for s in top[:12])
            self._log.info("Scanner: %d eligible — %s", len(self._eligible), summary)
        else:
            self._log.warning("Scanner: no symbols passed filters")

        return self._eligible
