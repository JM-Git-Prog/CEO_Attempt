"""sim-player/mechanic.py — the Sam Loop mechanic.

Reads one round's `analysis.json` defects, asks a coder model (`common.ollama_chat`, lane
"mechanic") for a small patch inside a strict JSON schema, and only lets it touch disk through a
fixed chain of guards — protect-the-boundary:
  1. ALLOWLIST   edit files only under src/web/**/*.py, src/web/static/**/*.js or
                 src/unified_pipeline/**/*.py; new_test only as tests/test_[a-z0-9_]+.py, not
                 already existing. run.py, *.bat, CLAUDE.md, anything named sim-player, `..` and
                 absolute paths are always rejected.
  2. HUMAN-TOUCH a file modified in the last 10 minutes is left alone — someone may be editing it.
  3. EXACT-MATCH `old` must appear exactly once in the file's current text, verbatim.
  4. BACKUPS     every target copied to patches/<attempt>/ before any write; a manifest records
                 before/after sha256; writes are atomic (.tmp + os.replace).
  5. THE GATE    `pytest tests -q -p no:cacheprovider --ignore=tests/e2e -rf` runs before and
                 after; the patch survives only if it adds no new failing test id and
                 `import src.web.app` (when present) still succeeds. Anything less reverts.
  6. THE LEDGER  every attempt — pass, reject, or revert — is appended to <round_dir>/patches.jsonl
                 and <runs_dir>/mechanic-ledger.jsonl.
A rejected proposal is never partially applied; a failed gate is always fully reverted. Backend
(transport) errors are never a verdict — three in a row abort the round instead of consuming it.
stdlib only. `--selftest` exercises every guard against a from-scratch temp repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

GATE_TIMEOUT_S = 600.0
IMPORT_CHECK_TIMEOUT_S = 120.0
HUMAN_TOUCH_WINDOW_S = 10 * 60
MAX_EXCERPT_CHARS = 600
MAX_RAW_CHARS = 4000
TOP_DEFECTS = 5
ROUTE_WINDOW_LINES = 60  # +/- this many lines around a route match, never the whole file

_ALLOW_EDIT_TREES = (("src/web/", ".py"), ("src/web/static/", ".js"), ("src/unified_pipeline/", ".py"))
_NEW_TEST_RE = re.compile(r"^tests/test_[a-z0-9_]+\.py$")
_BANNED_BASENAMES = {"run.py", "claude.md"}

SYSTEM_PROMPT = (
    "You are the Sam Loop mechanic: a coder model asked for ONE small patch that could fix a defect "
    "found while a simulated 10-year-old played The Living Room, a FastAPI app. Rules: make the "
    "minimal change that could plausibly fix it; never propose a file outside the allowlist (edits "
    "only under src/web/**/*.py, src/web/static/**/*.js or src/unified_pipeline/**/*.py; a new test "
    "only as tests/test_<name>.py); `old` must be copied verbatim from the source you were given and "
    "must occur exactly once in that file; never rename or change the signature of a public function; "
    "add a new test when you fix behaviour, so the fix stays pinned; answer with JSON only, matching "
    "the given schema exactly, nothing before or after it."
)

_EDIT_ITEM_SCHEMA = {"type": "object",
                     "properties": {"file": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
                     "required": ["file", "old", "new"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"}, "confidence": {"type": "number"},
        "edits": {"type": "array", "minItems": 1, "maxItems": 4, "items": _EDIT_ITEM_SCHEMA},
        "new_test": {"type": ["object", "null"], "properties": {"file": {"type": "string"}, "content": {"type": "string"}}},
        "restart_needed": {"type": "boolean"},
    },
    "required": ["diagnosis", "confidence", "edits", "restart_needed"],
}

# ---------------------------------------------------------------------------- small file helpers

def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

# ---------------------------------------------------------------------------- guards 1-3: validation

def _check_allowlist(rel: str) -> tuple[bool, str]:
    """Guard 1: is `rel` a file the mechanic is even allowed to name?"""
    if not isinstance(rel, str) or not rel or rel != rel.strip():
        return False, f"empty or malformed path: {rel!r}"
    norm = rel.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in norm.split("/"):
        return False, f"path escapes the repo: {rel!r}"
    basename = norm.rsplit("/", 1)[-1]
    if basename.lower() in _BANNED_BASENAMES:
        return False, f"{basename} may never be edited"
    if norm.lower().endswith(".bat"):
        return False, f"batch files may never be edited: {rel!r}"
    if "sim-player" in norm.lower():
        return False, f"sim-player is off limits: {rel!r}"
    for prefix, suffix in _ALLOW_EDIT_TREES:
        if norm.startswith(prefix) and norm.endswith(suffix) and len(norm) > len(prefix):
            return True, ""
    return False, f"not under an allowed tree: {rel!r}"

def _check_new_test_path(rel: str, repo: Path) -> tuple[bool, str]:
    norm = rel.replace("\\", "/") if isinstance(rel, str) else rel
    if not isinstance(norm, str) or not _NEW_TEST_RE.match(norm):
        return False, f"new_test.file must match tests/test_[a-z0-9_]+.py: {rel!r}"
    if (repo / norm).exists():
        return False, f"new_test.file already exists: {norm!r}"
    return True, ""

def _check_human_touch(repo: Path, rel: str) -> tuple[bool, str]:
    """Guard 2: leave a file alone if it changed in the last 10 minutes — a person may be editing it."""
    target = repo / rel
    if not target.is_file():
        return False, f"file not found: {rel!r}"
    age_s = time.time() - target.stat().st_mtime
    if age_s < HUMAN_TOUCH_WINDOW_S:
        return False, f"file changed {max(1, round(age_s / 60))} min ago — a person may be editing it"
    return True, ""

def _check_exact_match(repo: Path, rel: str, old: str) -> tuple[bool, str]:
    """Guard 3: `old` must appear exactly once in the file as it stands right now."""
    try:
        text = (repo / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, f"could not read {rel}: {exc}"
    count = text.count(old) if old else 0
    if count != 1:
        return False, f"'old' occurs {count} time(s) in {rel} (need exactly 1)"
    return True, ""

def _validate_shape(p: object) -> tuple[bool, str]:
    if not isinstance(p, dict):
        return False, "proposal is not a JSON object"
    if not isinstance(p.get("diagnosis"), str) or not p["diagnosis"].strip():
        return False, "missing diagnosis"
    if not isinstance(p.get("confidence"), (int, float)):
        return False, "missing/invalid confidence"
    edits = p.get("edits")
    if not isinstance(edits, list) or not (1 <= len(edits) <= 4):
        return False, "edits must be a list of 1-4 items"
    for e in edits:
        if not isinstance(e, dict) or not all(isinstance(e.get(k), str) and e.get(k) != "" for k in ("file", "old", "new")):
            return False, "each edit needs non-empty file/old/new strings"
        if e["old"] == e["new"]:
            return False, "edit's old and new are identical"
    nt = p.get("new_test")
    if nt is not None and (not isinstance(nt, dict) or not isinstance(nt.get("file"), str) or not isinstance(nt.get("content"), str)):
        return False, "new_test must be null or {file, content}"
    if not isinstance(p.get("restart_needed"), bool):
        return False, "missing/invalid restart_needed"
    return True, ""

def _validate_edits(proposal: dict, repo: Path) -> tuple[bool, str]:
    """Guards 1-3 for every edit, then the new test's path — reject the whole proposal on the first miss."""
    for edit in proposal["edits"]:
        rel = edit["file"].replace("\\", "/")
        for ok, why in (_check_allowlist(rel), _check_human_touch(repo, rel), _check_exact_match(repo, rel, edit["old"])):
            if not ok:
                return False, why
    nt = proposal.get("new_test")
    if nt is not None:
        ok, why = _check_new_test_path(nt["file"], repo)
        if not ok:
            return False, why
    return True, ""

