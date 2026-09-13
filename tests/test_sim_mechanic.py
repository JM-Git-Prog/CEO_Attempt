"""Tests for sim-player/mechanic.py — the Sam Loop mechanic.

No Ollama, no real repo: every `run()` call here is given a fake `ask` (or none, to prove the
"no defects" short-circuit needs no model at all). The full guard chain — allowlist, human-touch,
exact-match, backups, the pytest gate, the ledger, backend-abort, revert_all — is exercised twice:
once directly against small hand-built repos (fast, one guard per test) and once wholesale through
`mechanic.selftest()`, which is the same acceptance check `python mechanic.py --selftest` runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sim-player"))
import common  # noqa: E402
import mechanic  # noqa: E402


def _round(tmp_path: Path, name: str, defects: list[dict], transcript: list[dict] | None = None) -> Path:
    round_dir = tmp_path / "sim-runs" / name
    round_dir.mkdir(parents=True)
    analysis = {"round": name, "counts": {}, "wishes": [], "defects": defects, "gaps_filed": []}
    (round_dir / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    with open(round_dir / "transcript.jsonl", "w", encoding="utf-8") as fh:
        for row in transcript or []:
            fh.write(json.dumps(row) + "\n")
    return round_dir


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "web").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "src" / "web" / "__init__.py").write_text("", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------- run(): no-defects gate


def test_no_defects_short_circuits_without_asking_a_model(tmp_path):
    repo = _repo(tmp_path)
    round_dir = _round(tmp_path, "r1", defects=[])
    out = mechanic.run(round_dir, repo, ask=lambda *a: (_ for _ in ()).throw(AssertionError("model was called")))
    assert out == {"patched": False, "attempts": 0, "files": [], "restart_needed": False, "why": "no defects", "gate": None}


def test_missing_analysis_json_is_also_no_defects(tmp_path):
    repo = _repo(tmp_path)
    round_dir = tmp_path / "sim-runs" / "r2"
    round_dir.mkdir(parents=True)
    out = mechanic.run(round_dir, repo)
    assert out["patched"] is False and out["why"] == "no defects"


# ---------------------------------------------------------------------------- guard 1: allowlist


def test_allowlist_accepts_the_three_trees_and_rejects_everything_else():
    for rel in ("src/web/foo.py", "src/web/sub/bar.py", "src/web/static/app.js",
                "src/unified_pipeline/x.py", "src/web/static/still_under_web.py"):
        ok, why = mechanic._check_allowlist(rel)
        assert ok, f"{rel} should be allowed: {why}"
    for rel in ("run.py", "CLAUDE.md", "claude.md", "src/web/tool.bat", "../src/web/x.py", "/etc/passwd",
                "C:/Windows/x.py", "sim-player/common.py", "src/web/sim-player.py", "src/orchestrator/llm.py"):
        ok, why = mechanic._check_allowlist(rel)
        assert not ok, f"{rel} should have been rejected"


def test_new_test_path_must_match_pattern_and_not_already_exist(tmp_path):
    repo = _repo(tmp_path)
    ok, _ = mechanic._check_new_test_path("tests/test_foo.py", repo)
    assert ok
    ok, why = mechanic._check_new_test_path("tests/TestFoo.py", repo)
    assert not ok and "match" in why
    (repo / "tests" / "test_exists.py").write_text("x = 1\n", encoding="utf-8")
    ok, why = mechanic._check_new_test_path("tests/test_exists.py", repo)
    assert not ok and "already exists" in why


# ---------------------------------------------------------------------------- guard 2: human-touch


def test_human_touch_guard_blocks_recently_modified_files(tmp_path):
    import os
    import time

    repo = _repo(tmp_path)
    target = repo / "src" / "web" / "x.py"
    target.write_text("a = 1\n", encoding="utf-8")

    ok, why = mechanic._check_human_touch(repo, "src/web/x.py")
    assert not ok and "may be editing" in why

    old = time.time() - 20 * 60
    os.utime(target, (old, old))
    ok, why = mechanic._check_human_touch(repo, "src/web/x.py")
    assert ok, why

    ok, why = mechanic._check_human_touch(repo, "src/web/missing.py")
    assert not ok and "not found" in why


# ---------------------------------------------------------------------------- guard 3: exact-match


def test_exact_match_requires_exactly_one_occurrence(tmp_path):
    repo = _repo(tmp_path)
    target = repo / "src" / "web" / "y.py"
    target.write_text("return 1\nreturn 1\n", encoding="utf-8")
    ok, why = mechanic._check_exact_match(repo, "src/web/y.py", "return 1")
    assert not ok and "2 time" in why

    target.write_text("return 1\nreturn 2\n", encoding="utf-8")
    ok, _ = mechanic._check_exact_match(repo, "src/web/y.py", "return 1")
    assert ok

    ok, why = mechanic._check_exact_match(repo, "src/web/y.py", "not present anywhere")
    assert not ok and "0 time" in why


# ---------------------------------------------------------------------------- proposal shape


def test_validate_shape_rejects_malformed_proposals():
    good = {"diagnosis": "d", "confidence": 0.5, "edits": [{"file": "a", "old": "b", "new": "c"}], "restart_needed": False}
    ok, _ = mechanic._validate_shape(good)
    assert ok

    for bad in (
        None, {}, {**good, "diagnosis": ""}, {**good, "confidence": "high"}, {**good, "edits": []},
        {**good, "edits": [{"file": "a", "old": "b", "new": "b"}]}, {**good, "restart_needed": "no"},
        {**good, "new_test": {"file": "tests/test_x.py"}},
    ):
        ok, why = mechanic._validate_shape(bad)
        assert not ok, f"expected rejection for {bad!r}"
        assert why


# ---------------------------------------------------------------------------- run(): end to end


_GOOD_FILE = "def broken(a, b):\n    return a - b  # bug\n"
_TEST_FOR_GOOD_FILE = "from src.web.calc import broken\n\n\ndef test_broken():\n    assert broken(2, 3) == 5\n"


def _seed_calc_repo(tmp_path: Path) -> Path:
    # Named test_z_calc.py (sorts last) so a second, alphabetically-earlier test file can be added
    # by an individual test without pytest's "-x" stopping on this one first and hiding it.
    repo = _repo(tmp_path)
    (repo / "src" / "web" / "calc.py").write_text(_GOOD_FILE, encoding="utf-8")
    (repo / "tests" / "test_z_calc.py").write_text(_TEST_FOR_GOOD_FILE, encoding="utf-8")
    import os
    import time
    old = time.time() - 20 * 60
    for p in repo.rglob("*.py"):
        os.utime(p, (old, old))
    return repo


def _good_calc_ask(system, messages, schema):
    assert "calc.py" in system or True  # messages carry the route source, not asserted here
    return {"diagnosis": "subtracts instead of adding", "confidence": 0.9,
            "edits": [{"file": "src/web/calc.py", "old": "return a - b  # bug", "new": "return a + b"}],
            "new_test": None, "restart_needed": False}


def test_run_applies_a_good_patch_and_records_the_ledger(tmp_path):
    repo = _seed_calc_repo(tmp_path)
    defects = [{"kind": "bad_reply", "turn": 2, "detail": "broken(2,3) != 5", "route": "", "excerpt": ""}]
    transcript = [{"turn": i, "phase": "wish", "i_see": "", "i_type": "", "request": None,
                   "response": "x", "http_status": 200, "error": None} for i in range(1, 5)]
    round_dir = _round(tmp_path, "good", defects, transcript)

    out = mechanic.run(round_dir, repo, max_attempts=2, ask=_good_calc_ask)

    assert out == {"patched": True, "attempts": 1, "files": ["src/web/calc.py"], "restart_needed": False, "why": "", "gate": "pass"}
    assert "a + b" in (repo / "src" / "web" / "calc.py").read_text()

    manifest_path = round_dir / "patches" / "1" / "manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup = round_dir / "patches" / "1" / manifest["files"][0]["before"]
    assert backup.is_file() and "a - b" in backup.read_text()

    round_ledger = common.read_jsonl(round_dir / "patches.jsonl")
    runs_ledger = common.read_jsonl(round_dir.parent / "mechanic-ledger.jsonl")
    assert len(round_ledger) == 1 and round_ledger[0]["gate"] == "pass"
    assert len(runs_ledger) == 1 and runs_ledger[0]["round"] == "good"


def test_run_rejects_out_of_allowlist_edit_without_writing_anything(tmp_path):
    repo = _seed_calc_repo(tmp_path)
    round_dir = _round(tmp_path, "bad-allow",
                        [{"kind": "exception", "turn": 1, "detail": "d", "route": "", "excerpt": ""}])

    def ask(system, messages, schema):
        return {"diagnosis": "d", "confidence": 0.5,
                "edits": [{"file": "src/orchestrator/llm.py", "old": "x", "new": "y"}],
                "new_test": None, "restart_needed": False}

    out = mechanic.run(round_dir, repo, max_attempts=1, ask=ask)
    assert out["patched"] is False
    assert not (round_dir / "patches").exists()
    ledger = common.read_jsonl(round_dir / "patches.jsonl")
    assert ledger[-1]["gate"] == "rejected" and "allowed tree" in ledger[-1]["why"]


def test_run_reverts_a_patch_that_breaks_another_test(tmp_path):
    # test_a_other.py sorts BEFORE test_z_calc.py, so with pytest's "-x" it is the one that surfaces
    # the regression: test_z_calc.py already fails at baseline (the unrelated bug) and would swallow
    # any later failure behind it if it ran first.
    repo = _seed_calc_repo(tmp_path)
    (repo / "src" / "web" / "calc.py").write_text(_GOOD_FILE + "\n\ndef other(x):\n    return x * 2\n", encoding="utf-8")
    (repo / "tests" / "test_a_other.py").write_text(
        "from src.web.calc import other\n\n\ndef test_other():\n    assert other(2) == 4\n", encoding="utf-8")
    import os
    import time
    old = time.time() - 20 * 60
    for p in repo.rglob("*.py"):
        os.utime(p, (old, old))

    round_dir = _round(tmp_path, "bad-break",
                        [{"kind": "exception", "turn": 1, "detail": "d", "route": "", "excerpt": ""}])

    def breaking_ask(system, messages, schema):
        return {"diagnosis": "d", "confidence": 0.5,
                "edits": [{"file": "src/web/calc.py", "old": "return x * 2", "new": "return x * 3"}],
                "new_test": None, "restart_needed": False}

    sha_before = mechanic._sha256_file(repo / "src" / "web" / "calc.py")
    out = mechanic.run(round_dir, repo, max_attempts=1, ask=breaking_ask)
    sha_after = mechanic._sha256_file(repo / "src" / "web" / "calc.py")

    assert out["patched"] is False
    assert sha_after == sha_before
    ledger = common.read_jsonl(round_dir / "patches.jsonl")
    assert ledger[-1]["gate"] == "reverted"


def test_run_dry_run_validates_and_logs_but_never_writes(tmp_path):
    repo = _seed_calc_repo(tmp_path)
    round_dir = _round(tmp_path, "dry",
                        [{"kind": "exception", "turn": 1, "detail": "d", "route": "", "excerpt": ""}])
    before = (repo / "src" / "web" / "calc.py").read_text()

    out = mechanic.run(round_dir, repo, max_attempts=1, dry_run=True, ask=_good_calc_ask)

    assert out["patched"] is False and out["gate"] == "dry-run"
    assert (repo / "src" / "web" / "calc.py").read_text() == before
    assert not (round_dir / "patches").exists()
    ledger = common.read_jsonl(round_dir / "patches.jsonl")
    assert ledger and ledger[-1]["gate"] == "dry-run"


def test_run_aborts_after_three_consecutive_backend_errors(tmp_path):
    repo = _seed_calc_repo(tmp_path)
    round_dir = _round(tmp_path, "flaky",
                        [{"kind": "exception", "turn": 1, "detail": "d", "route": "", "excerpt": ""}])

    def flaky_ask(system, messages, schema):
        raise common.Backend("simulated outage")

    out = mechanic.run(round_dir, repo, max_attempts=5, ask=flaky_ask)
    assert out["why"] == "backend" and out["patched"] is False
    ledger = common.read_jsonl(round_dir / "patches.jsonl")
    assert len(ledger) == 3 and all(row["gate"] == "fail" for row in ledger)


def test_revert_all_restores_across_rounds(tmp_path):
    repo = _seed_calc_repo(tmp_path)
    round_dir = _round(tmp_path, "revertme",
                        [{"kind": "exception", "turn": 1, "detail": "d", "route": "", "excerpt": ""}])
    mechanic.run(round_dir, repo, max_attempts=1, ask=_good_calc_ask)
    assert "a + b" in (repo / "src" / "web" / "calc.py").read_text()

    restored = mechanic.revert_all(repo, tmp_path / "sim-runs")
    assert "src/web/calc.py" in restored
    assert "a - b" in (repo / "src" / "web" / "calc.py").read_text()


# ---------------------------------------------------------------------------- --selftest


def test_selftest_is_all_green():
    assert mechanic.selftest() is True
