from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from tools import e2e_qualification as qualification


def _command(name: str = "test", passed: bool = True) -> qualification.CommandEvidence:
    return qualification.CommandEvidence(
        name=name,
        argv=("python",),
        started_at_epoch=1.0,
        duration_seconds=0.1,
        returncode=0 if passed else 1,
        timed_out=False,
        passed=passed,
        stdout_tail="",
        stderr_tail="",
    )


def _iteration(identity: str, passed: bool = True) -> qualification.IterationEvidence:
    return qualification.IterationEvidence(
        iteration_id=identity,
        mode="tests-only",
        started_at_epoch=1.0,
        finished_at_epoch=2.0,
        duration_seconds=1.0,
        source_fingerprint_before="a" * 64,
        source_fingerprint_after="a" * 64,
        stale=False,
        changed_files=(),
        commands=(_command(passed=passed),),
        mock_e2e_result=None,
        e2e_result=None,
        regression_delta={},
        passed=passed,
    )


def test_evidence_store_is_append_only_and_atomic(tmp_path):
    store = qualification.EvidenceStore(tmp_path)
    store.write(_iteration("one"))
    store.write(_iteration("two", passed=False))

    lines = store.events.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["iteration_id"] for line in lines] == ["one", "two"]
    assert json.loads(store.latest.read_text(encoding="utf-8"))["iteration_id"] == "two"
    assert (tmp_path / "one" / "summary.json").is_file()
    assert (tmp_path / "two" / "report.md").is_file()
    assert (tmp_path / "scoreboard.json").is_file()
    assert (tmp_path / "NEXT.md").is_file()
    assert not list(tmp_path.rglob("*.tmp"))


def test_scoreboard_is_keyed_by_fingerprint_and_lane_with_conservative_verdict(tmp_path):
    store = qualification.EvidenceStore(tmp_path)
    fingerprint = "f" * 64

    def full_iteration(index: int, passed: bool) -> qualification.IterationEvidence:
        failure = None if passed else "plan/validation/item_out_of_bounds:sofa_1"
        stages = {
            "plan": {"status": "passed" if passed else "failed"},
            "canon": {"status": "passed" if passed else "incomplete"},
        }
        return qualification.IterationEvidence(
            iteration_id=f"trial-{index}", mode="full",
            started_at_epoch=float(index), finished_at_epoch=float(index + 1),
            duration_seconds=1.0,
            source_fingerprint_before=fingerprint,
            source_fingerprint_after=fingerprint,
            stale=False, changed_files=(),
            commands=(
                _command("compileall"), _command("node-check"),
                _command("full-tests"), _command("mock-v11-e2e"),
                _command("fresh-v11-e2e", passed=passed),
            ),
            mock_e2e_result={"passed": True, "session_id": f"mock-{index}"},
            e2e_result={
                "passed": passed,
                "session_id": f"real-{index}",
                "lane": "local-default",
                "stages": stages,
                "failure_signature": failure,
            },
            regression_delta={}, passed=passed,
        )

    for index, passed in enumerate((True, True, True, True, False), start=1):
        store.write(full_iteration(index, passed))
        scoreboard = json.loads(store.scoreboard.read_text(encoding="utf-8"))
        assert scoreboard["verdict"] == (
            "INDETERMINATE" if index < qualification.MIN_RATCHET_TRIALS else "KEEP"
        )

    lane = scoreboard["fingerprints"][fingerprint]["lanes"]["local-default"]
    assert lane["trials"] == 5 and lane["passes"] == 4 and lane["pass_rate"] == 0.8
    assert lane["top_signatures"] == [["plan/validation/item_out_of_bounds:sofa_1", 1]]
    assert scoreboard["best"] == {
        "fingerprint": fingerprint,
        "lane": "local-default",
        "pass_rate": 0.8,
        "trials": 5,
    }
    assert "Collect" not in store.next.read_text(encoding="utf-8")
    assert "Keep this fingerprint" in store.next.read_text(encoding="utf-8")

    deterministic_failure = full_iteration(6, False).model_copy(update={
        "source_fingerprint_before": "e" * 64,
        "source_fingerprint_after": "e" * 64,
        "commands": (_command("compileall", passed=False),),
        "mock_e2e_result": None,
        "e2e_result": None,
    })
    store.write(deterministic_failure)
    assert json.loads(store.scoreboard.read_text(encoding="utf-8"))["verdict"] == "REVERT"


def test_process_lock_serializes_and_recovers_stale_owner(tmp_path):
    path = tmp_path / ".lock"
    with qualification.ProcessLock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with qualification.ProcessLock(path):
                pass
    path.write_text('{"pid": -1}', encoding="utf-8")
    with qualification.ProcessLock(path):
        assert path.exists()
    assert not path.exists()


def test_source_fingerprint_tracks_content_not_mtime(tmp_path, monkeypatch):
    source = tmp_path / "src"
    source.mkdir()
    file = source / "sample.py"
    file.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(qualification, "ROOT", tmp_path)
    monkeypatch.setattr(qualification, "INCLUDE_ROOTS", ("src",))

    first = qualification.source_fingerprint()
    file.write_text("VALUE = 2\n", encoding="utf-8")
    second = qualification.source_fingerprint()

    assert first != second
    assert qualification.source_fingerprint() == second


