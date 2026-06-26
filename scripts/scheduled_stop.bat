@echo off
setlocal EnableExtensions
set "ROOT=%~dp0.."
set "LOG=%ROOT%\logs\scheduler.log"
cd /d "%ROOT%"

echo [%date% %time%] scheduled_stop >> "%LOG%"

call :kill_port 8000 "API"
call :kill_port 8080 "UI"
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
