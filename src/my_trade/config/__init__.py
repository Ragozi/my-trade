"""Config layer: typed settings loaded and validated from environment variables.

Phase 1 migration target for the prototype's `config.py`.
Rules:
  - No secrets in code; everything via env / .env (git-ignored).
  - Settings are frozen and validated at startup (fail fast on misconfig).
  - Live trading requires PAPER_TRADING=false AND ALLOW_LIVE_TRADING=true.
"""
