"""One-command self-test of the whole flywheel chain.

Why this exists: Claude works from a Linux sandbox with no GPU, no ollama, no
Windows, and no training venv, so it CANNOT run this loop. Every fix therefore
cost a round trip - patch, you click, one bug surfaces, repeat. This script
moves the testing to the machine that can actually run it: one click exercises
every stage and reports ALL failures at once, in a file Claude can read.

Every check here corresponds to something that has actually broken:
  1  imports              - a syntax/import error anywhere kills the loop silently
  2  training interpreter - wrong python = 7 hours of ModuleNotFoundError (07-25)
  3  relation reconciler  - 385/558 generations died on one schema rule (07-26)
  4  repair wiring        - the free geometry repair must fire inside _one_plan
  5  corpus round-trip    - rows must reach the corpus with their tags intact
  6  stuck detector       - a stale progress file caused a kill/restart loop (07-26)
  7  dashboard            - must generate from the real files without throwing
  8  live end-to-end      - (--live) one real plan, real model, real validator

Usage:
  python bench\\selftest.py           fast offline checks (seconds)
  python bench\\selftest.py --live    also does one real generation (~1-2 min)
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BENCH))

REPORT = BENCH / "selftest-report.json"
PY_TRAIN = BENCH / "venv-train" / "Scripts" / "python.exe"

results: list[dict] = []


def check(name: str):
    """Run one check. A check returns (ok, detail) or raises."""
    def wrap(fn):
        started = time.time()
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        results.append({"check": name, "ok": bool(ok), "detail": str(detail)[:400],
                        "seconds": round(time.time() - started, 1)})
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {name}: {detail}", flush=True)
        return ok
    return wrap


# ---------------------------------------------------------------- 1. imports
def _imports():
    import src.floor_plan.builder as b            # noqa: F401
    import src.floor_plan.repair as r             # noqa: F401
    import src.floor_plan.validator as v          # noqa: F401
    import plan_bench                             # noqa: F401
    import supervisor                             # noqa: F401
    import dashboard_gen                          # noqa: F401
    import ingest_bench_to_corpus                 # noqa: F401
    return True, "every module the loop needs imports cleanly"


# ------------------------------------------------- 2. training interpreter
def _training_interpreter():
    if not PY_TRAIN.exists():
        return False, f"training python missing at {PY_TRAIN}"
    probe = subprocess.run(
        [str(PY_TRAIN), "-c", "import torch, datasets, transformers; "
         "print(torch.__version__, torch.cuda.is_available())"],
        capture_output=True, text=True, timeout=180)
    if probe.returncode != 0:
        return False, "training venv cannot import torch/datasets: " + \
            (probe.stderr.strip().splitlines() or ["?"])[-1]
    ver, cuda = (probe.stdout.strip().split() + ["?", "?"])[:2]
    if cuda.lower() != "true":
        return False, f"torch {ver} present but CUDA NOT available - training would run on CPU"
    return True, f"torch {ver}, CUDA available"


# ------------------------------------------------- 3. relation reconciler
def _reconciler():
    from src.floor_plan.builder import _reconcile_v11_relations
    from src.floor_plan.models import FloorPlanV11

    base = None
    for line in (ROOT / "data" / "flywheel" / "corpus-bench.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            plan = json.loads(line).get("plan")
        except Exception:
            continue
        if isinstance(plan, dict) and plan.get("schema_version") == "floor-plan/v11" \
                and len(plan.get("items", [])) >= 3:
            try:
                FloorPlanV11.model_validate(plan)
                base = plan
                break
            except Exception:
                continue
    if base is None:
        return False, "no valid v11 plan in the corpus to test against"

    def fixes(mutate):
        p = copy.deepcopy(base)
        mutate(p)
        fixed, _ = _reconcile_v11_relations(p)
        try:
            FloorPlanV11.model_validate(fixed)
            return True
        except Exception:
            return False

    ghost = {"subject_id": "ghost_x", "kind": "centered",
             "parameters_m": {}, "relaxable": True}
    cases = {
        "orphan": lambda p: p["relationships"].append(dict(ghost)),
        "duplicate": lambda p: p["relationships"].append(dict(p["relationships"][0])),
        "missing": lambda p: p["relationships"].pop(0),
    }
    failed = [n for n, m in cases.items() if not fixes(m)]
    untouched, stats = _reconcile_v11_relations(copy.deepcopy(base))
    if untouched["relationships"] != base["relationships"] or stats:
        failed.append("healthy-plan-was-modified")
    if failed:
        return False, "reconciler failed: " + ", ".join(failed)
    return True, "orphan/duplicate/missing all repaired; healthy plan untouched"


# ------------------------------------------- 3b. surviving normalization
def _normalize_survival():
    """normalize_floor_plan drops surface-like items and rewrites ids AFTER
    the first validate. Relations (and the camera) must follow, or a plan the
    model got right dies on the second validate - the real source of most
    'one relation per item' failures on 2026-07-26."""
    import copy

    from src.floor_plan.builder import (_reconcile_v11_relations,
                                        _remap_relations_after_normalize)
    from src.floor_plan.models import FloorPlanV11
    from src.floor_plan.solver import solve_explicit_plan
    from src.floor_plan.validator import normalize_floor_plan

    base = None
    for line in (ROOT / "data" / "flywheel" / "corpus-bench.jsonl").read_text(
            encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            plan = json.loads(line).get("plan")
        except Exception:
            continue
        if isinstance(plan, dict) and plan.get("schema_version") == "floor-plan/v11" \
                and len(plan.get("items", [])) >= 4:
            try:
                FloorPlanV11.model_validate(plan)
                base = plan
                break
            except Exception:
                continue
    if base is None:
        return True, "skipped - no 4+ item v11 plan in the corpus"

    def survives(payload):
        plan = FloorPlanV11.model_validate(payload)
        solved = solve_explicit_plan(plan)
        pre = [(i.id, i.name) for i in solved.items]
        normalized, _, _ = normalize_floor_plan(
            solved, "", strict=False, infer_text_placement=False)
        fixed, stats = _remap_relations_after_normalize(
            pre, normalized.model_dump(mode="json"))
        fixed, more = _reconcile_v11_relations(fixed)
        FloorPlanV11.model_validate(fixed)          # raises if still broken
        return {**stats, **more}

    survives(copy.deepcopy(base))                   # untouched plan

    renamed = copy.deepcopy(base)
    old = renamed["items"][1]["id"]
    renamed["items"][1]["id"] = "Weird ID!! 2"
    for relation in renamed["relationships"]:
        if relation["subject_id"] == old:
            relation["subject_id"] = "Weird ID!! 2"
        if relation.get("target_id") == old:
            relation["target_id"] = "Weird ID!! 2"
    if (renamed.get("camera_intent") or {}).get("target_id") == old:
        renamed["camera_intent"]["target_id"] = "Weird ID!! 2"
    stats = survives(renamed)
    if not stats.get("relations_followed_rename"):
        return False, "a renamed item's relation did not follow it"
    if stats.get("synthesized_relations"):
        return False, "a pure rename invented placements instead of following them"

    dropped = copy.deepcopy(base)
    gone = dropped["items"][0]["id"]
    dropped["items"][0]["name"] = "Oak Floor"
    dropped["items"][0]["id"] = "oak_floor"
    for relation in dropped["relationships"]:
        if relation["subject_id"] == gone:
            relation["subject_id"] = "oak_floor"
        if relation.get("target_id") == gone:
            relation["target_id"] = "oak_floor"
    if (dropped.get("camera_intent") or {}).get("target_id") == gone:
        dropped["camera_intent"]["target_id"] = "oak_floor"
    survives(dropped)

    return True, "renames followed exactly; dropped items and camera recovered"


# ------------------------------------------------------ 3c. JSON repair
def _json_repair():
    """Local models emit JSON that is right except for punctuation. Each
    repair must be unambiguous AND must never alter text inside strings."""
    from src.orchestrator.llm import _repair_json_text

    good = {"name": "Diner", "room": {"width": 6, "depth": 4},
            "items": [{"id": "a", "name": "Counter"}, {"id": "b", "name": "Stool"}],
            "note": 'a } and a { and a // inside a string, plus "escaped" quotes'}
    canon = json.dumps(good, indent=2)

    cases = {
        "missing comma after }": canon.replace("},\n    {", "}\n    {"),
        "trailing comma": canon.replace("}\n  ],", "},\n  ],"),
        "line comment": canon.replace('{\n  "name"', '{\n  // plan\n  "name"'),
        "block comment": canon.replace('{\n  "name"', '{\n  /* plan */\n  "name"'),
        "truncated": canon[:-40],
        "already valid": canon,
    }
    broken_names = []
    for label, text in cases.items():
        try:
            parsed = json.loads(_repair_json_text(text))
        except Exception:
            broken_names.append(label)
            continue
        if label != "truncated" and parsed.get("note") != good["note"]:
            broken_names.append(label + " (content altered)")
    if broken_names:
        return False, "JSON repair failed on: " + ", ".join(broken_names)

    tricky = '{"a": "}{ // not a comment, [ unbalanced", "b": 1}'
    if json.loads(_repair_json_text(tricky))["a"] != "}{ // not a comment, [ unbalanced":
        return False, "a repair reached inside a string literal - unsafe"
    return True, "punctuation defects repaired; string contents untouched"


# --------------------------------------------- 3d. backend errors surface
def _backend_errors_surface():
    """A failing model backend must raise its real error, not quietly hand
    back mock output. That silent fallback made 50 ollama failures look like
    "the model returned invalid JSON" on 2026-07-26."""
    import asyncio

    import src.orchestrator.llm as llm

    original = llm._call_ollama
    original_url = llm.OLLAMA_URL

    async def boom(*a, **kw):
        raise llm.LLMError("simulated backend outage")

    try:
        llm._call_ollama = boom
        llm.OLLAMA_URL = llm.OLLAMA_URL or "http://127.0.0.1:11434"
        os.environ.pop("ALLOW_MOCK_LLM", None)
        try:
            asyncio.run(llm.generate("sys", "user", "llama3.1", json_mode=True))
        except llm.LLMError as exc:
            if "simulated backend outage" not in str(exc):
                return False, f"raised, but lost the real cause: {exc}"
            return True, "a backend failure now raises with its real cause attached"
        return False, "backend failure did NOT raise - mock output is still being substituted"
    finally:
        llm._call_ollama = original
        llm.OLLAMA_URL = original_url


# ------------------------------------------ 3e. empty 200 responses raise
def _empty_response_raises():
    """Ollama answers 200 with an empty message far more often than it errors.
    That is not an exception, so it used to surface as 'invalid JSON' with the
    real reason discarded. It must raise, carrying ollama's own counters."""
    import asyncio

    import src.orchestrator.llm as llm

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"message": {"content": "   "}, "done_reason": "length",
                    "prompt_eval_count": 16384, "eval_count": 0,
                    "total_duration": 5_000_000_000}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            return _Resp()

    original = llm.httpx.AsyncClient
    try:
        llm.httpx.AsyncClient = lambda *a, **kw: _Client()
        try:
            asyncio.run(llm._call_ollama("sys", "user", "llama3.1", json_mode=True))
        except llm.LLMError as exc:
            text = str(exc)
            for needed in ("EMPTY message", "done_reason", "prompt_eval_count", "num_ctx"):
                if needed not in text:
                    return False, f"raised but without {needed}: {text[:120]}"
            return True, "an empty 200 raises, carrying done_reason and the context counters"
        return False, "an empty 200 response did NOT raise - it would look like bad JSON again"
    finally:
        llm.httpx.AsyncClient = original


