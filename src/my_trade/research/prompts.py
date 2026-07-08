"""Prompt templates for equity research (structured JSON output)."""

from __future__ import annotations

import json

from my_trade.research.models import ResearchContext

SYSTEM_PROMPT = """You are an equity research analyst for a paper-trading system focused on
US intraday momentum — especially small/mid caps ($2–$20) ripping in the opening range.

You investigate setups BEFORE any trade is placed — you never place orders.

Workflow you must follow for EACH candidate_symbol:
1. Read technical_scans — deterministic RSI/VWAP/MACD/trend pattern evaluation.
2. Read recent_news — headlines and summaries (catalysts, PR, sector sympathy, halts).
3. Read trade_knowledge_log and recent_performance — what won/lost on this name recently.
4. Synthesize: is there a coherent INTRADAY momentum play (opening drive, VWAP reclaim,
   volume surge, news catalyst)? If not, say avoid or hold.
5. Only propose action "long" when pattern + volume + catalyst align for a same-day trade;
   prefer time_horizon "intraday" for these names.

Rules:
- Respond with a single JSON object matching the schema exactly.
- Prioritize liquid AM gainers and wild movers — NOT mega-cap semis unless explicitly listed.
- action must be one of: "long", "hold", "avoid".
- instrument must be "shares" for intraday (no options unless exceptional).
- confidence is 0.0–1.0 (conviction in the setup, not position size).
- thesis must reference pattern read AND any relevant news (or explicitly note no news).
- catalysts[]: concrete drivers from recent_news (PR, earnings, sympathy, sector move).
- risks[]: dilution, halts, fade after open, low float trap, prior losses on symbol.
- Be selective but not paralyzed: "long" when AM momentum + technicals align; avoid chip slow grinds.
- Do not invent symbols outside candidate_symbols.
- Propose an idea for every candidate_symbol when max_ideas allows (full watchlist coverage).
- Learn from trade_knowledge_log: reduce confidence on repeat losers; respect concentration_warnings.
"""

RESPONSE_SCHEMA = {
    "summary": "string — one-line overview of market read",
    "ideas": [
        {
            "symbol": "TICKER",
            "action": "long|hold|avoid",
            "confidence": 0.0,
            "instrument": "shares|options|leaps",
            "thesis": "string",
            "time_horizon": "intraday|swing|position",
            "suggested_stop_pct": 0.02,
            "suggested_target_pct": 0.05,
            "catalysts": ["string"],
            "risks": ["string"],
        }
    ],
}


def build_user_prompt(context: ResearchContext, *, max_ideas: int) -> str:
    reflections = [
        {
            "symbol": r.symbol,
            "closed_at": r.closed_at.isoformat(),
            "outcome": r.outcome,
            "pnl_estimate": r.pnl_estimate,
            "exit_reason": r.exit_reason,
            "thesis_at_entry": r.thesis_at_entry,
            "summary": r.summary,
        }
        for r in context.recent_reflections
    ]
    performance = (
        context.performance.model_dump() if context.performance is not None else None
    )
    portfolio = (
        context.portfolio.model_dump() if context.portfolio is not None else None
    )
    comparison = (
        context.comparison_summary.model_dump()
        if context.comparison_summary is not None
        else None
    )
    payload = {
        "as_of": context.as_of.isoformat(),
        "asset_class": context.asset_class,
        "equity": context.equity,
        "day_pnl": context.day_pnl,
        "peak_equity": context.peak_equity,
        "open_risk_dollars": context.open_risk_dollars,
        "open_risk_pct": round(context.open_risk_pct, 4),
        "session_open": context.session_open,
        "open_positions": [p.model_dump() for p in context.open_positions],
        "candidate_symbols": list(context.candidate_symbols),
        "recent_reflections": reflections,
        "recent_performance": performance,
        "portfolio_snapshot": portfolio,
        "claude_vs_strategy": comparison,
        "daily_brief": context.daily_brief,
        "trade_knowledge_log": list(context.trade_knowledge),
        "technical_scans": list(context.technical_scans),
        "recent_news": list(context.recent_news),
        "max_ideas": max_ideas,
    }
    return (
        "Analyze the following portfolio context and propose up to "
        f"{max_ideas} trade ideas (cover every candidate_symbol when possible).\n\n"
        "For each symbol: review technical_scans (pattern math), recent_news "
        "(catalysts), trade_knowledge_log (past wins/losses), and performance "
        "before deciding long/hold/avoid.\n\n"
        f"Context JSON:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        f"Return JSON matching this schema:\n{json.dumps(RESPONSE_SCHEMA, indent=2)}"
    )
