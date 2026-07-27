@echo off
title Register the trained model and run its first real exam
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo Two models have trained today and neither was ever benched. The reason:
echo train_probe.py looked for the .gguf inside the run folder, but Unsloth
echo writes it to a sibling "_gguf" folder. The search found nothing, so the
echo Modelfile was written as the literal text "FROM None" - and every
echo `ollama create` failed on it. The 4.9 GB GGUF was there the whole time.
echo.
echo The generator is fixed. This repairs the Modelfiles already on disk,
echo registers the newest trained model, then runs a real 30-prompt exam
echo against plain llama3.1 - the comparison the chart has been missing.
echo.
echo The exam takes a while and uses the GPU. Nothing is deleted.
echo.
pause

echo [1/3] Repairing Modelfiles and registering the model...
python tools\fix_modelfiles.py
if errorlevel 1 echo.
if errorlevel 1 echo FAILED - nothing was benched. Send the message above to Claude.
if errorlevel 1 pause
if errorlevel 1 exit /b 1

echo.
echo [2/3] Pausing the harvester so the exam gets the GPU...
echo paused for exam > bench\PAUSE-BENCH.txt

echo [3/3] Running the exam: 30 prompts, llama3.1 vs planner-probe-v1...
python bench\plan_bench.py --lanes "llama3.1,planner-probe-v1" --prompts 30

echo.
echo Resuming the harvester...
if exist "bench\PAUSE-BENCH.txt" del "bench\PAUSE-BENCH.txt"

echo.
echo Refreshing the dashboard so the new comparison shows up...
python bench\dashboard_gen.py

echo.
echo Done. The chart should now have a real trained-vs-baseline point.
echo.
pause
