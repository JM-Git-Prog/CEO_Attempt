@echo off
setlocal
title Stop the Sam Loop between rounds

REM STOP-SAM-LOOP.bat  -  2026-09-10  (the Sam Loop, decision 23 / John's "C")
REM Writes sim-player\STOP; the loop ends after the round it is in (a round takes up to 35 minutes). It never kills anything - the running round finishes and is analyzed.
REM Finds The Living Room by its known path first, then next to this file (a card you click is a
REM copy saved wherever the app puts downloads). Python is detected, never hard-coded: the same
REM python that runs LIVING-ROOM.bat (python on PATH), then py. Batch rules: no call :label, no
REM parenthesised blocks, no redirect characters except intended file redirects, every exit pauses.

set "CEO=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
if exist "%CEO%\sim-player\sam_loop.py" goto haveceo
set "CEO=%~dp0"
set "CEO=%CEO:~0,-1%"
if exist "%CEO%\sim-player\sam_loop.py" goto haveceo
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
echo stop> "%CEO%\sim-player\STOP"
echo.
echo   STOP written to sim-player\STOP - the Sam Loop ends after the current round.
echo   Watch sim-player\sim-runs\heartbeat.json: "phase": "stopped" means it is done.
echo.
pause
exit /b 0

:nopy
echo.
echo   STOP: no Python found. Looked for python.exe and py.exe on PATH.
echo   The Living Room itself runs with the same python, so this should not happen.
pause
exit /b 1

:noceo
echo.
echo   STOP: sim-player\sam_loop.py was not found. Looked in:
echo     1. C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt
echo     2. the folder this .bat is in
pause
exit /b 1
