@echo off
setlocal
title Ortho Bench - measurement chain check (no server, no GPU)
cd /d "%~dp0"
echo ============================================================
echo   ORTHO BENCH - runs the REAL measurement chain over the
echo   renders in workflows\ortho-test:
echo.
echo     room outline -^> anchored scale -^> segmentation
echo     -^> metric placements
echo.
echo   No server, no ComfyUI, no Ollama, no GPU. About a second.
echo   Iterate on measurement code WITHOUT restarting :8000.
echo.
echo   Pass part of a filename to filter, e.g.
echo     RUN-ORTHO-BENCH.bat margin-nadir
echo ============================================================
echo.
python tools\ortho_bench.py %*
echo.
echo ------------------------------------------------------------
echo Ortho bench finished. Read the summary line above.
echo ------------------------------------------------------------
pause
