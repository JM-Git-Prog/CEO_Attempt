@echo off
title Stop the Ratchet auto-start (trigger 1 of 3)
echo ============================================================
echo  DISABLES the Windows Scheduled Task "Ratchet Watch Keepalive"
echo  so Windows stops reviving ratchet-watch and telemetry-probe
echo  every 5 minutes.
echo.
echo  DISABLE, not delete. Fully reversible - the undo command is
echo  printed at the end. Nothing else on your PC is touched.
echo.
echo  This is a system-level change, which is why YOU run it and
echo  not Claude.
echo.
echo  NOTE: this is trigger 1 of 3. The two Kiro hooks are handled
echo  separately - see the chat.
echo ============================================================
echo.
pause

schtasks /Change /TN "Ratchet Watch Keepalive" /DISABLE

echo.
echo ---- VERIFY: Status below should read Disabled ----
schtasks /Query /TN "Ratchet Watch Keepalive" /FO LIST /V | findstr /I "TaskName Status"
echo.
echo The two windows already open keep running until closed.
echo.

choice /C YN /M "Also close the running ratchet-watch and telemetry-probe now"
if errorlevel 2 goto skip

taskkill /FI "WINDOWTITLE eq ratchet-watch*" /T /F
taskkill /FI "WINDOWTITLE eq telemetry-probe*" /T /F
echo.
echo ---- VERIFY: any surviving windows are listed below ----
tasklist /FI "WINDOWTITLE eq ratchet-watch*"
tasklist /FI "WINDOWTITLE eq telemetry-probe*"
echo.
echo If either still appears above, close that window by hand.
echo Force-closing is safe here: both scripts write files atomically
echo and both re-claim their own stale lock on next start.

:skip
echo.
echo ============================================================
echo  DONE - Windows will no longer auto-start them.
echo.
echo  To undo later:
echo    schtasks /Change /TN "Ratchet Watch Keepalive" /ENABLE
echo ============================================================
echo.
pause
