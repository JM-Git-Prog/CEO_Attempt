from __future__ import annotations

import json
from pathlib import Path

from tools import flywheel_corpus as flywheel


def _write_trial(root: Path, nested: bool = True) -> Path:
    iteration = root / "output" / "qualification" / "iteration-1"
    path = (
        iteration / "trials" / "local-llama31" / "trial-01.json"
        if nested else iteration / "v11-e2e.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "v11-e2e-result/v1",
        "canonical_prompt": "Build a room",
        "session_id": "session-1",
        "started_at_epoch": 1.0,
        "finished_at_epoch": 2.0,
        "duration_seconds": 1.0,
        "stages": {"plan": {"status": "failed", "validation": {"valid": False}}},
        "failure_signature": "plan/validation/item_out_of_bounds",
        "failure_signatures": [{
            "stage": "plan", "rule": "validation",
            "detail": "item_out_of_bounds",
            "signature": "plan/validation/item_out_of_bounds",
        }],
        "passed": False,
    }), encoding="utf-8")
    iteration.mkdir(parents=True, exist_ok=True)
    (iteration / "summary.json").write_text(json.dumps({
        "source_fingerprint_before": "fingerprint-1",
        "lane_results": {"local-llama31": [{"evidence_path": str(path)}]},
    }), encoding="utf-8")
    session = root / "output" / "session-1"
    session.mkdir(parents=True)
    (session / "floor_plan_v1.json").write_text(json.dumps({"items": [{"id": "sofa"}]}), encoding="utf-8")
    (session / "session.json").write_text(json.dumps({
        "world_contract": {"contract_id": "world-1"},
        "repair_actions_applied": [{"action": "clamp"}],
    }), encoding="utf-8")
    return path


def test_build_record_joins_trial_iteration_and_session_evidence(tmp_path):
    trial = _write_trial(tmp_path)

    record = flywheel.build_record(trial, tmp_path)

    assert record["description"] == "Build a room"
    assert record["plan"] == {"items": [{"id": "sofa"}]}
    assert record["world_contract"] == {"contract_id": "world-1"}
    assert record["per_gate_verdicts"]["plan"]["validation"] == {"valid": False}
    assert record["failure_signatures"][0]["signature"] == "plan/validation/item_out_of_bounds"
    assert record["repair_actions_applied"] == [{"action": "clamp"}]
    assert record["model_lane"] == "local-llama31"
    assert record["source_fingerprint"] == "fingerprint-1"
    assert record["timestamps"]["trial_started_at_epoch"] == 1.0
    assert record["source_evidence_path"].endswith("trial-01.json")


def test_extract_is_append_only_deduplicated_and_cooperatively_preemptible(tmp_path):
    trial = _write_trial(tmp_path, nested=False)
    original = trial.read_bytes()
    corpus = tmp_path / "data" / "flywheel" / "corpus.jsonl"
    log = corpus.with_name("idle-jobs.log")

    first = flywheel.extract_corpus(root=tmp_path, corpus_path=corpus, log_path=log)
    first_bytes = corpus.read_bytes()
    second = flywheel.extract_corpus(root=tmp_path, corpus_path=corpus, log_path=log)
    preempted = flywheel.extract_corpus(
        root=tmp_path,
        corpus_path=corpus.with_name("preempted.jsonl"),
        log_path=log,
        stop_requested=lambda: True,
    )

    assert first == {
        "status": "complete", "appended": 1, "skipped": 0,
        "errors": 0, "duration_seconds": first["duration_seconds"],
    }
    assert second["appended"] == 0 and second["skipped"] == 1
    assert corpus.read_bytes() == first_bytes
    assert trial.read_bytes() == original
    assert preempted["status"] == "preempted" and preempted["appended"] == 0
    assert len(corpus.read_text(encoding="utf-8").splitlines()) == 1
    assert log.is_file()

    qualification = tmp_path / "output" / "qualification"
    (qualification / ".qualification.lock").write_text('{"pid": 999}', encoding="utf-8")
    from pytest import MonkeyPatch
    monkeypatch = MonkeyPatch()
    monkeypatch.setattr(flywheel, "_pid_alive", lambda pid: pid == 999)
    try:
        blocked = flywheel.extract_corpus(
            root=tmp_path, corpus_path=corpus.with_name("blocked.jsonl"), log_path=log
        )
    finally:
        monkeypatch.undo()
    assert blocked["status"] == "preempted" and blocked["appended"] == 0
