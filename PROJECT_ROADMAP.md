# PROJECT_ROADMAP.md — My-Trade

> Phased build plan. **Deterministic core first, Claude last.**
> Each phase has an **Exit Gate** that must be 100% green before advancing.
> See `SCOPE.md` for risk rules and success criteria, `ARCHITECTURE.md` for design.

```
Phase 0  Foundations            ← we are here
Phase 1  Deterministic Core MVP
Phase 2  Backtesting & Validation
Phase 3  Paper Hardening (reliability + observability)
Phase 4  Claude Research Layer (guardrailed, advisory)
Phase 5  Live (small size) + ongoing ops
```

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Phase 0 — Foundations (current)

**Goal:** establish a professional, safe project skeleton and the documents that
govern everything else. No trading logic changes.

**Deliverables**
- [x] `SCOPE.md`, `PROJECT_ROADMAP.md`, `ARCHITECTURE.md`
- [x] Target package layout scaffolded (`src/my_trade/...`, `tests/`)
- [ ] First git commit on `main` (foundation only)
- [ ] `pyproject.toml` with dev tooling config (ruff, mypy, pytest) — *Phase 1 ok*
- [ ] Owner fills decisions table D1–D10 in `SCOPE.md`
- [ ] Confirm `.env` is git-ignored and **rotate any key that was ever pasted in chat**

**Exit Gate**
- [ ] All three governance docs reviewed by owner.
- [ ] Decisions D1–D10 recorded.
- [ ] Clean initial commit pushed to GitHub; no secrets in history.

---

## Phase 1 — Deterministic Core MVP

**Goal:** a tested, importable package that can run the existing strategy in paper
mode through clean, layered modules. Harden the prototype — don't rewrite blindly.

**Build (in this order — Risk Engine FIRST, it is the highest-priority core):**
1. **Risk engine** (`core/risk`) — ⭐ **start here**. Risk-based sizing (R1),
   max-total-open-risk cap (R2), daily-loss halt (R3), max-drawdown circuit
   breaker (R4), max positions, duplicate-entry guard, bracket price calc.
   **Rebuilt from scratch, test-first — do NOT migrate the old `risk.py`.**
   Pure functions wherever possible.
2. **Config layer** (`config/`): typed settings from env, validated, no secrets in code.
3. **Data layer** (`data/`): Alpaca bars/quotes wrapper returning clean DataFrames;
   explicit handling of empty/stale/`volume=0` crypto bars.
4. **Strategy** (`core/strategy`): indicators + entry/exit evaluation returning a
   typed `Signal | None` + structured reasons. No I/O. (Migrate prototype `strategy.py`, test-first.)
5. **Execution** (`core/execution`): Alpaca order adapter; bracket orders only;
   idempotent; paper/live toggle.
6. **Monitoring loop** (`core/monitoring`): scheduler, scan cycle, position
   management, restart-safe daily state.
7. **Journal** (`data/` or `observability`): SQLite event/trade log.

**Migration approach:**
- The **risk engine is rebuilt fresh** with tests first (the prototype's fixed-notional
  `risk.py` does not match the new risk-based model in `SCOPE.md` §5b).
- Other modules (strategy, data, execution) are **migrated** from the prototype into
  their package home *with a behavior-pinning test written first*, then refactored.

**Exit Gate**
- [ ] `pip install -e .` works; `python -m my_trade ...` (or CLI) runs paper loop.
- [ ] Unit tests for risk engine + strategy + data edge cases; `core/` coverage ≥ 85%.
- [ ] No backtest-only code paths (strategy/risk shared with live).
- [ ] Lint + type-check + tests green locally.

---

## Phase 2 — Backtesting & Validation

**Goal:** trust the strategy numerically before risking even paper reputation.

**Deliverables**
- [ ] Walk-forward backtester reusing the **exact** strategy/risk modules.
- [ ] Metrics report: trades, win-rate, avg R, profit factor, max drawdown, exposure.
- [ ] Deterministic, reproducible runs (seeded, pinned data window).
- [ ] Backtest results checked into `docs/backtests/` (CSV + summary).

**Exit Gate**
- [ ] ≥ 90 days backtest completes cleanly.
- [ ] Drawdown within owner tolerance (SCOPE §6).
- [ ] Results documented and reviewed.

---

## Phase 3 — Paper Hardening (reliability + observability)

**Goal:** run unattended in paper for weeks without surprises.

**Deliverables**
- [ ] Structured logging (levels, rotation) + quiet-by-default scan logs.
- [ ] Alerting (Slack) for: entries, exits, errors, kill-switch, daily summary.
- [ ] Restart safety: state persists; no duplicate entries after crash/restart.
- [ ] Health checks / heartbeat; graceful shutdown; flatten-on-demand command.
- [ ] Read-only monitoring dashboard (existing `dashboard/` hardened).

**Exit Gate**
- [ ] 30 consecutive paper days, no unhandled crash.
- [ ] Kill switch + restart safety demonstrated and documented.

---

## Phase 4 — Claude Research Layer (guardrailed, advisory)

**Goal:** add non-deterministic intelligence **without** giving it any execution
or risk authority. Mirrors the "deterministic + non-deterministic" split.

**Deliverables**
- [ ] `research/` package: Claude client wrapper (Anthropic API), retries, timeouts.
- [ ] **Strict output contracts**: every Claude response is JSON, schema-validated
      (e.g. pydantic). Invalid → discarded, system degrades to deterministic-only.
- [ ] Capabilities (advisory only):
  - Candidate screening (proposes symbols/watchlist — core still filters).
  - Catalyst/news/thesis summaries attached to journal + alerts.
  - Daily portfolio commentary (read-only).
  - Optional **veto/confidence score** that can *block* a trade but never *create* one.
- [ ] Cost controls: cache, rate-limit, "once per cycle/day" budgets.
- [ ] Kill flag: `ENABLE_CLAUDE=false` fully disables the layer with no behavior change to core.

**Exit Gate**
- [ ] Claude layer can be toggled off with zero impact on deterministic safety.
- [ ] Tests prove invalid/malicious Claude output cannot place/modify orders or limits.
- [ ] Cost per day measured and within budget.

---

## Phase 5 — Live (small size) + Ops

**Goal:** carefully go live with minimal capital and strong controls.

**Deliverables**
- [ ] Live keys configured; `PAPER_TRADING=false` + `ALLOW_LIVE_TRADING=true`.
- [ ] Position sizing starts at a fraction of paper size.
- [ ] Runbook: how to start/stop/flatten/rotate-keys/respond-to-incident.
- [ ] Daily + weekly performance review loop.

**Exit Gate (to scale up)**
- [ ] Live behavior matches paper expectations over a defined trial.
- [ ] No risk-rule violations observed.

---

## Cross-cutting (every phase)
- Conventional commits; PRs small and reviewable.
- CI green before merge.
- No secret ever committed; keys rotated if exposed.
- Update `SCOPE.md` when scope changes — docs lead code.