# ---------------------------------------------------------------------------- guard 4: apply / revert

def _apply_patch(round_dir: Path, attempt: int, repo: Path, proposal: dict, model: str, diagnosis: str) -> dict:
    """Backs every target up, THEN writes every edit, THEN the new test. Manifest records it all."""
    patch_dir = round_dir / "patches" / str(attempt)
    patch_dir.mkdir(parents=True, exist_ok=True)

    order: list[str] = []
    edits_by_file: dict[str, list[dict]] = {}
    for edit in proposal["edits"]:
        rel = edit["file"].replace("\\", "/")
        edits_by_file.setdefault(rel, [])
        if rel not in order:
            order.append(rel)
        edits_by_file[rel].append(edit)

    files_manifest = []
    for rel in order:
        target = repo / rel
        backup_name = rel.replace("/", "__") + ".before"
        shutil.copy2(target, patch_dir / backup_name)
        files_manifest.append({"path": rel, "before": backup_name, "sha_before": _sha256_file(target), "sha_after": None})

    for meta, rel in zip(files_manifest, order):
        target = repo / rel
        text = target.read_text(encoding="utf-8")
        for edit in edits_by_file[rel]:
            text = text.replace(edit["old"], edit["new"], 1)
        _atomic_write_text(target, text)
        meta["sha_after"] = _sha256_file(target)

    new_test_meta = None
    nt = proposal.get("new_test")
    if nt:
        rel = nt["file"].replace("\\", "/")
        _atomic_write_text(repo / rel, nt["content"])
        new_test_meta = {"file": rel}

    manifest = {"files": files_manifest, "new_test": new_test_meta, "diagnosis": diagnosis,
                "model": model, "at": common.now_iso()}
    _atomic_write_text(patch_dir / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest

def _revert_attempt(repo: Path, patch_dir: Path, manifest: dict) -> None:
    for f in manifest["files"]:
        backup = patch_dir / f["before"]
        if backup.is_file():
            shutil.copy2(backup, repo / f["path"])
    nt = manifest.get("new_test")
    if nt:
        try:
            (repo / nt["file"]).unlink()
        except FileNotFoundError:
            pass

# ---------------------------------------------------------------------------- guard 5: the gate

# The gate runs the PURE suites (no server, no model, no GPU) plus the tests of every file the patch
# touches and the test the patch adds. The whole tests/ tree holds live-service and GPU tests that
# take minutes and fail without their services — a gate that times out is a gate that never passes.
GATE_ALWAYS = ["tests/test_architect_card.py", "tests/test_vision_talk.py", "tests/test_jobsite.py",
               "tests/test_sim_player.py", "tests/test_sim_mechanic.py", "tests/test_sim_analysis.py"]


def _gate_targets(repo: Path, files: list[str] | None = None, new_test: str | None = None) -> list[str]:
    targets = [t for t in GATE_ALWAYS if (repo / t).is_file()]
    for f in files or []:
        stem = Path(f).stem
        cand = f"tests/test_{stem}.py"
        if (repo / cand).is_file() and cand not in targets:
            targets.append(cand)
    if new_test and (repo / new_test).is_file() and new_test not in targets:
        targets.append(new_test)
    if not targets:                                   # the selftest's temp tree: run everything it has
        targets = ["tests"]
    return targets


def gate_available() -> bool:
    """Can this python run pytest at all? (John's Windows python can; a bare VM python cannot.)"""
    try:
        return subprocess.run([sys.executable, "-m", "pytest", "--version"], capture_output=True, text=True, timeout=60).returncode == 0
    except Exception:
        return False


def _run_pytest(repo: Path, targets: list[str] | None = None) -> dict:
    cmd = [sys.executable, "-m", "pytest", *(targets or ["tests"]), "-q", "-p", "no:cacheprovider", "--ignore=tests/e2e", "-rf"]   # no -x: the gate must see EVERY failure, not the first
    try:
        proc = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=GATE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "failures": set(), "backend_err": f"gate timed out after {GATE_TIMEOUT_S:.0f}s"}
    except OSError as exc:
        return {"ok": False, "failures": set(), "backend_err": f"could not start pytest: {exc}"}
    out = proc.stdout + "\n" + proc.stderr
    failures = set(re.findall(r"^(?:FAILED|ERROR)\s+(\S+)", out, flags=re.MULTILINE))
    # fail CLOSED: a run that never reported a result (pytest missing, a collection crash, a usage
    # error) is a backend failure, never "no failures". Absent is not green.
    if not re.search(r"\b\d+ (passed|failed|error|errors)\b|no tests ran", out):
        return {"ok": False, "failures": failures, "backend_err": "pytest did not report a result: " + out.strip()[-300:]}
    if proc.returncode != 0 and not failures:
        return {"ok": False, "failures": failures, "backend_err": "pytest exited " + str(proc.returncode) + " without naming a failure: " + out.strip()[-300:]}
    return {"ok": proc.returncode == 0, "failures": failures, "backend_err": None}

