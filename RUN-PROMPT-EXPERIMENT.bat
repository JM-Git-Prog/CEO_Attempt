@echo off
title Stage A - prompt-variant experiment (no GPU cost, plan-only)
echo Tests whether a change to the planning prompt moves the legal-plan rate.
echo Model is held FIXED (planner-probe-v1) - only the prompt wording changes
echo across variants: control, explicit-math, self-check. 15 prompts each.
echo Leaderboard prints at the end and saves to bench\prompt-experiment-summary-*.json
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
python bench\prompt_experiment.py --lane planner-probe-v1 --prompts 15
echo.
echo Experiment finished (or failed - read above).
pause
