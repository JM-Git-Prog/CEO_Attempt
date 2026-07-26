"""PROOF, before changing the harvester: how many already-thrown-away bench
plans would the deterministic repair have rescued?

Replays every archived failing plan in bench/results-*.json through
src/floor_plan/repair.py (repair_near_miss - pure math, no model call), then
re-validates with tolerance="strict", the SAME bar bench/plan_bench.py's
report was produced with. Nothing is written; this only measures.

Why the re-validate matters: repair_near_miss's own internal loop re-validates
with tolerance="mvp" (looser - it forgives overlaps <=0.1m), so its
remaining_blockers list is NOT the bar the harvester actually judges by.
Trusting it would over-count rescues.

Usage:  python bench\\repair_harvest_proof.py
"""
from __future__ import annotations

import glob
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.floor_plan.models import FloorPlanV11
from src.floor_plan.repair import repair_near_miss
from src.floor_plan.validator import validate_floor_plan

OUT = ROOT / "bench" / "repair-harvest-proof.json"


def main() -> int:
    rescued = still_failing = unparseable = already_legal_on_replay = 0
    rescued_from = Counter()
    unrescued_from = Counter()
    worst_ms = 0.0
    total_ms = 0.0

    for rf in sorted(glob.glob(str(ROOT / "bench" / "results-*.json"))):
        try:
            doc = json.loads(Path(rf).read_text(encoding="utf-8"))
        except Exception:
            continue
        for lane, ld in (doc.get("lanes") or {}).items():
            for row in ld.get("rows") or []:
                if row.get("status") == "legal":
                    continue
                if not isinstance(row.get("plan"), dict):
                    continue  # error/timeout rows carry no plan
                blockers = row.get("blockers") or []
                if not blockers:
                    continue
                try:
                    plan = FloorPlanV11.model_validate(row["plan"])
                except Exception:
                    unparseable += 1
                    continue

                before = validate_floor_plan(plan, tolerance="strict")
                if before.valid:
                    # archived as blocked but replays clean - don't credit repair
                    already_legal_on_replay += 1
                    continue

                t0 = time.time()
                result = repair_near_miss(plan, before, max_nudge_m=0.3)
                after = validate_floor_plan(result.plan, tolerance="strict")
                elapsed_ms = (time.time() - t0) * 1000
                total_ms += elapsed_ms
                worst_ms = max(worst_ms, elapsed_ms)

                sig = ",".join(sorted(set(blockers)))
                if after.valid:
                    rescued += 1
                    rescued_from[sig] += 1
                else:
                    still_failing += 1
                    unrescued_from[sig] += 1

    attempted = rescued + still_failing
    summary = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "failing_plans_replayed": attempted,
        "rescued_by_math_alone": rescued,
        "still_failing_after_repair": still_failing,
        "rescue_rate": round(rescued / attempted, 3) if attempted else None,
        "plans_that_replayed_clean_not_credited": already_legal_on_replay,
        "unparseable_plan_payloads": unparseable,
        "worst_case_ms": round(worst_ms, 1),
        "mean_ms": round(total_ms / attempted, 1) if attempted else None,
        "rescued_by_blocker_signature": rescued_from.most_common(12),
        "unrescued_by_blocker_signature": unrescued_from.most_common(12),
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"replayed          : {attempted} failing plans")
    print(f"RESCUED by math   : {rescued}"
          + (f"  ({rescued / attempted * 100:.1f}%)" if attempted else ""))
    print(f"still failing     : {still_failing}")
    print(f"replayed clean    : {already_legal_on_replay} (not credited)")
    print(f"unparseable       : {unparseable}")
    print(f"cost              : {summary['mean_ms']} ms mean, {summary['worst_ms'] if 'worst_ms' in summary else worst_ms:.1f} ms worst")
    print()
    print("rescued, by what was originally wrong:")
    for sig, n in rescued_from.most_common(10):
        print(f"  {n:5d}  {sig}")
    print("NOT rescued, by what was originally wrong:")
    for sig, n in unrescued_from.most_common(10):
        print(f"  {n:5d}  {sig}")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
