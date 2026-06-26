"""Standalone one-shot Claude research run (no orders).

Run with:  python -m scripts.research_run   (or: poe research)

Fetches live account context, builds portfolio-aware prompt payload, and prints
the advisory proposal as JSON. Uses mock client when ENABLE_CLAUDE=false or
--mock is passed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.config import load_settings  # noqa: E402
from my_trade.core.monitoring.alpaca_account import AlpacaAccountProvider  # noqa: E402
from my_trade.core.monitoring.state import (  # noqa: E402
    DailyState,
    build_account_state,
    rollover_if_new_day,
    update_peak,
)
from my_trade.core.monitoring.store import DailyStateStore  # noqa: E402
from my_trade.research.advisor import ResearchAdvisor, ResearchConfig  # noqa: E402
from my_trade.research.client import MockClaudeResearchClient  # noqa: E402
from my_trade.research.context import build_research_context  # noqa: E402
from my_trade.research.factory import (  # noqa: E402
    build_research_advisor,
    build_research_client,
    build_research_evaluation,
    build_research_memory,
)
from my_trade.research.rate_limit import ResearchRateLimiter  # noqa: E402

log = logging.getLogger("my_trade.research_run")


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _candidate_symbols(settings) -> tuple[str, ...]:
    return settings.symbols


def _open_risk_dollars(snapshot, state, fallback_stop_pct: float) -> float:
    from my_trade.data import normalize_symbol

    total = 0.0
    for pos in snapshot.positions:
        sym = normalize_symbol(pos.symbol)
        stop = state.position_stops.get(sym)
        if stop is None:
            stop = pos.avg_entry_price * (1.0 - fallback_stop_pct)
        risk_per_share = pos.avg_entry_price - stop
        if risk_per_share > 0:
            total += risk_per_share * pos.qty
    return total


def run_once(*, mock: bool, verbose: bool) -> int:
    settings = load_settings()
    setup_logging(verbose)

    if (
        settings.asset_class != "equities"
        and settings.research.equities_only
        and not mock
    ):
        log.error(
            "Claude research is equities-only (ASSET_CLASS=%s). "
            "Set ASSET_CLASS=equities or CLAUDE_EQUITIES_ONLY=false.",
            settings.asset_class,
        )
        return 1

    account = AlpacaAccountProvider(
        settings.alpaca.api_key,
        settings.alpaca.api_secret,
        paper=settings.alpaca.paper_trading,
    )
    snapshot = account.get_snapshot()
    store = DailyStateStore(settings.runtime.daily_state_file)
    state = store.load() or DailyState.empty()
    now = datetime.now(UTC)
    state = rollover_if_new_day(state, now.date(), snapshot.equity)
    state = update_peak(state, snapshot.equity)
    account_state = build_account_state(
        snapshot, state, settings.strategy.stop_loss_pct
    )

    candidates = _candidate_symbols(settings)

    if mock or not settings.research.enabled:
        client = MockClaudeResearchClient()
        advisor = ResearchAdvisor(
            client,
            ResearchConfig(enabled=True, min_confidence=settings.research.min_confidence),
            rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=999),
        )
        log.info("using mock research client")
    else:
        advisor = build_research_advisor(settings)
        if advisor is None:
            log.error("Research enabled but advisor could not be built (check API keys)")
            return 1

    from my_trade.research.brief import load_brief
    from my_trade.research.factory import build_postmortem_client

    pm_client = build_postmortem_client(settings)
    memory = build_research_memory(settings, client=pm_client)
    evaluation = build_research_evaluation(settings)
    daily_brief = load_brief(settings.research.brief_file)

    sym_set = frozenset(s.upper() for s in candidates)
    recent_reflections = ()
    performance = None
    if memory is not None:
        memory.enrich_from_journal(
            settings.runtime.journal_db, candidate_symbols=candidates
        )
        recent_reflections = memory.recent_reflections(limit=10, symbols=sym_set)
        performance = memory.performance_summary(symbols=sym_set)

    comparison_summary = evaluation.summary() if evaluation is not None else None

    context = build_research_context(
        snapshot=snapshot,
        candidate_symbols=candidates,
        asset_class=settings.asset_class,
        session_open=True,
        as_of=now,
        equity=account_state.equity,
        day_pnl=account_state.realized_day_pnl,
        peak_equity=account_state.peak_equity,
        open_risk_dollars=_open_risk_dollars(
            snapshot, state, settings.strategy.stop_loss_pct
        ),
        recent_reflections=recent_reflections,
        performance=performance,
        comparison_summary=comparison_summary,
        daily_brief=daily_brief,
    )

    result = advisor.propose(context, when=now)
    proposal = result.proposal

    output = {
        "called_api": result.called_api,
        "rate_limited": result.rate_limited,
        "skipped": proposal.skipped,
        "skip_reason": proposal.skip_reason,
        "summary": proposal.summary,
        "model": proposal.model,
        "provider": proposal.provider,
        "latency_ms": proposal.latency_ms,
        "ideas": [i.model_dump() for i in proposal.ideas],
        "portfolio": context.portfolio.model_dump() if context.portfolio else None,
        "comparison_summary": (
            comparison_summary.model_dump() if comparison_summary else None
        ),
    }
    print(json.dumps(output, indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one Claude research cycle.")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock client even when ENABLE_CLAUDE=true",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run_once(mock=args.mock, verbose=args.verbose))


if __name__ == "__main__":
    main()
