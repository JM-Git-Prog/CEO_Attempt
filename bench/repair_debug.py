"""Instrument ONE failing variant: watch shipped repair rounds converge or thrash,
and audit the harness's single-pass verdict with a full final sweep."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import constraint_solver as cs
from src import solver_repair as sr
from src.world_contract import WorldContract
from solver_proof import stress_variants


def dirty(contract):
    inst = list(contract.instances)
    out = []
    for i in inst:
        iss = cs._hard_issues(i, contract, inst)
        if iss:
            out.append((i.id, [x.reason_code for x in iss]))
    return out


def main():
    template = None
    for line in (ROOT / "data" / "flywheel" / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        wc = d.get("world_contract")
        if isinstance(wc, dict) and any(i.get("name") == "Formica Counter" for i in wc.get("instances", [])):
            template = wc
            break
    variants = stress_variants(template, 60)
    picked = None
    for name, wc in variants:
        c = WorldContract.model_validate(wc)
        if not cs.solve_relationships(c).report.success:
            picked = (name, c)
            break
    name, contract = picked
    print("variant:", name)
    print("initial dirty:", dirty(contract))
    current = contract
    for rnd in range(1, 5):
        current, moved, unrepaired = sr._repair_instances(current)
        d = dirty(current)
        print(f"round {rnd}: moved={moved} unrepaired={unrepaired} dirty_after={d}")
        if not d:
            print("CONVERGED clean")
            break
        if moved == 0:
            print("STUCK - nothing movable helps")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
