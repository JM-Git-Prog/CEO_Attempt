"""Training-probe orchestrator: wait for a quiet GPU, then prep + train.

Sequenced so nothing collides: the plan-census (Ollama) and any renders own
the GPU first; training only starts after the census results file says
"finished" (or is stale) AND the GPU has been quiet for 3 consecutive checks.
Everything logs to bench/chain-log.txt (survives window closes).
"""
from __future__ import annotations

import glob
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "bench" / "chain-log.txt"
PROGRESS = ROOT / "bench" / "training-progress.json"
CADENCE_STATE = ROOT / "bench" / "exam-cadence-state.json"
SOLVER_FILES = (
    "src/floor_plan/solver.py",
    "src/constraint_solver.py",
    "src/solver_repair.py",
    "src/floor_plan/builder.py",
)


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


def _solver_signature() -> str:
    """Cheap fingerprint of the files that decide plan legality - lets the
    exam know when a fresh baseline (llama3.1) run is worth paying for again,
    because a pipeline fix can move the baseline's own score (it did: 6/30 ->
    8/30 in one afternoon with zero model change)."""
    parts = []
    for rel in SOLVER_FILES:
        p = ROOT / rel
        try:
            st = p.stat()
            parts.append(f"{rel}:{st.st_mtime_ns}:{st.st_size}")
        except FileNotFoundError:
            parts.append(f"{rel}:missing")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _decide_exam_lanes() -> str:
    """Baseline (llama3.1) lane only every 5th exam, or right after the
    solver/pipeline code changes - otherwise probe-solo, since harvesting
    and routine exams don't need to re-prove what's already established."""
    state = {"cycle": 0, "last_baseline_sig": ""}
    if CADENCE_STATE.exists():
        try:
            state.update(json.loads(CADENCE_STATE.read_text(encoding="utf-8")))
        except Exception:
            pass
    state["cycle"] = state.get("cycle", 0) + 1
    sig = _solver_signature()
    include_baseline = (sig != state.get("last_baseline_sig")) or (state["cycle"] % 5 == 0)
    if include_baseline:
        state["last_baseline_sig"] = sig
    CADENCE_STATE.write_text(json.dumps(state), encoding="utf-8")
    return "llama3.1,planner-probe-v1" if include_baseline else "planner-probe-v1"


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
    if r2.returncode != 0:
        return r2.returncode

    progress = {}
    try:
        progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    except Exception:
        pass
    modelfile = progress.get("modelfile")
    if progress.get("stage") != "done" or not modelfile:
        log("training-progress.json has no modelfile after a successful run - "
            "stopping before ollama create (register it by hand)")
        return 1

    log(f"registering the model: ollama create planner-probe-v1 -f {modelfile}")
    try:
        r3 = subprocess.run(["ollama", "create", "planner-probe-v1", "-f", modelfile], timeout=600)
    except Exception as exc:
        log(f"ollama create FAILED to launch: {exc} - stopping before exam")
        return 1
    if r3.returncode != 0:
        log(f"ollama create FAILED rc={r3.returncode} - stopping before exam "
            f"(the old model lane would score stale otherwise)")
        return 1
    log("ollama create OK - planner-probe-v1 registered")

    log("running the fast holdout check (Stage B - rows this model never trained on)")
    try:
        r_h = subprocess.run([sys.executable, str(ROOT / "bench" / "holdout_eval.py"),
                              "--lane", "planner-probe-v1"], timeout=20 * 60)
        log(f"holdout check finished rc={r_h.returncode} (informational - does not gate the exam)")
    except subprocess.TimeoutExpired:
        log("holdout check exceeded its 20min timeout - skipping, continuing to the exam anyway")
    except Exception as exc:
        log(f"holdout check failed to launch: {exc} - skipping, continuing to the exam anyway")

    lanes = _decide_exam_lanes()
    log(f"launching the exam - lanes: {lanes}")
    try:
        r4 = subprocess.run([sys.executable, str(ROOT / "bench" / "plan_bench.py"),
                             "--lanes", lanes, "--prompts", "30"], timeout=3 * 3600)
        log(f"exam finished rc={r4.returncode}")
    except subprocess.TimeoutExpired:
        log("exam exceeded its 3h timeout - killed, results file still has whatever it saved")
        return 1
    log("SUCCESS - full cycle done (train -> register -> exam)")
    return r4.returncode


if __name__ == "__main__":
    sys.exit(main())
