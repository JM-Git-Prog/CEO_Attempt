"""Ask the model for GRID CELLS instead of coordinates, and measure legality.

Everything measured so far repaired layouts that were already built wrong.
This asks a different question: if the model is asked for discrete cells from
the start, does it produce legal layouts?

Why cells might work where coordinates do not. Today the model emits
x=-2.13, z=5.47 and the collision is discovered afterwards, in validation.
On a grid it emits cell (4,7), and "that cell is taken" is something it can
check while writing - a symbol clash, not floating-point arithmetic. Models
are reliable at not repeating a symbol and unreliable at keeping forty coupled
floats consistent.

The conversion is exact, not approximate: a cell maps to a `centered` relation
carrying explicit x_offset_m / z_offset_m, and the solver honours those
offsets verbatim. So the plan the validator sees is exactly the grid the model
drew - no repair, no nudging, no synthesised relations. Same strict validator
as every other measurement, so the number is directly comparable to the 25%
baseline.

  python bench\\grid_gen_bench.py --selftest      prove the harness is correct
  python bench\\grid_gen_bench.py --prompts 30    run the real experiment
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CELL = 0.5          # metres per cell
ROOM_H = 2.8

GRID_SYSTEM = """You lay out rooms on a GRID. You never write coordinates.

The floor is a grid of 0.5 m squares. Cell (0,0) is the SOUTH-WEST corner.
cx increases toward the EAST. cz increases toward the NORTH.

Return ONLY this JSON:
{"room_cells":{"w":int,"d":int},
 "items":[{"id":"snake_case","name":"Human Name","cx":int,"cz":int,
           "w_cells":int,"d_cells":int,"height_m":number,
           "mount":"floor"|"wall"|"ceiling"}],
 "openings":[{"id":"snake_case","kind":"door"|"window","wall":"north"|"south"|"east"|"west",
              "offset_cells":int,"width_cells":int}],
 "camera":{"cx":int,"cz":int,"look":"north"|"south"|"east"|"west"}}

RULES - these are what make a layout legal:
1. An item occupies w_cells x d_cells starting at (cx,cz). Two items on the
   same mount MUST NOT share any cell. Check every cell before you place.
2. Every cell of every item must satisfy 0 <= cx+i < w and 0 <= cz+j < d.
3. Leave the cells in front of a door clear - a door needs 2 cells of空 space
   in front of it. Nothing may occupy them.
4. The camera's cell must be empty and must not be inside any item.
5. Sizes in cells: chair/stool 1x1, armchair 2x2, desk 3x2, sofa 4x2,
   counter 6x1, bed 3x4, table 2x2, lamp 1x1.
6. Repeated items get DIFFERENT cells - four stools in a row along a counter
   at cz=3 might be (2,3) (4,3) (6,3) (8,3), never the same cell twice.

