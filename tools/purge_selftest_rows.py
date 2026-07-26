"""Remove rows banked by an early, buggy version of bench/selftest.py.

Only touches rows whose model_lane is exactly "selftest-lane" - the synthetic
lane name the test used, which no real bench lane ever uses. Backs the corpus
up first and verifies the row count moved by exactly the expected amount
before replacing anything; anything unexpected aborts with the original file
untouched.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "flywheel" / "corpus-bench.jsonl"
FAKE_LANE = "selftest-lane"


def main() -> int:
    if not CORPUS.exists():
        print(f"corpus not found: {CORPUS}")
        return 1

    lines = CORPUS.read_text(encoding="utf-8").splitlines()
    keep, removed = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            keep.append(line)  # unparseable: never silently drop someone's data
            continue
        if row.get("model_lane") == FAKE_LANE:
            removed += 1
            continue
        keep.append(line)

    print(f"rows before : {len([l for l in lines if l.strip()])}")
    print(f"to remove   : {removed} (model_lane == {FAKE_LANE!r})")
    print(f"rows after  : {len(keep)}")

    if removed == 0:
        print("nothing to do - corpus is already clean.")
        return 0

    if len([l for l in lines if l.strip()]) - removed != len(keep):
        print("ABORT: arithmetic does not line up - refusing to write.")
        return 1

    backup = CORPUS.with_name(
        f"corpus-bench.BEFORE-SELFTEST-PURGE-{time.strftime('%Y%m%dT%H%M%S')}.jsonl")
    shutil.copy2(CORPUS, backup)
    print(f"backup      : {backup.name}")

    CORPUS.write_text("\n".join(keep) + "\n", encoding="utf-8")

    check = [l for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(check) != len(keep):
        print("ABORT: re-read does not match what was written - restoring backup.")
        shutil.copy2(backup, CORPUS)
        return 1
    print(f"verified    : {len(check)} rows on disk, 0 self-test rows remain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
