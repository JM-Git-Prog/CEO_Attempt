@echo off
title Grid generation experiment - does asking for CELLS beat asking for coordinates?
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"

echo Everything measured so far REPAIRED layouts that were already built wrong:
echo   nudge repair 14 percent, sampling search 16 percent, grid snapping 23 percent.
echo.
echo This asks a different question. Instead of coordinates, the model is asked
echo for GRID CELLS - "the counter occupies cells (3,7) to (8,7)". A collision
echo becomes two items claiming the same cell, which the model can check while
echo writing, instead of floating point arithmetic it discovers afterwards.
echo.
echo The conversion is exact: a cell becomes a centered relation with explicit
echo offsets, which the solver reproduces verbatim. No repair, no nudging, no
echo synthesised relations. Judged by the SAME strict validator as everything
echo else, so the number is directly comparable to the 25 percent baseline.
echo.
echo Takes roughly 20-40 minutes for 30 prompts. Uses the GPU.
echo.
pause

echo [1/3] Proving the harness itself is correct...
echo       A hand-built legal grid must pass, and a deliberate cell clash must
echo       be caught. If this fails, no model result would mean anything.
python bench\grid_gen_bench.py --selftest
if errorlevel 1 echo.
if errorlevel 1 echo HARNESS BROKEN - stopping. Send the output above to Claude.
if errorlevel 1 pause
if errorlevel 1 exit /b 1

echo.
echo [2/3] Pausing the harvester so the experiment gets the GPU...
echo paused for grid experiment > bench\PAUSE-BENCH.txt

echo [3/3] Running 30 prompts on llama3.1, grid mode...
python bench\grid_gen_bench.py --prompts 30 --lane llama3.1

echo.
echo Resuming the harvester...
if exist "bench\PAUSE-BENCH.txt" del "bench\PAUSE-BENCH.txt"

echo.
echo Done. The last lines above show grid legality vs the 25 percent baseline.
echo Results saved as bench\results-GRIDGEN-*.json
echo.
pause
