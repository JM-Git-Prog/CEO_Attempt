@echo off
title Who has my VRAM - per-process ranking
echo ============================================================
echo  READ-ONLY. Ranks every process by how much VRAM it holds.
echo  Nothing is killed, unloaded, or changed.
echo.
echo  Reads Windows' own GPU counters - the same numbers behind
echo  Task Manager's "Dedicated GPU memory" column - because
echo  nvidia-smi will not report per-process VRAM on a GeForce.
echo.
echo  Runs one local script, tools\gpu_memory_by_process.ps1,
echo  which Claude just wrote and you can open and read.
echo ============================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\tools\gpu_memory_by_process.ps1"

echo.
echo ============================================================
echo  Copy the table above back to Claude.
echo ============================================================
echo.
pause
