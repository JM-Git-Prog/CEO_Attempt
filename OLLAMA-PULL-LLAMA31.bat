@echo off
setlocal
title Ollama - pulling llama3.1 (about 4.9 GB, John approved 2026-07-30)
echo ============================================================
echo   Downloading llama3.1 into Ollama (~4.9 GB, one time).
echo   When it finishes, v15_Fable's planner switches from the
echo   procedural fallback to the real LLM automatically.
echo ============================================================
echo.
ollama pull llama3.1
echo.
echo -- installed models now: --
ollama list
echo.
echo DONE - you can close this window. v15_Fable will use the LLM
echo on the next "Draft three blueprints" click, no restart needed.
pause
