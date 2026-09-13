@echo off
setlocal
title Sam Loop self-tests (no model, no server)

REM RUN-SAM-SELFTESTS.bat  -  2026-09-10  (the Sam Loop, decision 23 / John's "C")
REM Runs the Sam Loop's tests under pytest: the state machine against a fake Living Room, the world seeding, the runner, the mechanic's guards, the analysis. No Ollama, no server, nothing outside a temp folder.
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
echo.
echo  ============================================================
echo   SAM LOOP SELF-TESTS  -  pytest, no model, no server
echo  ============================================================
echo.
"%PY%" -m pytest tests\test_sim_player.py tests\test_sim_mechanic.py tests\test_sim_analysis.py tests\test_sim_furnish.py tests\test_sim_board.py tests\test_candidate_labels.py tests\test_architect_card.py -q -p no:cacheprovider
set "RC=%ERRORLEVEL%"
echo.
echo   ---- the modules that can check themselves ----
"%PY%" sim-player\sim_board.py --selftest
if errorlevel 1 set "RC=1"
"%PY%" sim-player\eyes.py
if errorlevel 1 set "RC=1"
"%PY%" sim-player\remember.py
if errorlevel 1 set "RC=1"
"%PY%" sim-player\sam.py --selftest
if errorlevel 1 set "RC=1"
"%PY%" sim-player\sam_loop.py --selftest
if errorlevel 1 set "RC=1"
echo.
if "%RC%"=="0" echo   RESULT: ALL GREEN.
if not "%RC%"=="0" echo   RESULT: FAILED, exit code %RC%. The FAILED lines above say which.
echo.
pause
exit /b %RC%

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
