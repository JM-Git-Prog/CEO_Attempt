@echo off
setlocal
title FLUSH v15_fable - purge stale bytecode + native touch + restart
cd /d "%~dp0"
echo ============================================================
echo   Purges src\__pycache__ (stale .pyc can outlive bridge-written
echo   .py edits when the mtime freezes), touches v15_fable.py
echo   natively so Python re-reads it, then restarts The Living Room.
echo ============================================================
echo.
if exist "src\__pycache__" del /q "src\__pycache__\*.pyc" 2>nul
if exist "src\web\__pycache__" del /q "src\web\__pycache__\*.pyc" 2>nul
copy /b "src\v15_fable.py" +,, "src\v15_fable.py" >nul
echo Bytecode purged, file touched natively. Restarting the server...
call "RESTART-LIVING-ROOM-8000.bat"
