@echo off
title Reload the flywheel with the newest code
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo Restarts the supervisor and both loops so they pick up code changed on disk.
echo A running Python program keeps using whatever code it loaded at startup, so
echo editing a file does nothing until the program is restarted.
echo.
echo It will REFUSE to do anything if training is actively running right now -
echo never interrupt a live GPU job.
echo.

echo [1/4] Checking whether training is actively running...
set TRAINING_ACTIVE=0
python -c "import json,time,sys; d=json.load(open('bench/training-progress.json')); sys.exit(1 if d.get('stage') in ('training','loading_model','saving_gguf') and (time.time()-d.get('updated',0))<1800 else 0)" 2>NUL
if errorlevel 1 set TRAINING_ACTIVE=1

if "%TRAINING_ACTIVE%"=="1" echo.
if "%TRAINING_ACTIVE%"=="1" echo    STOPPING: training is live right now. Nothing was touched.
if "%TRAINING_ACTIVE%"=="1" echo    Run this again once the current cycle finishes.
if "%TRAINING_ACTIVE%"=="1" echo.
if "%TRAINING_ACTIVE%"=="1" pause
if "%TRAINING_ACTIVE%"=="1" exit /b 0

echo       Nothing actively training - safe to restart.

echo [2/4] Stopping the supervisor and everything it started...
taskkill /FI "WINDOWTITLE eq flywheel-supervisor" /T /F >NUL 2>&1
timeout /t 3 /nobreak >NUL

echo [3/4] Verifying it actually stopped...
set STILL_UP=0
tasklist /FI "WINDOWTITLE eq flywheel-supervisor" 2>NUL | find /I "cmd.exe" >NUL
if not errorlevel 1 set STILL_UP=1

if "%STILL_UP%"=="1" echo.
if "%STILL_UP%"=="1" echo    WARNING: the supervisor still shows as running after taskkill.
if "%STILL_UP%"=="1" echo    The kill did NOT verifiably work - check Task Manager for
if "%STILL_UP%"=="1" echo    "flywheel-supervisor" and close it by hand, then run this again.
if "%STILL_UP%"=="1" echo    Not starting a second copy on top of it.
if "%STILL_UP%"=="1" echo.
if "%STILL_UP%"=="1" pause
if "%STILL_UP%"=="1" exit /b 1

echo       Confirmed stopped.

echo [4/4] Starting it back up fresh via Clear Launcher...
call "C:\Users\JohnM\OneDrive\Desktop\Clear Launcher.bat"

echo.
echo Done - the harvester is now running the new code, including the free
echo repair pass. New rescued rows will show up in the dashboard's
echo "Rescued by the free repair pass" card as they happen.
echo.
pause
