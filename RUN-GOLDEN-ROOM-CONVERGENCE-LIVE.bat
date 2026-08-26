@echo off
setlocal EnableExtensions DisableDelayedExpansion
title Golden Room convergence - live task launcher
cd /d "%~dp0" || (
    echo ERROR: Could not enter repository root: "%~dp0"
    pause
    exit /b 1
)

set "WORKSPACE=%CD%"
set "SPEC_TASKS=%CD%\.kiro\specs\recliner-canon-visual-refinement-fix\tasks.md"
set "KIRO_CLI=C:\Users\JohnM\AppData\Local\Programs\Kiro\bin\kiro.cmd"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
set "LOG_DIR=%CD%\output\logs"
set "LOCK_DIR=%CD%\output\logs\.run-golden-room-convergence-live.lock"
set "PROMPT=Run all required tasks in the spec. Work through them sequentially, skipping optional tasks."
set "LAUNCHER=%~f0"

if /i "%~1"=="--worker" goto worker

if not exist "%POWERSHELL_EXE%" (
    echo ERROR: Required PowerShell executable was not found:
    echo   %POWERSHELL_EXE%
    pause
    exit /b 1
)
if not exist "%LOG_DIR%\" (
    echo ERROR: Existing log directory was not found:
    echo   %LOG_DIR%
    pause
    exit /b 1
)

2>nul mkdir "%LOCK_DIR%"
if errorlevel 1 (
    echo ERROR: Another launcher instance may already be active.
    echo Lock: "%LOCK_DIR%"
    echo No process was killed. If no instance is running, remove only this stale lock directory.
    pause
    exit /b 3
)

for /f "usebackq delims=" %%I in (`%POWERSHELL_EXE% -NoLogo -NoProfile -Command "Get-Date -Format 'yyyyMMdd-HHmmss'"`) do set "STAMP=%%I"
if not defined STAMP set "STAMP=unknown-time"
set "LOG_FILE=%LOG_DIR%\golden-room-convergence-live-%STAMP%.log"

>"%LOCK_DIR%\owner.txt" echo Started %DATE% %TIME%
>>"%LOCK_DIR%\owner.txt" echo Launcher "%LAUNCHER%"
>>"%LOCK_DIR%\owner.txt" echo Log "%LOG_FILE%"

"%POWERSHELL_EXE%" -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "& { & $env:LAUNCHER '--worker' 2>&1 | Tee-Object -FilePath $env:LOG_FILE -Append; $code = $LASTEXITCODE; if ($null -eq $code) { $code = 1 }; exit [int]$code }"
set "RUN_EXIT=%ERRORLEVEL%"

rmdir /s /q "%LOCK_DIR%" >nul 2>&1

echo.
echo ============================================================
echo Finished: %DATE% %TIME%
echo Exit code: %RUN_EXIT%
echo Log: "%LOG_FILE%"
echo ============================================================
echo.
pause
exit /b %RUN_EXIT%

:worker
echo ============================================================
echo Golden Room convergence task launcher
echo ============================================================
"%POWERSHELL_EXE%" -NoLogo -NoProfile -Command "Write-Output ('Timestamp: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz'))"
echo Workspace: "%WORKSPACE%"
echo Spec tasks: "%SPEC_TASKS%"
echo Kiro CLI: "%KIRO_CLI%"
echo.
echo Closing this window interrupts only this user-launched bounded run.
echo It does not stop or alter Scheduled Tasks, Ratchet watch, keepalive hooks,
echo ComfyUI, port 8188, services, sessions, qualification, or other owners.
echo.

if not exist "%SPEC_TASKS%" (
    echo BLOCKER: The exact spec tasks file does not exist.
    echo No task command was run.
    exit /b 2
)
if not exist "%KIRO_CLI%" (
    echo BLOCKER: The verified Kiro CLI executable is no longer present.
    echo No task command was run.
    exit /b 2
)

echo Current required task summary:
"%POWERSHELL_EXE%" -NoLogo -NoProfile -Command "$line = Get-Content -LiteralPath $env:SPEC_TASKS | Where-Object { $_ -match '^\s*-\s*\[\s\]\s+\d' -and $_ -notmatch '\(optional\)' } | Select-Object -First 1; if ($null -eq $line) { Write-Output 'No unchecked required task found.' } else { Write-Output $line.Trim() }"
echo.
echo Detected Kiro CLI version output:
call "%KIRO_CLI%" --version
echo.
echo Starting the verified Kiro agent chat command in the foreground.
echo Live agent progress appears in the Kiro GUI.
echo This CMD window records launcher output only through the existing log tee.
echo If Kiro launches the GUI and returns immediately, this launcher also returns;
echo the CMD process does not own or track the GUI agent after that handoff.
echo.
echo Command:
echo   call "%KIRO_CLI%" chat --mode agent --add-file "%SPEC_TASKS%" "%PROMPT%"
echo.
echo Prompt:
echo   %PROMPT%
echo.
call "%KIRO_CLI%" chat --mode agent --add-file "%SPEC_TASKS%" "%PROMPT%"
set "KIRO_EXIT=%ERRORLEVEL%"
echo.
echo Kiro chat launcher exit code: %KIRO_EXIT%
echo This is the CLI launcher exit code, not proof that the GUI agent completed.
exit /b %KIRO_EXIT%
