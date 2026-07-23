@echo off
title Enable Ollama parallel answers (one-time setup)
echo This makes ONE machine-level change: it tells Ollama it may serve TWO
echo requests at the same time (OLLAMA_NUM_PARALLEL=2), then restarts Ollama
echo so the setting takes effect. The Ratchet's parallel trials need this once.
echo.
echo If a trial is running this exact second it may fail once - harmless,
echo it just becomes one more sample in the stats.
echo.
echo Press any key to apply, or close this window to cancel.
pause
setx OLLAMA_NUM_PARALLEL 2 >nul
echo Setting saved to your Windows user environment.
echo Stopping Ollama...
taskkill /IM "ollama app.exe" /F >nul 2>&1
taskkill /IM ollama.exe /F >nul 2>&1
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" echo Could not find Ollama at the usual spot: %LOCALAPPDATA%\Programs\Ollama
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" echo Start Ollama yourself from the Start menu - the new setting still applies.
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" pause
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" exit /b 1
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
echo.
echo Done - Ollama restarted with parallel answers enabled.
echo.
pause
