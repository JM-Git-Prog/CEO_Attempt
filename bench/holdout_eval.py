"""Stage B - fast holdout evaluation.

make_training_set.py already carves off a 20% holdout split
(data/flywheel/training/probe-v1-holdout.jsonl) that the model never trains
on - but nothing reads it back. This is the missing read: convert it into a
plan_bench.py-compatible prompt-set and bench one model lane against it.
Same cost as any other bench run, but scored against rows genuinely held
out of training, not the live prompt-set.json rotation training may have
already seen indirectly through the harvester.

Read-only user of the holdout file and src/; writes only under bench/.

Usage:
  python bench\\holdout_eval.py --lane planner-probe-v1
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLDOUT_FILE = ROOT / "data" / "flywheel" / "training" / "probe-v1-holdout.jsonl"
PROMPT_SET_CACHE = ROOT / "bench" / "holdout-prompt-set.json"


def _holdout_to_prompt_set() -> Path:
    """Rebuild the prompt-set fresh from the holdout file every call, so this
    never drifts from whatever make_training_set.py most recently wrote."""
    prompts = []
    with HOLDOUT_FILE.open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            user_msg = next(
                (m for m in row.get("messages", []) if m.get("role") == "user"), None
            )
            if not user_msg:
                continue
            record_id = (row.get("meta") or {}).get("record_id", f"h{i:03d}")
            prompts.append({"id": f"holdout-{record_id}", "prompt": user_msg.get("content", "")})
    PROMPT_SET_CACHE.write_text(json.dumps({"prompts": prompts}, indent=1), encoding="utf-8")
    return PROMPT_SET_CACHE


def run_holdout_eval(lane: str, timeout: float = 120.0) -> dict:
    """Bench one model lane against the full holdout set. Returns a small
    summary dict; the full plan_bench.py results file is also kept on disk.
    """
    prompt_set = _holdout_to_prompt_set()
    prompts = json.loads(prompt_set.read_text(encoding="utf-8"))["prompts"]
    out_path = ROOT / "bench" / f"holdout-results-{time.strftime('%Y%m%dT%H%M%S')}.json"
    subprocess.run(
        [sys.executable, str(ROOT / "bench" / "plan_bench.py"),
         "--lanes", lane, "--prompts", str(len(prompts)),
         "--prompt-set", str(prompt_set), "--timeout", str(timeout),
         "--out", str(out_path)],
        cwd=str(ROOT),
    )
    data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    return {
        "lane": lane,
        "holdout_size": len(prompts),
        "result": data.get("lanes", {}).get(lane, {}),
        "results_file": str(out_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="planner-probe-v1")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--summary-out", default="",
                     help="also write the small summary dict as JSON here "
                          "(for callers like hparam_sweep.py that shell out "
                          "to this script instead of importing it)")
    args = ap.parse_args()

    summary = run_holdout_eval(args.lane, args.timeout)
    if args.summary_out:
        Path(args.summary_out).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    rate = summary["result"].get("legal_rate")
    legal = summary["result"].get("legal")
    total = summary["result"].get("total")
    rate_str = f"{round(100*rate)}%" if rate is not None else "n/a"
    print(f"\nHOLDOUT RESULT - {args.lane}: {rate_str} ({legal}/{total} legal, "
          f"{summary['holdout_size']} holdout prompts, never trained on)")
    print(f"Results written: {summary['results_file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