def test_run_command_is_bounded_and_argv_only():
    passed = qualification.run_command(
        "ok", [sys.executable, "-c", "print('ok')"], timeout=5
    )
    timed_out = qualification.run_command(
        "slow", [sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.05
    )

    assert passed.passed and passed.returncode == 0
    assert passed.argv[0] == sys.executable
    assert timed_out.timed_out and not timed_out.passed


def test_run_command_applies_allowlisted_child_env_without_leaking_or_mutating_parent(monkeypatch):
    monkeypatch.delenv("QUALIFICATION_MOCK_E2E", raising=False)
    evidence = qualification.run_command(
        "mock-env",
        [
            sys.executable, "-c",
            "import os; assert 'QUALIFICATION_MOCK_E2E' in os.environ",
        ],
        timeout=5,
        env_overrides={"QUALIFICATION_MOCK_E2E": "mock-secret-value"},
    )

    assert evidence.passed
    assert "mock-secret-value" not in evidence.model_dump_json()
    assert "QUALIFICATION_MOCK_E2E" not in qualification.os.environ
    with pytest.raises(ValueError, match="Unsafe qualification environment override"):
        qualification.run_command(
            "unsafe", [sys.executable, "-c", "pass"], 5,
            env_overrides={"UNSAFE_SECRET": "value"},
        )


def test_changes_during_iteration_mark_evidence_stale(tmp_path, monkeypatch):
    fingerprints = iter(("a" * 64, "b" * 64))
    monkeypatch.setattr(qualification, "source_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(
        qualification,
        "command_plan",
        lambda mode, path: [("focused", [sys.executable, "-c", "pass"])],
    )
    monkeypatch.setattr(
        qualification, "run_command", lambda *args, **kwargs: _command("focused")
    )

    result = qualification.run_iteration(
        qualification.EvidenceStore(tmp_path), "tests-only", 5, ("src/a.py",)
    )

    assert result.stale
    assert not result.passed
    assert result.source_fingerprint_before != result.source_fingerprint_after


def test_debounce_coalesces_rapid_changes_into_one_stable_fingerprint(monkeypatch):
    fingerprints = iter(("changed-1", "changed-2"))
    clocks = iter((0.0, 0.05, 0.06, 0.17))
    monkeypatch.setattr(qualification, "source_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(qualification.time, "monotonic", lambda: next(clocks))

    assert qualification._wait_for_stable_change("baseline", 0.1) == "changed-2"


def test_modes_and_fresh_adapter_never_accept_a_reused_session(tmp_path):
    e2e = tmp_path / "result.json"
    full = qualification.command_plan("full", e2e)
    tests_only = qualification.command_plan("tests-only", e2e)
    e2e_only = qualification.command_plan("e2e-only", e2e)

    mock = next(argv for name, argv in full if name == "mock-v11-e2e")
    fresh = next(argv for name, argv in full if name == "fresh-v11-e2e")
    assert "tools/v11_e2e_adapter.py" in mock
    assert "tools/v11_e2e_adapter.py" in fresh
    assert "--session-id" not in mock and "--session-id" not in fresh
    assert mock[-1] != fresh[-1]
    assert [name for name, _ in tests_only] == [
        "compileall", "node-check", "full-tests",
    ]
    assert all(name != "focused-tests" for name, _ in full)
    assert all(name not in {"mock-v11-e2e", "fresh-v11-e2e"} for name, _ in tests_only)
    assert [name for name, _ in e2e_only] == ["fresh-v11-e2e"]


def test_mock_runtime_stages_mark_only_expected_vision_unavailability_not_applicable():
    from tools import v11_e2e_adapter as adapter

    qa_entry = {
        "decision": "human_required",
        "screening": {
            "status": "failed",
            "diagnostic": "vision screening failed: connection refused",
        },
    }
    payload = {
        "compiler_manifests": ["prepared.json", "terminal.json"],
        "runtime_details": {"compiler": {
            "status": "fallback_success",
            "execution": "declared_fallback",
            "target": "godot",
            "capability": {"available": False},
        }},
        "parity_report": {"passed": True},
        "runtime_smoke_report": None,
        "qa_evidence": [qa_entry],
    }

    assert adapter._runtime_stages(payload, mock_qualification=True)["qa"] == {
        "status": "not_applicable",
        "entries": [qa_entry],
        "reason": "deterministic_mock_vision_unavailable",
    }
    assert adapter._runtime_stages(payload, mock_qualification=False)["qa"]["status"] == "failed"


def test_adapter_failure_signatures_are_stable_and_fail_closed():
    from tools import v11_e2e_adapter as adapter

    stages = {name: {"status": "passed"} for name in adapter.EXPECTED_STAGES}
    stages["plan"] = {
        "status": "failed",
        "validation": {"blockers": [{
            "code": "item_out_of_bounds", "item_ids": ["sofa_1"],
        }]},
    }
    result = {"stages": stages, "passed": True}

    adapter._finalize_result(result)

    assert result["passed"] is False
    assert result["failure_signature"] == "plan/validation/item_out_of_bounds:sofa_1"
    assert result["failure_signatures"] == [{
        "stage": "plan",
        "rule": "validation",
        "detail": "item_out_of_bounds:sofa_1",
        "signature": "plan/validation/item_out_of_bounds:sofa_1",
    }]

    incomplete = {
        "stages": {"interface": {"status": "passed"}},
        "exception": {"type": "RuntimeError", "message": "volatile detail"},
    }
    adapter._finalize_result(incomplete)
    assert incomplete["passed"] is False
    assert incomplete["failure_signature"] == "adapter/exception/runtimeerror"
    assert any(
        item["signature"] == "plan/incomplete/not_recorded"
        for item in incomplete["failure_signatures"]
    )


def test_cli_defaults_to_bounded_once_mode():
    args = qualification.parse_args([])
    assert args.once and not args.watch
    assert args.timeout > 0
    with pytest.raises(SystemExit):
        qualification.parse_args(["--timeout", "0"])
