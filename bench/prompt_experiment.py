"""Stage A - prompt-variant experiment harness (cheapest rung: zero GPU cost).

Tests whether a change to the v11 planning system prompt moves the
plan-legality rate, with the MODEL held fixed across variants so results
isolate the prompt as the one variable under test. Reuses plan_bench.py's
proven bench loop as a subprocess, pointed at each variant via the
V11_PLAN_SYSTEM_FILE env-var hook in src/floor_plan/builder.py.

Read-only user of src/ - writes only under bench/.

Usage:
  python bench\\prompt_experiment.py --lane planner-probe-v1 --prompts 15
  python bench\\prompt_experiment.py --lane llama3.1 --variants control,self-check --prompts 10
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # bench/ is not a package; make src importable

VARIANTS_DIR = ROOT / "bench" / "prompt_variants"

# Each addition is appended to the CURRENT production V11_PLAN_SYSTEM (read
# fresh from builder.py at run time, so a variant can never silently drift
# out of sync with whatever the real prompt says). "control" = no addition,
# i.e. the unmodified production prompt - the thing every variant is judged
# against.
ADDITIONS: dict[str, str] = {
    "control": "",
    "explicit-math": """

STAGE-A EXPERIMENT - EXPLICIT OVERLAP/CLEARANCE ARITHMETIC:
Before finalizing, check every item pair sharing floor space with actual
numbers, not intuition:
- Two items overlap if their X ranges AND Z ranges both intersect. If two
  items' X-ranges and Z-ranges both overlap by more than 0.1m, move one
  until they no longer do.
- A door/window is blocked if any item's bounding box comes within 1.0m of
  the opening's position along its wall. Compute this distance explicitly
  for every item on that wall before finalizing.
- In design_notes, state the two closest item-pairs and their computed gap
  in meters, proving they clear the 0.1m overlap / 1.0m door thresholds.
""",
    "self-check": """

STAGE-A EXPERIMENT - FINAL SELF-CHECK PASS:
Before returning JSON, silently re-read your own item list once as a final
verification pass and confirm, item by item: (1) it is fully inside the
room's width/depth bounds, (2) it does not share space with any other
item, (3) it does not sit within 1.0m of a door or window opening on its
wall. If any check fails, fix that item's position now, before returning
the final JSON. Do not mention this check in your output - just make sure
it passes.
""",
}


def _write_variant(name: str, addition: str) -> Path | None:
    """Materialize a variant file from the CURRENT production prompt + this
    addition. Returns None for the control (no override - use production
    V11_PLAN_SYSTEM exactly as builder.py already does by default).
    """
    if not addition:
        return None
    from src.floor_plan.builder import V11_PLAN_SYSTEM

    VARIANTS_DIR.mkdir(exist_ok=True)
    path = VARIANTS_DIR / f"{name}.txt"
    path.write_text(V11_PLAN_SYSTEM + addition, encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", default="planner-probe-v1",
                    help="model held fixed across every variant, so only the prompt varies")
    ap.add_argument("--prompts", type=int, default=15)
    ap.add_argument("--variants", default="all", help="comma-separated variant names, or 'all'")
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    all_names = list(ADDITIONS.keys())
    names = all_names if args.variants == "all" else [v.strip() for v in args.variants.split(",") if v.strip()]
    for n in names:
        if n not in ADDITIONS:
            print(f"Unknown variant '{n}'. Known: {', '.join(all_names)}")
            return 1

    stamp = time.strftime("%Y%m%dT%H%M%S")
    leaderboard = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "lane": args.lane, "prompts_per_variant": args.prompts, "variants": {},
    }

    for name in names:
        variant_path = _write_variant(name, ADDITIONS[name])
        out_path = ROOT / "bench" / f"prompt-experiment-{name}-{stamp}.json"
        env = dict(os.environ)
        env["LLM_MODEL"] = args.lane
        if variant_path:
            env["V11_PLAN_SYSTEM_FILE"] = str(variant_path)
        else:
            env.pop("V11_PLAN_SYSTEM_FILE", None)
        print(f"\n=== VARIANT '{name}' (lane={args.lane}, prompts={args.prompts}) ===", flush=True)
        r = subprocess.run(
            [sys.executable, str(ROOT / "bench" / "plan_bench.py"),
             "--lanes", args.lane, "--prompts", str(args.prompts),
             "--timeout", str(args.timeout), "--out", str(out_path)],
            cwd=str(ROOT), env=env,
        )
        data = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
        lane_result = data.get("lanes", {}).get(args.lane, {})
        leaderboard["variants"][name] = {
            "legal_rate": lane_result.get("legal_rate"),
            "legal": lane_result.get("legal"),
            "total": lane_result.get("total"),
            "violation_census": lane_result.get("violation_census", {}),
            "results_file": str(out_path),
            "rc": r.returncode,
        }

    ranked = sorted(
        leaderboard["variants"].items(),
        key=lambda kv: (kv[1]["legal_rate"] if kv[1]["legal_rate"] is not None else -1),
        reverse=True,
    )
    print("\n=== LEADERBOARD (best prompt variant first) ===")
    for name, res in ranked:
        rate = res["legal_rate"]
        rate_str = f"{round(100*rate)}%" if rate is not None else "n/a"
        print(f"  {name:16s} {rate_str:>5s}  ({res['legal']}/{res['total']} legal)")

    leaderboard["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    leaderboard["ranked"] = [name for name, _ in ranked]
    summary_path = ROOT / "bench" / f"prompt-experiment-summary-{stamp}.json"
    summary_path.write_text(json.dumps(leaderboard, indent=1), encoding="utf-8")
    print(f"\nSummary written: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
