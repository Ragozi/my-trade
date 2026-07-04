# Mobile & remote access

The operator console is a **React app** (`frontend/`) backed by a **FastAPI API** on your PC (`scripts/start_console.py` or `poe console`). Alpaca and the trading bot also run locally. Nothing is on the public internet until you deploy or tunnel it.

## What you can use today (no deploy)

| Method | Setup | Best for |
|--------|--------|----------|
| **Slack** | `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` in `.env` (already set) | Push alerts on trades/halts; Slack mobile app |
| **Same Wi‑Fi** | Open `http://<your-pc-ip>:8080` on phone | Dashboard while at home |
| **Tailscale** (free) | Install on PC + phone, open `http://100.x.x.x:8080` | Secure phone access from anywhere |

The bot journal and API only update while **paper_trade** and the **API/console** are running on your machine.

## Public URL (phone browser anywhere)

You need **two** reachable endpoints:

1. **Frontend** — static React build (Vercel, Netlify, Cloudflare Pages)
2. **Backend API** — must expose port 8000 to the internet (tunnel or VPS)

### Option A — Vercel frontend + Cloudflare Tunnel API (recommended)

**Frontend (Vercel)**

1. Push this repo to GitHub (already done after `git push`).
2. [vercel.com](https://vercel.com) → Import `my-trade` → Root directory: `frontend`
3. Environment variable: `VITE_API_BASE_URL=https://your-tunnel-url.trycloudflare.com` (or your permanent tunnel hostname)
4. Deploy → you get `https://my-trade-xxx.vercel.app` (bookmark on phone)

**API (Cloudflare Tunnel on your Windows PC)**

```powershell
# Install cloudflared, then:
cloudflared tunnel --url http://127.0.0.1:8000
```

Run `poe console` (or API + frontend) on the PC. Point Vercel’s `VITE_API_BASE_URL` at the tunnel URL. **Security:** add Cloudflare Access or API key middleware before exposing long-term.

### Option B — Lovable hosted preview

If Lovable is connected to GitHub, sync `frontend/` from `main`. Lovable preview URLs work on phone but still need a **public API URL** for live data (tunnel above).

### Option C — All-local PWA (advanced)

Build frontend with `npm run build`, serve from FastAPI, use Tailscale only — no public URL, but phone works via VPN.

## Telegram (optional alerts)

Legacy support exists in `utils.py` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Steps:

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy token
2. Message your bot, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` to find `chat_id`
3. Add to `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=...
   ```

Full Telegram *dashboard* (inline status) is not built yet; use **Slack** or the **web dashboard URL** for rich UI. Telegram is best for “halted / entry / daily summary” pings.

## Dashboard fields (slow & steady profile)

When `TRADING_CAPITAL=15000` is set:

- **Equity** on dashboard = virtual trading balance (~$15k + strategy day P&L)
- **Broker equity** = Alpaca paper account (shown on Risk page / account API as `broker_equity`)
- **Risk page** shows dollar limits: ~$150/trade risk, ~$3k max position, ~$450 daily halt

## Checklist before going mobile

- [ ] Bot + API running on PC (or VPS)
- [ ] `TRADING_CAPITAL` and risk limits in `.env` match slow-steady profile
- [ ] Frontend deployed with correct `VITE_API_BASE_URL`
- [ ] Tunnel or VPN tested from phone
- [ ] Slack or Telegram tested for halt alerts
