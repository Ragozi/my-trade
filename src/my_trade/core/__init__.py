"""Deterministic core — the ONLY layer permitted to move money.

Safety-critical and fully unit-tested (gate: >= 85% coverage on core/).

Subpackages:
  - models      : typed contracts (Signal, TradePlan, ScanEvaluation, ...)
  - strategy/   : indicators + entry/exit evaluation (pure: data in -> decision out)
  - risk/       : sizing, daily-loss halt, max positions, bracket price calc
  - execution/  : Alpaca bracket-order adapter (idempotent, paper/live)
  - monitoring/ : scan loop, scheduler, position management, restart-safe state

Invariant: nothing in research/ may import execution/ or mutate risk config.
"""
