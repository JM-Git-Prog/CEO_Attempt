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
    assert scoreboard["lane_winners"]["local-default"] == {
        "fingerprint": fingerprint,
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


def test_idle_f0_runs_only_after_quiet_threshold_and_yields_to_agent_or_download(
    tmp_path, monkeypatch
):
    fingerprints = iter(("baseline", "changed"))
    clocks = iter((0.0, 11.0, 12.0, 12.0))
    callbacks = []
    monkeypatch.setattr(qualification, "source_fingerprint", lambda: next(fingerprints))
    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(qualification.time, "monotonic", lambda: next(clocks))

    changed = qualification._wait_for_stable_change(
        "baseline", 0.0, idle_seconds=10.0,
        idle_callback=lambda: callbacks.append("ran") or True,
    )
    assert changed == "changed" and callbacks == ["ran"]
    monkeypatch.setattr(qualification, "source_fingerprint", lambda: "baseline")

    marker = tmp_path / "agent-active"
    marker.write_text("active", encoding="utf-8")
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "ready", "busy": False},
    )
    assert qualification._run_idle_f0(
        "baseline", corpus_path=tmp_path / "corpus.jsonl",
        log_path=tmp_path / "idle.log", agent_active_file=marker,
    ) is False
    marker.unlink()
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "model_download", "busy": True},
    )
    assert qualification._run_idle_f0(
        "baseline", corpus_path=tmp_path / "corpus.jsonl",
        log_path=tmp_path / "idle.log", agent_active_file=marker,
    ) is False

    from tools import flywheel_corpus, qualification_briefing
    captured = {}
    briefing_captured = {}
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "unavailable", "busy": True},
    )
    monkeypatch.setattr(
        flywheel_corpus, "extract_corpus",
        lambda **kwargs: captured.update(kwargs) or {"status": "complete"},
    )
    monkeypatch.setattr(
        qualification_briefing, "run_briefing",
        lambda **kwargs: briefing_captured.update(kwargs) or {"status": "complete"},
    )
    assert qualification._run_idle_f0(
        "baseline", corpus_path=tmp_path / "corpus.jsonl",
        log_path=tmp_path / "idle.log", agent_active_file=marker,
    ) is True
    assert captured["max_records"] == 25
    assert briefing_captured["root"] == qualification.ROOT
    assert briefing_captured["log_path"] == tmp_path / "idle.log"
    assert callable(briefing_captured["stop_requested"])


def test_modes_and_fresh_adapter_never_accept_a_reused_session(tmp_path):
    e2e = tmp_path / "result.json"
    full = qualification.command_plan("full", e2e)
    tests_only = qualification.command_plan("tests-only", e2e)
    e2e_only = qualification.command_plan("e2e-only", e2e)

    mock = next(argv for name, argv in full if name == "mock-v11-e2e")
    fresh = next(argv for name, argv in e2e_only if name == "fresh-v11-e2e")
    assert "tools/v11_e2e_adapter.py" in mock
    assert "tools/v11_e2e_adapter.py" in fresh
    assert "--session-id" not in mock and "--session-id" not in fresh
    assert all(name != "fresh-v11-e2e" for name, _ in full)
    assert [name for name, _ in tests_only] == [
        "compileall", "node-check", "full-tests",
    ]
    assert all(name != "focused-tests" for name, _ in full)
    assert all(name not in {"mock-v11-e2e", "fresh-v11-e2e"} for name, _ in tests_only)
    assert [name for name, _ in e2e_only] == ["fresh-v11-e2e"]


def test_scheduler_uses_k2_and_stops_after_three_identical_failures(tmp_path, monkeypatch):
    import threading

    store = qualification.EvidenceStore(tmp_path / "evidence")
    monkeypatch.setattr(
        qualification, "_measure_vram_headroom",
        lambda: {"available": True, "free_mib": 22_722, "total_mib": 24_564},
    )
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "ready", "busy": False},
    )
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_trial(iteration_dir, lane, index, timeout, lane_env=None):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return _command(f"trial-{index}", passed=False), {
            "lane": lane,
            "trial_index": index,
            "evidence_path": str(iteration_dir / f"trial-{index}.json"),
            "passed": False,
            "session_id": f"session-{index}",
            "failure_signature": "canon/provider/mock_fallback",
            "stages": {"canon": {"status": "failed"}},
        }

    monkeypatch.setattr(qualification, "_run_real_trial", fake_trial)
    commands, results, scheduler = qualification._run_stochastic_trials(
        store, tmp_path / "iteration", "f" * 64, 10,
        requested_workers=2, trial_limit=5,
    )

    assert len(commands) == len(results) == 3
    assert maximum_active == 2
    assert scheduler["status"] == "early_stopped"
    assert scheduler["early_stop_signature"] == "canon/provider/mock_fallback"
    assert scheduler["workers"] == 2
    assert scheduler["ollama_num_parallel"] == 2


