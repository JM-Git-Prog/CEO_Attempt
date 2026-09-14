@echo off
setlocal
title Start the Sam Loop - 10 rounds, one batch, then it stops

REM START-SAM-LOOP-ALL-NIGHT.bat  -  2026-09-14
REM
REM TEN ROUNDS, ONE BATCH, THEN IT STOPS. John, 2026-09-14: "change the all night run to 10 ...
REM not 200." The file is still named ALL-NIGHT and that name is now wrong - say the word and it
REM gets renamed; nothing else depends on it.
REM
REM WHY TEN IS THE RIGHT NUMBER. The batch dial is at 10 (sim-player\loop-control.json), so a run
REM of ten rounds is exactly ONE play-then-learn cycle: Sam plays ten nights, the loop reads the
REM whole batch, boils it to one sentence he can hold in his head, writes it into his head, rebuilds
REM the training corpus, and ends. Nothing runs unattended for hours on a lesson nobody has read.
REM You look at BATCH-001.md, decide whether it was worth it, and run this again - or change the
REM dial first.
REM
REM THE DIAL IS LIVE. sim-player\loop-control.json is re-read at the top of every round, so the
REM batch size can be changed WHILE THIS IS RUNNING and the next round uses it. {"batch": 0} means
REM keep playing and never consolidate. Anything broken in that file is ignored and the loop keeps
REM the size it already had.
REM
REM Sam plays on :8001 and never touches John's :8000. Patches are backed up and revertible with
REM REVERT-SAM-PATCHES.bat. The 4090 is waited on before every round. The factory push is local and
REM free - no credits are spent while this runs.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit pauses.

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
echo   THE SAM LOOP  -  10 ROUNDS, ONE BATCH, THEN IT STOPS
echo   Python: %PY%      Folder: %CEO%
echo.
echo   Sam plays 10 nights, depth C, factory ON. Then the loop consolidates:
echo     - it reads the whole batch - every wish, every verdict, what was refused
echo       the same way every time, and every question Sam asked about his own wish
echo     - it boils that to ONE sentence about HOW he asks, and writes it into his head
echo     - it rebuilds the training corpus into 05 Training\15-sam-loop-corpus
echo     - it writes sim-player\sim-runs\BATCH-001.md, then the run ends
echo.
echo   The gap router has TWO doors now: anything in the parametric catalogue (bed,
echo   crib, dresser, toilet, stove, rocking chair and 18 more) is BUILT ON THE SPOT
echo   in milliseconds; everything else goes to the pick board and the 4090 as before.
echo.
echo   Change the batch size mid-run:  sim-player\loop-control.json  ("batch": 10)
echo   Stop early:                     STOP-SAM-LOOP.bat
echo   Watch it live:                  THE-LINE-DASHBOARD.bat
echo  ============================================================
echo.
start "Sam Loop" cmd /k %PY% sim-player\sam_loop.py --rounds 10 --depth C --factory --batch 10
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
