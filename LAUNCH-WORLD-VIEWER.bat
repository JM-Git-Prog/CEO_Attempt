@echo off
title Launch World Viewer (live ops mode)
cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt"
echo Starting a tiny local file server on port 8123...
echo (If one is already running from last time, the extra window just closes itself - harmless.)
start "world-viewer-server" /min cmd /c "cd /d "C:\Users\JohnM\My Applications\Kiro\CEO_Kiro\CEO_Attempt" && python -m http.server 8123"
echo Opening the live viewer in your Work Chrome (Profile 8)...
call "C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\OPEN-IN-WORK-CHROME.bat" "http://localhost:8123/output/76f2952f/world-viewer.html" 1
echo.
echo Viewer launched in LIVE mode - the ops panel updates every 10 seconds
echo from the Ratchet's own files (scoreboard.json, NEXT.md, events.jsonl).
echo Keep the minimized "world-viewer-server" window running for live mode.
echo Close it any time - the page then falls back to snapshot mode.
echo.
pause
