@echo off
title Phase 1 - the builder, then the Living Room

REM ==========================================================================
REM  Phase 1 bring-up (2026-09-03). John chose "both, builder first".
REM  Supersedes START-PHASE-1.bat, which guessed at the E: path and added its
REM  own port probe. The real RESTART-NEIGHBOURHOOD-BUILDER.bat already does
REM  that better: it captures the PID listening on 8196, kills only that one,
REM  re-checks the port cleared, starts the builder from disk, waits, and
REM  re-checks it came back. So this card just runs the two scripts in order
REM  and stops if the first one fails.
REM
REM  Step 1: the Neighbourhood Builder (:8196). Until it restarts, the running
REM          service predates the "next version of a place" code, so an order
REM          raises a NEW world instead of adding the house to the block.
REM  Step 2: the Living Room / V17 (:8000). run.py pins reload=False on purpose,
REM          so tonight's Python changes are not live until this runs.
REM
REM  Nothing here deletes or overwrites anything. Every exit prints and pauses.
REM ==========================================================================

set "NB=E:\Software Development\Video Game Development\03 Projects\Cul-de-sac\RESTART-NEIGHBOURHOOD-BUILDER.bat"
set "LR=%~dp0LIVING-ROOM.bat"

echo.
echo ==================================================================
echo   PHASE 1 - bringing up the one-box router
echo ==================================================================
echo.
echo   Step 1 of 2: the Neighbourhood Builder on port 8196.
echo   Why it matters: until this restarts, your house lands in a brand
echo   new world instead of being added to your block.
echo.

if not exist "%NB%" goto nobuilder
if not exist "%LR%" goto nolivingroom

echo   Running: %NB%
echo   It will report whether 8196 came back, then wait for a keypress.
echo.
call "%NB%"
if errorlevel 1 goto builderfailed

echo.
echo ==================================================================
echo   Step 2 of 2: the Living Room / V17 on port 8000
echo ==================================================================
echo.
echo   LIVING-ROOM.bat will say PASS or FAIL and then open V17 in your
echo   work Chrome.
echo.
call "%LR%"

echo.
echo ==================================================================
echo   Phase 1 is up. Now type this into V17:
echo ==================================================================
echo.
echo     create a new house on the block, red bricks, white columns,
echo     white one 3 stories, very presidential
echo.
echo   Expect a receipt naming a HOUSE - bricks, columns, three storeys.
echo   No sofa. No palette. No "Interior photograph".
echo.
echo   Then type the sentence that broke last night:
echo.
echo     none of them looked like the picture
echo.
echo   It should still be talking about your house.
echo.
pause
exit /b 0

:builderfailed
echo.
echo   *** THE BUILDER RESTART REPORTED A PROBLEM ***
echo.
echo   Port 8196 did not clear, so the builder was not restarted. Read
echo   the message it printed just above this line.
echo.
echo   V17 has NOT been restarted, so nothing has changed. Fix the
echo   builder, then run this card again.
echo.
pause
exit /b 1

:nobuilder
echo.
echo   *** BUILDER RESTART SCRIPT NOT FOUND ***
echo   Looked for: %NB%
echo.
echo   Nothing has been started and nothing has been changed.
echo.
pause
exit /b 1

:nolivingroom
echo.
echo   *** LIVING-ROOM.bat NOT FOUND NEXT TO THIS FILE ***
echo   Looked for: %LR%
echo.
echo   Stopped before starting anything, so the builder is untouched too.
echo.
pause
exit /b 1
