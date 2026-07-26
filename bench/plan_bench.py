"""Plan-stage micro-bench — the cheap test for the expensive wall.

Measures ONLY what the pipeline currently dies on: can a model lane emit a
plan that survives the REAL validator + solver? No ComfyUI, no renders, no
world build - each datapoint costs seconds, not minutes, and the validation
report gives the FULL violation census per plan (not just first-death).

Lives in bench/ (outside the ratchet's fingerprint roots) so running or
editing it never resets the qualification ladder. Read-only user of src/.

Usage:
  python bench\\plan_bench.py --lanes llama3.1,glm-5.2:cloud --prompts 12
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # bench/ is not a package; make src importable

# How far the free repair pass may move any one item. Deliberately below the
# 0.5m row pitch the planner uses for seating rows - see _one_plan().
MAX_NUDGE_M = 0.3


def _stub_concept(description: str):
    """Identical minimal concept for every lane - keeps the bench fair.

    The plan stage is what's being measured; the concept fields just give the
    planner the same context a brief would.
    """
    from src.models import SceneConcept

    return SceneConcept(
        era="contemporary unless the description says otherwise",
        mood="neutral",
        palette="derived from the description",
        architecture_notes="single rectangular room, standard walls and floor",
        key_objects=[w for w in description.replace(",", " ").split() if len(w) > 3][:8],
        lighting_notes="simple daylight",
        image_prompt=description,
    )


async def _one_plan(description: str, timeout_s: float) -> dict:
    from src.floor_plan.builder import build_floor_plan

    started = time.time()
    try:
        plan, warnings, report = await asyncio.wait_for(
            build_floor_plan(
                description,
                _stub_concept(description),
                placement_policy="explicit-semantic-relations/v1",
            ),
            timeout=timeout_s,
        )
        blockers = [getattr(b, "code", str(b)) for b in (getattr(report, "blockers", None) or [])]
        advisories = [getattr(a, "code", str(a)) for a in (getattr(report, "advisories", None) or [])]

        # Free repair before rejection (LL3M's debug-loop idea): a plan that
        # only failed on WHERE something sits is geometry pure math can nudge -
        # no model call, ~0.6ms. Measured on every archived failure:
        # 48/183 rescued at this cap (bench/repair-harvest-proof.json).
        # The cap stays under the 0.5m row pitch the planner uses for seating,
        # so a repair can't silently shuffle an evenly-spaced row into a layout
        # that no longer matches its own description. Raising it rescues more
        # (see bench/nudge-sweep.txt) at the cost of that guarantee - a data
        # quality decision, not a free win.
        repaired_by_math = False
        repairs_applied: list[str] = []
        blockers_before = list(blockers)
        if blockers:
            from src.floor_plan.repair import repair_near_miss
            from src.floor_plan.validator import validate_floor_plan

            attempt = repair_near_miss(plan, report, max_nudge_m=MAX_NUDGE_M)
            if attempt.repaired:
                # Re-judge at the SAME bar the report was produced with.
                # repair_near_miss re-validates internally at "mvp" tolerance,
                # which forgives overlaps <=0.1m - trusting its own verdict
                # would bank plans this bench calls illegal.
                recheck = validate_floor_plan(attempt.plan, warnings, tolerance="strict")
                if recheck.valid:
                    plan, report = attempt.plan, recheck
                    blockers = []
                    advisories = [getattr(a, "code", str(a))
                                  for a in (getattr(recheck, "advisories", None) or [])]
                    repaired_by_math = True
                    repairs_applied = attempt.repairs_applied

        try:  # full plan payload so bench rows are TRAINING DATA, not just scores
            plan_payload = plan.model_dump(mode="json")
        except AttributeError:
            plan_payload = plan.dict()
        row = {
            "status": "legal" if not blockers else "blocked",
            "blockers": blockers,
            "advisories": advisories,
            "warnings": len(warnings or []),
            "items": len(getattr(plan, "items", []) or []),
            "seconds": round(time.time() - started, 1),
            "plan": plan_payload,
        }
        # Relation bookkeeping the builder had to reconcile to get this plan
        # past schema validation at all. "synthesized" means we invented a
        # placeholder placement - a guess - so those rows are marked.
        for warning in warnings or []:
            for key in ("synthesized_relations", "dropped_orphan_relations",
                        "dropped_duplicate_relations"):
                if isinstance(warning, str) and warning.startswith(key + ":"):
                    row[key] = int(warning.split(":", 1)[1])

        if repaired_by_math:
            # Tagged so a later run can train with and without these rows and
            # measure whether repaired exemplars actually help.
            row["repaired_by_math"] = True
            row["repairs_applied"] = repairs_applied
            row["blockers_before_repair"] = blockers_before
        return row
    except asyncio.TimeoutError:
        return {"status": "timeout", "seconds": round(time.time() - started, 1)}
    except Exception as exc:  # model emission / schema / plumbing failures
        return {
            "status": "error",
            "error_type": type(exc).__name__,
            "error": str(exc)[:300],
            "seconds": round(time.time() - started, 1),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", default="llama3.1")
    ap.add_argument("--prompts", type=int, default=12)
    ap.add_argument("--start", type=int, default=0, help="offset into the prompt set (rotation)")
    ap.add_argument("--prompt-set", default=str(ROOT / "data" / "flywheel" / "prompt-set-v1.json"))
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    prompt_doc = json.loads(Path(args.prompt_set).read_text(encoding="utf-8"))
    raw_prompts = prompt_doc.get("prompts") if isinstance(prompt_doc, dict) else prompt_doc
    prompts = []
    window = (raw_prompts[args.start:] + raw_prompts[:args.start])  # wrap-around rotation
    for p in window[: args.prompts]:
        if isinstance(p, dict):
            prompts.append({"id": p.get("id", "?"), "text": p.get("prompt") or p.get("description") or p.get("text", "")})
        else:
            prompts.append({"id": f"p{len(prompts)+1:03d}", "text": str(p)})

    out_path = Path(args.out) if args.out else (
        ROOT / "bench" / f"results-{time.strftime('%Y%m%dT%H%M%S')}.json"
    )
    results = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "prompts": len(prompts), "lanes": {}}

    for lane in [l.strip() for l in args.lanes.split(",") if l.strip()]:
        os.environ["LLM_MODEL"] = lane
        print(f"\n=== LANE {lane} — {len(prompts)} prompts ===", flush=True)
        lane_rows, census = [], {}
        for p in prompts:
            row = asyncio.run(_one_plan(p["text"], args.timeout))
            row["prompt_id"] = p["id"]
            lane_rows.append(row)
            for b in row.get("blockers", []):
                census[b] = census.get(b, 0) + 1
            if row["status"] == "error":
                census[f"error:{row.get('error_type')}"] = census.get(f"error:{row.get('error_type')}", 0) + 1
            print(f"  {p['id']}: {row['status']:8s} ({row['seconds']}s) "
                  f"{','.join(row.get('blockers', [])[:3])}", flush=True)
            # Save + refine the tally after EVERY prompt, not just once per
            # lane - live progress, and a kill mid-run only loses the one
            # in-flight prompt instead of the whole 30.
            legal = sum(1 for r in lane_rows if r["status"] == "legal")
            results["lanes"][lane] = {
                "legal": legal, "total": len(lane_rows),
                "legal_rate": round(legal / max(1, len(lane_rows)), 2),
                "violation_census": dict(sorted(census.items(), key=lambda x: -x[1])),
                "rows": lane_rows,
            }
            out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"  LANE RESULT: {legal}/{len(lane_rows)} legal plans "
              f"({round(100*legal/max(1,len(lane_rows)))}%)", flush=True)

    results["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    out_path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"\nResults written: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