# ------------------------------------------------------- 4. repair wiring
def _repair_wiring():
    import asyncio
    import glob
    import plan_bench
    import src.floor_plan.builder as builder
    from src.floor_plan.models import FloorPlanV11
    from src.floor_plan.repair import repair_near_miss
    from src.floor_plan.validator import validate_floor_plan

    rescuable = None
    for rf in sorted(glob.glob(str(BENCH / "results-*.json")), reverse=True):
        try:
            doc = json.loads(Path(rf).read_text(encoding="utf-8"))
        except Exception:
            continue
        for lane in (doc.get("lanes") or {}).values():
            for row in lane.get("rows") or []:
                if row.get("status") == "legal" or not isinstance(row.get("plan"), dict):
                    continue
                if not (row.get("blockers") or []):
                    continue
                plan = FloorPlanV11.model_validate(row["plan"])
                before = validate_floor_plan(plan, tolerance="strict")
                if before.valid:
                    continue
                attempt = repair_near_miss(plan, before, max_nudge_m=plan_bench.MAX_NUDGE_M)
                if validate_floor_plan(attempt.plan, tolerance="strict").valid:
                    rescuable = row["plan"]
                    break
            if rescuable:
                break
        if rescuable:
            break
    if rescuable is None:
        return True, "skipped - no archived rescuable failure available to replay"

    original = builder.build_floor_plan

    async def stub(description, concept, **kw):
        plan = FloorPlanV11.model_validate(rescuable)
        warnings: list[str] = []
        return plan, warnings, validate_floor_plan(plan, warnings, tolerance="strict")

    try:
        builder.build_floor_plan = stub
        row = asyncio.run(plan_bench._one_plan("selftest room", 60))
    finally:
        builder.build_floor_plan = original

    if row.get("status") != "legal" or not row.get("repaired_by_math"):
        return False, f"repair did not fire inside _one_plan (status={row.get('status')})"
    if not row.get("blockers_before_repair"):
        return False, "repaired row is missing its blockers_before_repair tag"
    return True, (f"a failing plan was rescued in _one_plan "
                  f"({len(row.get('repairs_applied') or [])} nudges) and tagged")