def _import_check(repo: Path) -> tuple[bool, str]:
    if not (repo / "src" / "web" / "app.py").is_file():
        return True, "skipped (no src/web/app.py)"
    try:
        proc = subprocess.run([sys.executable, "-c", "import src.web.app"], cwd=str(repo),
                               capture_output=True, text=True, timeout=IMPORT_CHECK_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"import check timed out after {IMPORT_CHECK_TIMEOUT_S:.0f}s"
    except OSError as exc:
        return False, f"could not start python for import check: {exc}"
    return (True, "") if proc.returncode == 0 else (False, f"import check failed: {proc.stderr[-500:].strip()}")

# ---------------------------------------------------------------------------- prompt building

def _excerpt_rows(transcript: list[dict], defects: list[dict]) -> list[dict]:
    turns: set[int] = set()
    for d in defects:
        t = d.get("turn")
        if isinstance(t, int):
            turns.update(range(t - 2, t + 3))
    rows, seen = [], set()
    for row in transcript:
        key = (row.get("turn"), row.get("phase"))
        if row.get("turn") in turns and key not in seen:
            seen.add(key)
            out = dict(row)
            resp = out.get("response")
            text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False) if resp is not None else ""
            out["response"] = text[:MAX_EXCERPT_CHARS] + ("…" if len(text) > MAX_EXCERPT_CHARS else "")
            rows.append(out)
    return rows

