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
python run.py
echo.
echo Server stopped. If it crashed right after boot, copy the
echo lines above and paste them to Claude.
pause
