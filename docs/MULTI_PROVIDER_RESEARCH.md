# Multi-Provider Research — Setup Guide

> **Advisory only.** LLMs propose ideas; the deterministic strategy and risk engine control every order.

---

## Keys — what to put in `.env`

All secrets go in **`D:\Projects\My-Trade\.env`** (gitignored). Copy from `.env.example`.

| Variable | Required when | Where to get it |
|----------|---------------|-----------------|
| `APCA_API_KEY_ID` | Always (trading) | [Alpaca](https://app.alpaca.markets/) → Paper API |
| `APCA_API_SECRET_KEY` | Always (trading) | Same |
| `OPENAI_API_KEY` | `RESEARCH_WORKHORSE_PROVIDER=openai` | [OpenAI Platform](https://platform.openai.com/api-keys) — **not** ChatGPT Plus |
| `ANTHROPIC_API_KEY` | `ENABLE_CLAUDE=true` | [Anthropic Console](https://console.anthropic.com/) |
| `XAI_API_KEY` | `RESEARCH_WORKHORSE_PROVIDER=xai` | [xAI Console](https://console.x.ai/) |

**Not used at runtime:** Cursor subscription, ChatGPT Plus, Grok on X Premium.

---

## Recommended starter `.env` (drop in all keys)

```env
ENABLE_RESEARCH=true
RESEARCH_TIER_MODE=both

# Workhorse — frequent, cheap
RESEARCH_WORKHORSE_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
RESEARCH_WORKHORSE_INTERVAL_SECONDS=900
RESEARCH_WORKHORSE_MAX_CALLS_PER_DAY=16

# Premium — sparse
ENABLE_CLAUDE=true
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_CALL_INTERVAL_SECONDS=1800
CLAUDE_MAX_CALLS_PER_DAY=6
CLAUDE_MARKET_HOURS_ONLY=true
```

**Workhorse only** (no Anthropic credits yet):

```env
ENABLE_RESEARCH=true
RESEARCH_TIER_MODE=workhorse_only
RESEARCH_WORKHORSE_PROVIDER=openai
OPENAI_API_KEY=sk-...
ENABLE_CLAUDE=false
```

**Instant off:**

```env
ENABLE_RESEARCH=false
ENABLE_CLAUDE=false
RESEARCH_WORKHORSE_PROVIDER=none
```

---

## How tiers work

| Tier | Provider | Default cadence | Role |
|------|----------|-----------------|------|
| **0** | None (Python) | After close / manual | `poe research-brief` → `logs/research_brief.json` |
| **1 Workhorse** | OpenAI `gpt-4o-mini` | Every 20 min, ≤10/day | Watchlist flags, hold/avoid |
| **2 Premium fallback** | xAI Grok (Claude off) | Every 30 min, ≤4/day | Deep thesis / session read |
| **2 Premium** | Claude Sonnet (credits on) | Every 30 min, ≤6/day | Replaces Grok premium tier |

`RESEARCH_TIER_MODE=both` tries **premium (Grok or Claude) first**, then falls back to **OpenAI mini** when rate-limited.

Every live call reads **`daily_brief`** from the brief file when present (run `poe research-brief` daily or after close).

---

## Commands

```bash
poe research-brief          # Build journal brief (no LLM, free)
poe research --mock         # One-shot mock proposal
poe research              # One-shot live call (uses configured tiers)
poe paper                 # Trading loop with research tiers
```

After changing `.env`, restart the paper bot (`Stop My-Trade.bat` → `Launch My-Trade.bat`).

---

## Install deps

```bash
pip install -e ".[dev]"
```

Adds `openai` and `anthropic` for API clients.

---

## Monitoring

- Console: `Research ACTIVE | mode=both | tiers=claude/... + openai/...`
- Dashboard: research banner shows active tiers
- Activity: proposals tagged with `[openai]` or `[claude]` in detail

---

## Cost control

Failed billing/quota errors trigger a **1-hour cooldown** per tier (same as Claude fix).

Keep `CLAUDE_MARKET_HOURS_ONLY=true` and conservative daily caps. See `docs/PHASE4_ACTIVATION.md` for the original Claude cost notes.

---

## Architecture

```
Journal + memory → research_brief.json
                         ↓
              ResearchContext (portfolio + brief)
                         ↓
         CompositeResearchAdvisor
              ↙          ↘
    OpenAI/Grok         Claude
    (workhorse)        (premium)
                         ↓
              Advisory proposals → journal (no orders)
```

Cursor is for **building and reviewing** this stack — not wired into the live loop.
