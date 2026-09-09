@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0.."
set "LOG=%ROOT%\logs\scheduler.log"
cd /d "%ROOT%"

echo [%date% %time%] scheduled_stop >> "%LOG%"

call :kill_port 8000 "API"
call :kill_port 8080 "UI"
call :kill_paper_bots
taskkill /FI "WINDOWTITLE eq My-Trade Paper Bot*" /F >> "%LOG%" 2>&1
taskkill /FI "WINDOWTITLE eq My-Trade API*" /F >> "%LOG%" 2>&1
taskkill /FI "WINDOWTITLE eq My-Trade UI*" /F >> "%LOG%" 2>&1

echo [%date% %time%] stop complete >> "%LOG%"
exit /b 0

:kill_port
set "PORT=%~1"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo [%date% %time%] killing %~2 PID %%P port %PORT% >> "%LOG%"
    taskkill /PID %%P /F >> "%LOG%" 2>&1
)
exit /b 0

:kill_paper_bots
set "BOTPID="
if exist "%ROOT%\logs\bot.pid" (
    set /p BOTPID=<"%ROOT%\logs\bot.pid"
    if defined BOTPID (
        echo [%date% %time%] killing paper bot PID !BOTPID! from pid file >> "%LOG%"
        taskkill /PID !BOTPID! /T /F >> "%LOG%" 2>&1
    )
    del "%ROOT%\logs\bot.pid" >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*scripts.paper_trade*' } | ForEach-Object { Write-Output ('killing paper bot PID ' + $_.ProcessId + ' from command line'); Stop-Process -Id $_.ProcessId -Force }" >> "%LOG%" 2>&1
exit /b 0
