@echo off
title Restart the Ratchet watch - loads today's new code
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo This restarts the qualification watch so it runs TODAY'S changes:
echo   1. Camera FOV ladder  (composition_sidecar.py - the stool_4 fix)
echo   2. Deterministic-failure freeze  (e2e_qualification.py)
echo   3. Five cloud lanes with harvest caps  (lanes.json + keepalive)
echo.
echo Stopping the currently running watch (it holds OLD code in memory)...
powershell -NoProfile -Command "try { $l = Get-Content 'output/qualification/.qualification.lock' -Raw | ConvertFrom-Json; Stop-Process -Id $l.pid -Force -ErrorAction Stop; Write-Host ('Stopped watch pid ' + $l.pid) } catch { Write-Host 'No running watch found (that is fine).' }"
echo.
echo Done. The keepalive task will revive the watch with FRESH code
echo within about 5 minutes, cloud lanes armed.
echo Watch it live on the dashboard: the world-viewer ops panel updates
echo from scoreboard.json as new trials land.
echo.
pause
