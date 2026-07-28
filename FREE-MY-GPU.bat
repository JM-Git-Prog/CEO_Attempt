@echo off
title Free my GPU - one change at a time
echo ============================================================
echo  Two separate fixes, each asked separately, each verified
echo  right after so you can see what it actually bought you.
echo.
echo  STEP 1  close the stray blenderplayer (UPBGE test window)
echo          - suspected cause of the 96%% utilization
echo  STEP 2  ask ComfyUI to unload its models  (~14 GB)
echo          - a clean unload, NOT a kill. ComfyUI keeps running
echo            and reloads models on the next render.
echo ============================================================
echo.

echo ---- BEFORE ----
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader
echo.

echo ---- STEP 1: the stray UPBGE window ----
tasklist /FI "IMAGENAME eq blenderplayer.exe"
echo.
echo Close it only if you are not deliberately running a UPBGE test.
choice /C YN /M "Close blenderplayer.exe now"
if errorlevel 2 goto step2

taskkill /IM blenderplayer.exe /T /F
timeout /t 4 /nobreak >nul
echo.
echo ---- VERIFY after step 1 ----
tasklist /FI "IMAGENAME eq blenderplayer.exe"
nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader
echo.
echo If utilization just dropped, the stray window was the cause.
echo.

:step2
echo ---- STEP 2: ComfyUI's resident models (~14 GB) ----
echo This sends ComfyUI its own "free memory" request on port 8188.
echo Nothing is deleted and ComfyUI stays running.
echo.
choice /C YN /M "Ask ComfyUI to unload its models now"
if errorlevel 2 goto done

echo {"unload_models":true,"free_memory":true}> "%TEMP%\comfy-free.json"
curl -s -S -X POST http://127.0.0.1:8188/free -H "Content-Type: application/json" -d @"%TEMP%\comfy-free.json"
del "%TEMP%\comfy-free.json" >nul 2>&1
timeout /t 6 /nobreak >nul
echo.
echo ---- VERIFY after step 2 ----
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,power.draw --format=csv,noheader
echo.

:done
echo ---- FINAL per-process ranking ----
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\tools\gpu_memory_by_process.ps1"
echo.
echo ============================================================
echo  Done. llama3.1 keeps its 7 GB on purpose - that is the
echo  KEEP_ALIVE setting that makes your trials fast. Leave it
echo  unless you need the whole card for a big render.
echo.
echo  Copy the results above back to Claude.
echo ============================================================
echo.
pause
