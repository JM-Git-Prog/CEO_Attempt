@echo off
title Stage B - fast holdout check (rows never trained on)
echo Benches ONE model against the 30 holdout rows make_training_set.py set
echo aside and never trains on - a fast, honest check that does not need a
echo full 30-prompt live exam to get a first read.
echo.
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
python bench\holdout_eval.py --lane planner-probe-v1
echo.
echo Holdout check finished (or failed - read above).
pause
