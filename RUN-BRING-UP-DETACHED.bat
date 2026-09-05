@echo off
REM ==========================================================================
REM  2026-09-04. Launch PHASE-1-BRING-UP.bat (builder, then Living Room) in its
REM  OWN window and return at once. Same reason as RUN-LIVING-ROOM-DETACHED.bat:
REM  the runner's 180 s ceiling kills anything it is still waiting on, and these
REM  scripts end by holding servers rather than finishing.
REM ==========================================================================
start "Phase 1 bring-up" cmd /c call "%~dp0PHASE-1-BRING-UP.bat"
echo Bring-up starting in its own window. Poll ports 8196 then 8000 to confirm.
exit /b 0
