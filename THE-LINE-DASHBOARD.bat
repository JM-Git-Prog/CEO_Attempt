@echo off
setlocal
title THE LINE - live dashboard on http://127.0.0.1:8099

REM THE-LINE-DASHBOARD.bat  -  2026-09-14
REM
REM John: "i need some type of live streaming dashboard i can run locally that shows me everything
REM happning live in my game, i.e. whats being painted, whats being rendered and meshed, what Sam is
REM doing, how the cloud models are responding etc."
REM
REM One page, refreshing every two seconds, on your own machine:
REM   SAM RIGHT NOW        the live round's transcript - what he sees, what he types, what the app said
REM   THE MODELS ANSWERING every call this round: tag, cloud or local, latency, tokens, and whether
REM                        the reply actually came back as JSON - plus what is holding the 4090
REM   RENDER/MESH/PAINT    ComfyUI 8188 / 8190 / 8183, what is running, what is queued, VRAM left
REM   WHAT GOT MADE        every png and glb written under worlds\ in the last 30 minutes
REM   THE LOOP             heartbeat, phase, and how each recent round was judged
REM   TRAINING SET         lessons kept against the 200 needed before a QLoRA run is honest
REM   SERVICES             all seven ports, up or down, with their response time
REM   LOG                  the loop log, live
REM
REM READ-ONLY. It opens no model, queues no job and writes no file. Safe to leave running all night,
REM safe to open while the loop is mid-round. Closing this window closes the dashboard; the loop and
REM the factory carry on without it.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit pauses.

set "CEO=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
if exist "%CEO%\sim-player\dashboard.py" goto haveceo
set "CEO=%~dp0"
set "CEO=%CEO:~0,-1%"
if exist "%CEO%\sim-player\dashboard.py" goto haveceo
goto noceo

:haveceo
set "PY="
where /q python.exe
if not errorlevel 1 set "PY=python"
if defined PY goto havepy
where /q py.exe
if not errorlevel 1 set "PY=py"
if defined PY goto havepy
goto nopy

:havepy
cd /d "%CEO%"
set "PORT=8099"
if not "%~1"=="" set "PORT=%~1"

REM If a copy of this dashboard is already on the port, the PYTHON takes over from it - it asks
REM the thing on the port who it is, and only stands it down if it answers with this dashboard's own
REM signature. That handshake used to live here in batch, as a PowerShell query nested inside a
REM for /f inside a quoted -Command, and it never fired once: the quoting collapsed, the check fell
REM through, and John got a stale build that looked live. Batch is the wrong place for it.
REM 2026-09-14: AND IF THE THING ON THE PORT IS TOO OLD TO ANSWER THE HANDSHAKE.
REM The takeover asks /api/whoami and only stands a copy down if it answers with this dashboard's
REM signature. A build from before that route existed answers with the HTML page instead, so the
REM python correctly refuses to touch it and exits 1 - which left John looking at a stale dashboard
REM with no way forward but hunting for the right window to close. It should never cost him that.
REM So: if the port is held by something this dashboard will not evict, move up one and say so.
REM Nothing is killed, nothing is closed, and the old one keeps serving whoever is watching it.
echo.
echo   Opening http://127.0.0.1:%PORT% in your browser in a moment.
echo   Leave THIS window open - it is the dashboard server.
echo.
start "" "http://127.0.0.1:%PORT%"
"%PY%" sim-player\dashboard.py --port %PORT%
if not errorlevel 1 goto stopped
set /a PORT=%PORT%+1
echo.
echo   :%PORT% it is, then - the old port is held by a copy too old to hand it over.
echo   Opening http://127.0.0.1:%PORT% instead. THIS window is the live one.
echo.
start "" "http://127.0.0.1:%PORT%"
"%PY%" sim-player\dashboard.py --port %PORT%
if not errorlevel 1 goto stopped
set /a PORT=%PORT%+1
echo.
echo   and :%PORT%. Opening http://127.0.0.1:%PORT%.
echo.
start "" "http://127.0.0.1:%PORT%"
"%PY%" sim-player\dashboard.py --port %PORT%

:stopped
echo.
echo   Dashboard stopped. Nothing else was affected.
echo.
pause
exit /b 0

:nopy
echo.
echo   STOP: no Python found. Looked for python.exe and py.exe on PATH.
pause
exit /b 1

:noceo
echo.
echo   STOP: sim-player\dashboard.py was not found. Looked in:
echo     1. C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt
echo     2. the folder this .bat is in
pause
exit /b 1