# --------------------------------------------------- 5. corpus round-trip
def _corpus_roundtrip():
    import ingest_bench_to_corpus as ing

    # Bank into a THROWAWAY corpus file, never the real one. The first version
    # of this check appended its synthetic row straight into corpus-bench.jsonl
    # - a test must not put fake rows in the training data it is testing.
    real_out = ing.OUT
    ing.OUT = BENCH / "corpus-SELFTEST-TEMP.jsonl"
    ing.OUT.unlink(missing_ok=True)

    fake_results = BENCH / "results-SELFTEST-TEMP.json"
    marker = f"selftest-{int(time.time())}"
    fake_results.write_text(json.dumps({
        "started": marker, "prompts": 1,
        "lanes": {"selftest-lane": {"legal": 1, "total": 1, "legal_rate": 1.0, "rows": [{
            "status": "legal", "blockers": [], "advisories": [], "warnings": 0,
            "items": 1, "seconds": 0.1, "prompt_id": "p001",
            "plan": {"schema_version": "floor-plan/v11", "selftest": marker},
            "repaired_by_math": True, "repairs_applied": ["selftest nudge"],
            "blockers_before_repair": ["out_of_bounds"],
            "synthesized_relations": 2,
        }]}},
    }), encoding="utf-8")
    try:
        ing.main()
        banked = None
        for line in ing.OUT.read_text(encoding="utf-8").splitlines():
            if marker in line:
                banked = json.loads(line)
        if banked is None:
            return False, "the synthetic row never reached the corpus"
        for field, want in (("repaired_by_math", True),
                            ("synthesized_relations", 2)):
            if banked.get(field) != want:
                return False, f"corpus lost the {field} tag (got {banked.get(field)!r})"
        if banked.get("per_gate_verdicts", {}).get("plan") != "passed":
            return False, "a legal row was not banked as passed"
        return True, "row reached the corpus with repaired_by_math + synthesized_relations intact"
    finally:
        fake_results.unlink(missing_ok=True)
        ing.OUT.unlink(missing_ok=True)
        ing.OUT = real_out


