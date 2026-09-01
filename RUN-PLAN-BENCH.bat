@echo off
setlocal
title Plan Bench - room layout check (no server, no GPU)
cd /d "%~dp0"
echo ============================================================
echo   PLAN BENCH - runs the REAL plan generator against the
echo   REAL PlanValidator. No server, no Ollama, no ComfyUI,
echo   no GPU. Takes about a second.
echo.
echo   Green here means spatial_reconstruction will accept the
echo   plan, so you can iterate on layout WITHOUT restarting
echo   The Living Room on :8000.
echo ============================================================
echo.
python tools\plan_bench.py %*
echo.
echo ------------------------------------------------------------
echo Plan bench finished. Read the PASS/FAIL line above.
echo ------------------------------------------------------------
pause
