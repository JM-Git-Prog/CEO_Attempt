@echo off
title The Switchboard - one place the line is turned on and off
setlocal

REM ==========================================================================
REM  2026-09-14. John: "i am so sick and tired of you not being able to start
REM  and stop all of the servers, i have tried a million different ways, can't
REM  you just put them all in docker or something to coordinate their spin up
REM  spin down and collision etc..."
REM
REM  This is that one thing. It starts sim-player\switchboard.py, which OWNS
REM  three services and can start and stop each of them without a console
REM  window and without a person:
REM
REM      world  :5173   the 3D world
REM      line   :8099   THE LINE dashboard  (moves to :8100+ if :8099 is squatted)
REM      loop    ---    the Sam Loop
REM
REM  Everything else - Ollama, ComfyUI, the Builder, John's own Living Room on
REM  :8000 and Pick Board on :8194, and Sam's own :8001 / :8294 which his loop
REM  starts for itself - is REPORTED on the page and never touched. Two owners
REM  for one port IS the collision, so the switchboard refuses to be a second
REM  owner of anything, and it never kills what it did not start.
REM
REM  Usage:  START-THE-SWITCHBOARD.bat              start it and open the page
REM          START-THE-SWITCHBOARD.bat noopen       start it, no browser
REM          START-THE-SWITCHBOARD.bat noopen restart
REM                 replace a switchboard that is already running with this
REM                 build. It asks the old one to STAND DOWN - the same thing
REM                 the dashboard does for its own older copies - and the new
REM                 one adopts a running Sam Loop from its heartbeat, so a
REM                 restart never orphans a loop mid-run.
REM ==========================================================================

set "HERE=%~dp0"
set "SB=%HERE%sim-player\switchboard.py"
set "URL=http://127.0.0.1:8777/"
set "PROBE=try{$w=Invoke-WebRequest -Uri 'http://127.0.0.1:8777/api/status' -TimeoutSec 3 -UseBasicParsing; if($w.Content -match 'switchboard/1'){exit 0}; exit 2}catch{exit 1}"
set "STANDDOWN=try{Invoke-WebRequest -Uri 'http://127.0.0.1:8777/api/standdown' -Method POST -TimeoutSec 5 -UseBasicParsing | Out-Null}catch{}; Start-Sleep -Milliseconds 900; $c = Get-NetTCPConnection -LocalPort 8777 -State Listen -ErrorAction SilentlyContinue; if($c){ Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 600 }"

set "WANT_RESTART="
if /i "%~1"=="restart" set "WANT_RESTART=1"
if /i "%~2"=="restart" set "WANT_RESTART=1"

if not exist "%SB%" goto nofile

echo.
echo   Switchboard
echo   -----------

powershell -NoProfile -ExecutionPolicy Bypass -Command "%PROBE%" >nul 2>&1
if errorlevel 2 goto notours
if errorlevel 1 goto findpython
if not defined WANT_RESTART goto alreadyup

REM --- A switchboard is running and this is a restart. Ask it to stand down.  ---
REM --- The ONLY thing killed here is a program that just told us it is a      ---
REM --- switchboard. Every service it started keeps running; the new one picks ---
REM --- the Sam Loop back up from the pid in its own heartbeat file.           ---
echo   asking the running switchboard to stand down for this build
powershell -NoProfile -ExecutionPolicy Bypass -Command "%STANDDOWN%" >nul 2>&1
goto findpython

:findpython
REM --- The switchboard itself needs nothing but the stdlib; it chooses its OWN ---
REM --- interpreter for the loop, by asking whether that interpreter can import ---
REM --- uvicorn. That is the wrong-python wedge that cost eleven minutes on     ---
REM --- 2026-09-14, fixed at the root.                                          ---
set "PY="
where py >nul 2>&1
if not errorlevel 1 set "PY=py"
if defined PY goto havepython
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto havepython
goto nopython

:havepython
echo   starting %SB%
start "Switchboard" /min "%PY%" "%SB%"

set /a TRIES=0
:wait
set /a TRIES+=1
powershell -NoProfile -ExecutionPolicy Bypass -Command "%PROBE%" >nul 2>&1
if not errorlevel 1 goto up
if %TRIES% GEQ 20 goto notup
ping -n 2 127.0.0.1 >nul
goto wait

:up
echo   LISTENING   %URL%
goto openmaybe

:alreadyup
echo   ALREADY UP  %URL%      nothing was started, nothing was stopped
goto openmaybe

:openmaybe
if /i "%~1"=="noopen" goto done
start "" "%URL%"
goto done

:done
echo.
echo   Turn the line on and off from that page, or from here:
echo     curl 127.0.0.1:8777/api/status
echo     curl -X POST "127.0.0.1:8777/api/start-all"
echo     curl -X POST "127.0.0.1:8777/api/stop-all"
echo.
exit /b 0

:notours
echo.
echo   *** :8777 IS HELD BY SOMETHING THAT IS NOT THE SWITCHBOARD ***
echo   It answered, but it did not say it was a switchboard, so it was left
echo   exactly as it was. Nothing was started and nothing was stopped.
echo   Find it with:  netstat -ano ^| findstr :8777
echo.
exit /b 1

:notup
echo.
echo   *** THE SWITCHBOARD DID NOT COME UP IN 20 SECONDS ***
echo   A window called "Switchboard" was started - read the error in it.
echo   Nothing else was started and nothing was stopped.
echo.
exit /b 1

:nopython
echo.
echo   *** NO PYTHON ON PATH ***
echo   Looked for "py" and for "python". Neither answered.
echo   Nothing was started and nothing was stopped.
echo.
exit /b 1

:nofile
echo.
echo   *** switchboard.py NOT FOUND ***
echo   Looked for: %SB%
echo   Nothing was started and nothing was stopped.
echo.
exit /b 1
