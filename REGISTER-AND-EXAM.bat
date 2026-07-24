@echo off
title Register planner-probe-v1 + bench exam vs base llama
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo [1/2] Registering your first trained model with Ollama...
for /d %%D in (bench\trained\probe-v1-*_gguf) do set GGUFDIR=%%D
if not defined GGUFDIR for /d %%D in (bench\trained\probe-v1-*) do set GGUFDIR=%%D
echo      using %GGUFDIR%
ollama create planner-probe-v1 -f "%GGUFDIR%\Modelfile"
if errorlevel 1 echo *** ollama create FAILED - check the Modelfile path above; tell Claude. ***
if errorlevel 1 pause
if errorlevel 1 exit /b 1
echo [2/2] THE EXAM: 30 held-out prompts, student vs teacher (llama3.1 measured 42%%)...
python bench\plan_bench.py --lanes "llama3.1,planner-probe-v1" --prompts 30 --start 40 > bench\exam-results-console.txt 2>&1
echo Exam done - results in the newest bench\results-*.json. Claude reads and reports.
pause
