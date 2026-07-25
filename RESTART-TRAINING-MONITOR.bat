@echo off
title Restart Training Monitor + keep the full flywheel loop running
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo This does two things:
echo   1. Makes sure the continuous flywheel loop is running: train -^> register
echo      -^> quick holdout check -^> exam -^> train again, forever. This is the
echo      loop learning the best room layout, from your solver math, your
echo      validator code, and everything banked in the corpus so far. If it is
echo      already running mid-cycle, this leaves it alone rather than
echo      interrupting it.
echo   2. Closes and reopens the Training Monitor so you're watching it fresh.
echo.

echo [1/3] Checking the flywheel loop...
tasklist /FI "WINDOWTITLE eq flywheel-loop" 2>NUL | find /I "cmd.exe" >NUL
if not errorlevel 1 echo       Already running - left alone.
if errorlevel 1 echo       Not running - starting it now.
if errorlevel 1 start "flywheel-loop" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python bench\flywheel_loop.py >> bench\flywheel-console.txt 2>&1"

echo [2/3] Closing any existing Training Monitor window...
taskkill /FI "WINDOWTITLE eq Training Monitor - The Living Room" /F >NUL 2>&1

echo [3/3] Opening a fresh Training Monitor...
start "training-monitor" cmd /c "python tools\training_monitor.py & echo. & echo Training Monitor closed (or failed to start - check above). & pause"

echo.
echo Done. Flywheel log: bench\flywheel-log.txt
echo Pause the whole flywheel any time by creating bench\PAUSE-FLYWHEEL.txt
echo.
pause
