"""Build the training-probe dataset from the corpus's accepted plans.

Emits chat-format JSONL matching the PRODUCTION prompt: the real
V11_PLAN_SYSTEM as system, the original description as user, the accepted
plan JSON as assistant. Runs on John's machine (needs the repo's deps).

Output: data/flywheel/training/probe-v1.jsonl (+ a held-out eval split).
Read-only over the corpus; writes only new files. Zero fingerprint churn
(bench/ and data/ are outside the ratchet's fingerprint roots).
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.floor_plan.builder import V11_PLAN_SYSTEM  # the real production prompt

CORPUS_FILES = [
    ROOT / "data" / "flywheel" / "corpus.jsonl",        # full-pipeline lessons
    ROOT / "data" / "flywheel" / "corpus-bench.jsonl",  # bench-grade plan lessons
]
OUT_DIR = ROOT / "data" / "flywheel" / "training"
HOLDOUT_FRACTION = 0.2  # kept aside so eval is never on training data

# Fields the solver overwrites — training the model on these teaches values
# that get thrown away. See TRAINING-REAIM-2026-07-28.md Owner C.
SOLVER_OWNED_ITEM_FIELDS = frozenset({"x", "z", "rotation_deg"})


def _strip_solver_owned_fields(plan: dict) -> dict:
    """Remove x/z/rotation_deg from items — the solver owns placement.

    The model should learn relation-kind selection (which determines legality),
    not coordinate prediction (which the solver immediately overwrites).
    """
    cleaned = dict(plan)
    items = cleaned.get("items")
    if isinstance(items, list):
        cleaned["items"] = [
            {k: v for k, v in item.items() if k not in SOLVER_OWNED_ITEM_FIELDS}
            if isinstance(item, dict) else item
            for item in items
        ]
    return cleaned


def _corpus_lines():
    for path in CORPUS_FILES:
        if path.exists():
            yield from path.read_text(encoding="utf-8").splitlines()


def main() -> int:
    rows = []
    for line in _corpus_lines():
        if not line.strip():
            continue
        d = json.loads(line)
        verdict = (d.get("per_gate_verdicts") or {}).get("plan")
        status = verdict.get("status") if isinstance(verdict, dict) else verdict
        if status not in ("passed", "pass"):
            continue
        description = (d.get("description") or "").strip()
        plan = d.get("plan")
        if not description or not isinstance(plan, (dict, list)):
            continue
        rows.append({
            "messages": [
                {"role": "system", "content": V11_PLAN_SYSTEM},
                {"role": "user", "content": description},
                {"role": "assistant", "content": json.dumps(
                    _strip_solver_owned_fields(plan), separators=(",", ":")
                )},
            ],
            "meta": {
                "record_id": d.get("record_id"),
                "model_lane": d.get("model_lane"),
                "pipeline_era": d.get("pipeline_era", "pre-inversion"),
                "grade": d.get("qualification_mode", "full-pipeline"),
            },
        })

    if not rows:
        print("NO accepted plans found - nothing to train on. Stopping honestly.")
        return 1

    random.Random(13).shuffle(rows)
    cut = max(1, int(len(rows) * HOLDOUT_FRACTION))
    holdout, train = rows[:cut], rows[cut:]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    train_path = OUT_DIR / "probe-v1.jsonl"
    hold_path = OUT_DIR / "probe-v1-holdout.jsonl"
    train_path.write_text("\n".join(json.dumps(r) for r in train) + "\n", encoding="utf-8")
    hold_path.write_text("\n".join(json.dumps(r) for r in holdout) + "\n", encoding="utf-8")
    (OUT_DIR / f"probe-v1-stats-{stamp}.json").write_text(json.dumps({
        "built": stamp, "train": len(train), "holdout": len(holdout),
        "source_records": len(rows), "system_prompt_chars": len(V11_PLAN_SYSTEM),
    }, indent=1), encoding="utf-8")
    print(f"TRAINING SET: {len(train)} train / {len(holdout)} holdout "
          f"-> {train_path}")
    print("Honest note: this is a SMALL probe set. The goal is a working "
          "training loop and a baseline delta, not a miracle model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
