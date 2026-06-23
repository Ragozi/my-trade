# SCOPE.md — My-Trade Automated Trading System

> Status: **Phase 0 — Foundations**
> Last updated: 2026-06-17
> Owner: @Ragozi

This document defines *what we are building and why*. It is the single source of
truth for scope. If a proposed feature is not covered here (or in the roadmap),
it does not get built until this document is updated.

---

## 1. Overall Goal

Build a **fully automated, paper-first algorithmic trading system** that:

- Executes trades on **Alpaca** (data + execution).
- Uses **Claude (Anthropic API)** strictly as a *research/insight* layer (screening,
  catalyst research, thesis generation, daily commentary).
- Has **zero human-in-the-loop at execution time** once a strategy is approved and
  promoted — but every automated decision is gated by a deterministic risk engine.
- Is **rigorously testable, backtestable, observable, and version-controlled**.

### One-sentence mission
> A deterministic trading core that is safe by default, with an optional,
> tightly-guardrailed Claude research layer that can *advise* but can **never**
> place an order or change a risk limit.

---

## 2. Non-Negotiable Principles

1. **Deterministic-first.** The core (risk, sizing, execution, monitoring, exits)
   is plain, testable Python with fixed rules. It is built and validated *before*
   any AI layer is added.
2. **Claude never touches money.** The non-deterministic layer produces
   *structured, validated suggestions only*. It cannot submit, modify, or cancel
   orders, and cannot change risk parameters. (See `ARCHITECTURE.md` → Guardrails.)
3. **Paper before live.** Live trading is unlocked only after explicit success
   gates are met (Section 6) and requires two separate env flags.
4. **Fail safe, not open.** On any error, ambiguity, stale data, or missing
   confirmation, the system does **nothing** (no trade) rather than guessing.
5. **Everything reproducible.** Same inputs → same deterministic decisions.
   Backtests and live logic share the same strategy/risk code paths.
6. **Small, gated phases.** Each phase has a clear exit gate. We do not advance
   until the gate passes.

---

## 3. Deterministic Core vs Non-Deterministic Layer

| Concern | Deterministic Core (always) | Non-Deterministic Layer (later, optional) |
|---|---|---|
| Position sizing | ✅ Fixed rules / formulas | ❌ Never |
| Order submission / cancel | ✅ Only here | ❌ Never |
| Stop-loss / take-profit / time-stop | ✅ Only here | ❌ Never |
| Daily loss limit & kill switches | ✅ Only here | ❌ Never |
| Entry signal (technical rules) | ✅ Primary | ⚠️ May *veto* or *score*, never *force* |
| Universe / candidate screening | ⚙️ Optional rules-based | ✅ Claude may propose candidates |
| Catalyst / news / thesis research | ❌ | ✅ Claude (advisory text + structured fields) |
| Daily portfolio commentary | ❌ | ✅ Claude (read-only insight) |
| Logging, metrics, alerting | ✅ | ⚙️ May enrich messages only |

**Rule of thumb:** if a component can *lose money* or *increase risk*, it lives in
the deterministic core and is covered by tests. Claude output is treated like an
untrusted external input: schema-validated, bounded, and advisory.

---

## 4. Current State (honest assessment)

- **Deterministic core (Phases 1–3)** is implemented in `src/my_trade/`: risk, strategy,
  execution, monitoring orchestrator, screener, journal, paper runner, operator UI.
- **Phase 4 research layer** is implemented in `src/my_trade/research/` (Claude client,
  advisor, memory/reflection, evaluation, portfolio-aware prompts). Advisory-only by
  default (`CLAUDE_REQUIRE_APPROVAL=false`).
- **Activation:** set `ASSET_CLASS=equities`, `ENABLE_CLAUDE=true`, and a valid
  `ANTHROPIC_API_KEY`. See `docs/PHASE4_ACTIVATION.md`.
- Legacy flat modules (`strategy.py`, `main.py` at repo root) remain as reference;
  the paper loop runs via `scripts/paper_trade.py`.
- Claude **never** calls Alpaca; orders flow only through the deterministic execution adapter.

---

## 5. Decisions Required From the Owner (only you can set these)

> ⚠️ **ACTION NEEDED:** review the **Recommended** column and confirm or adjust each
> value, then fill in "Your value". These numbers drive the deterministic risk
> engine, so they must be your real intended limits.

**Account assumption:** real capital **$12,000** (paper account mirrors the same
size so paper results translate directly to live).

### 5a. Account & strategy

| # | Decision | Recommended | Your value |
|---|---|---|---|
| D1 | Primary asset / market | BTC/USD (Alpaca Crypto, 24/7) | _confirm_ |
| D2 | Account & mode | Alpaca **paper** first, then live | _confirm_ |
| D3 | Capital | **$12,000** (paper mirrors live size) | _confirm_ |
| D4 | Position-sizing model | **Risk-based (% of equity)** — *not* fixed notional | _confirm_ |
| D5 | Max concurrent positions | **1** (open-risk cap also applies) | _confirm_ |
| D6 | Per-trade exit | Stop defines $ risk; take-profit target **1.5–2.0R** | _confirm_ |
| D7 | Max trades per day | **10** (conservative; was 50 in prototype) | _confirm_ |
| D8 | Strategy family | VWAP+RSI+MACD+Bollinger pullback | _confirm_ |
| D9 | Go-live gate (see §6) | All gates green for **30 paper days** | _confirm_ |

### 5b. Risk limits (conservative defaults for a $12,000 account)

These are the core safety dials. Dollar figures below assume **$12,000 equity**
and update automatically as equity changes (they are percentages, not fixed $).

