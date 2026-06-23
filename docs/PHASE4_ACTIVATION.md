# Phase 4 Activation Guide — Claude Research (Advisory Mode)

> **Goal:** Turn on Claude as an **advisory-only** research layer on **equities paper trading**.
> Claude proposes ideas and learns from closed trades; the deterministic strategy + risk engine still controls every order.

---

## What Phase 4 Does (and Does Not Do)

| Claude **can** | Claude **cannot** |
|----------------|-------------------|
| Propose long/hold/avoid ideas with thesis + confidence | Submit, modify, or cancel orders |
| Read portfolio context (equity, positions, day P&L) | Change risk limits or position sizing |
| Learn from closed trades via `research_memory.json` | Force an entry (unless you later enable approval gate) |
| Log proposals to journal + Activity UI | Run on crypto when `CLAUDE_EQUITIES_ONLY=true` (default) |

**Advisory mode** = `CLAUDE_REQUIRE_APPROVAL=false` (default). Strategy must still fire; Claude enriches context and builds memory.

**Approval mode** (later) = `CLAUDE_REQUIRE_APPROVAL=true`. Strategy + Claude long signal required.

---

## Cost control (read this first)

The trading loop scans every **60 seconds**, but Claude should **not** be called every scan.

| Variable | Conservative | Purpose |
|----------|--------------|---------|
| `ENABLE_CLAUDE` | `false` | Instant off — trading unaffected |
| `CLAUDE_CALL_INTERVAL_SECONDS` | `1800` (30 min) | Minimum gap between API calls |
| `CLAUDE_MAX_CALLS_PER_DAY` | `8` | Hard daily cap |
| `CLAUDE_MARKET_HOURS_ONLY` | `true` | Skip nights/weekends |
| `CLAUDE_MAX_IDEAS` | `3` | Smaller prompts |
| `CLAUDE_MAX_TOKENS` | `2048` | Shorter responses |
| `CLAUDE_POSTMORTEM_ENABLED` | `false` | Avoid extra calls on exit |

**Out-of-credits protection:** failed billing errors now trigger a **1-hour cooldown** (`CLAUDE_BILLING_COOLDOWN_SECONDS=3600`) and count against limits. Previously, failures retried every 60s and wasted quota.

**Pause Claude, keep trading:** `ENABLE_CLAUDE=false` → restart paper bot.

---

## Recommended `.env` (Phase 4 advisory, equities paper)

Copy from `.env.example` or add these blocks. **Never commit real API keys.**

```env
# --- Asset class (Phase 4 requires equities) ---
ASSET_CLASS=equities
CRYPTO_MODE=false
EQUITY_SYMBOLS=AAPL,MSFT,NVDA,AMD,TSLA

# --- Phase 4: Claude research (advisory) ---
ENABLE_CLAUDE=true
ANTHROPIC_API_KEY=your_key_here
CLAUDE_MODEL=claude-sonnet-4-20250514
CLAUDE_REQUIRE_APPROVAL=false
CLAUDE_EQUITIES_ONLY=true
CLAUDE_CALL_INTERVAL_SECONDS=1800
CLAUDE_MAX_CALLS_PER_DAY=8
CLAUDE_MARKET_HOURS_ONLY=true
CLAUDE_MAX_IDEAS=3
CLAUDE_MAX_TOKENS=2048
CLAUDE_MIN_CONFIDENCE=0.55

# Learning / evaluation files (auto-created under logs/)
CLAUDE_MEMORY_FILE=logs/research_memory.json
CLAUDE_EVALUATION_FILE=logs/research_evaluation.json
CLAUDE_POSTMORTEM_ENABLED=false
```

Optional screener for equities (uses `EQUITY_SYMBOLS` or Alpaca movers):

```env
USE_SCREENER=true
SCREENER_TOP_N=5
SCREENER_USE_MOVERS=true
SCREENER_MOVERS_SOURCE=actives
```

**Instant off switch:** `ENABLE_CLAUDE=false` → zero Anthropic calls, zero behavior change to risk/execution.

---

## Start the Bot

1. Confirm Alpaca paper keys and `PAPER_TRADING=true`.
2. Apply `.env` changes above; restart any running bot.
3. Start stack:
   - **Windows:** `Launch My-Trade.bat`
   - **CLI:** `poe paper` (loop) or `poe paper --once` (single cycle smoke test)
4. **One-shot research (no orders):** `poe research --mock` or `poe research` (live Claude call)

Console should show:

```
Claude research ENABLED | model=... interval=300s require_approval=False ...
Starting PAPER trading | asset_class=equities symbols=...
```

During market hours, every ~5 min (or your interval):

```
CLAUDE research | 3 ideas (2 long) | summary: ...
  - research_proposal   AAPL       long conf=0.72 shares swing: ...
```

---

## What to Monitor (First 7 Days)

### Console / logs (`logs/`)

| Signal | Meaning |
|--------|---------|
| `CLAUDE research \| N ideas` | Successful API call |
| `CLAUDE research skipped: rate limit` | Normal — waits for interval |
| `research_proposal` in cycle log | Ideas journaled |
| `research_reflection` on exit | Trade closed → memory updated |
| No `CLAUDE` lines + crypto asset class | Research inactive (expected) |

### Operator UI (`http://localhost:8080`)

- **Activity tab** — filter by `research_proposal`, `research_skipped`, `research_reflection`
- **Dashboard** — recent activity shows thesis + confidence in detail column
- **Stats** — today's research proposal count (API `/api/stats`)

### Files on disk

| File | When it grows |
|------|----------------|
| `logs/journal.db` | Every proposal / reflection event |
| `logs/research_memory.json` | After first closed trade with memory enabled |
| `logs/research_evaluation.json` | After cycles with both Claude + strategy scans |

**Memory is working when:** `research_memory.json` contains `reflections[]` with `summary`, `outcome`, and optional `thesis_at_entry` after you close positions.

**Evaluation is working when:** `research_evaluation.json` has `comparisons[]` and `entries[]` after paper entries.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No Claude calls | `ENABLE_CLAUDE=true`, `ASSET_CLASS=equities`, valid `ANTHROPIC_API_KEY` |
| Skipped every cycle | Rate limit — wait `CLAUDE_CALL_INTERVAL_SECONDS`; check daily cap |
| Research works but no trades | Normal in advisory mode — strategy filters still apply |
| API errors in log | Bot continues (fail-safe); check key, model name, network |
| Want crypto + Claude | Set `CLAUDE_EQUITIES_ONLY=false` (not recommended initially) |

---

## Safety Checklist

- [ ] `PAPER_TRADING=true`, `ALLOW_LIVE_TRADING=false`
- [ ] `CLAUDE_REQUIRE_APPROVAL=false` (advisory only for now)
- [ ] Verified `ENABLE_CLAUDE=false` disables all research (restart bot)
- [ ] No Anthropic key in git — `.env` is gitignored

---

## Next Steps After 7 Days

1. Review `research_evaluation.json` — Claude-only vs strategy-only vs both-agree alignment.
2. Review reflections — are theses improving?
3. Optionally enable `CLAUDE_POSTMORTEM_ENABLED=true` (1 LLM summary/day on close).
4. Later: `CLAUDE_REQUIRE_APPROVAL=true` to let Claude gate entries (still no direct orders).

See `PROJECT_ROADMAP.md` Phase 4 exit gate and `SCOPE.md` guardrails.
