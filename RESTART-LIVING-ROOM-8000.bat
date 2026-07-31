@echo off
setlocal
title RESTART The Living Room :8000 (listeners + spawn workers, engines untouched)
cd /d "%~dp0"
echo ============================================================
echo   Restarting The Living Room. Kills every :8000 listener AND
echo   every uvicorn spawn-worker (the 2026-07-30 lesson: workers
echo   inherit the socket and outlive their parents, serving stale
echo   code). Engine ports 8188/8190/8191 are never touched (G9).
echo ============================================================
echo.
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do echo Stopping :8000 listener PID %%p & taskkill /PID %%p /F >nul 2>&1
echo Deleting uvicorn spawn-workers...
wmic process where "name='python.exe' and CommandLine like '%%spawn_main%%'" delete >nul 2>&1
timeout /t 3 /nobreak >nul
set STILL=
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do set STILL=%%p
if defined STILL echo NOTE: a zombie netstat row may linger for a dead PID - starting anyway.
echo Booting one fresh Living Room...
start "" "START-LIVING-ROOM-8000.bat"
echo.
echo Done - leave the NEW Living Room window open. This one can close.
pause
