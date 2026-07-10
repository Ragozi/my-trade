# Register weekday My-Trade start/stop tasks (local time = Central when TZ is set correctly).
# Run once:  powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_tasks.ps1
#
# Start is early morning so research can study overnight gaps before premarket.
# Task Scheduler WakeToRun will try to wake the PC from sleep (enable wake timers
# in Windows Power Options if it sleeps overnight).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$StartBat = Join-Path $Root "scripts\scheduled_start.bat"
$StopBat = Join-Path $Root "scripts\scheduled_stop.bat"

$StartAction = New-ScheduledTaskAction -Execute $StartBat -WorkingDirectory $Root
$StopAction = New-ScheduledTaskAction -Execute $StopBat -WorkingDirectory $Root

# 3:30 AM CT ~= 4:30 AM ET - overnight gap / news research window (opens 4:00 ET).
# Entries still gated until cash open (9:30 ET / 8:30 CT).
$StartTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:30 AM"

# 3:00 PM CT = US cash close (4:00 PM ET)
$StopTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:00 PM"

# Wake PC from sleep; long enough for 3:30 AM -> 3:00 PM session.
$StartSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 13)

$StopSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "My-Trade Start" `
    -Action $StartAction `
    -Trigger $StartTrigger `
    -Settings $StartSettings `
    -Principal $Principal `
    -Description "Start My-Trade API, UI, and paper bot at 3:30 AM weekdays (Central) for overnight research." `
    -Force | Out-Null

Register-ScheduledTask -TaskName "My-Trade Stop" `
    -Action $StopAction `
    -Trigger $StopTrigger `
    -Settings $StopSettings `
    -Principal $Principal `
    -Description "Stop My-Trade at 3:00 PM weekdays (Central local time)." `
    -Force | Out-Null

Write-Host "Registered scheduled tasks:"
Write-Host "  My-Trade Start  - Mon-Fri 3:30 AM local (Central) - overnight research wake"
Write-Host "  My-Trade Stop   - Mon-Fri 3:00 PM local (Central)"
Write-Host ""
Write-Host "Wake: tasks use WakeToRun. If the PC sleeps, enable wake timers:"
Write-Host "  Power Options -> Change plan settings -> Change advanced power settings"
Write-Host "  -> Sleep -> Allow wake timers -> Enable"
Write-Host ""
Write-Host "Logs: $Root\logs\scheduler.log"
Write-Host "Requires you to be logged in (interactive tasks)."
Get-ScheduledTask -TaskName "My-Trade Start","My-Trade Stop" | Format-Table TaskName, State
