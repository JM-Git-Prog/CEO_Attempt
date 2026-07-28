@echo off
title What keeps starting UPBGE / blenderplayer?
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo Finds what launches UPBGE / blenderplayer, in three passes:
echo.
echo   1. Anything blender-ish running RIGHT NOW, and its PARENT process.
echo      The parent is the thing that started it - that is the answer.
echo   2. Scheduled tasks whose action mentions blender or upbge.
echo   3. Startup entries - Run registry keys and Startup folders.
echo.
echo READ-ONLY. Nothing is killed, disabled, or changed. It only reports.
echo.
echo Tip: if it is not running at this moment, start it once (or wait until
echo it appears again) and run this while it is up - section 1 is the one
echo that names the culprit outright.
echo.
pause

python tools\find_blender_launcher.py

echo.
echo Send the output above to Claude and I will tell you what to disable.
echo.
pause
