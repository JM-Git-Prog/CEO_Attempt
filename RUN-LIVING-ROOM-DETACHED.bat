@echo off
setlocal
REM RUN-LIVING-ROOM-DETACHED.bat - bring the Living Room (:8000) up and return at once.
REM The site-runner kills anything still running at 180 s, so this must never block or pause;
REM instead every line it prints is also appended to living-room-start-log.txt beside this
REM script, so a step whose tool call times out can still be read from disk afterwards
REM (the 2026-09-10 long-job rule: a long job writes its console to a file beside the job).
REM
REM 2026-09-11: two repairs, both from the 2026-09-10 outage.
REM  1. PATH. The window this opens inherits THIS environment. That night the site-runner's
REM     PATH held a python with no uvicorn, so START-LIVING-ROOM-8000.bat's bare "python run.py"
REM     died with ModuleNotFoundError and :8000 stayed down for hours. Find a python that
REM     actually HAS uvicorn - known locations first, then whatever PATH already offers, never
REM     assuming one - and put its folder first on PATH for the child.
REM  2. THE KILL. This used to route through LIVING-ROOM.bat, which runs a wmic delete of every
REM     python.exe whose command line contains spawn_main - a MACHINE-WIDE kill of every Python
REM     multiprocessing worker, flagged as dangerous in CANONICAL-LAUNCHERS-2026-09-05.md
REM     because John's training runs use them. This path now stops ONLY the process actually
REM     holding :8000, plus its own tree, and starts the server leaf directly. John's own
REM     one-button LIVING-ROOM.bat is untouched and still does the full open-and-verify.

set "LOG=%~dp0living-room-start-log.txt"
echo.>>"%LOG%"
echo === %DATE% %TIME% RUN-LIVING-ROOM-DETACHED>>"%LOG%"

REM --- 1. stop only what is holding :8000 (usually nothing) -------------------
set "HELD="
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do set "HELD=%%p"
if not defined HELD echo   :8000 was free - clean start.
if not defined HELD echo   :8000 was free - clean start.>>"%LOG%"
if not defined HELD goto pickboard
echo   stopping PID %HELD% - the process holding :8000, and its tree, only.
echo   stopping PID %HELD% - the process holding :8000, and its tree, only.>>"%LOG%"
taskkill /PID %HELD% /T /F >nul 2>&1
timeout /t 2 /nobreak >nul
set "STILL="
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do set "STILL=%%p"
if defined STILL echo   FAILED: :8000 is still held by PID %STILL% after the kill. Nothing was started.>>"%LOG%"
if defined STILL echo   FAILED: :8000 is still held by PID %STILL% after the kill. Nothing was started. && exit /b 1

:pickboard
REM --- 2. the Living Room's hard dependency: the Pick Board on :8194 ----------
set "BOARD="
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8194 " ^| findstr LISTENING') do set "BOARD=%%p"
if defined BOARD echo   Pick Board already up on PID %BOARD% - left alone.
if defined BOARD echo   Pick Board already up on PID %BOARD% - left alone.>>"%LOG%"
if not defined BOARD echo   Pick Board not running - starting it.
if not defined BOARD echo   Pick Board not running - starting it.>>"%LOG%"
if not defined BOARD start "" "C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\START-PICK-BOARD.bat"
if not defined BOARD timeout /t 4 /nobreak >nul

REM --- 3. a python that HAS uvicorn, detected, never assumed ------------------
set "PYDIR="
set "TRY=C:\Program Files\Python313"
if not exist "%TRY%\python.exe" goto try312
"%TRY%\python.exe" -c "import uvicorn" >nul 2>&1
if not errorlevel 1 set "PYDIR=%TRY%"

:try312
if defined PYDIR goto haveknown
set "TRY=C:\Program Files\Python312"
if not exist "%TRY%\python.exe" goto trypath
"%TRY%\python.exe" -c "import uvicorn" >nul 2>&1
if not errorlevel 1 set "PYDIR=%TRY%"

:trypath
if defined PYDIR goto haveknown
python -c "import uvicorn" >nul 2>&1
if not errorlevel 1 goto haveonpath
echo   FAILED: no python with uvicorn. Looked in: C:\Program Files\Python313, then>>"%LOG%"
echo   C:\Program Files\Python312, then PATH. Nothing was started.>>"%LOG%"
echo   FAILED: no python with uvicorn. Looked in: C:\Program Files\Python313, then C:\Program Files\Python312, then PATH. Nothing was started. && exit /b 1

:haveonpath
echo   python: the one already on PATH - it has uvicorn.
echo   python: the one already on PATH - it has uvicorn.>>"%LOG%"
goto launch

:haveknown
set "PATH=%PYDIR%;%PATH%"
echo   python: %PYDIR%\python.exe - it has uvicorn, and its folder now leads PATH.
echo   python: %PYDIR%\python.exe - it has uvicorn, and its folder now leads PATH.>>"%LOG%"

:launch
start "Living Room" cmd /c call "%~dp0START-LIVING-ROOM-8000.bat"
echo   Living Room starting in its own window. Poll :8000 to confirm it came up.
echo   Living Room starting in its own window. Poll :8000 to confirm it came up.>>"%LOG%"
exit /b 0