def test_scheduler_runs_n5_when_first_three_signatures_differ(tmp_path, monkeypatch):
    store = qualification.EvidenceStore(tmp_path / "evidence")
    monkeypatch.setattr(
        qualification, "_measure_vram_headroom",
        lambda: {"available": True, "free_mib": 22_722, "total_mib": 24_564},
    )
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "ready", "busy": False},
    )

    def fake_trial(iteration_dir, lane, index, timeout, lane_env=None):
        return _command(f"trial-{index}", passed=False), {
            "lane": lane,
            "trial_index": index,
            "evidence_path": str(iteration_dir / f"trial-{index}.json"),
            "passed": False,
            "session_id": f"session-{index}",
            "failure_signature": f"plan/validation/failure_{index % 2}",
            "stages": {"plan": {"status": "failed"}},
        }

    monkeypatch.setattr(qualification, "_run_real_trial", fake_trial)
    commands, results, scheduler = qualification._run_stochastic_trials(
        store, tmp_path / "iteration", "f" * 64, 10,
        requested_workers=2, trial_limit=5,
    )

    assert len(commands) == len(results) == 5
    assert scheduler["status"] == "complete"
    assert scheduler["total_trials"] == 5


def test_scheduler_holds_for_local_model_download_and_sets_ollama_parallel(tmp_path, monkeypatch):
    store = qualification.EvidenceStore(tmp_path / "evidence")
    real_trial = qualification._run_real_trial
    real_gpu_state = qualification._comfyui_gpu_state
    monkeypatch.setattr(
        qualification, "_measure_vram_headroom",
        lambda: {"available": True, "free_mib": 22_722, "total_mib": 24_564},
    )
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "model_download", "busy": True},
    )
    monkeypatch.setattr(
        qualification, "_run_real_trial",
        lambda *args, **kwargs: pytest.fail("busy guard must prevent trial launch"),
    )
    commands, results, scheduler = qualification._run_stochastic_trials(
        store, tmp_path / "iteration", "f" * 64, 10,
    )
    assert not commands and not results
    assert scheduler["status"] == "gpu_busy"

    captured = {}

    def fake_command(name, argv, timeout, env_overrides=None):
        captured["env"] = env_overrides
        path = Path(argv[-1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "passed": False,
            "session_id": "fresh",
            "failure_signature": "canon/provider/mock_fallback",
            "stages": {"canon": {"status": "failed"}},
        }), encoding="utf-8")
        return _command(name, passed=False)

    monkeypatch.setattr(qualification, "run_command", fake_command)
    monkeypatch.setattr(qualification, "_run_real_trial", real_trial)
    _command_result, summary = qualification._run_real_trial(
        tmp_path / "iteration", "local-default", 1, 10
    )
    assert captured["env"] == {"OLLAMA_NUM_PARALLEL": "2"}
    assert summary["session_id"] == "fresh"
    qualification._run_real_trial(
        tmp_path / "iteration", "ollama-pro-glm-5-2", 2, 10,
        {"LLM_MODEL": "glm-5.2:cloud"},
    )
    assert captured["env"] == {
        "OLLAMA_NUM_PARALLEL": "2", "LLM_MODEL": "glm-5.2:cloud",
    }
    assert qualification._effective_workers(3, {"available": False}) == 2
    assert qualification._effective_workers(3, {"available": True, "free_mib": 22_722}) == 3

    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:8188")
    monkeypatch.setattr(qualification, "_comfyui_gpu_state", real_gpu_state)
    monkeypatch.setattr(
        qualification, "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    unavailable = qualification._comfyui_gpu_state()
    assert unavailable["status"] == "unavailable" and unavailable["busy"] is True


def test_full_iteration_records_scheduler_health_without_claiming_sample_qualification(
    tmp_path, monkeypatch
):
    fingerprint = "f" * 64
    monkeypatch.setattr(qualification, "source_fingerprint", lambda: fingerprint)

    def fake_plan(_mode, result_path):
        return [
            ("compileall", ["python"]),
            ("node-check", ["node"]),
            ("full-tests", ["python"]),
            ("mock-v11-e2e", ["python", str(result_path.parent / "mock-v11-e2e.json")]),
        ]

    def fake_command(name, argv, timeout, env_overrides=None):
        if name == "mock-v11-e2e":
            path = Path(argv[-1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"passed": True, "session_id": "mock"}), encoding="utf-8")
        return _command(name)

    failed_sample = {
        "lane": qualification.DEFAULT_LANE,
        "trial_index": 1,
        "evidence_path": str(tmp_path / "trial-01.json"),
        "passed": False,
        "session_id": "fresh",
        "failure_signature": "canon/provider/mock_fallback",
        "stages": {"canon": {"status": "failed"}},
    }
    scheduler = {
        "status": "early_stopped", "lane": qualification.DEFAULT_LANE,
        "workers": 2, "total_trials": 3, "new_trials": 3,
        "vram": {"available": True, "free_mib": 22_722},
    }
    monkeypatch.setattr(qualification, "command_plan", fake_plan)
    monkeypatch.setattr(qualification, "run_command", fake_command)
    monkeypatch.setattr(
        qualification, "_run_stochastic_trials",
        lambda *args, **kwargs: ([], (failed_sample,), scheduler),
    )

    store = qualification.EvidenceStore(tmp_path / "evidence")
    result = qualification.run_iteration(store, "full", 10, ())

    assert result.passed is True
    assert result.e2e_result["passed"] is False
    assert result.scheduler["status"] == "early_stopped"
    report = (store.root / result.iteration_id / "report.md").read_text(encoding="utf-8")
    assert "## Tier 2 Scheduler" in report
    assert "Status: `early_stopped`" in report
    assert json.loads(store.latest.read_text(encoding="utf-8"))["scheduler"] == scheduler


