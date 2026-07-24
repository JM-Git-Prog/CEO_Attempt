@echo off
title Pull local bake-off models (qwen3.6:27b + gemma4:26b)
echo Downloading two Apache 2.0 licensed models from ollama.com (official library):
echo   qwen3.6:27b   about 17 GB  - best 24GB-class planner per July 2026 tests
echo   gemma4:26b    about 16 GB  - MoE, only ~4B active, fast on your 4090
echo Total about 33 GB. Safe to leave running; Ollama resumes broken downloads.
echo These become free local rungs in the planner bake-off ladder.
echo.
echo Press any key to start, or close this window to cancel.
pause
echo.
echo Pulling qwen3.6:27b ...
ollama pull qwen3.6:27b
echo.
echo Pulling gemma4:26b ...
ollama pull gemma4:26b
echo.
echo Both pulls attempted - scroll up to confirm both say "success".
echo When both succeeded, tell Claude "models pulled" and the two free
echo lanes get added to the bake-off ladder.
echo.
pause
