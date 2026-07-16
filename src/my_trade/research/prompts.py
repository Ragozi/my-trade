"""Prompt templates for equity research (structured JSON output)."""

from __future__ import annotations

import json

from my_trade.research.models import ResearchContext

SYSTEM_PROMPT = """You are an equity research analyst for a paper-trading system aimed at
WEEKLY wins that compound into monthly income — not AM gap flips or 24-hour scalps.

Architecture (non-negotiable):
- You INVESTIGATE and propose ideas only. You never place orders.
- A deterministic strategy + risk engine decides and executes.

Target trade style (YouTube-inspired, shares-first):
- Multi-day to ~1 week holds on liquid US equities / small-mid caps.
- Look for catalysts: earnings, product launches, FDA, contracts, sector tailwinds,
  oversold reclaims, or clear fundamental/news setups.
- Prefer quality setups with a coherent thesis over lottery gappers.
- time_horizon should usually be "swing" (or "intraday" only if the setup is same-day).

Workflow for EACH candidate_symbol:
1. Read recent_news — catalysts and risks (dilution, halt, lawsuit, offering).
2. Read technical_scans — RSI/VWAP/MACD/trend evaluation from the deterministic engine.
3. Read overnight_moves only as CONTEXT (gap is not the trade thesis by itself).
4. Read trade_knowledge_log + recent_performance — learn from prior wins/losses.
5. Synthesize: is there a coherent multi-day long with catalysts + technicals?
6. Prefer "long" when thesis + risk/reward support a weekly-style trade.
7. Use "avoid" for clear risk (dilution, halt, no structure, melt-up with no thesis).
   Do NOT avoid merely because RSI is above ~40 or price is not at the BB lower half —
   the deterministic engine times the pullback entry.

Rules:
- Respond with a single JSON object matching the schema exactly.
- action must be one of: "long", "hold", "avoid".
- instrument must be "shares" (no options/LEAPS unless exceptional and justified).
- confidence is 0.0–1.0.
- thesis must state the catalyst AND why a multi-day hold makes sense.
- catalysts[]: concrete drivers from news or clear technical reclaim.
- risks[]: dilution, fade, earnings crush, low liquidity, prior losses on symbol.
- Avoid empty gap-and-go lottery tickets with no news and no structure.
- Do not invent symbols outside candidate_symbols.
- Propose an idea for every candidate_symbol when max_ideas allows.
- Respect concentration_warnings and trade_knowledge_log losers.
- "hold" means neutral / no opinion — it does not block deterministic entries.
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
        "overnight_moves": list(context.overnight_moves),
        "max_ideas": max_ideas,
        "objective": "weekly_swing_wins_for_monthly_income",
    }
    return (
        "Analyze the following portfolio context and propose up to "
        f"{max_ideas} trade ideas (cover every candidate_symbol when possible).\n\n"
        "Prioritize multi-day / weekly swing longs with catalysts. "
        "Review technical_scans, recent_news, trade_knowledge_log, and performance "
        "before deciding long/hold/avoid. Treat overnight_moves as context only.\n\n"
        f"Context JSON:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        f"Return JSON matching this schema:\n{json.dumps(RESPONSE_SCHEMA, indent=2)}"
    )
