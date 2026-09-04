@echo off
setlocal enabledelayedexpansion
title CATCH UP TRAINING DATA - bank every bench run since 2026-08-30
cd /d "%~dp0"
echo ============================================================
echo   CATCH UP TRAINING DATA
echo.
echo   The ingester turns bench runs into training records in
echo   data\flywheel\corpus-bench.jsonl. It last ran 2026-08-30.
echo   Runs made since then have been banked NOWHERE.
echo.
echo   Safe to run any time: every record is keyed by a hash, so
echo   re-running never duplicates anything. Nothing is deleted.
echo ============================================================
echo.

set CORPUS=data\flywheel\corpus-bench.jsonl
set PY=python
if exist "bench\venv-train\Scripts\python.exe" set PY=bench\venv-train\Scripts\python.exe
echo Using interpreter: %PY%
echo.

set BEFORE=0
if exist "%CORPUS%" for /f %%c in ('find /c /v "" ^< "%CORPUS%"') do set BEFORE=%%c
echo [1/3] Records before: !BEFORE!
echo.

echo [2/3] Running the ingester...
"%PY%" bench\ingest_bench_to_corpus.py
set RC=%ERRORLEVEL%
echo.

if not "%RC%"=="0" echo   FAILED - the ingester exited with code %RC%.
if not "%RC%"=="0" echo   Nothing was banked. Copy the lines above to Claude.
if not "%RC%"=="0" echo.
if not "%RC%"=="0" pause
if not "%RC%"=="0" exit /b 1

set AFTER=0
if exist "%CORPUS%" for /f %%c in ('find /c /v "" ^< "%CORPUS%"') do set AFTER=%%c
set /a GAINED=!AFTER!-!BEFORE!
echo [3/3] Records after: !AFTER!   (new this run: !GAINED!)
echo.

if !AFTER! LEQ !BEFORE! echo   WARNING - the file did not grow.
if !AFTER! LEQ !BEFORE! echo   Either everything was already banked, or the ingester found
if !AFTER! LEQ !BEFORE! echo   no new results files. That is worth telling Claude.
if !AFTER! GTR !BEFORE! echo   Banked !GAINED! new training records.
echo.
echo   Training gate for your own model is 2000 accepted pairs
echo   (doc 28). Current probe set: 202 pairs + 50 holdout.
echo.
echo ============================================================
echo   Done. Nothing was deleted and nothing was overwritten.
echo ============================================================
echo.
pause
