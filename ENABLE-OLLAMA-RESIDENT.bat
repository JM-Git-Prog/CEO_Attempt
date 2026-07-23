@echo off
title Enable Ollama resident models (leverages your 96GB RAM)
echo This sets two machine-level Ollama settings, then restarts Ollama:
echo.
echo   OLLAMA_KEEP_ALIVE = -1        models NEVER auto-unload
echo   OLLAMA_MAX_LOADED_MODELS = 4  planner + vision judge + extractor stay resident together
echo.
echo Your 96GB RAM absorbs the resident models easily. This removes the
echo model-reload tax between harvest trial stages - more trials per hour, $0.
echo If a trial is mid-flight this second it may fail once - harmless.
echo.
echo Press any key to apply, or close this window to cancel.
pause
setx OLLAMA_KEEP_ALIVE "-1"
setx OLLAMA_MAX_LOADED_MODELS "4"
echo Settings saved to your Windows user environment.
echo Restarting Ollama...
taskkill /IM "ollama app.exe" /F >nul 2>&1
taskkill /IM ollama.exe /F >nul 2>&1
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" echo Could not find Ollama at the usual spot - start it from the Start menu; the settings still apply.
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" pause
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" exit /b 1
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
echo.
echo Done - Ollama restarted with resident models enabled.
echo.
pause
