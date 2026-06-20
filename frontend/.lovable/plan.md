## Goal

Finish converting the project from the old Kalshi sports-betting app into a clean, frontend-only **My-Trade** operator console for your Alpaca paper-trading bot. The new UI shell, API client, and seven pages are already in place from the previous turn — this plan removes everything Kalshi-related so the repo is lean and matches the spec.

## What stays (already built last turn)

- `src/App.tsx` — new routes: `/`, `/positions`, `/activity`, `/watchlist`, `/control`, `/risk`, `/settings`
- `src/components/Sidebar.tsx`, `StatusBadge.tsx`, `ConfirmDialog.tsx`, `LiveBanner.tsx`, `PageHeader.tsx`
- `src/lib/api.ts` (REST client → `VITE_API_BASE_URL`, default `http://localhost:8000`)
- `src/lib/types.ts`, `src/lib/format.ts`
- `src/hooks/useApi.ts` (React Query polling hooks)
- `src/pages/Dashboard.tsx`, `Positions.tsx`, `Activity.tsx`, `Watchlist.tsx`, `Control.tsx`, `Risk.tsx`, `Settings.tsx`, `NotFound.tsx`
- shadcn/ui, Tailwind theme, Sora + JetBrains Mono fonts, dark "premium analytics" look

## What gets deleted (Kalshi cleanup — "nuke it all")

**Frontend**
- Old pages: `src/pages/Pipeline.tsx`, `Markets.tsx`, `Analysis.tsx`, `Trades.tsx`, `History.tsx`, `Performance.tsx`, `Index.tsx`
- Old components: `src/components/ActivePositions.tsx`, `NotificationsFeed.tsx`, `SchedulerStatus.tsx`, `NavLink.tsx`
- Supabase client integration: `src/integrations/supabase/client.ts`, `src/integrations/supabase/types.ts`, and the `src/integrations/` folder
- Drop `@supabase/supabase-js` from `package.json`

**Backend (Lovable Cloud / Supabase)**
- Delete every edge function: `get-portfolio`, `get-run-history`, `injury-monitor`, `monitor-positions`, `pre-tipoff-check`, `run-analysis-cycle`, `save-settings`, `settle-trades`, `smart-scheduler`, `test-kalshi-auth`
- Delete all migrations under `supabase/migrations/`
- Delete the Kalshi-era secrets: `ANTHROPIC_API_KEY`, `KALSHI_KEY_ID`, `KALSHI_PRIVATE_KEY`, `SPORTRADAR_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (Lovable-managed Supabase secrets like `SUPABASE_*` and `LOVABLE_API_KEY` can't be deleted from here — that's fine, they're inert without a frontend client)
- Leave `supabase/config.toml` as a minimal stub so Lovable Cloud doesn't try to redeploy anything

**Misc**
- `.lovable/plan.md` (stale Kalshi plan)
- Old `README.md` content → replace with My-Trade overview + API contract
- `.env` keeps only `VITE_API_BASE_URL=http://localhost:8000`

## What gets added / tightened

- `.env` entry: `VITE_API_BASE_URL=http://localhost:8000`
- `README.md`: short overview, the REST contract the Python bot must implement, how to run locally
- Quick sanity sweep of the new pages now that the Supabase import path is gone, to confirm nothing still references `@/integrations/supabase/*`

## Out of scope (explicitly)

- No auth (single-operator per your answer)
- No hosted backend URL wiring yet (localhost default per your answer)
- No changes to the Python bot itself — this repo is UI-only
- No new features beyond what's already in the My-Trade spec

## File-by-file summary

```text
DELETE  src/pages/{Pipeline,Markets,Analysis,Trades,History,Performance,Index}.tsx
DELETE  src/components/{ActivePositions,NotificationsFeed,SchedulerStatus,NavLink}.tsx
DELETE  src/integrations/                       (whole folder)
DELETE  supabase/functions/*                    (all 10 functions, also via delete_edge_functions)
DELETE  supabase/migrations/*
DELETE  .lovable/plan.md
EDIT    package.json                            (remove @supabase/supabase-js)
EDIT    .env                                    (only VITE_API_BASE_URL)
EDIT    README.md                               (My-Trade overview + API contract)
EDIT    supabase/config.toml                    (strip to minimal stub)
SECRETS delete ANTHROPIC_API_KEY, KALSHI_KEY_ID, KALSHI_PRIVATE_KEY,
              SPORTRADAR_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
VERIFY  rg "integrations/supabase" src/         → expect zero hits
VERIFY  build succeeds
```

After this runs, the project is a pure React/Vite/Tailwind frontend that talks only to your Python `http://localhost:8000` API. When the bot is offline, every page shows a friendly "cannot reach My-Trade backend" message via the existing `ApiError` handling — no crashes.
