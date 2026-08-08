@echo off
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0.."
set "LOG=%ROOT%\logs\scheduler.log"
cd /d "%ROOT%"

if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"

echo [%date% %time%] scheduled_start >> "%LOG%"

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo [%date% %time%] ERROR venv missing >> "%LOG%"
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo [%date% %time%] ERROR node missing >> "%LOG%"
    exit /b 1
)

set "API_RUNNING=false"
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    set "API_RUNNING=true"
    echo [%date% %time%] API already listening on port 8000 >> "%LOG%"
)

set "UI_RUNNING=false"
netstat -ano | findstr ":8080 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    set "UI_RUNNING=true"
    echo [%date% %time%] UI already listening on port 8080 >> "%LOG%"
)

if not exist "%ROOT%\frontend\node_modules" (
    echo [%date% %time%] npm install >> "%LOG%"
    pushd "%ROOT%\frontend"
    call npm install >> "%LOG%" 2>&1
    popd
)

rem Refresh journal brief before session (free, no LLM)
"%ROOT%\.venv\Scripts\python.exe" -m scripts.research_brief >> "%LOG%" 2>&1

if "%API_RUNNING%"=="false" (
    start "My-Trade API" cmd /k "pushd %ROOT% && call .venv\Scripts\activate.bat && poe api"
)

if "%UI_RUNNING%"=="false" (
    start "My-Trade UI" cmd /k "pushd %ROOT%\frontend && npm run dev"
)

set "BOT_RUNNING=false"
if exist "%ROOT%\logs\bot.pid" (
    set /p BOT_PID=<"%ROOT%\logs\bot.pid"
    if defined BOT_PID (
        echo(!BOT_PID! | findstr /R "^[0-9][0-9]*$" >nul 2>&1
        if not errorlevel 1 (
            powershell -NoProfile -Command "if (Get-Process -Id !BOT_PID! -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
            if not errorlevel 1 set "BOT_RUNNING=true"
        )
    )
)

if "%BOT_RUNNING%"=="false" (
    start "My-Trade Paper Bot" cmd /k "pushd %ROOT% && call .venv\Scripts\activate.bat && poe paper"
) else (
    echo [%date% %time%] paper bot already running PID !BOT_PID! >> "%LOG%"
)

echo [%date% %time%] scheduled start complete API=%API_RUNNING% UI=%UI_RUNNING% BOT=%BOT_RUNNING% >> "%LOG%"
exit /b 0
