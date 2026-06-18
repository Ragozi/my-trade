"""Observability: logging, alerting, and metrics.

Phase 1/3 migration target for `utils.py` (logging) and `slack_notify.py`.

  - Structured logging (levels + rotation); quiet-by-default scan logs.
  - Slack alerts for material events only (entries, exits, errors, kill-switch,
    daily summary) — never per-scan spam.
  - Metrics/daily summary for backtest + live review.
"""
