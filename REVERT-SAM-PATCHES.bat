@echo off
setlocal
title Undo every patch the mechanic made

REM REVERT-SAM-PATCHES.bat  -  2026-09-10  (the Sam Loop, decision 23 / John's "C")
REM Restores every file the mechanic changed from its backup (sim-player\sim-runs\ROUND\patches), newest first, and deletes the tests it created. Then restart your Living Room with LIVING-ROOM.bat so the old code is what runs.
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
echo   REVERT SAM PATCHES  -  put every mechanic-changed file back
echo  ============================================================
echo.
"%PY%" sim-player\mechanic.py --revert-all
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo   Done. Restart your Living Room (LIVING-ROOM.bat) so the restored code runs.
if not "%RC%"=="0" echo   The revert reported exit code %RC% - read the lines above.
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
