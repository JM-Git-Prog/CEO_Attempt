@echo off
setlocal
title Start the Sam Loop (depth C, all night)

REM START-SAM-LOOP.bat  -  2026-09-10  (the Sam Loop, decision 23 / John's "C")
REM Starts the loop in its own window: up to 12 rounds, depth C - Sam plays, every round is analyzed, unmet wishes go to the gap router (things to the factory), defects go to the mechanic (a patch inside the gate, backed up, reverted on failure), and the sim Living Room restarts after a patch. Stop it any time with STOP-SAM-LOOP.bat.
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
echo   THE SAM LOOP  -  depth C, up to 12 rounds, in its own window
echo   Python: %PY%      Folder: %CEO%
echo   Sam plays on :8001 (your :8000 is not touched). Patches the mechanic
echo   makes are backed up under sim-player\sim-runs\ROUND\patches and listed
echo   in sim-player\sim-runs\mechanic-ledger.jsonl. REVERT-SAM-PATCHES.bat undoes them all.
echo   The factory push is ON (John, 2026-09-14: "so start the factory"). Sam asks for a
echo   thing, the gap router pushes it to the board, the 4090 renders and meshes it, and he
echo   SEES it next round - which is the half of the loop that was missing. $0: local GPU,
echo   no credits. To go back to decide-only, remove --factory from the line below.
echo   Before every round the loop waits while the 4090 is busy (training, a paint).
echo   Pause windows: sim-player\pause-windows.txt (lines like 02:00-03:30).
echo   To stop between rounds: STOP-SAM-LOOP.bat
echo  ============================================================
echo.
start "Sam Loop" cmd /k %PY% sim-player\sam_loop.py --rounds 12 --depth C --factory
echo   A second window titled "Sam Loop" opened - LEAVE IT OPEN, that window IS the loop.
echo   Heartbeat: sim-player\sim-runs\heartbeat.json      Log: sim-player\sim-runs\loop-log.txt
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
