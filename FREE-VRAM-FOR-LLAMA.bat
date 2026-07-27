@echo off
title Free the VRAM that gpt-oss:20b is holding forever
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo gpt-oss:20b is pinned in VRAM holding 12.9 GB with an expiry of the year
echo 2318 - i.e. never. That leaves too little room for llama3.1 to load with
echo the 16K context the pipeline asks for, which is why Ollama answers 200
echo with no completion in it.
echo.
echo This unloads gpt-oss:20b, verifies the VRAM actually came back, then
echo sends llama3.1 the exact request the pipeline sends to prove it works.
echo.
echo Nothing is deleted. gpt-oss:20b stays installed and reloads on demand
echo the next time something asks for it.
echo.
pause

python tools\free_vram.py
if errorlevel 1 echo.
if errorlevel 1 echo FAILED - see the message above. Send it to Claude.
if errorlevel 1 pause
if errorlevel 1 exit /b 1

echo.
echo Done. Now click Clear Launcher to restart the loop.
echo.
pause
