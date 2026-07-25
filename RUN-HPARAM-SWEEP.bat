@echo off
title Stage C - LoRA hyperparameter sweep (slow - trains 5 candidates)
echo Trains 5 hyperparameter combinations, each under its own model name
echo (planner-probe-sweep-*) so the live planner-probe-v1 is never touched.
echo Ranks them on the Stage B holdout set. If a combo actually beats
echo baseline, writes bench\best-hparams.json - the NEXT normal training
echo cycle then uses it automatically. This is slow: 5 full training runs.
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
bench\venv-train\Scripts\python bench\hparam_sweep.py
echo.
echo Sweep finished (or failed - read above). Log: bench\hparam-sweep-log.json
pause
