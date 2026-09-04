@echo off
title Save the V17 work (CEO_Attempt) - commit and push

REM ==========================================================================
REM  2026-09-04. CEO_Attempt is its own git repo (remote: JM-Git-Prog/CEO_Attempt)
REM  and had NO save script at all - the contractor site-runner's commit-all-push
REM  only covers the Artificial Intelligence repo, so a whole night of V17 work
REM  (the /api/v17/say router, the rewired page, the persona and picture fixes)
REM  was sitting uncommitted on one disk.
REM
REM  Modelled on John's proven COMMIT-ALL flow:
REM    - shows exactly what will be saved BEFORE saving it
REM    - safety-stops if a lot of files look deleted
REM    - takes a real message from COMMIT-MSG.txt and CONSUMES it after use,
REM      so the next commit can never silently reuse this one's words
REM    - verifies the commit actually landed and fails loudly if it did not
REM    - pushes to the CURRENT branch, whatever it is (not a hard-coded main)
REM ==========================================================================

cd /d "%~dp0"

echo.
echo ==================================================================
echo   SAVE THE V17 WORK - %~dp0
echo ==================================================================
echo.

where git.exe
if errorlevel 1 goto nogit

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BR=%%b"
if not defined BR goto norepo
echo   Branch: %BR%
echo.

echo   Staging everything that changed...
git add -A
if errorlevel 1 goto addfailed

echo.
echo   Here is what will be saved:
git status --short
echo.

set "DEL=0"
for /f %%n in ('git diff --cached --name-only --diff-filter=D ^| find /c /v ""') do set "DEL=%%n"
if %DEL% GTR 50 goto massdelete
echo   ^(%DEL% file^(s^) staged as deleted - under the safety limit of 50.^)
echo.

set "MSG="
if exist "COMMIT-MSG.txt" set /p MSG=<COMMIT-MSG.txt
if not defined MSG set "MSG=save: V17 work snapshot %DATE% %TIME%  (no COMMIT-MSG.txt supplied)"
echo   Commit message:
echo     %MSG%
echo.

git diff --cached --quiet
if not errorlevel 1 goto nothingtodo

git commit -m "%MSG%"
if errorlevel 1 goto commitfailed

REM Verify the commit REALLY landed - never print success after an error.
git diff --cached --quiet
if errorlevel 1 goto stillstaged
echo   Commit recorded:
git log -1 --oneline
echo.

REM Consume the message so the next save cannot silently reuse these words.
if exist "COMMIT-MSG.txt" del "COMMIT-MSG.txt"

echo   Pushing to GitHub on branch %BR%...
git push origin "%BR%"
if errorlevel 1 goto pushfailed

echo.
echo   SAVED AND PUSHED. Your V17 work is off this disk.
echo.
pause
exit /b 0

:nothingtodo
echo   Nothing has changed since the last save - nothing to commit.
echo.
pause
exit /b 0

:massdelete
echo.
echo   *** STOPPED - %DEL% FILES ARE STAGED AS DELETED ***
echo   That is over the safety limit of 50. Nothing has been committed.
echo   Look at the list above. If those deletions are real and wanted,
echo   commit them yourself; if not, run: git reset
echo.
pause
exit /b 1

:addfailed
echo.
echo   *** git add FAILED - nothing was committed. Read the error above. ***
echo.
pause
exit /b 1

:commitfailed
echo.
echo   *** git commit FAILED - NOTHING WAS SAVED. Read the error above. ***
echo   Your files are still on disk and still staged; nothing was lost.
echo.
pause
exit /b 1

:stillstaged
echo.
echo   *** git said it committed but changes are STILL staged. ***
echo   Treat this as a FAILED save. Nothing was pushed.
echo.
pause
exit /b 1

:pushfailed
echo.
echo   *** THE COMMIT SAVED LOCALLY BUT THE PUSH FAILED. ***
echo   Your work IS committed on this machine on branch %BR%, but it is not
echo   on GitHub yet. Most often this is a sign-in prompt - read the error
echo   above, then run this card again.
echo.
pause
exit /b 1

:norepo
echo.
echo   *** THIS FOLDER IS NOT A GIT REPOSITORY ***
echo   Nothing was changed.
echo.
pause
exit /b 1

:nogit
echo.
echo   *** git.exe WAS NOT FOUND ON THE PATH ***
echo   Nothing was changed. Install Git for Windows, or open this folder
echo   in a terminal that has git and run it there.
echo.
pause
exit /b 1
