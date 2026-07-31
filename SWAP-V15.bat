@echo off
setlocal
title SWAP v15_fable - native copy over the bridge-frozen file
cd /d "%~dp0"
set OUT=SWAP-V15-LOG.txt
> "%OUT%" echo SWAP-V15  %DATE% %TIME%
>>"%OUT%" echo.
>>"%OUT%" echo === BEFORE: does the live target have the new code? ===
findstr /C:"photo-unapprove" "src\v15_fable.py" >nul && >>"%OUT%" echo TARGET: NEW CODE ALREADY || >>"%OUT%" echo TARGET: OLD CODE
for %%A in ("src\v15_fable.py") do >>"%OUT%" echo target size: %%~zA
>>"%OUT%" echo === donor file present? ===
if exist "src\v15_fable_live.py" (>>"%OUT%" echo DONOR: exists) else (>>"%OUT%" echo DONOR: MISSING)
for %%A in ("src\v15_fable_live.py") do >>"%OUT%" echo donor size: %%~zA
findstr /C:"photo-unapprove" "src\v15_fable_live.py" >nul && >>"%OUT%" echo DONOR: has new code || >>"%OUT%" echo DONOR: OLD CODE TOO
>>"%OUT%" echo === swapping ===
copy /Y "src\v15_fable.py" "src\v15_fable.py.pre-swap.bak" >nul
copy /Y "src\v15_fable_live.py" "src\v15_fable.py" >> "%OUT%" 2>&1
>>"%OUT%" echo === AFTER ===
findstr /C:"photo-unapprove" "src\v15_fable.py" >nul && >>"%OUT%" echo TARGET NOW: NEW CODE || >>"%OUT%" echo TARGET NOW: STILL OLD
for %%A in ("src\v15_fable.py") do >>"%OUT%" echo target size now: %%~zA
if exist "src\__pycache__" del /q "src\__pycache__\*.pyc" 2>nul
echo Log written. Restarting the server...
call "RESTART-LIVING-ROOM-8000.bat"
