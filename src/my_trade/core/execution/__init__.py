"""Execution adapter (deterministic). Phase 1 migration target for the order parts
of the prototype's `broker.py`.

Rules:
  - Submit Alpaca BRACKET orders only (entry + stop + take-profit atomically).
  - Idempotent: never double-submit for the same intended entry.
  - Honors PAPER_TRADING / ALLOW_LIVE_TRADING flags.
  - No naked entries, no averaging down.

This is the ONLY module (with core/risk) allowed to mutate orders/positions.
"""
