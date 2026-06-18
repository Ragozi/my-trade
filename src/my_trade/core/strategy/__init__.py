"""Strategy engine (deterministic, pure).

Phase 1 migration target for the prototype's `strategy.py`.

Contract: given clean DataFrames (1m/5m/15m), compute indicators and return a
typed `Signal | None` plus a structured `ScanEvaluation` (reasons/failures).
No network calls; inject the clock for testability. Shared by backtest AND live.
"""
