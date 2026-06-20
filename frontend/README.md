# My-Trade — Operator Console

A dark-mode, frontend-only operator console for the **My-Trade** automated Alpaca paper-trading bot. The bot runs separately (Python); this app is the read-heavy, write-careful control panel that monitors it, edits its config, and starts/stops it.

## What this app is — and isn't

- **Is:** a Vite + React + Tailwind + shadcn/ui dashboard. Talks only to your bot's REST API.
- **Isn't:** anything that holds Alpaca, broker, or LLM keys. No secrets live in the browser. No order routing happens here — the bot is fully automated; this UI just tells it to start, stop, and reconfigure.

## Run it locally

```bash
bun install
bun run dev
```

By default the UI calls `http://localhost:8000`. Override with `VITE_API_BASE_URL` in `.env`.

When the backend is offline every page shows a friendly "cannot reach My-Trade backend" message instead of crashing.

## Pages

| Route        | What it does                                                                 |
|--------------|------------------------------------------------------------------------------|
| `/`          | Dashboard — KPIs, equity curve, recent activity, quick actions               |
| `/positions` | Open positions reported by the broker                                        |
| `/activity`  | Full event audit log with filters, search, CSV export                        |
| `/watchlist` | Screener output + static symbol list                                         |
| `/control`   | Start / Stop / Restart / Health check / Single cycle + live log tail         |
| `/risk`      | Live exposure vs configured risk limits + halt history                       |
| `/settings`  | Edit bot config (asset class, symbols, screener, strategy, risk, runtime)    |

PAPER / LIVE mode is shown prominently in the sidebar. LIVE shows a red banner. All destructive actions (start, stop, restart, risk changes) require a confirm modal; starting in LIVE mode requires typing `START LIVE`.

## Backend REST contract

Implement these endpoints in the Python bot. JSON in, JSON out.

```ts
GET  /api/health    → { status, bot_running, asset_class, paper_trading }
GET  /api/status    → { bot: { running, pid, started_at, last_cycle_at, cycles_today },
                        session: { open, asset_class }, halted, halt_reason }
GET  /api/account   → { equity, cash, buying_power, day_pnl, peak_equity,
                        open_positions, positions: [{ symbol, qty, avg_entry_price,
                        market_value, unrealized_pl }] }
GET  /api/config    → { asset_class, symbols, paper_trading,
                        screener: { ... }, strategy: { ... },
                        risk: { ... }, runtime: { ... } }
PATCH /api/settings → { ok, requires_restart, message }
GET  /api/events?limit=200&kind=&symbol=
                    → [{ ts, kind, symbol, detail, equity, day_pnl }]
GET  /api/stats     → { today: { entries, exits, halts, errors },
                        daily_state: { trading_day, start_of_day_equity,
                        peak_equity, entries_today }, latest_equity }
GET  /api/watchlist → { symbols, ranked: [...], refreshed_at, universe_source? }
GET  /api/logs?tail=100 → { lines: string[] }
POST /api/bot/start         → { ok, message }
POST /api/bot/stop          → { ok, message }
POST /api/bot/restart       → { ok, message }
POST /api/bot/health-check  → { ok, checks: { account, data, execution } }
POST /api/bot/once          → { ok, summary, actions }
```

See `src/lib/types.ts` for the exact TypeScript shapes and `src/hooks/useApi.ts` for polling intervals.

## Tech stack

React 18 · TypeScript · Vite · Tailwind CSS · shadcn/ui · TanStack Query · Recharts · React Router · Lucide.
