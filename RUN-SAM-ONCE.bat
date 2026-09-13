@echo off
setlocal
title Sam plays ONE round (depth A)

REM RUN-SAM-ONCE.bat  -  2026-09-10  (the Sam Loop, decision 23 / John's "C")
REM One round: Sam plays his own copy of the neighborhood on the loop's Living Room (:8001), the round is analyzed, unmet wishes go to the gap ledger, a REPORT.md is written. Nothing in the app changes (depth A). Takes 15-35 minutes; needs Ollama, the Neighbourhood Builder and Sam's OWN Pick Board on :8294 (all started for you if down). John's board on :8194 is never touched, started or written to.
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
echo   THE SAM LOOP  -  one round, depth A (play + analyze + file gaps)
echo   Python: %PY%      Folder: %CEO%
echo   Sam plays on http://127.0.0.1:8001 - your :8000 is not touched.
echo   Sam's world: worlds\sim-neighborhood (reset every round).
echo   This takes 15-35 minutes. The report lands in sim-player\sim-runs\...\REPORT.md
echo  ============================================================
echo.
"%PY%" sim-player\sam_loop.py --once --depth A
set "RC=%ERRORLEVEL%"
echo.
echo  ------------------------------------------------------------
if "%RC%"=="0" echo   RESULT: the round is over. Open sim-player\sim-runs\ - the newest folder holds REPORT.md, transcript.jsonl and calls.jsonl.
if not "%RC%"=="0" echo   RESULT: the loop stopped with exit code %RC%. Read sim-player\sim-runs\loop-log.txt for the reason.
echo  ------------------------------------------------------------
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