# ------------------------------------------------------ 6. stuck detector
def _stuck_detector():
    import supervisor

    progress = supervisor.PROGRESS
    if not progress.exists():
        return True, "skipped - no training-progress.json on disk yet"
    data = json.loads(progress.read_text(encoding="utf-8"))
    updated = data.get("updated", 0)
    age_h = (time.time() - updated) / 3600

    if supervisor.flywheel_is_stuck(time.time()):
        return False, ("a flywheel started NOW reads as stuck - this is the "
                       "kill/restart loop; the stale-progress guard is not working")
    if data.get("stage") in ("training", "loading_model", "saving_gguf") and age_h > 1:
        if not supervisor.flywheel_is_stuck(updated - 1):
            return False, "a genuinely frozen flywheel would NOT be detected - guard too broad"
        return True, (f"stale progress ({age_h:.1f}h old) correctly ignored, "
                      "real freezes still caught")
    return True, f"progress file is current ({age_h:.1f}h old), nothing to ignore"


# ----------------------------------------------------------- 7. dashboard
def _dashboard():
    import dashboard_gen

    dashboard_gen.build()
    html = dashboard_gen.OUT.read_text(encoding="utf-8")
    if "Why rows get thrown away" not in html:
        return False, "dashboard generated but is missing the failure-census section"
    return True, f"{dashboard_gen.OUT.name} generated ({len(html)} bytes)"