def test_lane_ladder_is_cheapest_first_and_cloud_requires_explicit_enable():
    config = qualification._load_lanes_config(qualification.DEFAULT_LANES_CONFIG)
    assert [lane["env"]["LLM_MODEL"] for lane in config["lanes"]] == [
        # Roster change 2026-07-23: kimi-k2.6:cloud added at John's direction
        # (authorization recorded in lanes.json). Ships disabled like all
        # remote lanes; enabled only via --enable-lane at launch.
        # Roster change 2026-07-23 (later, 500-plan harvest, John's "yes for all"):
        # gpt-oss:120b-cloud, qwen3-coder:480b-cloud and deepseek-v3.1:671b-cloud
        # added; harvest caps raised to 400 requests/run on all remote lanes
        # (authorization recorded per lane in lanes.json).
        "llama3.1", "gpt-oss:20b", "glm-5.2:cloud", "kimi-k2.6:cloud",
        "gpt-oss:120b-cloud", "qwen3-coder:480b-cloud", "deepseek-v3.1:671b-cloud",
    ]
    for lane in config["lanes"]:
        if lane.get("remote"):
            assert lane["enabled"] is False
            assert lane["authorization"]["approved"] is True
            assert lane["caps"]["max_requests_per_run"] == 400

    fingerprint = "f" * 64
    scoreboard = {"fingerprints": {fingerprint: {"lanes": {}}}}
    lane, state = qualification._select_lane(config, scoreboard, fingerprint)
    assert lane["name"] == "local-llama31" and state["status"] == "sampling"

    def plateau(signature):
        return {
            "trials": 5, "passes": 0, "pass_rate": 0.0,
            "top_signatures": [[signature, 5]],
        }

    lanes = scoreboard["fingerprints"][fingerprint]["lanes"]
    lanes["local-llama31"] = plateau("plan/validation/item_out_of_bounds:sofa")
    lane, _state = qualification._select_lane(config, scoreboard, fingerprint)
    assert lane["name"] == "local-gpt-oss-20b"

    lanes["local-gpt-oss-20b"] = plateau("plan/validation/item_out_of_bounds:sofa")
    lane, state = qualification._select_lane(config, scoreboard, fingerprint)
    assert lane is None and state == {
        "status": "awaiting_explicit_enable", "next_lane": "ollama-pro-glm-5-2",
    }
    lane, _state = qualification._select_lane(
        config, scoreboard, fingerprint, ("ollama-pro-glm-5-2",)
    )
    assert lane["name"] == "ollama-pro-glm-5-2"

    lanes["ollama-pro-glm-5-2"] = {
        "trials": 2, "passes": 0, "pass_rate": 0.0,
        "top_signatures": [["brief/provider/weekly_limit", 2]],
        "cap_exhausted": True,
    }
    lane, state = qualification._select_lane(config, scoreboard, fingerprint)
    assert lane is None and state["status"] == "cloud_cap_exhausted"

    lanes["local-llama31"] = plateau("canon/provider/mock_fallback")
    lane, state = qualification._select_lane(config, scoreboard, fingerprint)
    assert lane is None and state["status"] == "lane_escalation_blocked"


