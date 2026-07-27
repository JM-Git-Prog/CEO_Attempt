@echo off
title Stop loop - free VRAM - restart Ollama - verify the exam
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo ================================================================
echo  WHY THIS EXISTS
echo ================================================================
echo Every exam since 03:22 today scored 0%% because Ollama answered
echo HTTP 200 with an empty body - no plan was ever produced. The
echo bench counted each transport failure as an illegal plan, so an
echo outage looked identical to a model scoring zero. That is what
echo produced four straight "about the same" verdicts.
echo.
echo Your own check_ollama run showed TWO models pinned at 9.2 GB
echo each - 18.4 of 24 GB - because OLLAMA_MAX_LOADED_MODELS=4 and
echo KEEP_ALIVE=-1. That leaves too little headroom for a 16K
echo context once a training job also wants the card.
echo.
echo This script does four things, in order:
echo   1. stops the flywheel loop and any running exam
echo   2. pins only ONE model instead of four, restarts Ollama
echo   3. asks Ollama directly whether it answers
echo   4. runs a real 5-prompt exam and shows the score
echo.
echo Nothing is deleted. No training data is touched.
echo.
echo Press any key to start, or close this window to cancel.
pause

echo.
echo ============ STEP 1 of 4 - stop the loop ============
echo Only python processes whose command line mentions flywheel_loop,
echo plan_bench or bench_loop are touched. Nothing else is killed.
echo.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and ($_.CommandLine -match 'flywheel_loop|plan_bench|bench_loop') } | ForEach-Object { Write-Host ('  killing PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force }"
echo.
echo   Re-checking that they actually died. A kill that reports
echo   success is not proof it cleared - see 2026-07-25.
powershell -NoProfile -Command "$r = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and ($_.CommandLine -match 'flywheel_loop|plan_bench|bench_loop') }; if ($r) { Write-Host '  *** STILL RUNNING - the kill did NOT clear. Stop them by hand. ***' } else { Write-Host '  CONFIRMED: loop and exam are stopped.' }"
echo.
pause

echo.
echo ============ STEP 2 of 4 - free VRAM headroom ============
echo Setting OLLAMA_MAX_LOADED_MODELS from 4 to 1, so one 9.2 GB
echo model is resident instead of two. KEEP_ALIVE stays -1 so the
echo model does not unload between prompts.
echo.
echo Trade-off, stated plainly: switching lanes now costs one model
echo reload, roughly a few seconds. In exchange a 16K context has
echo about 14 GB of headroom instead of 5.6 GB.
echo.
setx OLLAMA_MAX_LOADED_MODELS "1"
echo.
echo Restarting Ollama so the new setting takes effect...
taskkill /IM "ollama app.exe" /F >nul 2>&1
taskkill /IM ollama.exe /F >nul 2>&1
if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" goto noollama
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
echo Waiting 15 seconds for Ollama to come back up...
timeout /t 15 /nobreak >nul
goto step3

:noollama
echo.
echo Could not find Ollama at the usual location. The setting was
echo still saved - start Ollama from the Start menu, then re-run
echo this script from STEP 3.
echo.
pause
exit /b 1

:step3
echo.
echo ============ STEP 3 of 4 - does Ollama answer? ============
echo Asking Ollama directly, outside the pipeline.
echo.
python tools\check_ollama.py
echo.
echo Read the [loaded right now] list above. It should show ONE
echo model, not two. If it still shows two, Ollama did not pick up
echo the new setting - reboot and re-run this script.
echo.
pause

echo.
echo ============ STEP 4 of 4 - prove the exam scores ============
echo Running a real 5-prompt exam on llama3.1.
echo.
echo The bench has been patched so backend errors no longer count as
echo illegal plans. Watch the last line:
echo.
echo   "LANE RESULT: n/5 legal plans"     backend is healthy
echo   "...[n backend errors excluded]"   partly degraded, still scored
echo   "LANE RESULT: NO SCORE"            backend still broken
echo.
echo It now also aborts a lane after 3 consecutive backend errors
echo instead of burning all the prompts against a dead server.
echo.
python bench\plan_bench.py --lanes "llama3.1" --prompts 5
echo.
echo ================================================================
echo  DONE
echo ================================================================
echo If you saw a real score above, the backend is fixed and the 0%%
echo was never your model - llama3.1 scored 11/15 on 2026-07-25.
echo.
echo Do NOT restart the flywheel until the score above is non-zero.
echo Training against a dead backend is what wasted this morning.
echo.
pause
