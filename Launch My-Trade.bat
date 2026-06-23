@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
cd /d "%ROOT%"

title My-Trade Launcher

echo.
echo  ========================================
echo   My-Trade Operator Console + Paper Bot
echo  ========================================
echo.

if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo  [ERROR] Python venv not found at .venv
    echo.
    echo  Run once from this folder:
    echo    python -m venv .venv
    echo    .venv\Scripts\activate
    echo    pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Node.js not found on PATH.
    echo  Install from https://nodejs.org/ then re-run this launcher.
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\package.json" (
    echo  [ERROR] frontend\package.json not found.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\node_modules" (
    echo  Installing frontend dependencies ^(first run only^)...
    pushd "%ROOT%frontend"
    call npm install
    if errorlevel 1 (
        echo  npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

if not exist "%ROOT%frontend\.env" (
    if exist "%ROOT%frontend\.env.example" (
        copy /Y "%ROOT%frontend\.env.example" "%ROOT%frontend\.env" >nul
        echo  Created frontend\.env from example.
    )
)

rem Ensure Python dependencies (anthropic, fastapi, etc.) when Claude is enabled
findstr /B /C:"ENABLE_CLAUDE=true" "%ROOT%.env" >nul 2>&1
if not errorlevel 1 (
    "%ROOT%.venv\Scripts\python.exe" -c "import anthropic" >nul 2>&1
    if errorlevel 1 (
        echo  Installing Python dependencies ^(anthropic, etc.^) — one-time setup...
        "%ROOT%.venv\Scripts\pip.exe" install -e "%ROOT%[dev]"
        if errorlevel 1 (
            echo  pip install failed. Run manually: pip install -e ".[dev]"
            pause
            exit /b 1
        )
    )
)

echo  Starting three windows:
echo    1. My-Trade API      ^(port 8000^)
echo    2. My-Trade UI       ^(port 8080^)
echo    3. My-Trade Paper Bot ^(Phase 4 advisory — Claude + strategy^)
echo.

rem NOTE: Do not nest quotes around %%ROOT%% inside cmd /k "..." — that breaks paths.
start "My-Trade API" cmd /k "pushd %ROOT% && call .venv\Scripts\activate.bat && echo. && echo My-Trade API on http://127.0.0.1:8000 && echo. && poe api"
start "My-Trade UI" cmd /k "pushd %ROOT%frontend && echo. && echo My-Trade UI on http://localhost:8080 && echo. && npm run dev"
start "My-Trade Paper Bot" cmd /k "pushd %ROOT% && call .venv\Scripts\activate.bat && echo. && echo My-Trade PAPER bot — Claude advisory mode && echo Close this window to stop trading. && echo. && poe paper"

echo  Waiting for servers to bind...
timeout /t 8 /nobreak >nul

start "" "http://localhost:8080"

echo.
echo  Opened http://localhost:8080 in your browser.
echo.
echo  If a window closes immediately, read the error shown there.
echo  Common fixes:
echo    - pip install -e ".[dev]"  ^(installs poe + dependencies^)
echo    - npm install              ^(in frontend folder^)
echo    - Stop My-Trade.bat        ^(free ports 8000 / 8080^)
echo.
echo  Phase 4: Claude runs in the Paper Bot window ^([CLAUDE] log lines^).
echo  On weekends the US market is closed — entries pause, Claude still proposes.
echo.
pause
