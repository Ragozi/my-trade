"""Claude research layer (Phase 4) — ADVISORY ONLY, guardrailed.

Hard guardrails (enforced by design + guard tests):
  - MUST NOT import my_trade.core.execution or mutate risk configuration.
  - Cannot submit/modify/cancel orders or change risk limits. Ever.
  - Every Claude response is JSON and schema-validated (pydantic).
    Invalid / late / over-budget -> discarded; system runs deterministic-only.
  - Fully disabled by ENABLE_CLAUDE=false with zero change to core behavior.

Allowed outputs (advisory):
  - candidate screening (core still applies its own filters)
  - catalyst / news / thesis summaries (attached to journal + alerts)
  - daily portfolio commentary (read-only)
  - optional confidence score / VETO that can only SUPPRESS a deterministic
    signal, never create or size one.
"""
