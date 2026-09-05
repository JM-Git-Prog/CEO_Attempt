"""Prove the event log actually captures a turn. Run me through RUN-VERIFY-EVENT-LOG.bat.

Two checks, in order:

  1. SELFTEST  - import the two changed modules and write one probe row. This proves
                 the code is syntactically sound, the log path is writable, and the
                 folder gets created. It does NOT need the V17 server to be running.

  2. REAL TURN - look for a row written by an actual /api/v17/say call (stage="say")
                 and confirm the fields that are UNRECOVERABLE if not captured at the
                 moment are present: the exact rendered prompt, the model digest, the
                 router's candidate list, and the transport-vs-bad-answer split.

If check 2 says NO REAL TURNS YET: restart V17 (LIVING-ROOM.bat), type one sentence
into the left pane, then run this again. The server pins reload=False on purpose, so
a running V17 keeps the OLD code in memory until it is restarted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

print("=" * 72)
print("EVENT LOG VERIFICATION")
print("=" * 72)

try:
    from src.unified_pipeline import event_log, model_router
except Exception as exc:
    print(f"\nFAIL - could not import the changed modules: {type(exc).__name__}: {exc}")
    print("       (this means the edit broke something - nothing was logged)")
    raise SystemExit(1)

print(f"\nlog file: {event_log.log_path()}")

# ---------------------------------------------------------------- check 1
probe = event_log.append_event(
    stage="selftest",
    note="written by VERIFY-EVENT-LOG.py",
    outcome={"ok": True, "error": None},
)
if not probe:
    print("\nFAIL - append_event returned None. The log could not be written.")
    raise SystemExit(1)
print(f"\n[1/2] SELFTEST  PASS - wrote probe row {probe}")

path = event_log.log_path()
try:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
except OSError as exc:
    print(f"\nFAIL - wrote the row but could not read the file back: {exc}")
    raise SystemExit(1)

rows = []
bad = 0
for ln in lines:
    try:
        rows.append(json.loads(ln))
    except json.JSONDecodeError:
        bad += 1

print(f"      {len(rows)} row(s) in the log" + (f", {bad} unparseable" if bad else ""))

# ---------------------------------------------------------------- check 2
says = [r for r in rows if r.get("stage") == "say"]
if not says:
    print("\n[2/2] REAL TURN  NO REAL TURNS YET")
    print("      Restart V17 with LIVING-ROOM.bat, type one sentence in the left pane,")
    print("      then run this again. Until the restart, V17 is still running the old")
    print("      code in memory and nothing will be captured.")
    print("\n" + "=" * 72)
    print("RESULT: the log works. Waiting on one real sentence to prove the wiring.")
    print("=" * 72)
    raise SystemExit(0)

last = says[-1]
inp = last.get("input") or {}
model = last.get("model") or {}
router = last.get("router") or {}
outcome = last.get("outcome") or {}

checks = [
    ("exact prompt sent (prompt_rendered)", bool(inp.get("prompt_rendered"))),
    ("prompt fingerprint (prompt_sha)", bool(inp.get("prompt_sha"))),
    ("which model answered", bool(model.get("route"))),
    ("model digest (which weights)", bool(model.get("digest"))),
    ("router candidate lane", bool(router.get("candidates"))),
    ("chosen model + rank", router.get("chosen") is not None and router.get("rank") is not None),
    ("transport-vs-bad-answer split", "error" in outcome),
    ("latency (ms)", outcome.get("ms") is not None),
    ("the classified result", (last.get("result") or {}).get("kind") is not None),
]

print(f"\n[2/2] REAL TURN  found {len(says)} captured turn(s). Newest:")
print(f"      said: {str(inp.get('message'))[:60]!r}")
print(f"      kind: {(last.get('result') or {}).get('kind')}   "
      f"model: {model.get('route')}   ms: {outcome.get('ms')}")
print()

failed = 0
for label, ok in checks:
    print(f"      {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        failed += 1

# the misses are the whole point of John's 2026-09-04 decision
misses = [r for r in says if not ((r.get("outcome") or {}).get("ok", True))]
print(f"\n      captured turns that FAILED (the misses, kept on purpose): {len(misses)}")

print("\n" + "=" * 72)
if failed:
    print(f"RESULT: {failed} field(s) missing. Those are unrecoverable - fix before relying on it.")
    print("=" * 72)
    raise SystemExit(1)
print("RESULT: PASS. Every unrecoverable field is being captured.")
print("=" * 72)
