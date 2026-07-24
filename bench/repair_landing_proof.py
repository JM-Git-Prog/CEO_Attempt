"""Verify the SHIPPED repair module (src/solver_repair.py) rescues the same
reproduced failure population the proof harness did. Run after landing."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import constraint_solver as cs
from src.solver_repair import attempt_repair
from src.world_contract import WorldContract
from solver_proof import stress_variants  # bench sibling

def main() -> int:
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
    rescued = failed_greedy = still_unsat = 0
    worst = 0.0
    for name, wc in variants:
        contract = WorldContract.model_validate(wc)
        solved = cs.solve_relationships(contract)
        if solved.report.success:
            continue
        failed_greedy += 1
        t0 = time.time()
        result = attempt_repair(contract)
        worst = max(worst, time.time() - t0)
        if result is not None:
            rescued += 1
        else:
            still_unsat += 1
            print("UNSAT:", name)
    print(f"SHIPPED-MODULE PROOF: greedy failed {failed_greedy}/60 | rescued {rescued} | "
          f"still-unsat {still_unsat} | worst repair {worst*1000:.0f} ms")
    return 0 if rescued >= failed_greedy - 2 else 1


if __name__ == "__main__":
    sys.exit(main())
