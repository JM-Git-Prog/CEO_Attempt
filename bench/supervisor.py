"""Supervisor - keeps the two always-on flywheel processes alive, forever.

Manages exactly two children:
  - harvester  (bench_loop.py)     - plain python, no special deps
  - flywheel   (flywheel_loop.py)  - the training venv, it needs torch/unsloth/etc.

Every CHECK_EVERY seconds it asks: is each one still actually running? If a
child process has exited, it's restarted with the SAME interpreter it always
uses (never guessed, never inherited) - this is the exact bug that broke
training all day on 2026-07-25 (wrong interpreter silently used).

It also catches the OTHER failure from that day: a process that's still
"running" but frozen solid (e.g. a stuck GPU job). bench/training-progress.json
says what stage training is in and when it last moved; if it claims to be
training but hasn't updated in STUCK_AFTER seconds, the whole flywheel
process tree is killed by PID (not by window title - title matching was
tried once already and didn't reliably reach the real process) and
restarted fresh. The kill is verified afterward, not assumed.

Pause this supervisor's restart logic (without killing it) any time by
creating bench/PAUSE-SUPERVISOR.txt - useful if you're deliberately poking
at one of the two processes by hand and don't want it auto-restarted out
from under you.

Run this directly, or via the Desktop launcher, which starts it if it's not
already running. Close its window (or Ctrl+C) to stop supervising - the
two children it started keep running on their own; this only stops
watching/restarting them.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
LOG = BENCH / "supervisor-log.txt"
PROGRESS = BENCH / "training-progress.json"
PAUSE_SUPERVISOR = BENCH / "PAUSE-SUPERVISOR.txt"

PY_PLAIN = "python"
PY_TRAIN = str(BENCH / "venv-train" / "Scripts" / "python.exe")

CHECK_EVERY = 60       # seconds between health checks
STUCK_AFTER = 30 * 60  # 30 min with no progress update = treat as frozen


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def start(name: str, python_exe: str, script: str, console_log: str):
    out = open(BENCH / console_log, "a", encoding="utf-8")
    proc = subprocess.Popen(
        [python_exe, str(BENCH / script)],
        cwd=str(ROOT),
        stdout=out,
        stderr=subprocess.STDOUT,
    )
    log(f"{name} started (pid={proc.pid}, interpreter={python_exe})")
    return proc


def alive(proc) -> bool:
    return proc is not None and proc.poll() is None


def kill_tree(proc, name: str) -> None:
    """Kill this process and everything it spawned, by PID - not by window
    title. Verifies the PID is actually gone afterward instead of assuming
    the taskkill call worked."""
    if proc is None:
        return
    pid = proc.pid
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    time.sleep(2)
    check = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                            capture_output=True, text=True)
    if str(pid) in check.stdout:
        log(f"WARNING: {name} (pid {pid}) still shows up after taskkill /T /F - "
            f"check Task Manager by hand, the kill did not verifiably work")
    else:
        log(f"{name} (pid {pid}) confirmed gone")


def flywheel_is_stuck() -> bool:
    if not PROGRESS.exists():
        return False
    try:
        d = json.loads(PROGRESS.read_text(encoding="utf-8"))
    except Exception:
        return False
    stage = d.get("stage")
    updated = d.get("updated", 0)
    if stage in ("training", "loading_model", "saving_gguf"):
        return (time.time() - updated) > STUCK_AFTER
    return False


def main() -> None:
    log("supervisor starting")
    harvester = start("harvester", PY_PLAIN, "bench_loop.py", "bench-loop-console.txt")
    flywheel = start("flywheel", PY_TRAIN, "flywheel_loop.py", "flywheel-console.txt")

    while True:
        time.sleep(CHECK_EVERY)

        if PAUSE_SUPERVISOR.exists():
            log("PAUSE-SUPERVISOR.txt present - not touching anything this cycle")
            continue

        if not alive(harvester):
            log("harvester is not running - restarting")
            harvester = start("harvester", PY_PLAIN, "bench_loop.py", "bench-loop-console.txt")

        if not alive(flywheel):
            log("flywheel is not running - restarting")
            flywheel = start("flywheel", PY_TRAIN, "flywheel_loop.py", "flywheel-console.txt")
        elif flywheel_is_stuck():
            log(f"training-progress.json has not moved in {STUCK_AFTER // 60}+ min "
                "while claiming to be training - treating as frozen")
            kill_tree(flywheel, "flywheel")
            flywheel = start("flywheel", PY_TRAIN, "flywheel_loop.py", "flywheel-console.txt")


if __name__ == "__main__":
    main()
