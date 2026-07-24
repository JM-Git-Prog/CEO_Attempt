@echo off
title Start telemetry probe (dashboard machine panel)
echo Starting the telemetry probe - it feeds the MACHINE panel on your
echo executive dashboard with live CPU / GPU / RAM per component.
echo.
echo Safe to run any time: if a probe is already running, the new one
echo notices within a second and exits - no duplicates.
echo (The 5-minute keepalive task also revives it automatically, so you
echo only ever need this button for an instant start or restart.)
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
start "telemetry-probe" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python tools\telemetry_probe.py >> output\qualification\telemetry.log 2>&1"
echo Probe launched in a minimized window. The dashboard panel goes live
echo within ~15 seconds of the next page refresh.
echo.
pause
