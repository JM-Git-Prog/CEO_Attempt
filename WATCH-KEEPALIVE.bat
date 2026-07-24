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
REM --enable-lane = John's explicit cloud authorization (recorded in lanes.json
REM authorization blocks, 2026-07-22 and 2026-07-23). File ships disabled by
REM design; enabling happens here, at launch, per the loop's spend-guard.
start "ratchet-watch" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python tools\ratchet_loop.py --watch --timeout 1200 --trial-workers 2 --trials-per-lane 5 --enable-lane ollama-pro-glm-5-2 --enable-lane ollama-pro-kimi-k2-6 --enable-lane ollama-pro-gpt-oss-120b --enable-lane ollama-pro-qwen3-coder-480b --enable-lane ollama-pro-deepseek-v3-1 --changed-files keepalive-revive >> output\qualification\keepalive.log 2>&1"
REM Telemetry probe (dashboard CPU/GPU/RAM panel) - same idempotent pattern:
REM its own lock refuses duplicates within ~1 second.
start "telemetry-probe" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python tools\telemetry_probe.py >> output\qualification\telemetry.log 2>&1"
exit /b 0
