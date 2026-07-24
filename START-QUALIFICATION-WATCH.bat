@echo off
title Ratchet qualification watch (manual start - BACKUP ONLY)
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo NOTE (2026-07-22): Kiro has SOLE custody of the watch now.
echo Use this only if Kiro is down and its watch is dead - otherwise
echo this will simply refuse because Kiro's watch holds the lock.
echo.
echo Starting the Ratchet qualification watch.
echo If a watch is already running it will say so and stop - safe to run any time.
echo This window IS the loop - leave it open. Ctrl+C stops it cleanly.
echo.
python tools\e2e_qualification.py --watch --timeout 1200 --output-root output\qualification --enable-lane ollama-pro-glm-5-2 --enable-lane ollama-pro-kimi-k2-6 --enable-lane ollama-pro-gpt-oss-120b --enable-lane ollama-pro-qwen3-coder-480b --enable-lane ollama-pro-deepseek-v3-1 --changed-files manual-start
echo.
echo Watch exited (or refused because one is already running - read the line above).
pause