def test_cloud_cap_exhaustion_pauses_lane_without_queuing_local_work(tmp_path, monkeypatch):
    store = qualification.EvidenceStore(tmp_path / "evidence")
    monkeypatch.setattr(
        qualification, "_measure_vram_headroom",
        lambda: {"available": True, "free_mib": 22_722},
    )
    monkeypatch.setattr(
        qualification, "_comfyui_gpu_state",
        lambda: {"status": "ready", "busy": False},
    )

    def capped_trial(iteration_dir, lane, index, timeout, lane_env=None):
        assert lane == "ollama-pro-glm-5-2"
        assert lane_env == {"LLM_MODEL": "glm-5.2:cloud"}
        return _command(f"trial-{index}", passed=False), {
            "lane": lane,
            "trial_index": index,
            "evidence_path": str(iteration_dir / f"trial-{index}.json"),
            "passed": False,
            "session_id": f"cloud-{index}",
            "failure_signature": "brief/provider/weekly_limit",
            "remote_cap_exhausted": True,
            "stages": {"brief": {"status": "failed"}},
        }

    monkeypatch.setattr(qualification, "_run_real_trial", capped_trial)
    commands, results, scheduler = qualification._run_stochastic_trials(
        store,
        tmp_path / "iteration",
        "f" * 64,
        10,
        lane="ollama-pro-glm-5-2",
        lane_env={"LLM_MODEL": "glm-5.2:cloud"},
        remote=True,
        caps={
            "estimated_requests_per_trial": 4,
            "max_requests_per_batch": 20,
            "max_requests_per_run": 20,
        },
        requested_workers=2,
        trial_limit=5,
    )

    assert len(commands) == len(results) == 2
    assert scheduler["status"] == "cloud_cap_exhausted"
    assert scheduler["request_cap"] == 20
    assert scheduler["new_trials"] == 2


@pytest.mark.parametrize("formal_passed", [True, False])
def test_rolling_threshold_runs_one_serial_formal_trial_and_records_result(
    tmp_path, monkeypatch, formal_passed
):
    fingerprint = "f" * 64
    store = qualification.EvidenceStore(tmp_path / "evidence")
    store.root.mkdir(parents=True)
    history = [
        {
            "passed": index < 4,
            "failure_signature": None if index < 4 else "plan/validation/sample_failure",
            "evidence_path": str(tmp_path / f"sample-{index}.json"),
            "session_id": f"sample-{index}", "formal": False,
        }
        for index in range(5)
    ]
    scoreboard = qualification._empty_scoreboard()
    scoreboard["fingerprints"][fingerprint] = {
        "tiers": {"t0": "pass", "t1": "pass"},
        "lanes": {qualification.DEFAULT_LANE: {
            "trials": 5, "passes": 4, "pass_rate": 0.8,
            "rolling_pass_rate": 0.8, "history": history,
            "top_signatures": [], "evidence_paths": [item["evidence_path"] for item in history],
            "iteration_ids": [], "stage_counts": {}, "stage_pass": {},
            "signature_counts": {},
        }},
    }
    store.scoreboard.write_text(json.dumps(scoreboard), encoding="utf-8")
    monkeypatch.setattr(qualification, "source_fingerprint", lambda: fingerprint)
    monkeypatch.setattr(
        qualification, "command_plan",
        lambda mode, path: [
            ("compileall", ["python"]), ("node-check", ["node"]),
            ("full-tests", ["python"]),
            ("mock-v11-e2e", ["python", str(path.parent / "mock-v11-e2e.json")]),
        ],
    )

    def fake_command(name, argv, timeout, env_overrides=None):
        if name == "mock-v11-e2e":
            path = Path(argv[-1])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"passed": True, "session_id": "mock"}), encoding="utf-8")
        return _command(name)

    formal_calls = []

    def fake_formal(iteration_dir, lane, timeout, lane_env):
        formal_calls.append(lane)
        summary = {
            "lane": lane, "trial_index": 0,
            "evidence_path": str(iteration_dir / "formal-v11-e2e.json"),
            "passed": formal_passed, "session_id": "formal-session",
            "failure_signature": None if formal_passed else "plan/validation/formal_failure",
            "formal": True,
            "stages": {"plan": {"status": "passed" if formal_passed else "failed"}},
        }
        return _command("formal", passed=formal_passed), summary

    monkeypatch.setattr(qualification, "run_command", fake_command)
    monkeypatch.setattr(qualification, "_comfyui_gpu_state", lambda: {"busy": False, "status": "ready"})
    monkeypatch.setattr(qualification, "_run_formal_trial", fake_formal)

    result = qualification.run_iteration(store, "full", 10, ())

    assert formal_calls == [qualification.DEFAULT_LANE]
    assert result.qualified is formal_passed
    assert result.scheduler["status"] == ("qualified" if formal_passed else "formal_failed")
    assert (store.root / "QUALIFIED.md").exists() is formal_passed
    updated = json.loads(store.scoreboard.read_text(encoding="utf-8"))
    lane = updated["fingerprints"][fingerprint]["lanes"][qualification.DEFAULT_LANE]
    assert lane["history"][-1]["formal"] is True
    if not formal_passed:
        assert lane["formal_failed"] is True
        selected, state = qualification._select_lane(
            qualification._load_lanes_config(qualification.DEFAULT_LANES_CONFIG),
            updated, fingerprint,
        )
        assert selected["name"] == qualification.DEFAULT_LANE
        assert state["status"] == "sampling"