def _grep_route(repo: Path, route: str) -> tuple[str, str] | None:
    """The route's own source, windowed — never the whole repo."""
    web_dir = repo / "src" / "web"
    if not web_dir.is_dir():
        return None
    for path in sorted(web_dir.glob("*.py")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if route in line:
                lo, hi = max(0, i - ROUTE_WINDOW_LINES), min(len(lines), i + ROUTE_WINDOW_LINES)
                return str(path.relative_to(repo)).replace("\\", "/"), "\n".join(lines[lo:hi])
    return None

def _build_messages(analysis: dict, defects: list[dict], excerpts: list[dict], routes: dict) -> list[dict]:
    parts = [
        f"Round: {analysis.get('round', '?')}",
        "Top defects (worst first):", json.dumps(defects, ensure_ascii=False, indent=2),
        "Transcript excerpts (+/-2 turns around each defect; response bodies truncated to 600 chars):",
        json.dumps(excerpts, ensure_ascii=False, indent=2),
    ]
    for route, (relpath, window) in routes.items():
        parts.append(f"Source near route {route!r} ({relpath}):\n```python\n{window}\n```")
    return [{"role": "user", "content": "\n\n".join(parts)}]

def _default_ask(round_dir: Path):
    model = common.pick_lane("mechanic")      # a label; ask_lane proves a rung live before committing

    def ask(system: str, messages: list[dict], schema: dict) -> dict:
        result = common.ask_lane("mechanic", system, messages, schema=schema, temperature=0.2, num_predict=4000,
                                     timeout=180.0, capture_to=round_dir / "calls.jsonl", purpose="mechanic-patch")
        if result["json"] is None:
            raise common.Backend(f"mechanic: reply was not valid JSON: {result['text'][:200]!r}")
        return result["json"]

    return ask, model

# ---------------------------------------------------------------------------- guard 6: the ledger

def _ledger(round_dir: Path, runs_dir: Path, row: dict) -> None:
    common.capture(round_dir / "patches.jsonl", row)
    common.capture(runs_dir / "mechanic-ledger.jsonl", row)

def _ledger_row(at, round_id, attempt, model, diagnosis, files, new_test, gate, why, baseline, after, restart_needed, raw) -> dict:
    return {"at": at, "round": round_id, "attempt": attempt, "model": model, "diagnosis": diagnosis,
            "files": files, "new_test": new_test, "gate": gate, "why": why,
            "baseline_failures": sorted(baseline), "failures_after": sorted(after),
            "restart_needed": restart_needed, "raw_json": raw}

# ---------------------------------------------------------------------------- the public API

def run(round_dir: Path, repo: Path, *, max_attempts: int = 2, dry_run: bool = False, ask=None) -> dict:
    round_dir, repo = Path(round_dir), Path(repo)
    analysis = _load_json(round_dir / "analysis.json")
    defects = (analysis or {}).get("defects") or []
    if not analysis or not defects:
        return {"patched": False, "attempts": 0, "files": [], "restart_needed": False, "why": "no defects", "gate": None}
    if not gate_available():                      # no gate, no patch — the door is the whole point
        why = f"pytest is not installed for {sys.executable} — the gate cannot run, so nothing is patched"
        common.capture(round_dir / "patches.jsonl", {"at": common.now_iso(), "round": round_dir.name, "gate": "unavailable", "why": why})
        return {"patched": False, "attempts": 0, "files": [], "restart_needed": False, "why": why, "gate": "unavailable"}

    transcript = common.read_jsonl(round_dir / "transcript.jsonl")
    top = defects[:TOP_DEFECTS]
    excerpts = _excerpt_rows(transcript, top)
    routes: dict[str, tuple[str, str]] = {}
    for d in top:
        route = d.get("route")
        if route and route not in routes:
            found = _grep_route(repo, route)
            if found:
                routes[route] = found
    messages = _build_messages(analysis, top, excerpts, routes)
    round_id = analysis.get("round", round_dir.name)
    runs_dir = round_dir.parent
    ask, model_name = (ask, getattr(ask, "model_name", "custom-ask")) if ask else _default_ask(round_dir)

    attempt, backend_strikes = 0, 0
    last_why, last_gate = "no attempts made", None
    while attempt < max_attempts:
        attempt += 1
        at = common.now_iso()
        try:
            proposal = ask(SYSTEM_PROMPT, messages, SCHEMA)
        except common.Backend as exc:
            backend_strikes += 1
            _ledger(round_dir, runs_dir, _ledger_row(at, round_id, attempt, model_name, "", [], None,
                                                      "fail", f"backend: {exc}", set(), set(), False, ""))
            if backend_strikes >= 3:
                return {"patched": False, "attempts": attempt, "files": [], "restart_needed": False,
                        "why": "backend", "gate": "fail"}
            attempt -= 1  # a transport failure never spends an attempt
            continue
        backend_strikes = 0

        raw = json.dumps(proposal, ensure_ascii=False)[:MAX_RAW_CHARS] if isinstance(proposal, (dict, list)) else str(proposal)[:MAX_RAW_CHARS]
        ok, why = _validate_shape(proposal)
        if ok:
            ok, why = _validate_edits(proposal, repo)
        diagnosis = proposal.get("diagnosis", "") if isinstance(proposal, dict) else ""
        if not ok:
            _ledger(round_dir, runs_dir, _ledger_row(at, round_id, attempt, model_name, diagnosis, [], None,
                                                      "rejected", why, set(), set(), False, raw))
            last_why, last_gate = why, "rejected"
            continue

        files = [e["file"].replace("\\", "/") for e in proposal["edits"]]
        restart_needed = bool(proposal.get("restart_needed"))
        new_test = proposal.get("new_test")
        new_test_rel = new_test["file"].replace("\\", "/") if new_test else None

        if dry_run:
            _ledger(round_dir, runs_dir, _ledger_row(at, round_id, attempt, model_name, diagnosis, files,
                                                      new_test_rel, "dry-run", "validated only, --dry-run",
                                                      set(), set(), restart_needed, raw))
            return {"patched": False, "attempts": attempt, "files": files, "restart_needed": restart_needed,
                    "why": "dry-run: validated, not applied", "gate": "dry-run"}

        targets = _gate_targets(repo, files, new_test_rel)
        baseline = _run_pytest(repo, targets)
        if baseline["backend_err"]:
            why = f"gate backend error (baseline): {baseline['backend_err']}"
            _ledger(round_dir, runs_dir, _ledger_row(at, round_id, attempt, model_name, diagnosis, files,
                                                      new_test_rel, "fail", why, set(), set(), restart_needed, raw))
            last_why, last_gate = why, "fail"
            continue

        manifest = _apply_patch(round_dir, attempt, repo, proposal, model_name, diagnosis)
        after = _run_pytest(repo, _gate_targets(repo, files, new_test_rel))
        import_ok, import_why = (False, "") if after["backend_err"] else _import_check(repo)

        if after["backend_err"]:
            passed, why = False, f"gate backend error (after): {after['backend_err']}"
        else:
            pytest_pass = after["ok"] or after["failures"].issubset(baseline["failures"])
            new_test_ok = new_test_rel is None or not any(f.startswith(new_test_rel) for f in after["failures"])
            if not pytest_pass:
                passed, why = False, f"new failing test(s): {sorted(after['failures'] - baseline['failures'])}"
            elif not new_test_ok:
                passed, why = False, f"the new test itself failed: {new_test_rel}"
            elif not import_ok:
                passed, why = False, f"import check failed: {import_why}"
            else:
                passed, why = True, ""

        gate = "pass" if passed else "reverted"
        if not passed:
            _revert_attempt(repo, round_dir / "patches" / str(attempt), manifest)
        _ledger(round_dir, runs_dir, _ledger_row(at, round_id, attempt, model_name, diagnosis, files, new_test_rel,
                                                  gate, why, baseline["failures"], after.get("failures", set()),
                                                  restart_needed, raw))
        last_why, last_gate = why, gate
        if passed:
            return {"patched": True, "attempts": attempt, "files": files, "restart_needed": restart_needed,
                    "why": "", "gate": "pass"}

    return {"patched": False, "attempts": attempt, "files": [], "restart_needed": False, "why": last_why, "gate": last_gate}

def revert_all(repo: Path, runs_dir: Path) -> list[str]:
    """Restore every backed-up file across every round under `runs_dir`, newest patch first."""
    repo, runs_dir = Path(repo), Path(runs_dir)
    entries = []
    for round_dir in runs_dir.iterdir() if runs_dir.is_dir() else []:
        patches_dir = round_dir / "patches"
        if not patches_dir.is_dir():
            continue
        for attempt_dir in patches_dir.iterdir():
            manifest = _load_json(attempt_dir / "manifest.json")
            if manifest is not None:
                entries.append((manifest.get("at", ""), attempt_dir, manifest))
    entries.sort(key=lambda e: e[0], reverse=True)

    restored: list[str] = []
    for _, attempt_dir, manifest in entries:
        for f in manifest.get("files", []):
            backup, target = attempt_dir / f["before"], repo / f["path"]
            if not backup.is_file():
                continue
            current = _sha256_file(target)
            if current not in (f.get("sha_before"), f.get("sha_after")):
                common.log(f"revert-all: {f['path']} matches neither before nor after sha — "
                           "someone edited it since; restoring anyway")
            shutil.copy2(backup, target)
            restored.append(f["path"])
        nt = manifest.get("new_test")
        if nt:
            try:
                (repo / nt["file"]).unlink()
                restored.append(nt["file"] + " (test removed)")
            except FileNotFoundError:
                pass
    return restored

# ---------------------------------------------------------------------------- --selftest

_FAKE_ROUTES_PY = '''"""Fake route module for mechanic --selftest: one function with an obvious bug."""

ROUTE = "/api/fake/add"  # POST /api/fake/add

def add_widget(a: int, b: int) -> int:
    return a - b  # BUG: should add

def stable_fn(x: int) -> int:
    return x * 2
'''
_TEST_B_FAKE_PY = "from src.web.fake_routes import add_widget\n\n\ndef test_add_widget():\n    assert add_widget(2, 3) == 5\n"
_TEST_A_STABLE_PY = "from src.web.fake_routes import stable_fn\n\n\ndef test_stable_fn():\n    assert stable_fn(4) == 8\n"
_ST_ANALYSIS = {
    "round": "selftest-round", "counts": {}, "wishes": [],
    "defects": [{"kind": "bad_reply", "turn": 3, "detail": "add_widget(2,3) returned -1, not 5",
                 "route": "/api/fake/add", "excerpt": "2+3=-1"}],
    "gaps_filed": [],
}
_ST_TRANSCRIPT = [
    {"turn": 1, "phase": "look", "i_see": "a yard", "i_type": "", "request": None, "response": "ok", "http_status": 200, "error": None},
    {"turn": 2, "phase": "wish", "i_see": "a yard", "i_type": "add 2 and 3", "request": {"text": "add 2 and 3"}, "response": {"ok": True}, "http_status": 200, "error": None},
    {"turn": 3, "phase": "wish", "i_see": "still a yard", "i_type": "add widget", "request": {"a": 2, "b": 3}, "response": {"result": -1}, "http_status": 200, "error": None},
    {"turn": 4, "phase": "check", "i_see": "wrong number", "i_type": "", "request": None, "response": "nothing happened", "http_status": 200, "error": None},
]

def _st_build_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    for rel, content in (
        ("run.py", "print('do not touch')\n"), ("src/__init__.py", ""), ("src/web/__init__.py", ""),
        ("src/web/fake_routes.py", _FAKE_ROUTES_PY), ("tests/test_a_stable.py", _TEST_A_STABLE_PY),
        ("tests/test_b_fake.py", _TEST_B_FAKE_PY),
    ):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    old = time.time() - 20 * 60  # age everything past the 10-minute human-touch window
    for path in repo.rglob("*.py"):
        os.utime(path, (old, old))
    return repo

def _st_prep(tmp: Path, n: int) -> tuple[Path, Path]:
    sub = tmp / f"t{n}"
    repo = _st_build_repo(sub)
    round_dir = sub / "sim-runs" / f"r{n}"
    round_dir.mkdir(parents=True, exist_ok=True)
    (round_dir / "analysis.json").write_text(json.dumps(_ST_ANALYSIS), encoding="utf-8")
    with open(round_dir / "transcript.jsonl", "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row) + "\n" for row in _ST_TRANSCRIPT)
    return repo, round_dir

def _mk_ask(file: str, old: str, new: str, new_test: dict | None = None):
    def ask(system, messages, schema):
        return {"diagnosis": "selftest patch", "confidence": 0.8, "edits": [{"file": file, "old": old, "new": new}],
                "new_test": new_test, "restart_needed": False}
    return ask

_ST_GOOD_ASK = _mk_ask("src/web/fake_routes.py", "return a - b  # BUG: should add", "return a + b", new_test={
    "file": "tests/test_add_widget_fix.py",
    "content": "from src.web.fake_routes import add_widget\n\n\ndef test_add_widget_fixed():\n    assert add_widget(2, 3) == 5\n",
})
_ST_RUNPY_ASK = _mk_ask("run.py", "print('do not touch')", "print('touched')")
_ST_NONUNIQUE_ASK = _mk_ask("src/web/fake_routes.py", "return", "return ")
_ST_BREAKING_ASK = _mk_ask("src/web/fake_routes.py", "return x * 2", "return x * 3")

def _st_backend_ask(system, messages, schema):
    raise common.Backend("selftest: simulated backend outage")

def selftest() -> bool:
    """Builds a temp repo + fake model per route; trips every guard on known-bad input."""
    results: list[bool] = []
    if not gate_available():
        print(f"[selftest] WARNING: pytest is not installed for {sys.executable} — routes 1 and 4 need the gate and will FAIL here; "
              "run RUN-SAM-SELFTESTS.bat with the Living Room's python instead")

    def check(name: str, cond: bool) -> None:
        results.append(bool(cond))
        print(f"[selftest] {name}: {'ok' if cond else 'FAIL'}")

    with tempfile.TemporaryDirectory(prefix="mechanic-selftest-") as td:
        tmp = Path(td)

        repo1, round1 = _st_prep(tmp, 1)
        out1 = run(round1, repo1, max_attempts=2, ask=_ST_GOOD_ASK)
        ledger1 = common.read_jsonl(round1 / "patches.jsonl")
        check("1 good patch: gate passes, files written, ledger row",
              out1["patched"] and out1["gate"] == "pass" and "a + b" in (repo1 / "src/web/fake_routes.py").read_text()
              and (repo1 / "tests/test_add_widget_fix.py").is_file() and ledger1 and ledger1[-1]["gate"] == "pass")

        for n, (name, ask, watch) in enumerate((
            ("2 file outside allowlist (run.py) rejected, nothing written", _ST_RUNPY_ASK, "run.py"),
            ("3 non-unique old rejected, nothing written", _ST_NONUNIQUE_ASK, "src/web/fake_routes.py"),
            ("4 patch that breaks another test is reverted, sha restored", _ST_BREAKING_ASK, "src/web/fake_routes.py"),
        ), start=2):
            repo, round_dir = _st_prep(tmp, n)
            before = (repo / watch).read_text()
            out = run(round_dir, repo, max_attempts=1, ask=ask)
            check(name, not out["patched"] and (repo / watch).read_text() == before)

        repo5, round5 = _st_prep(tmp, 5)
        target5 = repo5 / "src/web/fake_routes.py"
        target5.write_text(target5.read_text(), encoding="utf-8")  # touch: mtime becomes "now"
        out5 = run(round5, repo5, max_attempts=1, ask=_ST_GOOD_ASK)
        ledger5 = common.read_jsonl(round5 / "patches.jsonl")
        check("5 fresh-mtime file rejected by human-touch guard",
              not out5["patched"] and ledger5 and "may be editing" in ledger5[-1]["why"])

        repo6, round6 = _st_prep(tmp, 6)
        out6 = run(round6, repo6, max_attempts=2, ask=_st_backend_ask)
        check("6 three backend errors abort the round", out6["why"] == "backend")

        restored = revert_all(repo1, tmp / "t1" / "sim-runs")
        check("7 revert_all restores the good patch",
              bool(restored) and "a - b" in (repo1 / "src/web/fake_routes.py").read_text()
              and not (repo1 / "tests/test_add_widget_fix.py").exists())

    ok = all(results)
    print("ALL GREEN" if ok else "SELFTEST FAILED")
    return ok

# ---------------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The Sam Loop mechanic: propose, guard, patch, gate, revert.")
    parser.add_argument("--round", help="round directory holding analysis.json + transcript.jsonl")
    parser.add_argument("--repo", help="repo root (default: common.ROOT)")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--revert-all", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        return 0 if selftest() else 1

    repo = Path(args.repo) if args.repo else common.ROOT
    if args.revert_all:
        restored = revert_all(repo, common.RUNS)
        print(f"revert-all: restored {len(restored)} file write(s)")
        for path in restored:
            print(f"  {path}")
        return 0

    if not args.round:
        parser.error("--round is required unless --selftest or --revert-all")
    result = run(Path(args.round), repo, max_attempts=args.max_attempts, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0

if __name__ == "__main__":
    common.utf8_console()
    sys.exit(main())
