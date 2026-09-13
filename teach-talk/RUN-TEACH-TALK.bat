@echo off
setlocal
title Teach the talk lane - draft 12 turns and keep only the survivors

REM The conversation's first teacher factory (John, 2026-09-11).
REM Proves the grader FIRST, then drafts twelve real kid-and-builder turns on the prepaid
REM cloud lane (the 4090 stays free) and keeps only the replies that pass every rule.
REM Survivors land in talk-sft.jsonl; the rest are kept in talk-rejected.jsonl WITH the
REM reason, because a rejected draft is evidence about the teacher, not rubbish.
REM Takes about two minutes. Nothing is trained, nothing in the world is touched.
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
echo   TEACH THE TALK LANE - twelve turns, graded
echo   Python: %PY%
echo   Folder: %HERE%
echo  ============================================================
echo.
echo  [1/2] Proving the grader before it is allowed to make training data...
"%PY%" "%HERE%\teach_talk.py" --selftest
if errorlevel 1 echo. && echo   RESULT: FAILED - the grader did not pass its own test, so no training data was made. && pause && exit /b 1

echo.
echo  [2/2] Drafting twelve turns on the cloud lane and grading each one...
"%PY%" "%HERE%\teach_talk.py" --once 12
if errorlevel 1 echo. && echo   RESULT: FAILED while drafting - read teach-talk-log.txt in %HERE%. && pause && exit /b 1

echo.
echo  ------------------------------------------------------------
echo   RESULT: OK - the "kept N of 12" line above is the survival rate.
echo   Survivors:  %HERE%\talk-sft.jsonl
echo   Rejected:   %HERE%\talk-rejected.jsonl  (each with its reason)
echo   Every call: %HERE%\calls.jsonl          (the capture law)
echo   Log:        %HERE%\teach-talk-log.txt
echo  ------------------------------------------------------------
echo.
pause
exit /b 0
