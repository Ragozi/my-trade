"""Monitoring loop (deterministic). Phase 1 migration target for `main.py`'s loop.

Responsibilities:
  - Scheduler (e.g. 60s scan cycle).
  - Orchestrate: risk pre-checks -> data -> strategy -> risk sizing -> execution.
  - Manage open positions (time-stop, RSI exit) beyond the broker bracket.
  - Restart-safe daily state (no duplicate entries after a crash/restart).

Fail-safe: on any error/ambiguity/stale data, skip the cycle (do nothing).
"""
