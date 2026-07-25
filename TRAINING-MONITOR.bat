@echo off
title Training Monitor (desktop app)
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo Opening the Training Monitor desktop app...
echo (Live CPU/GPU/RAM, training stage, and generation history. Close its
echo  window when you're done - this console will then let you press a key.)
python tools\training_monitor.py
echo.
echo Training Monitor closed (or failed to start - check any error above).
echo.
pause
