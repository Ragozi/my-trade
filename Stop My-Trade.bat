@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0"

echo.
echo  Stopping My-Trade services on ports 8000 and 8080...
echo.

call :kill_port 8000 "API"
call :kill_port 8080 "UI"

echo.
echo  Stopping paper bot processes...
call :kill_paper_bots
taskkill /FI "WINDOWTITLE eq My-Trade Paper Bot*" /F >nul 2>&1

echo.
echo  Done. Close any remaining My-Trade terminal windows manually.
echo.
pause
exit /b 0

:kill_port
set "PORT=%~1"
set "LABEL=%~2"
set "FOUND=0"
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    set "FOUND=1"
    echo  Stopping %LABEL% ^(PID %%P^) on port %PORT%...
    taskkill /PID %%P /F >nul 2>&1
)
if "%FOUND%"=="0" echo  Nothing listening on port %PORT%.
exit /b 0

:kill_paper_bots
set "BOTPID="
if exist "%ROOT%logs\bot.pid" (
    set /p BOTPID=<"%ROOT%logs\bot.pid"
    if defined BOTPID (
        echo  Stopping paper bot PID !BOTPID! from bot.pid...
        taskkill /PID !BOTPID! /T /F >nul 2>&1
    )
    del "%ROOT%logs\bot.pid" >nul 2>&1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*scripts.paper_trade*' } | ForEach-Object { Write-Host ('Stopping paper bot PID ' + $_.ProcessId + ' from command line...'); Stop-Process -Id $_.ProcessId -Force }"
exit /b 0