# ------------------------------------------------------- 8. live end-to-end
def _live():
    out = BENCH / "results-SELFTEST-LIVE.json"
    out.unlink(missing_ok=True)
    proc = subprocess.run(
        [sys.executable, str(BENCH / "plan_bench.py"),
         "--lanes", "llama3.1", "--prompts", "1", "--timeout", "180",
         "--out", str(out)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    if not out.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, "plan_bench produced no results file: " + (tail[-1] if tail else "?")
    doc = json.loads(out.read_text(encoding="utf-8"))
    rows = [r for lane in (doc.get("lanes") or {}).values() for r in lane.get("rows") or []]
    out.unlink(missing_ok=True)
    if not rows:
        return False, "plan_bench ran but produced no rows"
    row = rows[0]
    status = row.get("status")
    extra = []
    if row.get("repaired_by_math"):
        extra.append("geometry-repaired")
    if row.get("synthesized_relations"):
        extra.append(f"{row['synthesized_relations']} relations synthesized")
    note = f"real generation -> {status}"
    if extra:
        note += " (" + ", ".join(extra) + ")"
    if status == "error":
        return False, note + f": {row.get('error', '')[:160]}"
    # blocked is a legitimate outcome for one prompt - the CHAIN worked
    return True, note


def main() -> int:
    live = "--live" in sys.argv
    print("Flywheel self-test\n" + "=" * 60, flush=True)
    check("1 imports")(_imports)
    check("2 training interpreter")(_training_interpreter)
    check("3 relation reconciler")(_reconciler)
    check("3b surviving normalization")(_normalize_survival)
    check("3c JSON repair")(_json_repair)
    check("3d backend errors surface")(_backend_errors_surface)
    check("3e empty 200 raises")(_empty_response_raises)
    check("4 geometry repair wiring")(_repair_wiring)
    check("5 corpus round-trip")(_corpus_roundtrip)
    check("6 stuck detector")(_stuck_detector)
    check("7 dashboard")(_dashboard)
    if live:
        check("8 live end-to-end")(_live)
    else:
        print("  [skip] 8 live end-to-end: pass --live to run one real generation",
              flush=True)

    failed = [r for r in results if not r["ok"]]
    REPORT.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "live": live,
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "checks": results,
    }, indent=2), encoding="utf-8")

    print("=" * 60)
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed"
          f"   ->  {REPORT.name}", flush=True)
    for r in failed:
        print(f"   FAILED: {r['check']} - {r['detail']}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
