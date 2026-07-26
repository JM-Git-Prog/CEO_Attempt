@echo off
title The learning-training flywheel - continuous train + exam
echo Starts the full flywheel: waits for the corpus to grow, tops it up with
echo higher-hit-rate cloud-lane plans (glm-5.2:cloud + kimi-k2.6:cloud, same
echo $0 subscription as RUN-PLAN-BENCH.bat), trains a fresh probe, registers
echo it with Ollama, and benches it against llama3.1 - then waits for the
echo next growth threshold and does it again. Forever, until you pause it.
echo.
echo POLITE: pauses the llama3.1 harvester during each training window and
echo resumes it after, even if a cycle fails. Pause the WHOLE flywheel any
echo time by creating bench\PAUSE-FLYWHEEL.txt. Log: bench\flywheel-log.txt
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
start "flywheel-loop" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && bench\venv-train\Scripts\python bench\flywheel_loop.py >> bench\flywheel-console.txt 2>&1"
echo Loop launched minimized. The Training Monitor shows its live status.
echo.
pause
