"""Cheap strict World Test Kit scoring checks; no browser or model execution."""
from __future__ import annotations

import json

import httpx
import pytest

from src.unified_pipeline.object_manifest import build_selected_manifest
from tests.e2e.world_test_kit.config import WTKConfigError, load_wtk_config
from tests.e2e.world_test_kit.orchestrator import WorldTestOrchestrator
from tests.e2e.world_test_kit.playtester import (
    PipelineResult,
    PlaytesterAgent,
    _canon_qa_schema,
    _reconcile_canon_qa_verdicts,
    _validate_canon_qa_verdict,
)
from tests.e2e.world_test_kit.reporter import PlaytestReport, PlaytestReporter


def test_canonical_config_requires_100_out_of_100():
    config = load_wtk_config()
    assert config.strict_real is True
    assert config.pass_threshold == 100.0
    assert config.individual_minimum == 100.0
    assert PlaytestReport().pass_threshold == 100.0
    assert PlaytestReport().individual_minimum == 100.0


def test_strict_config_rejects_lower_environment_threshold(monkeypatch, tmp_path):
    config_path = tmp_path / "wtk.yaml"
    config_path.write_text("strict_real: true\n", encoding="utf-8")
    monkeypatch.setenv("WTK_PASS_THRESHOLD", "99")
    with pytest.raises(WTKConfigError, match="100/100"):
        load_wtk_config(config_path)


def test_reporter_requires_every_layer_to_score_100():
    reporter = PlaytestReporter(load_wtk_config())
    passed = reporter.generate({"layers": {"world": {"score": 100.0, "passed": True}}})
    failed = reporter.generate({"layers": {"world": {"score": 99.9, "passed": True}}})
    assert passed.passed is True
    assert failed.passed is False


def test_failed_partial_pipeline_scores_zero():
    class Agent:
        @staticmethod
        def wait_for_pipeline():
            return PipelineResult(
                success=False,
                stages_completed=["conversation", "brief", "dream_preview", "canon_generation"],
            )

    result = WorldTestOrchestrator(load_wtk_config())._run_pipeline_wait(Agent())
    assert result.passed is False
    assert result.score == 0.0


def test_fatal_layer_forces_zero_score_and_failure():
    report = PlaytestReporter(load_wtk_config()).generate({
        "layers": {
            "world": {"score": 100.0, "passed": True},
            "_fatal": {"score": 0.0, "passed": False, "error": "stopped"},
        }
    })
    assert report.passed is False
    assert report.overall_score == 0.0
    assert report.errors == ["stopped"]


def _valid_canon_verdict() -> dict:
    return {
        "pass": True,
        "failed_checks": [],
        "confidence": 0.9,
        "checks": {
            "kitchenette_geometry": True,
            "round_table_count": 1,
            "chair_count": 2,
            "counter_count": 1,
            "coffee_maker_count": 1,
            "rain_window_count": 1,
            "coherent_camera_openings": True,
            "plausible_finishes": True,
            "no_duplicate_or_deformed_required_objects": True,
        },
    }


def test_canon_qa_requires_typed_complete_exact_count_evidence():
    valid = _valid_canon_verdict()
    assert _validate_canon_qa_verdict(valid) == (True, [])
    assert _validate_canon_qa_verdict({**valid, "pass": "false"})[0] is False

    duplicate = {**valid, "checks": {**valid["checks"], "coffee_maker_count": 2}}
    passed, errors = _validate_canon_qa_verdict(duplicate)
    assert passed is False
    assert "coffee_maker_count must equal 1" in errors

    schema = _canon_qa_schema()
    count_schema = schema["properties"]["checks"]["properties"]
    for name in (
        "round_table_count", "chair_count", "counter_count",
        "coffee_maker_count", "rain_window_count",
    ):
        assert count_schema[name] == {"type": "integer"}
        assert "const" not in count_schema[name]


def test_canon_qa_fails_closed_on_independent_count_disagreement():
    primary = _valid_canon_verdict()
    cross_check = {
        **_valid_canon_verdict(),
        "confidence": 1.0,
        "checks": {
            **_valid_canon_verdict()["checks"],
            "coffee_maker_count": 2,
            "no_duplicate_or_deformed_required_objects": False,
        },
    }

    passed, errors = _reconcile_canon_qa_verdicts(primary, cross_check)

    assert passed is False
    assert any("cross-check disagreement for coffee_maker_count" in error for error in errors)
    assert any("coffee_maker_count must equal 1" in error for error in errors)
    assert any("no_duplicate_or_deformed_required_objects" in error for error in errors)


