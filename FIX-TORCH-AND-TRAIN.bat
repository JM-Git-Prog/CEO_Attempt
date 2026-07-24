@echo off
title Fix CUDA torch in the training venv, then relaunch the chain
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo [1/3] Reinstalling torch 2.11.0 as the CUDA 12.6 build (~2.5 GB)...
echo       (unsloth's installer had swapped in the CPU-only wheel)
bench\venv-train\Scripts\pip install --force-reinstall torch==2.11.0 --index-url https://download.pytorch.org/whl/cu126
echo [2/3] Verifying the GPU is visible to torch...
bench\venv-train\Scripts\python -c "import torch; print('torch', torch.__version__, '| cuda available:', torch.cuda.is_available())" > bench\torch-fix.txt 2>&1
type bench\torch-fix.txt
findstr /C:"cuda available: True" bench\torch-fix.txt >nul 2>&1
if errorlevel 1 echo *** STILL NO CUDA - do not train. Tell Claude; fallback is the WSL route. ***
if errorlevel 1 pause
if errorlevel 1 exit /b 1
echo [3/3] CUDA confirmed - relaunching the training chain (it waits its GPU turn).
start "training-chain" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && bench\venv-train\Scripts\python bench\run_chain.py >> bench\chain-log-console.txt 2>&1"
echo Chain relaunched. Watch it on the Ops board (Training chain card).
echo.
pause
