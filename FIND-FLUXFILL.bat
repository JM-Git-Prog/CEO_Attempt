@echo off
setlocal
title FIND FluxFill - where do the pack and the model live?
cd /d "%~dp0"
set OUT=FIND-FLUXFILL-LAST.txt
> "%OUT%" echo FIND-FLUXFILL  %DATE% %TIME%
>>"%OUT%" echo.
>>"%OUT%" echo === pack folders named *fluxfill* under ComfyUI-Installs ===
dir /s /b /ad "C:\Users\JohnM\ComfyUI-Installs\*fluxfill*" >> "%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === any file mentioning FluxFill under custom_nodes dirs ===
dir /s /b "C:\Users\JohnM\ComfyUI-Installs\ComfyUI\ComfyUI\custom_nodes" >> "%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === the model: flux1-fill anywhere in the usual model shelves ===
dir /s /b "C:\Users\JohnM\ComfyUI-Shared\*flux1-fill*" >> "%OUT%" 2>&1
dir /s /b "C:\Users\JohnM\ComfyUI-Installs\*flux1-fill*" >> "%OUT%" 2>&1
dir /s /b "C:\Users\JohnM\Documents\ComfyUI\*flux1-fill*" >> "%OUT%" 2>&1
>>"%OUT%" echo.
>>"%OUT%" echo === Comfy Desktop custom_nodes (if present) ===
dir /s /b /ad "C:\Users\JohnM\Documents\ComfyUI\custom_nodes" >> "%OUT%" 2>&1
dir /s /b /ad "C:\Users\JohnM\AppData\Roaming\ComfyUI\custom_nodes" >> "%OUT%" 2>&1
echo Written to %OUT%
echo.
pause
