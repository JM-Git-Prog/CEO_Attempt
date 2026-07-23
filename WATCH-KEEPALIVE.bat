@echo off
REM ============================================================
REM  WATCH-KEEPALIVE.bat - for Task Scheduler and Kiro hooks ONLY.
REM  Non-interactive BY DESIGN: no pause (approved exception to the
REM  interactive-bat pause rule; this runs hidden every few minutes).
REM  Idempotent: it always tries to start the Ratchet watch; if one
REM  is already running, the loop's own lock refuses the duplicate
REM  within ~1 second and this instance exits harmlessly.
REM  The real watch it starts is OS-owned - it survives Kiro closing,
REM  agent context boundaries, and session ends.
REM ============================================================
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
start "ratchet-watch" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python tools\ratchet_loop.py --watch --timeout 1200 --trial-workers 2 --trials-per-lane 5 --changed-files keepalive-revive >> output\qualification\keepalive.log 2>&1"
exit /b 0
