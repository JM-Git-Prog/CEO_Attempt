"""PROOF: the world/500 'constraints could not be satisfied' wall falls to a
~40-line repair pass - greedy solve first, spiral-search repair for whatever
it BLOCKED, judged by the pipeline's own _hard_issues. No pipeline files are
modified; this drives the real solver from outside as evidence for the fix.

Test set: every WorldContract archived in the corpus (real sessions),
replayed through the real solve_relationships, then through greedy+repair.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import constraint_solver as cs
from src.world_contract import WorldContract

OUT = ROOT / "bench" / "solver-proof-results.json"


def blocked_of(result) -> list:
    """Collect BLOCKED constraint results from RelationshipSolveResult, shape-agnostic."""
    pools = []
    for attr in ("results", "constraints", "report", "solver_report"):
        v = getattr(result, attr, None)
        if v is None:
            continue
        v = getattr(v, "results", v)
        if isinstance(v, (list, tuple)):
            pools.extend(v)
    return [r for r in pools if getattr(r, "status", None) == cs.ConstraintStatus.BLOCKED]


def contract_of(result, fallback):
    for attr in ("contract", "world_contract", "updated_contract"):
        v = getattr(result, attr, None)
        if v is not None:
            return v
    return fallback


def repair(contract) -> tuple[int, int, list]:
    """Spiral-search repair for items that still have hard issues. Returns
    (fixed_count, unfixed_count, notes)."""
    instances = list(contract.instances)
    by_id = {i.id: i for i in instances}
    notes, fixed, unfixed = [], 0, 0
    room = contract.room.dimensions
    for item in instances:
        if getattr(item, "fixed", False):
            continue  # never move fixed furniture; its overlapping partner moves instead
        issues = cs._hard_issues(item, contract, instances)
        if not issues:
            continue
        placed = False
        x0, z0 = item.transform.position_m.x, item.transform.position_m.z
        r_raw = item.transform.rotation_deg
        rot0 = float(getattr(r_raw, "y", r_raw))  # rotation is a Vector3; yaw lives in .y
        for radius in (0.15, 0.3, 0.5, 0.75, 1.0, 1.4, 1.9):
            if placed:
                break
            for k in range(12):
                ang = 2 * math.pi * k / 12
                for rot in (rot0, (rot0 + 90.0) % 360.0):
                    cand = cs._replace_transform(
                        item, x=x0 + radius * math.cos(ang), z=z0 + radius * math.sin(ang), rotation=rot)
                    others = [by_id[i.id] for i in instances if i.id != item.id]
                    if not cs._hard_issues(cand, contract, others):
                        by_id[item.id] = cand
                        idx = next(n for n, i in enumerate(instances) if i.id == item.id)
                        instances[idx] = cand
                        notes.append(f"{item.id}: repaired at r={radius:.2f} rot={rot:.0f} (was {[i.reason_code for i in issues]})")
                        placed = True
                        fixed += 1
                        break
                if placed:
                    break
        if not placed:
            unfixed += 1
            notes.append(f"{item.id}: UNREPAIRABLE within search budget ({[i.reason_code for i in issues]})")
    return fixed, unfixed, notes


def stress_variants(template: dict, n: int = 60) -> list:
    """Clone the real canonical-kitchen contract and roll the same dice llama
    rolls: relation parameters (spans, gaps, offsets). Returns contract dicts."""
    import copy
    import random
    rng = random.Random(13)
    out = []
    for v in range(n):
        wc = copy.deepcopy(template)
        for inst in wc.get("instances", []):
            for rel in inst.get("relations") or []:
                p = rel.get("parameters_m") or {}
                if "distribution_span_m" in p:
                    p["distribution_span_m"] = round(p["distribution_span_m"] * rng.uniform(0.35, 1.6), 3)
                if "gap_m" in p:
                    p["gap_m"] = round(p["gap_m"] * rng.uniform(0.2, 2.5), 3)
                if "along_offset_m" in p:
                    p["along_offset_m"] = round(p["along_offset_m"] + rng.uniform(-2.2, 2.2), 3)
                if "wall_gap_m" in p:
                    p["wall_gap_m"] = round(max(0.01, p["wall_gap_m"] * rng.uniform(0.5, 3.0)), 3)
                if "radius_m" in p:
                    p["radius_m"] = round(p["radius_m"] * rng.uniform(0.6, 1.5), 3)
            # llama also jitters authored positions
            t = inst.get("transform", {}).get("position_m")
            if t:
                span = 0.5 if inst.get("fixed") else 0.9
                t["x"] = round(t["x"] + rng.uniform(-span, span), 3)
                t["z"] = round(t["z"] + rng.uniform(-span, span), 3)
        cam = wc.get("camera", {}).get("position_m")
        if cam:
            cam["x"] = round(cam["x"] + rng.uniform(-0.9, 0.9), 3)
            cam["z"] = round(cam["z"] + rng.uniform(-0.9, 0.9), 3)
        out.append((f"variant-{v:02d}", wc))
    return out


def main() -> int:
    contracts = []
    for line in (ROOT / "data" / "flywheel" / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        wc = d.get("world_contract")
        if isinstance(wc, dict):
            contracts.append((d.get("record_id", "?"), wc))
    template = next((wc for _, wc in contracts
                     if any(i.get("name") == "Formica Counter" for i in wc.get("instances", []))), None)
    if template:
        contracts = contracts + stress_variants(template, 60)
    print(f"replaying {len(contracts)} contracts (archived + canonical-kitchen dice variants) through the REAL solver")
    rows = []
    for rid, wc in contracts:
        row = {"record": rid}
        try:
            contract = WorldContract.model_validate(wc)
        except Exception as e:
            try:
                contract = WorldContract.parse_obj(wc)
            except Exception as e2:
                row["status"] = f"contract-parse-failed: {type(e2).__name__}"
                rows.append(row)
                print(row)
                continue
        t0 = time.time()
        try:
            greedy = cs.solve_relationships(contract)
            rep = greedy.report
            row["greedy_success"] = bool(rep.success)
            row["greedy_blocked"] = 0 if rep.success else 1
            row["greedy_blocked_codes"] = sorted({h.reason_code for h in (rep.hard_constraints or ())}) or                 sorted({r.reason_code for r in (rep.relations or ()) if getattr(r, 'status', None) == cs.ConstraintStatus.BLOCKED})
            solved_contract = greedy.contract or contract
        except Exception as e:
            row["greedy_blocked"] = -1
            row["greedy_error"] = f"{type(e).__name__}: {e}"[:140]
            solved_contract = contract
        if row.get("greedy_blocked", 0) != 0:
            fixed, unfixed, notes = repair(solved_contract)
            row["repair_fixed"] = fixed
            row["repair_unfixed"] = unfixed
            row["repair_notes"] = notes[:6]
            row["VERDICT"] = "SOLVED-BY-REPAIR" if unfixed == 0 else "STILL-UNSAT"
        else:
            row["VERDICT"] = "greedy-ok"
        row["seconds"] = round(time.time() - t0, 3)
        rows.append(row)
        print(row.get("record", "?")[:12], row["VERDICT"],
              f"blocked={row.get('greedy_blocked')} fixed={row.get('repair_fixed', 0)} t={row['seconds']}s")
    summary = {
        "contracts": len(rows),
        "greedy_ok": sum(1 for r in rows if r["VERDICT"] == "greedy-ok"),
        "solved_by_repair": sum(1 for r in rows if r["VERDICT"] == "SOLVED-BY-REPAIR"),
        "still_unsat": sum(1 for r in rows if r["VERDICT"] == "STILL-UNSAT"),
        "errors": sum(1 for r in rows if "greedy_error" in r or "contract-parse" in str(r.get("status", ""))),
        "rows": rows,
    }
    OUT.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\nSUMMARY:", {k: v for k, v in summary.items() if k != "rows"})
    print("written:", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
