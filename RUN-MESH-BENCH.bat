@echo off
setlocal
title Mesh Bench - does each mesh fit its box without being deformed?
cd /d "%~dp0"
echo ============================================================
echo   MESH BENCH - scores every generated mesh against its
echo   catalogue bounding box BEFORE the scale is applied.
echo.
echo   anisotropy = biggest axis scale / smallest axis scale
echo     1.0  = perfect proportional fit
echo    ^>1.3  = the mesh is being deformed, not resized
echo.
echo   Verdicts:  ok = fits   ROT = right shape, wrong axes
echo              FAIL = wrong shape, regenerate it
echo.
echo   No server, no ComfyUI, no GPU. Reads .glb files on disk.
echo.
echo   Pass a session id prefix to pick one, e.g.
echo     RUN-MESH-BENCH.bat 39009e89
echo ============================================================
echo.
python tools\mesh_bench.py %*
echo.
echo ------------------------------------------------------------
echo Mesh bench finished. Read the summary line above.
echo ------------------------------------------------------------
pause
