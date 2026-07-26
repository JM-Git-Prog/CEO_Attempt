@echo off
title Restart Training Monitor + keep the full flywheel loop running
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo This does two things:
echo   1. Makes sure the continuous flywheel loop is running: train -^> register
echo      -^> quick holdout check -^> exam -^> train again, forever - and every
echo      10th cycle, a hyperparameter sweep so a winning combo keeps advancing,
echo      learning, and repeating. If it's currently mid-training, this leaves
echo      it alone rather than interrupting a live GPU job. If it's running but
echo      IDLE (just waiting for more data), this restarts it so it picks up
echo      the latest code - a running copy keeps using whatever code it loaded
echo      when it started, even after a file changes on disk.
echo   2. Closes and reopens the Training Monitor so you're watching it fresh.
echo.

echo [1/3] Checking the flywheel loop...
set FLYWHEEL_RUNNING=0
tasklist /FI "WINDOWTITLE eq flywheel-loop" 2>NUL | find /I "cmd.exe" >NUL
if not errorlevel 1 set FLYWHEEL_RUNNING=1

if "%FLYWHEEL_RUNNING%"=="0" echo       Not running - starting it now.
if "%FLYWHEEL_RUNNING%"=="0" start "flywheel-loop" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && bench\venv-train\Scripts\python bench\flywheel_loop.py >> bench\flywheel-console.txt 2>&1"

set FLYWHEEL_BUSY=0
if "%FLYWHEEL_RUNNING%"=="1" python -c "import json,time,sys; d=json.load(open('bench/training-progress.json')); sys.exit(1 if d.get('stage') in ('training','loading_model','saving_gguf') and (time.time()-d.get('updated',0))<1800 else 0)" 2>NUL
if "%FLYWHEEL_RUNNING%"=="1" if errorlevel 1 set FLYWHEEL_BUSY=1

if "%FLYWHEEL_RUNNING%"=="1" if "%FLYWHEEL_BUSY%"=="1" echo       Already running and mid-training right now - left alone (never interrupt a live GPU job).
if "%FLYWHEEL_RUNNING%"=="1" if "%FLYWHEEL_BUSY%"=="0" echo       Already running, idle right now - restarting it so it's on the latest code.
if "%FLYWHEEL_RUNNING%"=="1" if "%FLYWHEEL_BUSY%"=="0" taskkill /FI "WINDOWTITLE eq flywheel-loop" /F >NUL 2>&1
if "%FLYWHEEL_RUNNING%"=="1" if "%FLYWHEEL_BUSY%"=="0" start "flywheel-loop" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && bench\venv-train\Scripts\python bench\flywheel_loop.py >> bench\flywheel-console.txt 2>&1"

echo [2/3] Closing any existing Training Monitor window...
taskkill /FI "WINDOWTITLE eq Training Monitor - The Living Room" /F >NUL 2>&1

echo [3/3] Opening a fresh Training Monitor...
start "training-monitor" cmd /c "python tools\training_monitor.py & echo. & echo Training Monitor closed (or failed to start - check above). & pause"

echo.
echo Done. Flywheel log: bench\flywheel-log.txt
echo Pause the whole flywheel any time by creating bench\PAUSE-FLYWHEEL.txt
echo.
pause
