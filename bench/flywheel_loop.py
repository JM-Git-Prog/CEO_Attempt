"""The learning<->training flywheel: closes train -> exam -> train into a loop.

Politeness + safety rules (mirrors bench_loop.py's proven pattern):
1. Pauses whenever bench/PAUSE-FLYWHEEL.txt exists (John's off switch for the
   WHOLE flywheel - training + exam + top-up).
2. Only starts a new training cycle once the corpus has grown by
   GROWTH_THRESHOLD rows since the last cycle - retraining on the same data
   twice does nothing useful.
3. Before each cycle: runs a small cloud-lane top-up bench (glm-5.2:cloud +
   kimi-k2.6:cloud - your subscription, $0, the same lanes RUN-PLAN-BENCH.bat
   already uses) to bank a burst of higher-hit-rate "good" plans fast, since
   llama3.1 alone only clears the validator ~30% of the time. Only a modest
   batch per cycle, not continuous, to stay polite to the shared subscription.
4. Pauses the llama3.1 harvester (bench_loop.py, via PAUSE-BENCH.txt) for the
   duration of each training run so the two never fight over the GPU/Ollama,
   then resumes it - even if the cycle fails or times out.
5. Every sub-step is wrapped so ONE failure (a timeout, a crashed bench run)
   never kills the loop - it logs, cleans up, and tries again next cycle.

Logs to bench/flywheel-log.txt. State in bench/flywheel-state.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
LOG = BENCH / "flywheel-log.txt"
STATE = BENCH / "flywheel-state.json"
PAUSE_FLYWHEEL = BENCH / "PAUSE-FLYWHEEL.txt"
PAUSE_BENCH = BENCH / "PAUSE-BENCH.txt"
CORPUS_FILES = (ROOT / "data" / "flywheel" / "corpus.jsonl",
                ROOT / "data" / "flywheel" / "corpus-bench.jsonl")

GROWTH_THRESHOLD = 50    # new corpus rows needed before retraining
TOPUP_PROMPTS = 15       # synthetic good-data top-up batch size per cycle
CHECK_EVERY_S = 600      # 10 min between growth checks while waiting


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _corpus_rows() -> int:
    total = 0
    for p in CORPUS_FILES:
        if p.exists():
            total += sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    return total


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_trained_rows": 0}


def _save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state), encoding="utf-8")


def _run(script: str, *args, timeout=None) -> int:
    return subprocess.run([sys.executable, str(BENCH / script), *args],
                           cwd=str(ROOT), timeout=timeout).returncode


def main() -> int:
    log("flywheel loop up - waiting for corpus growth before the first cycle")
    state = _load_state()

    while True:
        if PAUSE_FLYWHEEL.exists():
            log("PAUSE-FLYWHEEL.txt present - sleeping 5 min")
            time.sleep(300)
            continue

        rows = _corpus_rows()
        grown = rows - state.get("last_trained_rows", 0)
        if grown < GROWTH_THRESHOLD:
            log(f"waiting: {grown}/{GROWTH_THRESHOLD} new corpus rows since last cycle "
                f"({rows} total)")
            time.sleep(CHECK_EVERY_S)
            continue

        log(f"threshold met ({grown} new rows, {rows} total) - starting a cycle")

        log(f"synthetic top-up: {TOPUP_PROMPTS} prompts on glm-5.2:cloud + kimi-k2.6:cloud "
            f"(higher legal-rate lanes, same $0 sub as RUN-PLAN-BENCH.bat)")
        try:
            _run("plan_bench.py", "--lanes", "glm-5.2:cloud,kimi-k2.6:cloud",
                 "--prompts", str(TOPUP_PROMPTS), timeout=3600)
        except Exception as exc:
            log(f"top-up failed/timed out: {exc} - continuing without it this cycle")

        try:
            r = _run("ingest_bench_to_corpus.py", timeout=300)
            log(f"ingest rc={r}")
        except Exception as exc:
            log(f"ingest failed: {exc} - continuing")

        log("pausing the llama3.1 harvester for the training window")
        PAUSE_BENCH.write_text("paused by flywheel_loop.py for a training cycle\n", encoding="utf-8")
        try:
            log("launching the training chain (make_training_set -> train -> register -> exam)")
            r = _run("run_chain.py", timeout=6 * 3600)
            log(f"training chain finished rc={r}")
        except subprocess.TimeoutExpired:
            log("training chain exceeded its 6h timeout - killed, will retry next cycle")
        except Exception as exc:
            log(f"training chain crashed: {exc}")
        finally:
            if PAUSE_BENCH.exists():
                PAUSE_BENCH.unlink()
            log("resumed the llama3.1 harvester")

        state["last_trained_rows"] = _corpus_rows()
        state["last_cycle_finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_state(state)
        log(f"cycle done - corpus now at {state['last_trained_rows']} rows")


if __name__ == "__main__":
    sys.exit(main())
