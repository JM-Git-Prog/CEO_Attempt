@echo off
title What is Ollama actually doing?
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo Asks Ollama directly - one small request, outside the whole pipeline - and
echo prints exactly what comes back, plus which models are loaded and how much
echo VRAM they are holding.
echo.
echo Right now every generation fails with a 200 response that contains no
echo completion at all (every counter reads None). This says why.
echo.

python tools\check_ollama.py

echo.
pause