def test_stuck_and_budget_stop_gpu_tiers_but_keep_deterministic_iteration_green(tmp_path):
    fingerprint = "f" * 64
    signature = "plan/validation/repeated"
    history = [
        {
            "passed": False, "failure_signature": signature,
            "evidence_path": f"trial-{index}.json", "session_id": f"s-{index}",
            "formal": False,
        }
        for index in range(qualification.STUCK_FAILURES)
    ]
    scoreboard = {
        "schema_version": "qualification-scoreboard/v1",
        "fingerprints": {fingerprint: {
            "history": [
                {**item, "lane": "local-llama31" if index < 3 else "local-gpt-oss-20b"}
                for index, item in enumerate(history)
            ],
            "lanes": {},
        }},
    }
    stuck = qualification._stuck_state(scoreboard, fingerprint)
    assert stuck["status"] == "stuck"
    assert stuck["lane"] == "multiple"
    assert stuck["failure_signature"] == signature

    store = qualification.EvidenceStore(tmp_path / "budget")
    evidence = qualification.IterationEvidence(
        iteration_id="budget", mode="full", started_at_epoch=1.0,
        finished_at_epoch=2.0, duration_seconds=1.0,
        source_fingerprint_before=fingerprint, source_fingerprint_after=fingerprint,
        stale=False, changed_files=(),
        commands=(_command("compileall"), _command("node-check"), _command("full-tests"), _command("mock-v11-e2e")),
        mock_e2e_result={"passed": True}, e2e_result=None,
        scheduler={"status": "budget_exhausted", "reason": "wall_clock_budget"},
        stop_condition="BUDGET", regression_delta={}, passed=True,
    )
    store.write(evidence)
    assert (store.root / "BUDGET.md").is_file()
    assert not (store.root / "QUALIFIED.md").exists()


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

    # 422 semantic batch rejection produces stable non-volatile signature
    semantic_stages = {name: {"status": "passed"} for name in adapter.EXPECTED_STAGES}
    semantic_stages["world"] = {
        "status": "failed",
        "http_status": 422,
        "response": {"error": "Semantic command batch rejected after bounded repair: unsafe content"},
    }
    semantic_result = {"stages": semantic_stages, "passed": True}
    adapter._finalize_result(semantic_result)
    assert semantic_result["passed"] is False
    assert semantic_result["failure_signature"] == "world/semantic_command/batch_rejected"

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
    assert args.trial_workers == 2
    assert args.trials_per_lane == 5
    assert args.budget_hours == 8.0
    assert args.flywheel_idle_seconds == 180.0
    assert args.flywheel_corpus == qualification.DEFAULT_FLYWHEEL_CORPUS
    assert args.lanes_config == qualification.DEFAULT_LANES_CONFIG
    assert args.enable_lane == []
    enabled = qualification.parse_args(["--enable-lane", "ollama-pro-glm-5-2"])
    assert enabled.enable_lane == ["ollama-pro-glm-5-2"]
    with pytest.raises(SystemExit):
        qualification.parse_args(["--timeout", "0"])
    with pytest.raises(SystemExit):
        qualification.parse_args(["--trial-workers", "0"])
