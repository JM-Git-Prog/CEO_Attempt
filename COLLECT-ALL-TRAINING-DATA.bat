@echo off
setlocal
title COLLECT ALL TRAINING DATA -> 05 Training\15-sam-loop-corpus

REM COLLECT-ALL-TRAINING-DATA.bat  -  2026-09-14
REM
REM John's standing rule: "all usable training data we have from all of our interactions with claude
REM and all data gathered from ollamma must always be catagorized and placed into that folder."
REM
REM That folder is E:\Software Development\Video Game Development\05 Training. The collector lives
REM there, in its own numbered native folder, beside 11-nuextract-pairs / 12-world-text-bench /
REM 14-scene-recovery-solver. This card sits HERE, in CEO_Attempt, because this is where the work
REM happens and a rule nobody can reach in one click is a rule that quietly stops happening.
REM
REM It rebuilds the whole corpus from the original logs, every time. Idempotent: it WRITES the pair
REM files rather than appending, so it cannot double-count. Safe to run while the Sam Loop is
REM playing - every source is read-only, and a half-written last line is skipped rather than fatal.
REM
REM   cards\   a sentence            -> the architect's build card, with real centimetres
REM   judge\   a transcript + a wish -> got / cant_yet / nothing / other, with the evidence quote
REM   router\  an unbuildable phrase -> thing / ability / word
REM   tape\    a build card          -> every fault in its measurements
REM   ollama\  EVERY model call ever captured: the real rendered prompt -> the real reply
REM   claude\  what we worked out together   (AUTHORED - read and counted, never rewritten)
REM
REM Nothing there trains until John approves it as a class. Read its README.md first.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit pauses.

set "T=E:\Software Development\Video Game Development\05 Training\15-sam-loop-corpus"
if exist "%T%\collect_sam_corpus.py" goto havefolder
echo.
echo   STOP: the collector was not found at
echo     %T%
echo   Is the E: drive connected?
echo.
pause
exit /b 1

:havefolder
set "PY="
where /q python.exe
if not errorlevel 1 set "PY=python"
if defined PY goto havepy
where /q py.exe
if not errorlevel 1 set "PY=py"
if defined PY goto havepy
echo.
echo   STOP: no Python found. Looked for python.exe and py.exe on PATH.
pause
exit /b 1

:havepy
echo.
echo  ============================================================
echo   1. THE COLLECTOR'S OWN CHECKS
echo  ============================================================
"%PY%" "%T%\collect_sam_corpus.py" --selftest
if errorlevel 1 goto selftestfailed

echo.
echo  ============================================================
echo   2. REBUILDING THE CORPUS FROM SOURCE
echo  ============================================================
"%PY%" "%T%\collect_sam_corpus.py" --out "%T%"
set "RC=%ERRORLEVEL%"
echo.
echo   Counts: %T%\summary.md
echo   Manifest: %T%\catalog.json
echo.
pause
exit /b %RC%

:selftestfailed
echo.
echo   STOP: the collector failed its own checks. NOTHING was rebuilt, and that is deliberate -
echo   a collector that cannot prove itself must not be trusted to rewrite the corpus.
echo.
pause
exit /b 1
