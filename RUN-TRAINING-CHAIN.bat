@echo off
title Training chain - install, wait for quiet GPU, train, export
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo [1/5] Creating isolated venv at bench\venv-train (touches nothing else)...
python -m venv bench\venv-train
if not exist bench\venv-train\Scripts\python.exe echo *** venv creation FAILED - python not on PATH? Read any error above. ***
if not exist bench\venv-train\Scripts\python.exe pause
if not exist bench\venv-train\Scripts\python.exe exit /b 1
echo [2/5] Upgrading pip...
bench\venv-train\Scripts\python -m pip install --upgrade pip
echo [3/5] Installing torch (CUDA 12.4 wheels, official PyTorch index, ~2.5 GB)...
bench\venv-train\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu124
echo [4/5] Installing unsloth + training stack (PyPI, ~1 GB)...
bench\venv-train\Scripts\pip install unsloth
echo [5/5] Orchestrator takes over: waits for the census + quiet GPU, then
echo       builds the training set and trains. Log: bench\chain-log.txt
bench\venv-train\Scripts\python bench\run_chain.py
echo.
echo Chain exited - scroll up for the verdict. Log: bench\chain-log.txt
pause
