@echo off
setlocal
title DIAG :8000 round 2 - find the hidden server
cd /d "%~dp0"
set OUT=DIAG-8000-LAST.txt
> "%OUT%" echo DIAG-8000 round2  %DATE% %TIME%
>>"%OUT%" echo.
>>"%OUT%" echo === every :8000 row, ALL states ===
netstat -aon | findstr ":8000" >> "%OUT%"
>>"%OUT%" echo.
>>"%OUT%" echo === every python / node / uvicorn process alive ===
tasklist | findstr /I "python node uvicorn" >> "%OUT%"
>>"%OUT%" echo.
>>"%OUT%" echo === command lines of the pythons (wmic) ===
wmic process where "name='python.exe'" get ProcessId,CommandLine /format:list >> "%OUT%" 2>&1
echo Written to %OUT%
echo.
pause
