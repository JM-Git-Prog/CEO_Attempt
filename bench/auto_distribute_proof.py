"""Measure: how many failing plans become legal if repeated items are spread out?

Finding this is built on (2026-07-28): of 888 groups of repeated identical
items across the archive, 70% carry NO distribution parameters at all. The
solver then places every copy against the same anchor with no spread, so four
stools land on one another. That single omission is the largest single source
of physical_overlap.

The solver spreads items two different ways, and a fix has to know which:
  * against_wall / near_corner - position comes from `along_offset_m`;
    distribution_* is IGNORED entirely. Copies need distinct offsets.
  * south_of / north_of / above - spread along x via distribution_index/count
  * adjacent_to / east_of / west_of - spread along z, same mechanism
  * around - index/count over a circle

This measures the fix offline against every archived failure before a line of
it goes near the pipeline. Read-only apart from its own report.

Usage:  python bench\\auto_distribute_proof.py
"""
from __future__ import annotations

import glob
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.floor_plan.models import FloorPlanV11
from src.floor_plan.solver import solve_explicit_plan
from src.floor_plan.validator import validate_floor_plan

OUT = ROOT / "bench" / "auto-distribute-proof.json"

ALONG_KINDS = {"against_wall", "near_corner"}
X_SPREAD = {"south_of", "north_of", "above"}
Z_SPREAD = {"adjacent_to", "east_of", "west_of"}


def _base_name(name: str) -> str:
    return re.sub(r"[\s_#-]*\d+$", "", (name or "").strip().lower())


def _pad(clearance: float) -> float:
    """The validator's real padding rule."""
    return min(0.4, max(0.0, clearance) / 2)


def auto_distribute(payload: dict) -> tuple[dict, int]:
    """Give repeated items a spread when the model supplied none.

    Only fires when EVERY copy in a group shares the same relation kind, target
    and wall, and NONE of them already carries spread information - so it can
    never override a deliberate layout.
    """
    items = payload.get("items")
    relations = payload.get("relationships")
    if not isinstance(items, list) or not isinstance(relations, list):
        return payload, 0

    by_id = {i.get("id"): i for i in items if isinstance(i, dict)}
    rel_by_subject = {r.get("subject_id"): r for r in relations if isinstance(r, dict)}
    room = payload.get("room") or {}
    half_w = float(room.get("width", 0)) / 2
    half_d = float(room.get("depth", 0)) / 2

    groups = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        relation = rel_by_subject.get(item.get("id"))
        if not relation:
            continue
        key = (_base_name(item.get("name", "")), relation.get("kind"),
               relation.get("target_id"), relation.get("wall"))
        groups[key].append((item, relation))

    fixed = 0
    for (_, kind, _, wall), members in groups.items():
        if len(members) < 2:
            continue
        params = [m[1].setdefault("parameters_m", {}) for m in members]

        if kind in ALONG_KINDS:
            offsets = [p.get("along_offset_m") for p in params]
            if len({round(o, 3) for o in offsets if o is not None}) > 1:
                continue  # already spread deliberately
            axis_limit = half_w if wall in ("north", "south") else half_d
        else:
            if any(p.get("distribution_count") is not None for p in params):
                continue  # model already handled it
            if kind not in X_SPREAD and kind not in Z_SPREAD and kind != "around":
                continue
            axis_limit = half_w if kind in X_SPREAD else half_d

        count = len(members)
        # smallest pitch that keeps neighbours clear of each other
        pitch = max(
            (m[0].get("width", 0.5) + m[0].get("depth", 0.5)) / 2
            + 2 * _pad(m[0].get("clearance_m", 0.0)) + 0.02
            for m in members
        )
        span = pitch * (count - 1)
        if axis_limit > 0:
            span = min(span, max(0.0, 2 * axis_limit - pitch))

        if kind == "around":
            for index, (_, relation) in enumerate(members):
                relation["parameters_m"]["distribution_index"] = float(index)
                relation["parameters_m"]["distribution_count"] = float(count)
            fixed += 1
            continue

        if kind in ALONG_KINDS:
            start = -span / 2
            base = next((o for o in offsets if o is not None), 0.0) or 0.0
            for index, (_, relation) in enumerate(members):
                offset = start + (span * index / (count - 1) if count > 1 else 0.0)
                relation["parameters_m"]["along_offset_m"] = round(base * 0 + offset, 3)
            fixed += 1
        else:
            for index, (_, relation) in enumerate(members):
                relation["parameters_m"]["distribution_index"] = float(index)
                relation["parameters_m"]["distribution_count"] = float(count)
                relation["parameters_m"]["distribution_span_m"] = round(span, 3)
            fixed += 1
    return payload, fixed


def main() -> int:
    payloads = []
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
                payloads.append(row["plan"])

    replayed = rescued = untouched = 0
    groups_fixed = 0
    started = time.time()

    for payload in payloads:
        try:
            plan = FloorPlanV11.model_validate(payload)
        except Exception:
            continue
        if validate_floor_plan(plan, tolerance="strict").valid:
            continue
        replayed += 1

        patched, fixed = auto_distribute(json.loads(json.dumps(payload)))
        groups_fixed += fixed
        if fixed == 0:
            untouched += 1
            continue
        try:
            resolved = solve_explicit_plan(FloorPlanV11.model_validate(patched))
        except Exception:
            continue
        if validate_floor_plan(resolved, tolerance="strict").valid:
            rescued += 1

    elapsed = time.time() - started
    eligible = replayed - untouched
    summary = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "failing_plans_replayed": replayed,
        "plans_with_repeated_items_to_fix": eligible,
        "plans_with_nothing_to_fix": untouched,
        "groups_given_a_spread": groups_fixed,
        "now_legal": rescued,
        "rate_of_all_failures": round(rescued / replayed, 3) if replayed else None,
        "rate_of_eligible": round(rescued / eligible, 3) if eligible else None,
        "seconds_total": round(elapsed, 1),
    }
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"failing plans replayed            : {replayed}")
    print(f"  had repeated items to spread    : {eligible}")
    print(f"  nothing to fix (no repeats)     : {untouched}")
    print(f"  groups given a spread           : {groups_fixed}")
    print(f"  NOW LEGAL after auto-distribute : {rescued}"
          + (f"  ({rescued / replayed * 100:.1f}% of all failures,"
             f" {rescued / eligible * 100:.1f}% of eligible)" if eligible else ""))
    print(f"  cost                            : {elapsed:.1f}s for {replayed} plans")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
