"""Greedy first-fit vs sampling-based placement, on the real failure population.

The question this answers: is the 25% legality rate a MODEL problem or a
PLACEMENT problem?

Today the plan path places each item once, relative to its relation anchor, and
never checks the result globally - the textbook "naive placement" that REST3D
measures at 4-16% physical stability. Their fix is a support tree plus
constrained optimization over candidate poses, which lands at 93-96%.

You already have the support tree (FloorPlanV11.relationships) and the
objective function (the validator's own hard checks). What is missing is the
search. This adds it - a displacement-minimising spiral over candidate poses,
accepting the smallest move that clears every constraint - and re-solves every
archived FAILING plan both ways.

Read only. Nothing is written except this script's own report.

Usage:  python bench\\placement_search_proof.py
"""
from __future__ import annotations

import glob
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.floor_plan.geometry import footprints_intersect, inside_room
from src.floor_plan.models import FloorPlanV11
from src.floor_plan.validator import _opening_volumes, validate_floor_plan

OUT = ROOT / "bench" / "placement-search-proof.json"

# Candidate poses are tried nearest-first, so the accepted fix is always the
# smallest move that works - the "minimise displacement while remaining valid"
# objective, without needing a physics engine.
RADII = [0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0]
ANGLES = 16
ROUNDS = 6


def _volume(item):
    return item


def _item_conflicts(item, plan, others, opening_zones) -> bool:
    """Does this item violate a hard constraint where it currently sits?"""
    if not inside_room(item, plan.room.width, plan.room.depth):
        return True
    for other in others:
        if other.id == item.id:
            continue
        if footprints_intersect(item, other):
            return True
    for zone in opening_zones:
        if footprints_intersect(item, zone):
            return True
    return False


def sampling_place(plan: FloorPlanV11) -> FloorPlanV11:
    """Search for a globally feasible arrangement, nearest-first."""
    work = plan.model_copy(deep=True)
    opening_zones = _opening_volumes(work)

    for _ in range(ROUNDS):
        items = list(work.items)
        offenders = [i for i in items if _item_conflicts(i, work, items, opening_zones)]
        if not offenders:
            break
        moved_any = False
        for item in offenders:
            if getattr(item, "fixed", False):
                continue
            x0, z0, rot0 = item.x, item.z, item.rotation_deg
            placed = False
            for radius in RADII:
                if placed:
                    break
                steps = 1 if radius == 0.0 else ANGLES
                for step in range(steps):
                    angle = 2.0 * math.pi * step / ANGLES
                    for rot in (rot0, (rot0 + 90.0) % 360.0):
                        item.x = x0 + radius * math.cos(angle)
                        item.z = z0 + radius * math.sin(angle)
                        item.rotation_deg = rot
                        others = [o for o in work.items if o.id != item.id]
                        if not _item_conflicts(item, work, others, opening_zones):
                            placed = True
                            moved_any = True
                            break
                    if placed:
                        break
            if not placed:
                item.x, item.z, item.rotation_deg = x0, z0, rot0
        if not moved_any:
            break
    return work


def main() -> int:
    plans = []
    for path in glob.glob(str(ROOT / "bench" / "results-*.json")):
        try:
            doc = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for lane in (doc.get("lanes") or {}).values():
            for row in lane.get("rows") or []:
                if row.get("status") == "legal" or not isinstance(row.get("plan"), dict):
                    continue
                if not (row.get("blockers") or []):
                    continue
                plans.append(row["plan"])

    usable = []
    for payload in plans:
        try:
            plan = FloorPlanV11.model_validate(payload)
        except Exception:
            continue
        if not validate_floor_plan(plan, tolerance="strict").valid:
            usable.append(plan)

    rescued = 0
    still = 0
    worst_ms = 0.0
    total_ms = 0.0
    displacement = []

    for plan in usable:
        started = time.time()
        solved = sampling_place(plan)
        elapsed = (time.time() - started) * 1000
        total_ms += elapsed
        worst_ms = max(worst_ms, elapsed)
        if validate_floor_plan(solved, tolerance="strict").valid:
            rescued += 1
            moves = [math.dist((a.x, a.z), (b.x, b.z))
                     for a, b in zip(plan.items, solved.items)]
            if moves:
                displacement.append(max(moves))
        else:
            still += 1

    total = rescued + still
    summary = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "failing_plans": total,
        "greedy_first_fit_legal": 0,      # by definition - these all failed
        "sampling_search_legal": rescued,
        "sampling_rate": round(rescued / total, 3) if total else None,
        "still_infeasible": still,
        "mean_ms": round(total_ms / total, 1) if total else None,
        "worst_ms": round(worst_ms, 1),
        "median_max_displacement_m": (
            round(sorted(displacement)[len(displacement) // 2], 2) if displacement else None),
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"archived FAILING plans replayed : {total}")
    print(f"  greedy first-fit (today)      : 0/{total} legal  (that is why they are here)")
    print(f"  sampling search (proposed)    : {rescued}/{total} legal"
          + (f"  ({rescued / total * 100:.1f}%)" if total else ""))
    print(f"  still infeasible              : {still}")
    print(f"  cost                          : {summary['mean_ms']} ms mean, "
          f"{summary['worst_ms']} ms worst")
    print(f"  median largest move           : {summary['median_max_displacement_m']} m")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
