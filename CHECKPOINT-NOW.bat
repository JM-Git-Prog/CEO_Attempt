@echo off
title Checkpoint - restore point commit
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo.
echo Creating a restore-point commit of everything changed right now...
echo.
git add -A
echo checkpoint: manual restore point - changed files listed below> "%TEMP%\ckpt-msg.txt"
echo.>> "%TEMP%\ckpt-msg.txt"
git status --porcelain>> "%TEMP%\ckpt-msg.txt"
git commit -F "%TEMP%\ckpt-msg.txt"
echo.
echo If it said "nothing to commit", there was nothing new to protect.
echo Otherwise the commit above is your new local restore point.
echo This does NOT push to GitHub - your existing flows handle that.
echo Safe to run any time, even while Kiro is working.
echo.
pause
