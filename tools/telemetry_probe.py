"""Telemetry probe — samples live CPU/RAM/GPU per application component.

Writes output/qualification/telemetry.json every few seconds for the executive
dashboard (world-viewer.html). Read-only observer: it never touches pipeline
code, evidence, or the qualification loop. Owned like the watch: revived by
WATCH-KEEPALIVE.bat (Task Scheduler, every 5 min); its own lock refuses
duplicates.

Engines: psutil when available (cheap), else PowerShell CIM + nvidia-smi
(stdlib-only fallback — nothing to install).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output", "qualification", "telemetry.json")
LOCK = os.path.join(ROOT, "output", "qualification", "telemetry.lock")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# component -> case-insensitive regex over "name + cmdline"
GROUPS = [
    ("ratchet", "Ratchet loop (tests & harvest)", r"ratchet_loop|e2e_qualification|v11_e2e_adapter"),
    ("comfyui", "ComfyUI (image renders)", r"comfy"),
    ("ollama", "Ollama (planner + vision models)", r"ollama"),
    ("kiro", "Kiro (the builder)", r"kiro\.exe"),
    ("dashboard", "Dashboard server :8123", r"http\.server\s+8123"),
    ("anythingllm", "AnythingLLM (research)", r"anythingllm"),
    ("probe", "This telemetry probe", r"telemetry_probe"),
]

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


def _run(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, creationflags=NO_WINDOW).stdout
    except Exception:
        return ""


def pid_alive(pid: int) -> bool:
    if psutil:
        return psutil.pid_exists(pid)
    out = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    return f'"{pid}"' in out


def acquire_lock() -> bool:
    try:
        with open(LOCK, encoding="utf-8") as f:
            old = json.load(f)
        if old.get("pid") and pid_alive(int(old["pid"])):
            return False
    except Exception:
        pass
    with open(LOCK, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "created": time.time()}, f)
    return True


def gpu_sample():
    """(totals-dict-or-None, {pid: vram_gb})"""
    tot = _run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits"]).strip().splitlines()
    totals = None
    if tot:
        p = [x.strip() for x in tot[0].split(",")]
        try:
            totals = {"gpu_util_pct": float(p[0]), "vram_used_gb": float(p[1]) / 1024,
                      "vram_total_gb": float(p[2]) / 1024, "gpu_temp_c": float(p[3]),
                      "gpu_power_w": float(p[4])}
        except (ValueError, IndexError):
            totals = None
    per_pid = {}
    for line in _run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                      "--format=csv,noheader,nounits"]).strip().splitlines():
        p = [x.strip() for x in line.split(",")]
        try:
            per_pid[int(p[0])] = float(p[1]) / 1024
        except (ValueError, IndexError):
            continue
    return totals, per_pid


def procs_psutil():
    rows, ncpu = [], (os.cpu_count() or 1)
    for p in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
        try:
            cpu = p.cpu_percent(interval=None) / ncpu  # machine-relative %
            info = p.info
            rows.append({"pid": info["pid"], "cpu": cpu,
                         "ram_gb": (info["memory_info"].rss if info["memory_info"] else 0) / 2**30,
                         "match": ((info["name"] or "") + " " + " ".join(info["cmdline"] or [])).lower()})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    vm = psutil.virtual_memory()
    totals = {"cpu_pct": psutil.cpu_percent(interval=None),
              "ram_used_gb": (vm.total - vm.available) / 2**30, "ram_total_gb": vm.total / 2**30}
    return rows, totals


PS_SCRIPT = (
    "$p=Get-CimInstance Win32_PerfFormattedData_PerfProc_Process|"
    "Where-Object{$_.Name -ne '_Total' -and $_.Name -ne 'Idle'}|"
    "Select-Object Name,IDProcess,PercentProcessorTime,WorkingSet;"
    "$c=Get-CimInstance Win32_Process|Select-Object ProcessId,CommandLine;"
    "$o=Get-CimInstance Win32_OperatingSystem|Select-Object TotalVisibleMemorySize,FreePhysicalMemory;"
    "$t=(Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor|"
    "Where-Object{$_.Name -eq '_Total'}).PercentProcessorTime;"
    "@{procs=$p;cmds=$c;os=$o;cpu=$t}|ConvertTo-Json -Depth 4 -Compress"
)


def _aslist(x):
    return x if isinstance(x, list) else ([] if x is None else [x])


def procs_powershell():
    raw = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SCRIPT], timeout=25)
    d = json.loads(raw)
    cmd_by_pid = {c.get("ProcessId"): (c.get("CommandLine") or "") for c in _aslist(d.get("cmds"))}
    ncpu = os.cpu_count() or 1
    rows = []
    for p in _aslist(d.get("procs")):
        pid = p.get("IDProcess")
        rows.append({"pid": pid, "cpu": (p.get("PercentProcessorTime") or 0) / ncpu,
                     "ram_gb": (p.get("WorkingSet") or 0) / 2**30,
                     "match": ((p.get("Name") or "") + " " + cmd_by_pid.get(pid, "")).lower()})
    osd = _aslist(d.get("os"))[0] if d.get("os") else {}
    tot_kb = float(osd.get("TotalVisibleMemorySize") or 0)
    free_kb = float(osd.get("FreePhysicalMemory") or 0)
    totals = {"cpu_pct": float(d.get("cpu") or 0),
              "ram_used_gb": (tot_kb - free_kb) / 2**20, "ram_total_gb": tot_kb / 2**20}
    return rows, totals


def sample():
    rows, totals = procs_psutil() if psutil else procs_powershell()
    gpu_tot, gpu_by_pid = gpu_sample()
    if gpu_tot:
        totals.update(gpu_tot)
    groups = []
    for key, label, pat in GROUPS:
        rx = re.compile(pat, re.I)
        mine = [r for r in rows if rx.search(r["match"])]
        groups.append({"key": key, "label": label, "procs": len(mine),
                       "cpu_pct": round(sum(r["cpu"] for r in mine), 1),
                       "ram_gb": round(sum(r["ram_gb"] for r in mine), 2),
                       "vram_gb": round(sum(gpu_by_pid.get(r["pid"], 0) for r in mine), 2)})
    return {"ts": time.time(), "engine": "psutil" if psutil else "powershell",
            "totals": {k: round(v, 1) for k, v in totals.items()}, "groups": groups}


def write_out(doc):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f)
    os.replace(tmp, OUT)


def main():
    once = "--once" in sys.argv
    if not once and not acquire_lock():
        print("telemetry probe already running - exiting")
        return 0
    interval = 5 if psutil else 8
    if psutil:  # prime cpu_percent so the first real sample is meaningful
        for p in psutil.process_iter():
            try:
                p.cpu_percent(interval=None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.cpu_percent(interval=None)
        time.sleep(1)
    print(f"telemetry probe up - engine={'psutil' if psutil else 'powershell'} interval={interval}s")
    while True:
        try:
            write_out(sample())
        except Exception as e:
            print(f"sample failed: {e!r}")
        if once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
