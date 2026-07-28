"""Discrete floor-grid assignment vs continuous placement, on the real failures.

The hypothesis (John, 2026-07-28): a one-point-perspective construction turns
the floor into a receding grid, which turns placement from "keep 40 coupled
floats consistent" into "assign each object a cell nobody else has". Overlap
stops being geometry and becomes a symbol clash - something a language model
can actually satisfy.

This tests the representation, not the renderer. Every archived FAILING plan is
re-placed by discrete cell assignment instead of continuous coordinates:

  * the floor is divided into cell-size squares
  * each item claims ceil(extent / cell) cells, rotation-aware, and is centred
    in its claimed block - so two items in different blocks cannot intersect
  * door and window keep-clear volumes claim their cells first
  * fixed items claim next, then the rest largest-first, each taking the free
    block NEAREST its solver-derived position, so the model's intent survives
  * items are layered by mount (floor / wall / ceiling) because the validator
    only calls it a collision when the vertical extents also overlap

Then the result is judged by the SAME strict validator as everything else.

Baselines already measured on this population: nudge repair 14%, continuous
sampling search 16%, auto-distribute 1.3%.

Usage:  python bench\\grid_assignment_proof.py
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

from src.floor_plan.models import FloorPlanV11
from src.floor_plan.validator import _opening_volumes, validate_floor_plan

OUT = ROOT / "bench" / "grid-assignment-proof.json"
CELL_SIZES = (0.25, 0.5, 0.75)


def _extent(item) -> tuple[float, float]:
    """Rotation-aware footprint extent."""
    rad = math.radians(getattr(item, "rotation_deg", 0.0) or 0.0)
    w = abs(item.width * math.cos(rad)) + abs(item.depth * math.sin(rad))
    d = abs(item.width * math.sin(rad)) + abs(item.depth * math.cos(rad))
    return w, d


def _layer(item) -> str:
    mount = getattr(item, "mount", "floor") or "floor"
    return mount if mount in ("floor", "ceiling", "wall") else "floor"


def assign_on_grid(plan: FloorPlanV11, cell: float) -> FloorPlanV11 | None:
    work = plan.model_copy(deep=True)
    half_w, half_d = work.room.width / 2.0, work.room.depth / 2.0
    nx = int(work.room.width / cell)
    nz = int(work.room.depth / cell)
    if nx < 1 or nz < 1:
        return None

    def cell_of(x: float, z: float) -> tuple[int, int]:
        return (min(nx - 1, max(0, int((x + half_w) / cell))),
                min(nz - 1, max(0, int((z + half_d) / cell))))

    def centre_of(cx: int, cz: int, cw: int, ch: int) -> tuple[float, float]:
        return (-half_w + (cx + cw / 2.0) * cell,
                -half_d + (cz + ch / 2.0) * cell)

    taken: dict[str, set[tuple[int, int]]] = {"floor": set(), "ceiling": set(), "wall": set()}

    # openings claim their cells on the floor layer first - nothing may stand
    # in a doorway, and this is where 422 blockers came from
    for zone in _opening_volumes(work):
        zw, zd = zone.width, zone.depth
        cx0, cz0 = cell_of(zone.x - zw / 2, zone.z - zd / 2)
        cx1, cz1 = cell_of(zone.x + zw / 2, zone.z + zd / 2)
        for cx in range(cx0, cx1 + 1):
            for cz in range(cz0, cz1 + 1):
                taken["floor"].add((cx, cz))

    def free(layer: str, cx: int, cz: int, cw: int, ch: int) -> bool:
        if cx < 0 or cz < 0 or cx + cw > nx or cz + ch > nz:
            return False
        return all((cx + i, cz + j) not in taken[layer]
                   for i in range(cw) for j in range(ch))

    def claim(layer: str, cx: int, cz: int, cw: int, ch: int) -> None:
        for i in range(cw):
            for j in range(ch):
                taken[layer].add((cx + i, cz + j))

    # biggest first - a large item has the fewest legal positions
    ordered = sorted(work.items,
                     key=lambda i: (not getattr(i, "fixed", False), -(i.width * i.depth)))

    for item in ordered:
        layer = _layer(item)
        ew, ed = _extent(item)
        cw, ch = max(1, math.ceil(ew / cell)), max(1, math.ceil(ed / cell))
        if cw > nx or ch > nz:
            return None  # item genuinely cannot fit in this room

        want_x, want_z = cell_of(item.x, item.z)
        best = None
        best_cost = None
        # search outward from where the solver wanted it: intent preserved,
        # displacement minimised, but the cell claim makes overlap impossible
        for radius in range(0, max(nx, nz) + 1):
            if best is not None:
                break
            for dx in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    if max(abs(dx), abs(dz)) != radius:
                        continue
                    cx, cz = want_x + dx, want_z + dz
                    if not free(layer, cx, cz, cw, ch):
                        continue
                    cost = dx * dx + dz * dz
                    if best_cost is None or cost < best_cost:
                        best, best_cost = (cx, cz), cost
        if best is None:
            return None
        claim(layer, best[0], best[1], cw, ch)
        item.x, item.z = centre_of(best[0], best[1], cw, ch)

    return work


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

    failing = []
    for payload in payloads:
        try:
            plan = FloorPlanV11.model_validate(payload)
        except Exception:
            continue
        if not validate_floor_plan(plan, tolerance="strict").valid:
            failing.append(plan)

    results = {}
    print(f"archived FAILING plans replayed : {len(failing)}")
    print("baselines on this same population: nudge 14% | sampling 16% | auto-distribute 1.3%")
    print()
    for cell in CELL_SIZES:
        legal = unplaceable = 0
        started = time.time()
        for plan in failing:
            placed = assign_on_grid(plan, cell)
            if placed is None:
                unplaceable += 1
                continue
            if validate_floor_plan(placed, tolerance="strict").valid:
                legal += 1
        elapsed = time.time() - started
        rate = legal / len(failing) if failing else 0
        results[str(cell)] = {"legal": legal, "unplaceable": unplaceable,
                              "rate": round(rate, 3), "seconds": round(elapsed, 1)}
        print(f"  cell {cell:>4} m : {legal:4d}/{len(failing)} legal ({rate * 100:5.1f}%)"
              f"   no fit: {unplaceable:3d}   {elapsed:.1f}s")

    OUT.write_text(json.dumps(
        {"generated": time.strftime("%Y-%m-%d %H:%M:%S"),
         "failing_plans": len(failing), "by_cell_size": results}, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
