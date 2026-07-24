"""The $0 data factory: continuous plan-bench + corpus banking.

Politeness rules (in order):
1. WAITS for the training chain to finish (or go stale 2h) before starting -
   tonight's LoRA probe owns the quiet GPU first.
2. Pauses whenever bench/PAUSE-BENCH.txt exists (John's off switch).
3. Batches of 15 prompts, rotating through the whole set, 90s breather
   between batches so trials/harvest can interleave on Ollama.

Logs to bench/bench-loop-log.txt (registered on the Ops board).
"""
from __future__ import annotations

import glob
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
LOG = BENCH / "bench-loop-log.txt"
STATE = BENCH / "loop-state.json"
PAUSE = BENCH / "PAUSE-BENCH.txt"
CHAIN_LOG = BENCH / "chain-log.txt"
BATCH = 15
TOTAL_PROMPTS = 100


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def chain_done() -> bool:
    if list(BENCH.glob("trained/*/")):
        return True  # training produced output
    if not CHAIN_LOG.exists():
        return True  # chain never started - nothing to wait for
    age = time.time() - CHAIN_LOG.stat().st_mtime
    if age > 2 * 3600:
        log(f"chain log stale {age/3600:.1f}h - assuming chain dead, proceeding")
        return True
    return False


def main() -> int:
    log("bench loop up - waiting for training chain to finish first")
    while not chain_done():
        time.sleep(300)
    log("GPU turn acquired - continuous benching begins")

    start = 0
    if STATE.exists():
        try:
            start = int(json.loads(STATE.read_text(encoding="utf-8")).get("next_start", 0))
        except Exception:
            start = 0

    while True:
        if PAUSE.exists():
            log("PAUSE-BENCH.txt present - sleeping 5 min")
            time.sleep(300)
            continue
        log(f"batch: prompts {start}..{(start + BATCH - 1) % TOTAL_PROMPTS} (llama3.1)")
        r = subprocess.run(
            [sys.executable, str(BENCH / "plan_bench.py"),
             "--lanes", "llama3.1", "--prompts", str(BATCH), "--start", str(start)],
            cwd=str(ROOT),
        )
        log(f"bench batch rc={r.returncode}")
        r2 = subprocess.run([sys.executable, str(BENCH / "ingest_bench_to_corpus.py")],
                            cwd=str(ROOT), capture_output=True, text=True)
        log(f"ingest: {(r2.stdout or '').strip()[:140]}")
        start = (start + BATCH) % TOTAL_PROMPTS
        STATE.write_text(json.dumps({"next_start": start}), encoding="utf-8")
        time.sleep(90)


if __name__ == "__main__":
    sys.exit(main())
