@echo off
setlocal
title MAKE SAM'S TRAINING SET - the nights he played, turned into lessons

REM MAKE-SAM-TRAINSET.bat  -  2026-09-14
REM
REM John: "get sam training and learning how to build video game using v17", and then the shape of
REM it: "starting with text to create the picture that has the data needed to generate the world."
REM
REM That is one row of events-sim.jsonl read left to right: a sentence somebody typed, and the
REM build card the architect wrote back - name, style, materials, footprint in centimetres, storeys,
REM roof, rooms, a build plan. Sentence in, buildable data out. This card turns those rows into the
REM ChatML file Unsloth trains on, and writes a summary saying what it kept, what it threw away and
REM why.
REM
REM Until today nothing on this machine read those rows. export.py opens events.jsonl with the path
REM hard-coded; the train_student.py that v17_say_routes.py names has never existed. Sam has been
REM writing training data into a dead end since 2026-09-10.
REM
REM READ-ONLY on the event logs. Writes only into sim-player\sim-runs\training\.
REM Costs nothing: no model, no GPU, no network. Safe to run while the loop is playing.
REM
REM Batch rules: no call :label, no parenthesised blocks, every exit pauses.

set "CEO=C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
if exist "%CEO%\sim-player\teach_sam.py" goto haveceo
set "CEO=%~dp0"
set "CEO=%CEO:~0,-1%"
if exist "%CEO%\sim-player\teach_sam.py" goto haveceo
goto noceo

:haveceo
set "PY="
where /q python.exe
if not errorlevel 1 set "PY=python"
if defined PY goto havepy
where /q py.exe
if not errorlevel 1 set "PY=py"
if defined PY goto havepy
goto nopy

:havepy
cd /d "%CEO%"
echo.
echo   Reading the rounds Sam has played. Sam's rows only.
echo   To include the sentences YOU typed - kept labelled by=john, never merged
echo   silently into his - close this and run:
echo      python sim-player\teach_sam.py --include-john
echo.
"%PY%" sim-player\teach_sam.py
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo   The set and its summary are in sim-player\sim-runs\training\
if not "%RC%"=="0" echo   It could not finish, exit code %RC%. The lines above say why.
echo.
pause
exit /b %RC%

:nopy
echo.
echo   STOP: no Python found. Looked for python.exe and py.exe on PATH.
pause
exit /b 1

:noceo
echo.
echo   STOP: sim-player\teach_sam.py was not found. Looked in:
echo     1. C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt
echo     2. the folder this .bat is in
pause
exit /b 1
