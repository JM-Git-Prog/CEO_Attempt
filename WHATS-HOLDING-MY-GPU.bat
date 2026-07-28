@echo off
title What is holding the GPU
echo ============================================================
echo  READ-ONLY. Asks Ollama and the driver what is on the card.
echo  Nothing is killed, unloaded, or changed.
echo ============================================================
echo.

echo ---- 1. Models Ollama has parked in VRAM ----
echo (Look at UNTIL. "Forever" or a year like 2318 = pinned, never unloads.)
echo.
ollama ps
echo.

echo ---- 2. Card totals ----
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw --format=csv
echo.

echo ---- 3. Per-process VRAM ----
echo (Often blank on a GeForce under Windows - blank means the driver would
echo  not say, NOT that the card is empty. Use Task Manager if blank:
echo  Details tab, right-click a column, add "Dedicated GPU memory".)
echo.
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
echo.

echo ---- 4. The two settings that pin models forever ----
echo OLLAMA_KEEP_ALIVE        = %OLLAMA_KEEP_ALIVE%
echo OLLAMA_MAX_LOADED_MODELS = %OLLAMA_MAX_LOADED_MODELS%
echo (Blank here just means this window started before they were set -
echo  the lines below read the saved machine-level values.)
reg query "HKCU\Environment" /v OLLAMA_KEEP_ALIVE 2>nul
reg query "HKCU\Environment" /v OLLAMA_MAX_LOADED_MODELS 2>nul
echo.

echo ============================================================
echo  Copy everything above back to Claude.
echo ============================================================
echo.
pause
