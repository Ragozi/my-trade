"""Prompt templates for equity research (structured JSON output)."""

from __future__ import annotations

import json

from my_trade.research.models import ResearchContext

SYSTEM_PROMPT = """You are an equity research assistant for a paper-trading system.
You propose trade ideas ONLY — you never place orders.

Rules:
- Respond with a single JSON object matching the schema exactly.
- Focus on US equities. Prefer liquid large/mid caps from the candidate list.
- action must be one of: "long", "hold", "avoid".
- instrument must be one of: "shares", "options", "leaps".
- confidence is 0.0–1.0 (how strong the setup is, not position size).
- For options/LEAPs, still name the underlying symbol; note instrument in the field.
- Be conservative: "avoid" or "hold" when uncertain.
- Do not invent symbols outside candidate_symbols.
- You receive recent trade outcomes and performance stats. Learn from them:
  reduce confidence on symbols/setups that recently lost; favor what worked.
  If win_rate is low, prefer "hold"/"avoid" unless the setup is clearly improved.
- portfolio_snapshot shows sector concentration; heed concentration_warnings — avoid
  adding correlated exposure when a sector is already heavy.
- claude_vs_strategy shows how often your ideas align with the deterministic
  strategy; when strategy_only entries outperform, be more selective on "long".
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
        "max_ideas": max_ideas,
    }
    return (
        "Analyze the following portfolio context and propose up to "
        f"{max_ideas} trade ideas.\n\n"
        "Use daily_brief (pre-digested journal stats), recent_reflections, "
        "recent_performance, portfolio_snapshot, and claude_vs_strategy "
        "to adjust your suggestions.\n\n"
        f"Context JSON:\n{json.dumps(payload, indent=2, default=str)}\n\n"
        f"Return JSON matching this schema:\n{json.dumps(RESPONSE_SCHEMA, indent=2)}"
    )
