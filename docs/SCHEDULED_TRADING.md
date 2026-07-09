# Scheduled trading (Windows Task Scheduler)

Automated weekday start/stop for the paper bot stack.

| Task | Time (local) | Action |
|------|----------------|--------|
| **My-Trade Start** | Mon–Fri **7:30 AM** | API + UI + paper bot |
| **My-Trade Stop** | Mon–Fri **3:00 PM** | Kill ports 8000/8080 + bot windows |

Times assume your PC uses **US Central** local time (CDT/CST).

- **7:30 AM CT** = **8:30 AM ET** — about **1 hour before** cash open (8:30 AM CT / 9:30 AM ET).
- During that premarket hour the bot warms the screener watchlist and may run research; **new entries stay gated until cash open**.
- **3:00 PM CT** matches cash close (4:00 PM ET).

## One-time setup

```powershell
cd D:\Projects\My-Trade
powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_tasks.ps1
```

Re-run the script after changing start/stop times so Task Scheduler picks up the new triggers.

## Requirements

- Windows user **logged in** at start time (tasks run interactively so cmd windows can open).
- `.venv`, Node.js, and `.env` configured as for manual launch.
- PC awake at **7:30 AM** (disable sleep during market hours or use wake timers).

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
