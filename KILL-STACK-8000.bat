@echo off
setlocal
title KILL the :8000 stack by explicit PID list (engines untouched)
cd /d "%~dp0"
set OUT=KILL-STACK-LOG.txt
> "%OUT%" echo KILL-STACK  %DATE% %TIME%
echo Killing every Living Room parent and worker from the 22:50 census...
for %%p in (23028 4200 42088 27092 27024 40344 19228 36644 1656 36004 45808 44292 21468 43628 44900 27256 4708 47140) do taskkill /PID %%p /F >> "%OUT%" 2>&1
timeout /t 3 /nobreak >nul
>>"%OUT%" echo === listeners after the kill ===
netstat -aon | findstr ":8000" | findstr LISTENING >> "%OUT%"
>>"%OUT%" echo === (empty above = port truly clear) ===
echo Booting ONE fresh Living Room...
start "" "START-LIVING-ROOM-8000.bat"
timeout /t 8 /nobreak >nul
>>"%OUT%" echo === listeners after fresh boot ===
netstat -aon | findstr ":8000" | findstr LISTENING >> "%OUT%"
echo Done. Log: %OUT%
pause
