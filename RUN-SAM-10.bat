@echo off
setlocal
title RUN SAM 10 - the whole line, ten rounds, one batch

REM RUN-SAM-10.bat  -  2026-09-14
REM
REM ONE DOUBLE-CLICK. John: "i want to see Sam go through 10 complete end to end runs right now
REM with all the servers he needs up and running, and he ends with what he wants."
REM
REM WHY THIS FILE EXISTS. Everything Sam needs was going up in a different window each time, in a
REM folder with a hundred and twenty .bat files, and when one of them was missed the loop wedged
REM looking perfectly healthy. This starts the lot, in order, in their own windows, and then runs
REM the ten rounds.
REM
REM WHAT IT STARTS
REM   1. the world on :5173          - so you can walk into the house Sam is building in
REM   2. THE LINE on :8099           - the live view: Sam's wishes, the models, the factory, ASKED vs BUILT
REM   3. the Sam Loop                - 10 rounds, depth C, factory ON, consolidating once at the end
REM
REM The loop starts the REST by itself and waits for each one: Ollama, Sam's Pick Board (:8294),
REM the Neighbourhood Builder (:8196) and Sam's own Living Room (:8001). It never touches John's
REM :8000 or his :8194.
REM
REM WHAT IT ENDS WITH. sim-player\sim-runs\WHAT-SAM-WANTS.md - what he has, what he is still
REM chasing after all these nights, and what he gave up on. Plus BATCH-001.md, the one sentence he
REM worked out from the ten nights. Both are written whether or not a model answered.
REM
REM Nothing here is killed or closed. Anything already running is left alone - a second copy simply
REM refuses the port and says so.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit pauses.

set "CEO=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
set "WORLD=C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World"
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
echo   RUN SAM 10  -  the whole line
echo   Python: %PY%
echo  ============================================================
echo.

echo   1/3  the world on :5173
if exist "%WORLD%\RESTART-WORLD-5173.bat" start "World 5173" cmd /k "%WORLD%\RESTART-WORLD-5173.bat"
if not exist "%WORLD%\RESTART-WORLD-5173.bat" echo        skipped - RESTART-WORLD-5173.bat not found
timeout /t 8 /nobreak >nul

echo   2/3  THE LINE on :8099
start "THE LINE" cmd /k %PY% sim-player\dashboard.py --port 8099
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:8099"

echo   3/3  the Sam Loop - 10 rounds, batch 10, factory ON
echo.
echo        The loop brings up Ollama, Sam's Pick Board, the Builder and his
echo        Living Room by itself, and waits for each. First round starts within
echo        a minute or two.
echo.
start "Sam Loop" cmd /k %PY% sim-player\sam_loop.py --rounds 10 --depth C --factory --batch 10

echo  ============================================================
echo   Three windows opened. LEAVE THEM OPEN - they are the servers.
echo.
echo   Watch it live:  http://127.0.0.1:8099
echo   Walk the world: http://localhost:5173/sim-neighborhood
echo   Stop early:     STOP-SAM-LOOP.bat
echo.
echo   When the ten rounds are done, read:
echo     sim-player\sim-runs\WHAT-SAM-WANTS.md   what he still wants
echo     sim-player\sim-runs\BATCH-001.md        what he worked out
echo  ============================================================
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
echo   STOP: sim-player\sam_loop.py was not found. Looked in:
echo     1. C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt
echo     2. the folder this .bat is in
pause
exit /b 1
