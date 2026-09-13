@echo off
setlocal
title The Living Room :8000 (v3-v14 + v15_Fable)
cd /d "%~dp0"
echo ============================================================
echo   THE LIVING ROOM - FastAPI on http://127.0.0.1:8000
echo   Serves every interface version including /?v=15_Fable
echo   Leave this window OPEN - closing it stops the server.
echo ============================================================
echo.
REM DECISION 32 (John, 2026-09-11, "type a sentence and then boom a room"): the architect
REM writes the plan on the FIRST sentence now, so its speed IS the product's speed.
REM Measured 2026-09-11 on the same sentence: qwen3.8:27b on the 4090 took 70 SECONDS and
REM answered in paragraphs; gpt-oss:120b-cloud took 4.3 and answered in short parts.
REM That is the house routing law applied where it always pointed - text and reasoning go
REM to a prepaid cloud tag, the 4090 stays free for ComfyUI and the mesh engine. Scoped to
REM THIS window by setlocal: Sam's loop starts its own server with its own environment, so
REM his architect is still the resident local model and costs him no extra VRAM.
REM To put it back: delete the next line.
set "V17_ARCHITECT_MODEL=gpt-oss:120b-cloud"
python run.py
echo.
echo Server stopped. If it crashed right after boot, copy the
echo lines above and paste them to Claude.
pause
