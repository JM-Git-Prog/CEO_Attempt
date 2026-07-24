"""Training-probe orchestrator: wait for a quiet GPU, then prep + train.

Sequenced so nothing collides: the plan-census (Ollama) and any renders own
the GPU first; training only starts after the census results file says
"finished" (or is stale) AND the GPU has been quiet for 3 consecutive checks.
Everything logs to bench/chain-log.txt (survives window closes).
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "bench" / "chain-log.txt"


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def gpu_util() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip().splitlines()
        return int(out[0]) if out else 100
    except Exception:
        return 100  # unknown = assume busy, stay polite


def census_done() -> bool:
    files = sorted(glob.glob(str(ROOT / "bench" / "results-*.json")))
    if not files:
        return True  # nothing running that we know of
    newest = Path(files[-1])
    try:
        if "finished" in json.loads(newest.read_text(encoding="utf-8")):
            return True
    except Exception:
        pass
    return (time.time() - newest.stat().st_mtime) > 90 * 60  # stale = give up waiting


def free_comfyui_vram() -> None:
    """Ask ComfyUI to unload its models (it reloads on the next render).
    Without this, ~23 GB stays resident even when idle and training OOMs."""
    import urllib.request
    for port in (8188, 8191, 8190):
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/free",
                data=b'{"unload_models": true, "free_memory": true}',
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=10)
            log(f"asked ComfyUI :{port} to free VRAM")
        except Exception:
            pass  # port not up - nothing to free


def main() -> int:
    log("chain started - waiting for census + a mostly-quiet GPU (2 of 3 checks)")
    recent = []
    while True:
        done, util = census_done(), gpu_util()
        recent = (recent + [util])[-3:]
        quiet_votes = sum(1 for u in recent if u < 35)
        if done and len(recent) == 3 and quiet_votes >= 2:
            log(f"claiming the GPU (recent utils {recent}) - renders will queue behind training")
            break
        log(f"waiting (census done={done}, gpu {util}%, quiet votes {quiet_votes}/3)")
        time.sleep(60)

    free_comfyui_vram()
    time.sleep(5)
    log("GPU is ours - building training set")
    r1 = subprocess.run([sys.executable, str(ROOT / "bench" / "make_training_set.py")])
    if r1.returncode != 0:
        log(f"make_training_set FAILED rc={r1.returncode} - stopping")
        return 1

    log("training probe starting (QLoRA, this is the long part)")
    r2 = subprocess.run([sys.executable, str(ROOT / "bench" / "train_probe.py")])
    log(f"train_probe finished rc={r2.returncode}")
    if r2.returncode == 0:
        log("SUCCESS - next: ollama create + bench (commands printed above)")
    return r2.returncode


if __name__ == "__main__":
    sys.exit(main())
