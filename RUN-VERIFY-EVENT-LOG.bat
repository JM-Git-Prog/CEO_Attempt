@echo off
title Verify the V17 event log
echo.
echo ==========================================================
echo    VERIFY THE V17 EVENT LOG
echo ==========================================================
echo.
echo This proves every sentence you type into V17 is captured as
echo training data - including the turns that fail.
echo.

set "REPO=%~dp0"
set "PY="

if exist "%REPO%.venv\Scripts\python.exe" set "PY=%REPO%.venv\Scripts\python.exe"
if not defined PY if exist "%REPO%venv\Scripts\python.exe" set "PY=%REPO%venv\Scripts\python.exe"
if not defined PY if exist "%REPO%.venv\Scripts\python3.exe" set "PY=%REPO%.venv\Scripts\python3.exe"
if defined PY goto RUNIT

echo Looking for Python on your PATH...
where python
if errorlevel 1 goto NOPYTHON
set "PY=python"

:RUNIT
echo.
echo Using: %PY%
echo.
"%PY%" "%REPO%VERIFY-EVENT-LOG.py"
if errorlevel 1 goto FAILED
echo.
echo ==========================================================
echo    DONE - the check passed.
echo ==========================================================
echo.
pause
exit /b 0

:FAILED
echo.
echo ==========================================================
echo    The check reported a problem. Read the lines above.
echo ==========================================================
echo.
pause
exit /b 1

:NOPYTHON
echo.
echo ==========================================================
echo    Could not find Python. Looked in:
echo      %REPO%.venv\Scripts\python.exe
echo      %REPO%venv\Scripts\python.exe
echo      %REPO%.venv\Scripts\python3.exe
echo      python on your PATH
echo ==========================================================
echo.
pause
exit /b 1
