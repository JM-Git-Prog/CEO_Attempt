@echo off
title Restart Ratchet watch with cloud lanes enabled
echo The running watch was started WITHOUT the cloud-lane flags, so it
echo would sit at "awaiting explicit enable" forever. This restarts it
echo with your two authorized Ollama Pro cloud lanes switched on:
echo   glm-5.2:cloud  and  kimi-k2.6:cloud   ($0 marginal, cap-pause on)
echo.
echo Step 1 - stopping any running ratchet watch...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -like '*ratchet_loop.py*' -or $_.CommandLine -like '*e2e_qualification.py*'} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  stopped pid ' + $_.ProcessId) }"
echo Step 2 - relaunching via the keepalive (now carries --enable-lane flags)...
call "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt\WATCH-KEEPALIVE.bat"
echo.
echo Done. The watch is back up minimized with cloud rungs armed.
echo Ladder order stays cheapest-first: llama3.1, gpt-oss:20b, then
echo GLM-5.2 cloud, then Kimi K2.6 cloud. Watch the dashboard lane cards.
echo.
pause
