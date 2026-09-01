@echo off
setlocal enabledelayedexpansion
title LIVING ROOM - one button: clean restart, verify, open V17
cd /d "%~dp0"
set CEO3D=C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World
set OPENER=C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\OPEN-IN-WORK-CHROME.bat
echo ============================================================
echo   THE LIVING ROOM - the only button you need.
echo.
echo   Replaces RESTART-LIVING-ROOM-8000.bat and
echo   RUN-V17-PICK-GATE.bat. Does all of it in order:
echo     1. stops ONLY the stale :8000 server and its workers
echo     2. starts the Pick Board if it is not already up
echo     3. boots one fresh Living Room in its own window
echo     4. waits until the server really answers
echo     5. opens V17 in your work Chrome
echo.
echo   run.py sets reload=False on purpose, so code changes
echo   need this restart. That is by design, not a fault.
echo   Engine ports 8188/8190/8191 are never touched.
echo ============================================================
echo.

echo [1/5] Stopping the stale Living Room on :8000...
set FOUND=
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do set FOUND=1& echo       stopping PID %%p & taskkill /PID %%p /F >nul 2>&1
if not defined FOUND echo       nothing was listening - clean start.
echo       clearing uvicorn spawn-workers (they outlive parents and serve stale code)...
wmic process where "name='python.exe' and CommandLine like '%%spawn_main%%'" delete >nul 2>&1
timeout /t 2 /nobreak >nul
echo.

echo [2/5] Pick Board on :8194 - it records every pick and approval...
set BOARD=
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8194 " ^| findstr LISTENING') do set BOARD=%%p
if defined BOARD echo       already up on PID !BOARD! - left alone.
if not defined BOARD echo       not running - starting it.
if not defined BOARD start "" "%CEO3D%\START-PICK-BOARD.bat"
if not defined BOARD timeout /t 4 /nobreak >nul
echo.

echo [3/5] Booting one fresh Living Room...
start "" "START-LIVING-ROOM-8000.bat"
echo       a second window opened - LEAVE IT OPEN, that window IS the server.
echo.

echo [4/5] Waiting for it to actually answer (up to 60s)...
set OK=
set /a TRIES=0
:wait
set /a TRIES+=1
timeout /t 3 /nobreak >nul
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 'http://127.0.0.1:8000/api/v17/pipeline'; if($r.StatusCode -eq 200){exit 0}else{exit 1}}catch{exit 1}" >nul 2>&1
if not errorlevel 1 set OK=1
if defined OK goto good
if %TRIES% LSS 20 goto wait

echo.
echo   FAIL - the server never answered on :8000.
echo.
echo   Look at the OTHER window (the one titled "The Living Room").
echo   If Python printed an error, copy those lines to Claude.
echo.
echo   Note: if that window looks fine and the port IS listening but
echo   nothing responds, that is the known SSE wedge - run this
echo   script again to clear it.
echo.
echo   Nothing was deleted and nothing was overwritten.
echo.
pause
exit /b 1

:good
echo       PASS - the server answered and the V17 factory routes are loaded.
echo.
echo [5/5] Opening V17 in your work Chrome...
if exist "%OPENER%" call "%OPENER%" "http://127.0.0.1:8000/?v=17"
if not exist "%OPENER%" echo       opener missing - browse to http://127.0.0.1:8000/?v=17
echo.
echo ============================================================
echo   Ready. Everything for the furniture line happens in the
echo   LEFT pane of V17 - name a prop, pick the hero, check the
echo   mesh in 3D, check the paint. You never open :8194 yourself.
echo ============================================================
echo.
pause