Count the cells before you answer. No prose, JSON only."""


def cells_to_plan(raw: dict, description: str) -> dict:
    """Exact conversion - a cell becomes a centered relation with explicit
    offsets, which the solver reproduces verbatim."""
    rc = raw.get("room_cells") or {}
    nx, nz = int(rc.get("w", 0)), int(rc.get("d", 0))
    if nx < 1 or nz < 1:
        raise ValueError("room_cells missing or zero")
    width, depth = nx * CELL, nz * CELL
    half_w, half_d = width / 2.0, depth / 2.0

    items, relationships = [], []
    for entry in raw.get("items") or []:
        cx, cz = int(entry["cx"]), int(entry["cz"])
        cw, ch = max(1, int(entry.get("w_cells", 1))), max(1, int(entry.get("d_cells", 1)))
        x = -half_w + (cx + cw / 2.0) * CELL
        z = -half_d + (cz + ch / 2.0) * CELL
        mount = entry.get("mount", "floor")
        items.append({
            "id": entry["id"], "name": entry.get("name", entry["id"]),
            "category": "furniture", "mount": mount,
            "x": round(x, 3), "z": round(z, 3),
            "width": cw * CELL, "depth": ch * CELL,
            "height": float(entry.get("height_m", 0.8)),
            "elevation": 0.0, "rotation_deg": 0.0, "fixed": False,
            "clearance_m": 0.0,      # the grid already guarantees separation
            "description": entry.get("name", entry["id"]),
        })
        relationships.append({
            "subject_id": entry["id"], "kind": "centered", "target_id": None,
            "wall": None,
            "parameters_m": {"x_offset_m": round(x, 3), "z_offset_m": round(z, 3)},
            "weight": 1.0, "relaxable": False,
        })

    openings, opening_intents = [], []
    for entry in raw.get("openings") or []:
        wall = entry.get("wall", "north")
        span = max(1, int(entry.get("width_cells", 2))) * CELL
        along = int(entry.get("offset_cells", 0)) * CELL
        offset = (along - (half_w if wall in ("north", "south") else half_d)
                  + span / 2.0)
        openings.append({
            "id": entry["id"], "kind": entry.get("kind", "door"), "wall": wall,
            "offset": round(offset, 3), "width": span,
            "height": 2.1 if entry.get("kind") == "door" else 1.2,
            "sill_height": 0.0 if entry.get("kind") == "door" else 0.9,
        })
        opening_intents.append({"opening_id": entry["id"], "wall": wall,
                                "placement": "centered", "margin_m": 0.1})

    cam = raw.get("camera") or {}
    cam_x = -half_w + (int(cam.get("cx", 0)) + 0.5) * CELL
    cam_z = -half_d + (int(cam.get("cz", 0)) + 0.5) * CELL
    target = items[0]["id"] if items else None

    return {
        "name": description[:60] or "Grid room",
        "room": {"width": width, "depth": depth, "height": ROOM_H},
        "items": items, "openings": openings,
        "camera": {"x": round(cam_x, 3), "y": 1.6, "z": round(cam_z, 3),
                   "target_x": 0.0, "target_y": 1.2, "target_z": 0.0,
                   "fov_deg": 55.0},
        "circulation_notes": ["grid layout"], "design_notes": ["grid layout"],
        "schema_version": "floor-plan/v11",
        "relationships": relationships, "opening_intents": opening_intents,
        "camera_intent": {"target_id": target, "corner": "southwest",
                          "inset_m": 0.45, "eye_height_m": 1.6,
                          "target_height_m": 1.2, "fov_deg": 55.0},
    }


def judge(payload: dict):
    from src.floor_plan.models import FloorPlanV11
    from src.floor_plan.validator import validate_floor_plan
    plan = FloorPlanV11.model_validate(payload)
    report = validate_floor_plan(plan, tolerance="strict")
    return report.valid, [b.code for b in report.blockers]


def selftest() -> int:
    """A hand-built, deliberately legal grid must validate. If this fails the
    harness is broken and no model result from it would mean anything."""
    good = {
        "room_cells": {"w": 12, "d": 10},
        "items": [
            {"id": "counter", "name": "Counter", "cx": 3, "cz": 7, "w_cells": 6,
             "d_cells": 1, "height_m": 1.0, "mount": "floor"},
            {"id": "stool_1", "name": "Stool 1", "cx": 3, "cz": 5, "w_cells": 1, "d_cells": 1},
            {"id": "stool_2", "name": "Stool 2", "cx": 5, "cz": 5, "w_cells": 1, "d_cells": 1},
            {"id": "stool_3", "name": "Stool 3", "cx": 7, "cz": 5, "w_cells": 1, "d_cells": 1},
        ],
        "openings": [{"id": "door_1", "kind": "door", "wall": "south",
                      "offset_cells": 1, "width_cells": 2}],
        "camera": {"cx": 10, "cz": 1, "look": "north"},
    }
    valid, blockers = judge(cells_to_plan(good, "selftest diner"))
    print(f"  legal grid  -> valid={valid}  blockers={blockers}")

    clash = json.loads(json.dumps(good))
    clash["items"][2]["cx"] = 3          # stool_2 onto stool_1's cell
    clash["items"][2]["cz"] = 5
    bad_valid, bad_blockers = judge(cells_to_plan(clash, "selftest clash"))
    print(f"  cell clash  -> valid={bad_valid}  blockers={bad_blockers}")

    ok = valid and not bad_valid and "physical_overlap" in bad_blockers
    print(f"\n  HARNESS {'OK - legal passes, clash is caught' if ok else 'BROKEN'}")
    return 0 if ok else 1


async def one(description: str, timeout_s: float) -> dict:
    from src.orchestrator.llm import generate_json
    started = time.time()
    try:
        raw = await asyncio.wait_for(
            generate_json(GRID_SYSTEM, description), timeout=timeout_s)
        payload = cells_to_plan(raw, description)
        valid, blockers = judge(payload)
        return {"status": "legal" if valid else "blocked", "blockers": blockers,
                "seconds": round(time.time() - started, 1), "plan": payload}
    except asyncio.TimeoutError:
        return {"status": "timeout", "seconds": round(time.time() - started, 1)}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__,
                "error": str(exc)[:300], "seconds": round(time.time() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--prompts", type=int, default=30)
    ap.add_argument("--lane", default="llama3.1")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    import os
    os.environ["LLM_MODEL"] = args.lane

    doc = json.loads((ROOT / "data" / "flywheel" / "prompt-set-v1.json")
                     .read_text(encoding="utf-8"))
    raw = doc.get("prompts") if isinstance(doc, dict) else doc
    prompts = []
    for index, entry in enumerate(raw[: args.prompts]):
        text = (entry.get("prompt") or entry.get("description") or entry.get("text", "")
                if isinstance(entry, dict) else str(entry))
        prompts.append({"id": entry.get("id", f"p{index+1:03d}")
                        if isinstance(entry, dict) else f"p{index+1:03d}", "text": text})

    out = ROOT / "bench" / f"results-GRIDGEN-{time.strftime('%Y%m%dT%H%M%S')}.json"
    rows, census = [], {}
    legal = 0
    print(f"=== GRID GENERATION - {args.lane} - {len(prompts)} prompts ===", flush=True)
    for entry in prompts:
        row = asyncio.run(one(entry["text"], args.timeout))
        row["prompt_id"] = entry["id"]
        rows.append(row)
        if row["status"] == "legal":
            legal += 1
        for code in row.get("blockers", []):
            census[code] = census.get(code, 0) + 1
        if row["status"] == "error":
            key = f"error:{row.get('error_type')}"
            census[key] = census.get(key, 0) + 1
        print(f"  {entry['id']}: {row['status']:8s} ({row['seconds']}s) "
              f"{','.join(row.get('blockers', [])[:3])}", flush=True)
        out.write_text(json.dumps(
            {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "prompts": len(prompts),
             "lanes": {f"{args.lane}-GRID": {
                 "legal": legal, "total": len(rows),
                 "legal_rate": round(legal / len(rows), 3),
                 "violation_census": census, "rows": rows}}}, indent=1), encoding="utf-8")

    print(f"\nGRID legality: {legal}/{len(rows)} = {legal / len(rows) * 100:.1f}%")
    print("coordinate baseline on the same validator: ~25%")
    print(f"wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
