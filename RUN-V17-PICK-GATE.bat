@echo off
setlocal enabledelayedexpansion
title V17 PICK GATE - start the board, restart :8000, verify the new route
cd /d "%~dp0"
set CEO3D=C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World
set OPENER=C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\OPEN-IN-WORK-CHROME.bat
echo ============================================================
echo   V17 HERO PICK GATE - first run
echo.
echo   New Python routes were added to the Living Room, but the
echo   running server still has the OLD code in memory, so the
echo   gate answers 404 until it restarts. This does that, then
echo   PROVES the route answers before handing the page over.
echo.
echo   Engine ports 8188/8190/8191 are never touched.
echo ============================================================
echo.

echo [1/4] Pick Board on :8194 - it records every pick...
set BOARD=
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8194 " ^| findstr LISTENING') do set BOARD=%%p
if defined BOARD echo       already up on PID !BOARD! - leaving it alone.
if not defined BOARD echo       not running - starting it now.
if not defined BOARD start "" "%CEO3D%\START-PICK-BOARD.bat"
if not defined BOARD timeout /t 4 /nobreak >nul
echo.

echo [2/4] Restarting The Living Room on :8000 (your own restart script)...
start "" "RESTART-LIVING-ROOM-8000.bat"
echo       a second window opened - you can close it once it says Done.
echo.

echo [3/4] Waiting for /api/v17/pipeline to answer (up to 60s)...
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
echo   FAIL - the route never answered 200.
echo.
echo   Most likely the server did not come back up. Look at the
echo   Living Room window for a Python error and send me the last
echo   lines - if my new file has a mistake, that is where it shows.
echo.
echo   Nothing was deleted and nothing was overwritten.
echo.
pause
exit /b 1

:good
echo       PASS - /api/v17/pipeline answered 200. The gate is wired.
echo.
echo [4/4] Opening V17 in your work Chrome...
if exist "%OPENER%" call "%OPENER%" "http://127.0.0.1:8000/?v=17"
if not exist "%OPENER%" echo       opener missing - browse to http://127.0.0.1:8000/?v=17
echo.
echo ============================================================
echo   Ready. The pick panel stays hidden until a prop run parks
echo   four candidates - then it appears in the LEFT pane and you
echo   click the one you like. You never open :8194 yourself.
echo ============================================================
echo.
pause
