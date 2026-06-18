"""My-Trade: fully automated, paper-first algorithmic trading system.

Architecture (see ARCHITECTURE.md):
  - data/          : market data + cleaning + journal (I/O only)
  - core/          : DETERMINISTIC, safety-critical (strategy, risk, execution, monitoring)
  - research/      : Claude layer (Phase 4) — advisory only, never touches money
  - observability/ : logging, alerting, metrics
  - config/        : typed settings from env

This package is the *target* layout. The flat prototype modules at the repo root
(strategy.py, risk.py, broker.py, ...) migrate here in Phase 1 WITH TESTS FIRST.
"""

__version__ = "0.0.0"
