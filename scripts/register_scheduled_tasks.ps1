# Register weekday My-Trade start/stop tasks (local time = Central when TZ is set correctly).
# Run once:  powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_tasks.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$StartBat = Join-Path $Root "scripts\scheduled_start.bat"
$StopBat = Join-Path $Root "scripts\scheduled_stop.bat"

$StartAction = New-ScheduledTaskAction -Execute $StartBat -WorkingDirectory $Root
$StopAction = New-ScheduledTaskAction -Execute $StopBat -WorkingDirectory $Root

# 7:30 AM CT — ~1 hour before US cash open (9:30 ET = 8:30 CT)
# Premarket warmup: screener + research run; entries stay gated until 8:30 CT.
$StartTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "7:30 AM"

# 3:00 PM — US cash close in Central (4:00 PM ET = 3:00 PM CT)
$StopTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:00 PM"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 9)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "My-Trade Start" `
    -Action $StartAction `
    -Trigger $StartTrigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Start My-Trade API, UI, and paper bot at 7:30 AM weekdays (Central) for premarket warmup." `
    -Force | Out-Null

Register-ScheduledTask -TaskName "My-Trade Stop" `
    -Action $StopAction `
    -Trigger $StopTrigger `
    -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries) `
    -Principal $Principal `
    -Description "Stop My-Trade at 3:00 PM weekdays (Central local time)." `
    -Force | Out-Null

Write-Host "Registered scheduled tasks:"
Write-Host "  My-Trade Start  - Mon-Fri 7:30 AM local time (1h before cash open)"
Write-Host "  My-Trade Stop   - Mon-Fri 3:00 PM local time"
Write-Host ""
Write-Host "Logs: $Root\logs\scheduler.log"
Write-Host "Requires you to be logged in (interactive tasks)."
Get-ScheduledTask -TaskName "My-Trade Start","My-Trade Stop" | Format-Table TaskName, State
