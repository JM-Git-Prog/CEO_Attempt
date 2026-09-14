@echo off
setlocal
title PROVE SAM - the three things that have never actually run

REM PROVE-SAM.bat  -  2026-09-14
REM
REM Everything built on 09-11 has passed unit tests and has NEVER EXECUTED IN PRODUCTION.
REM The tests ran in a Linux container with no GPU, no Ollama and no local servers - they
REM prove the logic and nothing about the runtime. The loop log carries two lines nobody read:
REM    REFUSING to start the sim Pick Board: port 8194 is John's own board
REM ...and sim-player\sim-board\ does not exist, which is the folder the board makes before
REM it spawns. So the board has never served a request.
REM
REM This proves, live and in order, stopping at the first failure:
REM   1. the sim Pick Board starts on :8294 and answers
REM   2. a real vision model scores a real picture - and is not just saying the same number
REM   3. a round folds into sam-head.json and loads back (rolled back afterwards)
REM
REM Costs nothing: no render, no mesh, no paint. Your board on :8194 is not touched.
REM Needs Ollama up. Takes a couple of minutes.

set "CEO=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
if exist "%CEO%\sim-player\prove_sam.py" goto haveceo
set "CEO=%~dp0"
set "CEO=%CEO:~0,-1%"
if exist "%CEO%\sim-player\prove_sam.py" goto haveceo
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
REM Everything goes to prove-sam-log.txt as well as the screen, so a run can be read back
REM after the window is gone or buried. Batch has no tee: redirect, then type it out.
"%PY%" sim-player\prove_sam.py > "%CEO%\prove-sam-log.txt" 2>&1
set "RC=%ERRORLEVEL%"
type "%CEO%\prove-sam-log.txt"
echo.
if "%RC%"=="0" echo   Next: RUN-SAM-ONCE.bat
if not "%RC%"=="0" echo   Do not start the night loop until the failures above are fixed.
echo.
pause
exit /b %RC%

:nopy
echo.
echo   STOP: no Python found. Looked for python.exe and py.exe on PATH.
pause
exit /b 1

:noceo
echo.
echo   STOP: sim-player\prove_sam.py was not found.
pause
exit /b 1
