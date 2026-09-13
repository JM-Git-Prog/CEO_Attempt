@echo off
setlocal
title Teach the talk lane - prove the checker

REM Proves the conversation grader before it is ever allowed to make training data:
REM every rule trips on a known-bad reply, and the product's own system prompt and
REM reply schema are still the ones this factory teaches. No model is called, nothing
REM is written, nothing is spent.

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "H1=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\teach-talk"
if exist "%H1%\teach_talk.py" set "HERE=%H1%"
if not exist "%HERE%\teach_talk.py" echo   teach_talk.py was not found. Looked in: %H1% and %~dp0 - nothing was run. && pause && exit /b 1

set "PY="
if exist "C:\Program Files\Python313\python.exe" set "PY=C:\Program Files\Python313\python.exe"
if not defined PY if exist "C:\Program Files\Python312\python.exe" set "PY=C:\Program Files\Python312\python.exe"
if not defined PY set "PY=python"

echo.
echo  ============================================================
echo   TEACH THE TALK LANE - the checker's own proof
echo   Python: %PY%
echo  ============================================================
echo.
"%PY%" "%HERE%\teach_talk.py" --selftest
if errorlevel 1 echo. && echo   RESULT: FAILED - the grader is not trustworthy yet, so it must not make training data. && pause && exit /b 1
echo.
echo   RESULT: OK - every rule trips on a known-bad reply, and the product still uses this contract.
echo   Next: teach_talk.py --once 12   (drafts 12 turns on the cloud lane and keeps only the survivors)
echo.
pause
exit /b 0