| # | Risk limit | Recommended | On $12,000 | Your value |
|---|---|---|---|---|
| R1 | **Max risk per trade** | **2%** of *current* equity | ≈ **$240** | _confirm_ |
| R2 | **Max total open risk** | **7%** of equity | ≈ **$840** | _confirm_ |
| R3 | **Daily loss limit** (halt new entries) | **5%** of start-of-day equity | ≈ **$600** | _confirm_ |
| R4 | **Max-drawdown circuit breaker** (halt ALL trading, manual reset) | **15%** from peak equity | ≈ **$1,800** | _confirm_ |

**Plain-English meaning**
- **R1** — Position size is computed so that *if the stop is hit*, you lose at most
  ~$240. Sizing = `risk_dollars / (entry − stop)`. Risk never scales with conviction
  or any AI score.
- **R2** — The sum of open risk across all live positions may never exceed ~$840.
  A new trade is rejected if it would push total open risk over the cap.
- **R3** — Once realized losses for the day reach ~$600, **no new entries** open for
  the rest of the day. Protective brackets on existing positions stay active.
- **R4** — If equity falls 15% below its all-time peak (~$1,800 down from a $12k
  peak), the bot **halts all trading** and requires a manual reset after review.

**Professional note (for your decision):** 2% risk per trade is the classic upper
bound. For a *high-frequency crypto scalper* with up to 10 trades/day, combining 2%
per trade with a 5% daily stop means roughly **2–3 full-stop losses ends the day** —
that is intentionally conservative and sane. If you later find the strategy trades
very frequently, consider lowering R1 to **1%** to smooth equity. Start at the
recommended values; tighten, don't loosen.

Update the "Your value" columns before exiting Phase 1.

---

## 6. Success Criteria & Gates

A strategy may **only** be promoted (paper→live, or version→version) when **all**
of the following are true. These are deliberately strict.

### Code / safety gates (every phase)
- [ ] All deterministic-core modules have unit tests; coverage ≥ 85% on `core/`.
- [ ] Risk engine has tests for: daily-loss halt, max-positions, sizing, dup-entry.
- [ ] No secret is ever committed (`.env` git-ignored; verified).
- [ ] CI runs lint + type-check + tests on every push and is green.

### Backtest gates (before paper)
- [ ] Walk-forward backtest over ≥ 90 days of data completes with no errors.
- [ ] Strategy + risk use the **same** code path as live (no backtest-only logic).
- [ ] Reported metrics: trades, win-rate, avg R, max drawdown, profit factor.
- [ ] Max drawdown within tolerance (must stay above the **R4 circuit breaker = 15%** from peak).

### Paper-trading gates (before live)
- [ ] ≥ 30 consecutive calendar days running in paper without an unhandled crash.
- [ ] Restart-safety verified (state survives process restart; no double-entries).
- [ ] Daily-loss kill switch verified to actually halt new entries.
- [ ] Observability: every order, fill, exit, and skip is logged + alertable.
- [ ] Realized paper performance meets owner-defined bar (DECISION D10).

### Live gates (ongoing)
- [ ] `PAPER_TRADING=false` **and** `ALLOW_LIVE_TRADING=true` both set explicitly.
- [ ] Position sizes start at a fraction of paper size.
- [ ] A documented manual kill switch (stop process + flatten) is tested.

---

## 7. Hard Risk Rules (enforced in deterministic core)

These are invariants. They are enforced in code and covered by tests, not by docs.
All percentages are evaluated against *live* equity (or start-of-day / peak as noted).

1. **Risk-based sizing (R1).** Quantity is chosen so that
   `(entry − stop) × qty ≤ max_risk_per_trade_pct × equity`. Risk never scales with
   conviction or any AI score. If the stop is invalid (`stop ≥ entry` for a long),
   **no trade**.
2. **Max total open risk (R2).** A new entry is rejected if it would push the sum of
   open risk across all positions above `max_total_open_risk_pct × equity`.
3. **Daily loss limit (R3).** When realized day P&L ≤ −(daily_loss_limit_pct ×
   start-of-day equity), **no new entries** for the rest of the day. Existing
   protective brackets remain.
4. **Max-drawdown circuit breaker (R4).** When equity ≤ (1 − max_drawdown_pct) ×
   peak equity, **halt ALL trading** and require an explicit manual reset.
5. **Max concurrent positions** = D5.
6. **Every entry ships with a bracket** (stop + take-profit) atomically. No naked
   entries.
7. **No averaging down.** No adding to losers.
8. **Stale/empty data ⇒ no trade.** Missing bars, NaN indicators, or failed fetch
   ⇒ skip this cycle.
9. **Claude unavailable / invalid output ⇒ degrade to deterministic-only.** The AI
   layer is never a hard dependency for safety.

**Evaluation order** (first failure wins, fail-safe): circuit breaker → daily loss
limit → max positions → compute size → max open-risk cap → approve.

---

## 8. Explicit Non-Goals (for now)

- ❌ High-frequency / sub-second trading.
- ❌ Shorting, margin, leverage, or derivatives (until explicitly scoped).
- ❌ Multi-broker support.
- ❌ Letting Claude place or size trades (ever, by design).
- ❌ A fancy web trading UI (a read-only monitoring dashboard is enough).

---

## 9. Glossary

- **Deterministic core** — rule-based code; same input → same output; fully tested.
- **Non-deterministic layer** — Claude-powered; advisory; schema-validated.
- **Gate** — a checklist that must be 100% green to advance a phase or promote a strategy.
- **Bracket order** — entry + attached stop-loss + take-profit submitted together.

---

_See `PROJECT_ROADMAP.md` for the phased build plan and `ARCHITECTURE.md` for the
system design._
