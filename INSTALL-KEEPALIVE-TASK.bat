@echo off
title Install the Ratchet keep-alive (run once)
echo This registers ONE Windows Scheduled Task named "Ratchet Watch Keepalive".
echo Every 5 minutes, Windows itself runs WATCH-KEEPALIVE.bat, which revives the
echo qualification watch if it is down and does nothing if it is healthy.
echo.
echo This is the fix for last night: the loop becomes OS-owned - it no longer
echo depends on Kiro being open, an agent session staying alive, or anyone
echo remembering to restart it. Only PC sleep can stop it.
echo.
echo This changes Windows Task Scheduler (a system-level change), which is why
echo YOU run this, not Claude. Press any key to install, or close to cancel.
pause
schtasks /Create /F /TN "Ratchet Watch Keepalive" /TR "\"C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\WATCH-KEEPALIVE.bat\"" /SC MINUTE /MO 5
echo.
echo If it says SUCCESS above, the keep-alive is live: the watch will be
echo revived within 5 minutes any time it dies, around the clock.
echo To remove it later:  schtasks /Delete /TN "Ratchet Watch Keepalive" /F
echo.
pause
