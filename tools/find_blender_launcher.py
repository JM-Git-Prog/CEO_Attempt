"""Find out what keeps starting UPBGE / blenderplayer.

Reports, in order of usefulness:
  1. any Blender-ish process running right now, and its PARENT - the parent is
     the thing that started it, which is the actual answer
  2. scheduled tasks whose action mentions blender or upbge
  3. Run-key and Startup-folder entries that mention them

Read-only. Nothing is killed, disabled or changed - this only reports.
"""
from __future__ import annotations

import subprocess
import sys

NEEDLES = ("blender", "upbge", "blenderplayer")


def ps(script: str, timeout: int = 90) -> str:
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=timeout)
        return (done.stdout or "").strip() or (done.stderr or "").strip()
    except Exception as exc:
        return f"({type(exc).__name__}: {exc})"


def main() -> int:
    print("=" * 68)
    print("1. RUNNING NOW - and what started it")
    print("=" * 68)
    print(ps(r"""
$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match 'blender|upbge' -or $_.CommandLine -match 'blender|upbge' }
if (-not $procs) { 'nothing blender-ish is running right now'; exit }
foreach ($p in $procs) {
    $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($p.ParentProcessId)" -ErrorAction SilentlyContinue
    ''
    'PROCESS : {0}  (pid {1})' -f $p.Name, $p.ProcessId
    'STARTED : {0}' -f $p.CreationDate
    'COMMAND : {0}' -f $p.CommandLine
    '>> PARENT: {0}  (pid {1})   <-- THIS is what launched it' -f `
        $(if ($parent) { $parent.Name } else { 'gone - it exited after launching' }), $p.ParentProcessId
    if ($parent) { '   parent command: {0}' -f $parent.CommandLine }
}
"""))

    print()
    print("=" * 68)
    print("2. SCHEDULED TASKS that mention blender or upbge")
    print("=" * 68)
    print(ps(r"""
$hits = Get-ScheduledTask -ErrorAction SilentlyContinue | ForEach-Object {
    $t = $_
    foreach ($a in $t.Actions) {
        $line = "$($a.Execute) $($a.Arguments)"
        if ($line -match 'blender|upbge') {
            [pscustomobject]@{ Task = $t.TaskPath + $t.TaskName; State = $t.State; Runs = $line }
        }
    }
}
if ($hits) { $hits | Format-List } else { 'no scheduled task mentions blender or upbge' }
"""))

    print()
    print("=" * 68)
    print("3. STARTUP entries (Run keys + Startup folders)")
    print("=" * 68)
    print(ps(r"""
$found = $false
foreach ($key in @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce')) {
    if (Test-Path $key) {
        $item = Get-ItemProperty $key
        foreach ($p in $item.PSObject.Properties) {
            if ($p.Value -is [string] -and $p.Value -match 'blender|upbge') {
                $found = $true; '{0}  ->  {1} = {2}' -f $key, $p.Name, $p.Value
            }
        }
    }
}
foreach ($dir in @(
    "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup",
    "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Startup")) {
    if (Test-Path $dir) {
        Get-ChildItem $dir -ErrorAction SilentlyContinue | Where-Object {
            $_.Name -match 'blender|upbge' } | ForEach-Object {
            $found = $true; 'startup folder: {0}' -f $_.FullName }
    }
}
if (-not $found) { 'no Run-key or Startup-folder entry mentions blender or upbge' }
"""))

    print()
    print("Read the PARENT line in section 1 - that names the culprit.")
    print("If the parent says 'gone', it launched and exited; check sections 2 and 3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
