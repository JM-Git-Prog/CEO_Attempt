@echo off
title Remove self-test rows from the training corpus
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo An early version of bench\selftest.py banked its synthetic test row into
echo the REAL corpus instead of a throwaway file. That bug is fixed, but 1 fake
echo row is already in data\flywheel\corpus-bench.jsonl and would otherwise be
echo used as a training example.
echo.
echo This removes ONLY rows whose model_lane is exactly "selftest-lane".
echo It writes a timestamped backup first and refuses to proceed if the row
echo count changes by anything other than the number it meant to remove.
echo.
pause

python tools\purge_selftest_rows.py
if errorlevel 1 echo.
if errorlevel 1 echo FAILED - nothing was changed. Send the message above to Claude.
if errorlevel 1 pause
if errorlevel 1 exit /b 1

echo.
echo Done. The corpus is clean.
echo.
pause
