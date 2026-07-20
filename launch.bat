@echo off
echo ============================================
echo   THE LIVING ROOM - Launch Script
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from python.org
    pause
    exit /b 1
)

:: Install dependencies if needed
echo Installing dependencies...
pip install -e . >nul 2>&1
pip install scipy >nul 2>&1
echo Done.
echo.

:: Ask what to run
echo Choose mode:
echo   1 = Web UI (chat interface at http://localhost:8000)
echo   2 = CLI Demo (generates Godot project directly)
echo.
set /p choice="Enter 1 or 2: "

if "%choice%"=="2" (
    echo.
    echo Running full pipeline demo...
    echo.
    python build_demo.py
    echo.
    echo Your Godot project is in: output\demo_diner\godot_project\
    echo Open it in Godot 4 and press F5 to play.
    pause
) else (
    echo.
    echo Starting web server...
    echo Open http://localhost:8000 in your browser.
    echo Press Ctrl+C to stop.
    echo.
    python run.py
)
