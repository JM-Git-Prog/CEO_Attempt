from __future__ import annotations

import json
from pathlib import Path

from tools import qualification_briefing as briefing


def _write_round(root: Path, name: str, trials: list[dict], *, relative: bool = False) -> Path:
    iteration = root / "output" / "qualification" / name
    lane = iteration / "trials" / "local-llama31"
    lane.mkdir(parents=True)
    results = []
    for index, payload in enumerate(trials, start=1):
        path = lane / f"trial-{index:02d}.json"
        path.write_text(json.dumps({
            "schema_version": "v11-e2e-result/v1",
            "session_id": f"session-{index}",
            "passed": False,
            "stages": {"world": {"status": "failed", "http_status": 500}},
            **payload,
        }), encoding="utf-8")
        evidence = path.relative_to(root).as_posix() if relative else str(path.resolve())
        results.append({"evidence_path": evidence})
    (iteration / "summary.json").write_text(json.dumps({
        "iteration_id": name,
        "source_fingerprint_before": "fingerprint",
        "duration_seconds": 12.0,
        "stale": False,
        "passed": False,
        "scheduler": {"status": "complete"},
        "lane_results": {"local-llama31": results},
    }), encoding="utf-8")
    return iteration


def _failure(signature: str, detail: str = "500:status_500") -> dict:
    stage, rule, _ = signature.split("/", 2)
    return {
        "failure_signature": signature,
        "failure_signatures": [{
            "signature": signature, "stage": stage, "rule": rule, "detail": detail,
        }],
    }


def test_custom_root_loads_relative_evidence_and_orders_rounds(tmp_path):
    older = _write_round(tmp_path, "20260722T110000_000000Z-old", [_failure("world/http_status/500:status_500")])
    newer = _write_round(tmp_path, "20260722T120000_000000Z-new", [_failure("plan/stage_status/failed")], relative=True)

    discovered = briefing.discover_iterations(tmp_path)
    loaded = briefing.load_iteration(discovered[0], tmp_path)

    assert discovered == (newer, older)
    assert len(loaded["trials"]) == 1
    assert loaded["trials"][0].name == "trial-01.json"


def test_fact_packet_has_deltas_counts_exact_values_and_paths(tmp_path):
    older = _write_round(tmp_path, "20260722T110000_000000Z-old", [_failure("world/http_status/500:status_500")])
    newer = _write_round(tmp_path, "20260722T120000_000000Z-new", [
        _failure("world/http_status/500:status_500"),
        _failure("plan/stage_status/failed", "failed"),
    ])

    facts = briefing.build_fact_packet([
        briefing.load_iteration(newer, tmp_path),
        briefing.load_iteration(older, tmp_path),
    ], tmp_path)

    assert facts["round_trial_count"] == 2
    assert facts["trial_count_delta"] == 1
    assert facts["signature_counts"]["world/http_status/500:status_500"] == 2
    assert {item["session_id"] for item in facts["occurrences"]} >= {"session-1"}
    assert all(item["evidence_path"].startswith("output/qualification/") for item in facts["occurrences"])


def test_run_briefing_uses_all_local_models_and_writes_substantive_artifacts(tmp_path):
    round_path = _write_round(tmp_path, "20260722T120000_000000Z-new", [_failure("world/http_status/500:status_500")])
    calls = []

    def model_runner(model, prompt, **kwargs):
        calls.append(model)
        if model == "nuextract":
            return "complete", '{"top_failure_count":1,"total_trials":1}'
        if model == "gpt-oss:20b":
            return "complete", "1. Optional semantic enrichment is rejected.\n\n## Next probe\nRun the focused semantic repair test."
        return "complete", "```diff\n--- a/example.py\n+++ b/example.py\n```"

    result = briefing.run_briefing(root=tmp_path, model_runner=model_runner)
    briefing_text = (tmp_path / "output" / "qualification" / "BRIEFING.md").read_text(encoding="utf-8")
    draft_text = (tmp_path / "output" / "qualification" / "DRAFT-PATCH.md").read_text(encoding="utf-8")

    assert result["status"] == "complete"
    assert calls == ["nuextract", "gpt-oss:20b", "qwen3-coder-next"]
    assert "world/http_status/500:status_500" in briefing_text
    assert "session-1" in briefing_text
    assert "[evidence: output/qualification/" in briefing_text
    assert f"briefing-round: {round_path.name}" in briefing_text
    assert "NOT APPLIED" in draft_text


def test_run_local_model_forces_utf8_and_unloads_model(monkeypatch):
    captured: dict = {}

    class CaptureStdin:
        def __init__(self):
            self.chunks: list[str] = []

        def write(self, value: str) -> None:
            self.chunks.append(value)

        def close(self) -> None:
            pass

    class CompleteProcess:
        returncode = 0

        def __init__(self):
            self.stdin = CaptureStdin()

        def poll(self) -> int:
            return 0

    def fake_popen(command, **kwargs):
        process = CompleteProcess()
        kwargs["stdout"].write("draft → ok".encode("utf-8"))
        captured.update(command=command, kwargs=kwargs, process=process)
        return process

    monkeypatch.setattr(briefing.subprocess, "Popen", fake_popen)

    status, text = briefing.run_local_model(
        "qwen3-coder-next", "bounded prompt",
        stop_requested=lambda: False, timeout_seconds=1,
    )

    payload = json.loads("".join(captured["process"].stdin.chunks))
    assert (status, text) == ("complete", "draft → ok")
    assert payload["keep_alive"] == 0
    assert captured["kwargs"]["env"]["PYTHONIOENCODING"] == "utf-8"
    assert captured["kwargs"]["env"]["PYTHONUTF8"] == "1"
    assert "sys.stdout.buffer.write" in captured["command"][2]


def test_model_failures_keep_deterministic_briefing_and_report_warning(tmp_path):
    _write_round(tmp_path, "20260722T120000_000000Z-new", [_failure("world/http_status/500:status_500")])

    traceback = "Traceback: UnicodeEncodeError → failed model output"
    result = briefing.run_briefing(
        root=tmp_path,
        model_runner=lambda *_args, **_kwargs: ("failed", traceback),
    )
    text = (tmp_path / "output" / "qualification" / "BRIEFING.md").read_text(encoding="utf-8")
    draft = (tmp_path / "output" / "qualification" / "DRAFT-PATCH.md").read_text(encoding="utf-8")

    assert result["status"] == "complete_with_model_warning"
    assert "world/http_status/500:status_500" in text
    assert "Local prose model unavailable" in text
    assert "Traceback" not in text
    assert "Traceback" not in draft
    assert "NEEDS-JUDGMENT: local patch draft unavailable." in draft


def test_preemption_writes_no_partial_artifacts(tmp_path):
    _write_round(tmp_path, "20260722T120000_000000Z-new", [_failure("world/http_status/500:status_500")])

    result = briefing.run_briefing(root=tmp_path, stop_requested=lambda: True)

    assert result["status"] == "preempted"
    assert not (tmp_path / "output" / "qualification" / "BRIEFING.md").exists()
    assert not (tmp_path / "output" / "qualification" / "DRAFT-PATCH.md").exists()
