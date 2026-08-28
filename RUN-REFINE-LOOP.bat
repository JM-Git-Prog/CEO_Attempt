@echo off
title V2.0 Refine Loop (500 cycles)
echo ================================================================
echo   V2.0 REFINE LOOP — 500 learning cycles
echo   Session: 8df83612-1b81-4428-b711-7fbabc9536bb
echo   View: http://127.0.0.1:8000/?v=2.0^&session=8df83612-1b81-4428-b711-7fbabc9536bb
echo ================================================================
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
python tools\v2_refine_auto.py
echo.
echo Loop complete. Check output\8df83612-1b81-4428-b711-7fbabc9536bb\artifacts\refine_log.json
pause
