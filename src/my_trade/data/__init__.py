"""Data layer: market data access, normalization, and persistence (I/O only).

Phase 1 migration target for the data-fetch parts of the prototype's `broker.py`
plus `journal.py`.

Responsibilities:
  - Wrap Alpaca data clients; return tidy, time-indexed pandas DataFrames.
  - Detect crypto realities explicitly: empty bars, stale timestamps, volume==0.
  - Persist daily snapshots + a SQLite journal of events/trades for audit/dashboard.

NON-responsibility: this layer makes NO trading decisions.
"""