def test_canon_visual_qa_persists_both_screens_and_rejects_duplicate(monkeypatch, tmp_path):
    session_dir = tmp_path / "fresh-session"
    artifacts = session_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "canon.png").write_bytes(b"test-canon-image")
    (session_dir / "conversation.json").write_text(
        json.dumps({"turns": [{"role": "user", "content": "canonical room"}]}),
        encoding="utf-8",
    )
    primary = _valid_canon_verdict()
    cross_check = {
        **_valid_canon_verdict(),
        "pass": False,
        "failed_checks": ["duplicate coffee-making appliance"],
        "checks": {
            **_valid_canon_verdict()["checks"],
            "coffee_maker_count": 2,
            "no_duplicate_or_deformed_required_objects": False,
        },
    }
    responses = iter((primary, cross_check))
    payloads = []

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        def json(self):
            return {"message": {"content": json.dumps(next(responses))}}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def post(_url, **kwargs):
            payloads.append(kwargs["json"])
            return Response()

    agent = PlaytesterAgent(_ApprovalPage(), load_wtk_config(), "fresh-session")
    monkeypatch.setattr(agent, "_session_output_dir", lambda _session_id: session_dir)
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: Client())

    assert agent._canon_visual_qa("fresh-session") is False
    assert [payload["model"] for payload in payloads] == [
        load_wtk_config().vision_model, "qwen3.6:27b"
    ]
    assert "think" not in payloads[0]
    assert payloads[1]["think"] is False
    assert payloads[1]["options"]["num_predict"] == 1024
    evidence = json.loads((artifacts / "canon_vision_qa.json").read_text("utf-8"))
    assert evidence["schema_version"] == "canon-vision-qa/v3"
    assert evidence["pass"] is False
    assert evidence["screen_only"] is True
    assert evidence["release_authority"] == "headed_human_visual_inspection"
    assert set(evidence["screens"]) == {
        "primary_count_screen", "independent_duplicate_screen"
    }
    assert any("coffee_maker_count" in item for item in evidence["failed_checks"])


class _ApprovalPage:
    @staticmethod
    def evaluate(_script):
        return "approval-race-session"


class _PickerResponse:
    status_code = 200
    text = ""

    @staticmethod
    def raise_for_status():
        return None

    @staticmethod
    def json():
        return {"objects": [{"object_id": "canon-object-1"}]}


def _write_durable_blockout_acceptance(session_dir):
    decision = {
        "stage": "blockout_approval",
        "approved": True,
        "stale": False,
        "plan_revision": 1,
        "approval_revision": 1,
    }
    orchestrator_dir = session_dir / "orchestrator"
    checkpoints_dir = orchestrator_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True)
    (orchestrator_dir / "approvals.json").write_text(
        json.dumps({"active": {"blockout_approval::global": decision}}),
        encoding="utf-8",
    )
    (checkpoints_dir / "blockout_approval--global.json").write_text(
        json.dumps({
            "session_id": "approval-race-session",
            "stage": "blockout_approval",
            "completion_state": "completed",
            "plan_revision": 1,
            "approval_revision": 1,
            "output": {"approved": True},
        }),
        encoding="utf-8",
    )
    artifacts_dir = session_dir / "artifacts"
    artifacts_dir.mkdir()
    manifest = build_selected_manifest(
        {
            "canon_sha256": "canon-hash",
            "document_sha256": "detected-hash",
            "objects": [{"id": 0, "object_id": "canon-object-1", "name": "table"}],
        },
        ["canon-object-1"],
        plan_revision=1,
        approval_revision=1,
    )
    (artifacts_dir / "selected_objects.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_gate_timeout_reconciles_only_current_durable_acceptance(monkeypatch, tmp_path):
    session_dir = tmp_path / "approval-race-session"
    agent = PlaytesterAgent(_ApprovalPage(), load_wtk_config(), "approval-race-session")
    monkeypatch.setattr(agent, "_session_output_dir", lambda _session_id: session_dir)

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url):
            return _PickerResponse()

        def post(self, _url, **_kwargs):
            _write_durable_blockout_acceptance(session_dir)
            raise httpx.ReadTimeout("response lost after backend acceptance")

    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: Client())
    assert agent._try_approve_gate("blockout") is True


def test_gate_timeout_fails_closed_without_durable_acceptance(monkeypatch, tmp_path):
    session_dir = tmp_path / "approval-race-session"
    agent = PlaytesterAgent(_ApprovalPage(), load_wtk_config(), "approval-race-session")
    monkeypatch.setattr(agent, "_session_output_dir", lambda _session_id: session_dir)

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, _url):
            return _PickerResponse()

        def post(self, _url, **_kwargs):
            raise httpx.ReadTimeout("response lost before backend acceptance")

    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: Client())
    assert agent._try_approve_gate("blockout") is False
