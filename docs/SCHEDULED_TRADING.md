# Scheduled trading (Windows Task Scheduler)

Automated weekday start/stop for the paper bot stack.

| Task | Time (local) | Action |
|------|----------------|--------|
| **My-Trade Start** | Mon–Fri **3:30 AM** | Wake PC + API + UI + paper bot |
| **My-Trade Stop** | Mon–Fri **3:00 PM** | Kill ports 8000/8080 + bot windows |

Times assume your PC uses **US Central** local time (CDT/CST).

- **3:30 AM CT** ≈ **4:30 AM ET** — early overnight study window.
- Research / screener may run from **4:00 ET** (3:00 CT) through cash close so the bot can read overnight gaps and news before premarket.
- **New entries stay gated until cash open** (9:30 ET / 8:30 CT), and with opening-scalp mode only until ~10:00 ET.
- **3:00 PM CT** matches cash close (4:00 PM ET).

## One-time setup

```powershell
cd D:\Projects\My-Trade
powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_tasks.ps1
```

Re-run the script after changing start/stop times so Task Scheduler picks up the new triggers.

## Wake from sleep

The start task uses **WakeToRun**. Also enable wake timers so Windows will leave sleep:

1. **Settings → System → Power → Screen and sleep** (or classic Power Options)
2. **Change plan settings → Change advanced power settings**
3. **Sleep → Allow wake timers → Enable** (and On battery if needed)

The machine must be able to wake (sleep OK; hibernate/fully off is less reliable).

## Requirements

- Windows user **logged in** at start time (tasks run interactively so cmd windows can open).
- `.venv`, Node.js, and `.env` configured as for manual launch.
- Prefer sleep + wake timers over shutting down overnight.

## Logs

`logs/scheduler.log` — append-only start/stop history.

## Manual override

- Start now: `Launch My-Trade.bat` or `scripts\scheduled_start.bat`
- Stop now: `Stop My-Trade.bat` or `scripts\scheduled_stop.bat`

## Remove tasks

```powershell
Unregister-ScheduledTask -TaskName "My-Trade Start" -Confirm:$false
Unregister-ScheduledTask -TaskName "My-Trade Stop" -Confirm:$false
```
