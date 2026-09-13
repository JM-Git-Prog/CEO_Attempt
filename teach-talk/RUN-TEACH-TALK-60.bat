@echo off
setlocal
title Teach the talk lane - sixty turns, graded

REM The scale batch (John, 2026-09-11, "b now"). Twelve turns survived 12 of 12 once the
REM grader's plural bug was fixed; sixty says whether that holds, which is the only thing
REM that decides if this may ever run unwatched.
REM
REM Three steps: prove the grader, rescue what the OLD grader wrongly binned, then draft
REM sixty turns on the prepaid cloud lane (the 4090 stays free). About a minute. Nothing
REM is trained, nothing in the world is touched, nothing is spent.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit prints and pauses,
REM no redirect characters except intended file redirects, and the working folder is found
REM by a known path with a fallback - the card you click is a copy saved wherever your
REM downloads go, not the file in the project folder.

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
echo   TEACH THE TALK LANE - sixty turns, graded
echo   Python: %PY%
echo   Folder: %HERE%
echo  ============================================================
echo.
echo  [1/2] Proving the grader, including the two replies it wrongly binned last time...
"%PY%" "%HERE%\teach_talk.py" --selftest
if errorlevel 1 echo. && echo   RESULT: FAILED - the grader did not pass its own test, so no training data was made. && pause && exit /b 1

echo.
echo  [2/2] Rescuing what the old grader binned, then drafting sixty turns...
"%PY%" "%HERE%\teach_talk.py" --regrade --once 60
if errorlevel 1 echo. && echo   RESULT: FAILED while drafting - read teach-talk-log.txt in %HERE%. && pause && exit /b 1

echo.
echo  ------------------------------------------------------------
echo   RESULT: OK - read two lines above: how many earlier rejections were rescued,
echo   and the "kept N of 60" survival rate. That rate decides whether this may
echo   ever run overnight unwatched.
echo   Survivors:  %HERE%\talk-sft.jsonl
echo   Rejected:   %HERE%\talk-rejected.jsonl  (each with its reason)
echo   Rescued:    %HERE%\promoted.jsonl
echo   Log:        %HERE%\teach-talk-log.txt
echo  ------------------------------------------------------------
echo.
pause
exit /b 0
