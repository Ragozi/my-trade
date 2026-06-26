# Scheduled trading (Windows Task Scheduler)

Automated weekday start/stop for the paper bot stack.

| Task | Time (local) | Action |
|------|----------------|--------|
| **My-Trade Start** | Mon–Fri **7:55 AM** | API + UI + paper bot |
| **My-Trade Stop** | Mon–Fri **3:00 PM** | Kill ports 8000/8080 + bot windows |

Times assume your PC uses **US Central** local time (CDT/CST).  
7:55 AM is ~35 minutes before cash open (8:30 AM CT).  
3:00 PM matches cash close (3:00 PM CT / 4:00 PM ET).

## One-time setup

```powershell
cd D:\Projects\My-Trade
powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_tasks.ps1
```

## Requirements

- Windows user **logged in** at start time (tasks run interactively so cmd windows can open).
- `.venv`, Node.js, and `.env` configured as for manual launch.
- PC awake at 7:55 AM (disable sleep during market hours or use wake timers).

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
