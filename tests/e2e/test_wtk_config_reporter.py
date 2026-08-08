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


def test_canon_qa_requires_typed_complete_per_check_evidence():
    valid = {
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
    assert _validate_canon_qa_verdict(valid) == (True, [])
    assert _validate_canon_qa_verdict({**valid, "pass": "false"})[0] is False
    schema = _canon_qa_schema()
    assert schema["properties"]["checks"]["properties"]["chair_count"] == {
        "type": "integer"
    }
    assert "const" not in schema["properties"]["checks"]["properties"]["chair_count"]


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
