@echo off
title The $0 data factory - continuous plan bench
echo Starts the continuous plan-bench loop: batches of 15 prompts through
echo llama3.1 and the REAL validators, banking every graded plan into
echo data\flywheel\corpus-bench.jsonl. No renders, no cloud, no spend.
echo.
echo POLITE: waits for tonight's training chain to finish first, and pauses
echo any time you create bench\PAUSE-BENCH.txt. Log: bench\bench-loop-log.txt
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
start "bench-loop" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python bench\bench_loop.py >> bench\bench-loop-console.txt 2>&1"
echo Loop launched minimized. Watch it on the Ops board (SERVERS page).
echo.
pause
