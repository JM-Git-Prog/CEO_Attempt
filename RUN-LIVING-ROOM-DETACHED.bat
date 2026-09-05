@echo off
REM ==========================================================================
REM  2026-09-04. Launch LIVING-ROOM.bat in its OWN window and return at once.
REM
REM  Why this exists: the site-runner MCP tool gives up after 180 s and kills
REM  whatever it is still waiting on. LIVING-ROOM.bat never "finishes" — it
REM  ends holding a server — so running it directly from the runner killed the
REM  Living Room twice on 2026-09-04. Detaching means the runner has nothing
REM  left to wait on, and nothing to kill.
REM
REM  The quoting lives HERE, in a .bat, not inside site-runner.config.json —
REM  a quoted window title written as \" in JSON reached Windows as a literal
REM  \"Living Room\" and failed with "The system cannot find the file".
REM ==========================================================================
start "Living Room" cmd /c call "%~dp0LIVING-ROOM.bat"
echo Living Room starting in its own window. Poll port 8000 to confirm it came up.
exit /b 0
