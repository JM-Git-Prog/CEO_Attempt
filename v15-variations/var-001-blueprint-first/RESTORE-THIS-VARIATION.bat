@echo off
setlocal
title RESTORE v15_Fable var-001 - blueprint-first (the original)
cd /d "%~dp0"
echo ============================================================
echo   REWIND v15_Fable to var-001 - blueprint-first original.
echo   The two live files are backed up first as .before-rewind,
echo   then this variation's copies are put in place.
echo ============================================================
echo.
copy /Y "..\..\src\v15_fable.py" "..\..\src\v15_fable.py.before-rewind" >nul
copy /Y "..\..\src\web\templates\index_v15_fable.html" "..\..\src\web\templates\index_v15_fable.html.before-rewind" >nul
copy /Y "v15_fable.py" "..\..\src\v15_fable.py"
copy /Y "index_v15_fable.html" "..\..\src\web\templates\index_v15_fable.html"
echo.
echo DONE. Now restart the server: double-click START-LIVING-ROOM-8000.bat
echo in the CEO-3D-World folder, then refresh the v15_Fable tab.
echo (Undo this rewind: the .before-rewind files hold what was live.)
echo.
pause
