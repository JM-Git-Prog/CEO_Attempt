@echo off
title Probe exam (llama3.1 vs planner-probe-v1)
echo Benching your trained probe against plain llama3.1 - PLAN LEGALITY only.
echo No ComfyUI, no renders. 30 prompts x 2 lanes - takes a while (each plan
echo is a real model call + real solver, roughly 20-90 seconds each).
echo Results stream below and save to bench\results-*.json as they go -
echo the Training Monitor app picks up the new score automatically.
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
python bench\plan_bench.py --lanes "llama3.1,planner-probe-v1" --prompts 30
echo.
echo Exam finished (or failed - read above).
echo.
pause
