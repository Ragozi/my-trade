@echo off
setlocal EnableExtensions

echo.
echo  Stopping My-Trade services on ports 8000 and 8080...
echo.

call :kill_port 8000 "API"
call :kill_port 8080 "UI"

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
