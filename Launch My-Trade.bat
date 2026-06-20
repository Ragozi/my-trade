@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
cd /d "%ROOT%"

title My-Trade Launcher

if not exist "%ROOT%.venv\Scripts\activate.bat" (
    echo.
    echo  Virtual environment not found at .venv
    echo  From this folder run:
    echo    python -m venv .venv
    echo    .venv\Scripts\activate
    echo    pip install -e .
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\package.json" (
    echo.
    echo  Frontend folder not found. Expected: frontend\package.json
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%frontend\node_modules" (
    echo.
    echo  Installing frontend dependencies ^(first run only^)...
    pushd "%ROOT%frontend"
    call npm install
    if errorlevel 1 (
        echo npm install failed.
        popd
        pause
        exit /b 1
    )
    popd
)

echo.
echo  Starting My-Trade Operator Console...
echo.

start "My-Trade API" cmd /k "cd /d "%ROOT%" && call .venv\Scripts\activate.bat && echo My-Trade API ^(port 8000^) && poe api"
start "My-Trade UI" cmd /k "cd /d "%ROOT%frontend" && echo My-Trade UI ^(port 8080^) && npm run dev"

echo  Waiting for servers...
timeout /t 6 /nobreak >nul

start "" "http://localhost:8080"

echo.
echo  Started:
echo    API:      http://127.0.0.1:8000
echo    Console:  http://localhost:8080
echo.
echo  Use Dashboard -^> Health check, then Single cycle or Start bot.
echo  Close the "My-Trade API" and "My-Trade UI" windows to stop.
echo.
pause
