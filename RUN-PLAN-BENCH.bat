@echo off
title Plan-stage micro-bench (no GPU renders - cheap and fast)
echo Benching PLAN LEGALITY only: model -^> real validator -^> real solver.
echo No ComfyUI, no renders. Each plan costs seconds. 12 prompts x 3 lanes.
echo Lanes: llama3.1 (free local) + glm-5.2:cloud + kimi-k2.6:cloud (your sub, $0)
echo Results stream below and save to bench\results-*.json as they go.
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
python bench\plan_bench.py --lanes "llama3.1,glm-5.2:cloud,kimi-k2.6:cloud" --prompts 12
echo.
echo Bench finished (or failed - read above). Claude reads the results file.
pause
