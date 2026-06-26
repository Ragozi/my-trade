@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
set "LOG=%ROOT%\logs\scheduler.log"
cd /d "%ROOT%"

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

rem Skip if API already listening (already running)
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [%date% %time%] skip start — port 8000 already in use >> "%LOG%"
    exit /b 0
)

if not exist "%ROOT%\frontend\node_modules" (
    echo [%date% %time%] npm install >> "%LOG%"
    pushd "%ROOT%\frontend"
    call npm install >> "%LOG%" 2>&1
    popd
)

rem Refresh journal brief before session (free, no LLM)
"%ROOT%\.venv\Scripts\python.exe" -m scripts.research_brief >> "%LOG%" 2>&1

start "My-Trade API" cmd /k "pushd %ROOT% && call .venv\Scripts\activate.bat && poe api"
start "My-Trade UI" cmd /k "pushd %ROOT%\frontend && npm run dev"
start "My-Trade Paper Bot" cmd /k "pushd %ROOT% && call .venv\Scripts\activate.bat && poe paper"

echo [%date% %time%] started API, UI, paper bot >> "%LOG%"
exit /b 0
