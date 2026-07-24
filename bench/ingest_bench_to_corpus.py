"""Bank bench results as training corpus records.

Writes to data/flywheel/corpus-bench.jsonl — a SEPARATE append-only file from
the extractor's corpus.jsonl, so two writers never touch one file (the
site-log lesson). Training prep reads both. Records are era- and mode-tagged
so nothing bench-grade can ever masquerade as full-pipeline evidence.

Dedup: record_id = sha256(results-file | lane | prompt_id) — re-running the
ingester is always safe.
"""
from __future__ import annotations

import glob
import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "flywheel" / "corpus-bench.jsonl"
PROMPTS = ROOT / "data" / "flywheel" / "prompt-set-v1.json"


def prompt_texts() -> dict:
    doc = json.loads(PROMPTS.read_text(encoding="utf-8"))
    raw = doc.get("prompts") if isinstance(doc, dict) else doc
    out = {}
    for i, p in enumerate(raw):
        if isinstance(p, dict):
            out[p.get("id", f"p{i+1:03d}")] = p.get("prompt") or p.get("description") or p.get("text", "")
        else:
            out[f"p{i+1:03d}"] = str(p)
    return out


def existing_ids() -> set:
    ids = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                ids.add(json.loads(line).get("record_id"))
            except Exception:
                continue
    return ids


def main() -> int:
    texts = prompt_texts()
    seen = existing_ids()
    added = skipped = no_plan = 0
    buf = []
    for rf in sorted(glob.glob(str(ROOT / "bench" / "results-*.json"))):
        try:
            doc = json.loads(Path(rf).read_text(encoding="utf-8"))
        except Exception:
            continue
        for lane, ld in (doc.get("lanes") or {}).items():
            for row in ld.get("rows") or []:
                pid = row.get("prompt_id", "?")
                rid = hashlib.sha256(f"{Path(rf).name}|{lane}|{pid}".encode()).hexdigest()[:24]
                if rid in seen:
                    skipped += 1
                    continue
                if not isinstance(row.get("plan"), (dict, list)):
                    no_plan += 1  # error/timeout rows carry no plan - stats only
                    continue
                legal = row.get("status") == "legal"
                buf.append(json.dumps({
                    "schema_version": "flywheel-corpus/bench-v1",
                    "record_id": rid,
                    "description": texts.get(pid, ""),
                    "plan": row["plan"],
                    "per_gate_verdicts": {"plan": "passed" if legal else "failed"},
                    "failure_signatures": [f"plan/validator/{c}" for c in row.get("blockers", [])],
                    "model_lane": lane,
                    "qualification_mode": "bench",
                    "pipeline_era": "pre-inversion",
                    "timestamps": {"extracted_at": time.strftime("%Y-%m-%dT%H:%M:%S")},
                    "source_results_file": Path(rf).name,
                }, separators=(",", ":")))
                seen.add(rid)
                added += 1
    if buf:
        with OUT.open("a", encoding="utf-8") as f:
            f.write("\n".join(buf) + "\n")
    print(f"ingest: +{added} records | {skipped} already banked | {no_plan} plan-less rows skipped")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
