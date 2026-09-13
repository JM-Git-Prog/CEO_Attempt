@echo off
setlocal
title SAM'S PICK BOARD - http://127.0.0.1:8294

REM START-SIM-PICK-BOARD.bat  -  2026-09-11  (John: "Give the sim its own Pick Board")
REM
REM This is the SIM'S board, not yours. Same server, same screen, different port and a different
REM folder underneath: sim-player\sim-board\  holds its stations, its reroll queue, its flags and
REM its own preferences.jsonl. Nothing Sam picks here ever reaches your taste ledger, and your
REM board on :8194 is not started, stopped or read by anything in the Sam Loop.
REM
REM You do not need to run this to play the night - START-SAM-LOOP.bat starts it and stops it with
REM the loop. Run this when you want to LOOK at what Sam has been choosing, or to answer a wall he
REM left open because he could not see the pictures.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit pauses.

set "CEO=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
if exist "%CEO%\sim-player\sim_board.py" goto haveceo
set "CEO=%~dp0"
set "CEO=%CEO:~0,-1%"
if exist "%CEO%\sim-player\sim_board.py" goto haveceo
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
echo.
echo  ============================================================
echo    SAM'S PICK BOARD  -  http://127.0.0.1:8294
echo.
echo    Four takes of a thing Sam asked for go up here; he looks
echo    at each one and picks, and anything he thought was wrong
echo    he marks as denied. Walls he could NOT see are left open
echo    for you - those are the ones worth a click.
echo.
echo    Writes only under: sim-player\sim-board\
echo    Your own board on :8194 is untouched.
echo    Keep this window open. Close it to stop the board.
echo  ============================================================
echo.
"%PY%" sim-player\sim_board.py --start
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo   The board stopped with exit code %RC%. The lines above say why.
pause
exit /b %RC%

:nopy
echo.
echo   STOP: no Python found. Looked for python.exe and py.exe on PATH.
pause
exit /b 1

:noceo
echo.
echo   STOP: sim-player\sim_board.py was not found. Looked in:
echo     1. C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt
echo     2. the folder this .bat is in
pause
exit /b 1
