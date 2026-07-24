@echo off
title Install training kit (own venv - touches NOTHING existing)
echo This creates a NEW python environment just for training - your paint
echo shop venv, ComfyUI, and everything else are untouched.
echo.
echo WILL INSTALL (pip, into bench\venv-train only):
echo   unsloth  - QLoRA fine-tuning framework (Apache-2.0, PyPI)
echo   plus its pinned dependencies: torch/CUDA, transformers, trl,
echo   peft, bitsandbytes, datasets  (~3-4 GB of wheels)
echo.
echo WILL DOWNLOAD on first training run:
echo   unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit  (~6 GB, Hugging Face,
echo   Meta Llama 3.1 Community License - fine for local fine-tuning)
echo.
echo Security notes (per the constitution's installer pass): all packages
echo from PyPI under their official names, no install-time scripts beyond
echo standard wheels; bitsandbytes/torch ship prebuilt binaries. The venv
echo isolates everything; deleting bench\venv-train removes it all.
echo.
echo Press any key to install, or close this window to cancel.
pause
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
python -m venv bench\venv-train
call bench\venv-train\Scripts\activate.bat
python -m pip install --upgrade pip
pip install unsloth
echo.
echo Install finished - scroll up for errors. Next steps (Claude fires them):
echo   1) bench\venv-train\Scripts\python bench\make_training_set.py
echo   2) bench\venv-train\Scripts\python bench\train_probe.py
echo.
pause
