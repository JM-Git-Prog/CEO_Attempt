"""Tests for the zero-state qualification harness.

Uses asyncio.run() wrappers instead of @pytest.mark.asyncio to avoid
Windows hang issues with pytest-asyncio event loop teardown.

Validates Requirements 30.1, 30.2, 30.3, 30.4.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.unified_pipeline.orchestrator import DEFAULT_STAGE_SPECS
from src.unified_pipeline.qualification import (
    CANONICAL_PROMPT,
    QualificationHarness,
    QualificationRoundResult,
    StageEvidence,
)
from src.unified_pipeline.stage_handlers import GPU_STAGES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run an async coroutine synchronously — avoids pytest-asyncio Windows hang."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test 1: run_round() creates a fresh session (never reuses)
# ---------------------------------------------------------------------------


class TestFreshSession:
    """Requirement 30.1: Fresh-session creation — never reuse or restore."""

    def test_run_round_creates_fresh_session(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result1 = _run(harness.run_round())
        result2 = _run(harness.run_round())

        # Each round must have a unique session_id
        assert result1.session_id != result2.session_id
        assert result1.session_id.startswith("qual-")
        assert result2.session_id.startswith("qual-")

    def test_run_round_creates_unique_round_ids(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result1 = _run(harness.run_round())
        result2 = _run(harness.run_round())

        assert result1.round_id != result2.round_id

    def test_session_directory_is_created(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        session_dir = tmp_path / "sessions" / result.session_id
        assert session_dir.exists()


# ---------------------------------------------------------------------------
# Test 2: Canonical prompt is injected into conversation stage
# ---------------------------------------------------------------------------


class TestCanonicalPromptInjection:
    """Requirement 30.2: Canonical prompt injection."""

    def test_default_canonical_prompt_used(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        # Verify the diagnostic records the canonical prompt
        diag_path = tmp_path / "diagnostics.jsonl"
        assert diag_path.exists()
        lines = diag_path.read_text(encoding="utf-8").strip().splitlines()
        started_entry = json.loads(lines[0])
        assert started_entry["event"] == "round_started"
        assert started_entry["prompt"] == CANONICAL_PROMPT

    def test_custom_prompt_injected(self, tmp_path: Path):
        custom_prompt = "a medieval castle with a drawbridge and moat"
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round(canonical_prompt=custom_prompt))

        diag_path = tmp_path / "diagnostics.jsonl"
        lines = diag_path.read_text(encoding="utf-8").strip().splitlines()
        started_entry = json.loads(lines[0])
        assert started_entry["prompt"] == custom_prompt

    def test_canonical_prompt_is_dannys_kitchenette(self):
        """Danny's kitchenette prompt is the canonical default."""
        assert "small, warm kitchen" in CANONICAL_PROMPT
        assert "round table" in CANONICAL_PROMPT
        assert "two chairs" in CANONICAL_PROMPT
        assert "coffee maker" in CANONICAL_PROMPT
        assert "rain" in CANONICAL_PROMPT


# ---------------------------------------------------------------------------
# Test 3: All stages are traversed in order
# ---------------------------------------------------------------------------


class TestStageTraversal:
    """Requirement 30.3: Complete stage traversal in DEFAULT_STAGE_SPECS order."""

    def test_all_non_per_object_stages_traversed(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        # Should have evidence for stages that were executed
        traversed_stages = [ev.stage for ev in result.stage_results]
        # The pipeline should cover non-per-object global stages
        # Per-object stages may not appear if there are no objects in the brief
        global_stages = [
            s.name for s in DEFAULT_STAGE_SPECS if not s.per_object
        ]
        for stage in global_stages:
            assert stage in traversed_stages, (
                f"Stage {stage!r} was not traversed"
            )

    def test_stage_order_matches_default_specs(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        traversed_stages = [ev.stage for ev in result.stage_results]
        # Check that traversed stages are in the order defined by DEFAULT_STAGE_SPECS
        spec_order = [s.name for s in DEFAULT_STAGE_SPECS]
        # Traversed stages should match spec order (subset, same relative order)
        stage_indices = [spec_order.index(s) for s in traversed_stages]
        assert stage_indices == sorted(stage_indices), (
            "Stages were not traversed in DEFAULT_STAGE_SPECS order"
        )

    def test_pipeline_completes_successfully(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        assert result.passed is True
        assert result.failure_stage == ""
        assert result.failure_reason == ""


# ---------------------------------------------------------------------------
# Test 4: Artifact hashes and contract_hash are recorded
# ---------------------------------------------------------------------------


class TestArtifactRecording:
    """Requirement 30.4: Record source fingerprints, artifact hashes, contract hash."""

    def test_contract_hash_recorded(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        # world_contract stage produces a contract_hash
        assert result.contract_hash != ""
        assert len(result.contract_hash) == 64  # SHA-256 hex

    def test_stage_output_hashes_recorded(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        for evidence in result.stage_results:
            # Every completed stage should have an output hash
            if evidence.passed:
                assert evidence.output_hash != "", (
                    f"Stage {evidence.stage} has no output_hash"
                )
                assert len(evidence.output_hash) == 64

    def test_plan_and_approval_revisions_recorded(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        # All stages should have plan_revision == 1 in qualification
        for ev in result.stage_results:
            assert ev.plan_revision >= 1, (
                f"Stage {ev.stage} has plan_revision={ev.plan_revision}"
            )

    def test_diagnostics_are_append_only(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        _run(harness.run_round())
        _run(harness.run_round())

        diag_path = tmp_path / "diagnostics.jsonl"
        lines = diag_path.read_text(encoding="utf-8").strip().splitlines()
        # Two rounds should produce multiple entries (append-only)
        assert len(lines) > 10  # Each round produces several entries
        # Verify each line is valid JSON
        for line in lines:
            entry = json.loads(line)
            assert "recorded_at" in entry
            assert "event" in entry


# ---------------------------------------------------------------------------
# Test 5: Failed gate produces passed=False with failure stage recorded
# ---------------------------------------------------------------------------


class TestFailedGate:
    """Gate verification — automated and human final gates must pass."""

    def test_failed_automated_validation_produces_failure(self, tmp_path: Path):
        """When automated final validation fails, the round reports failure."""
        harness = QualificationHarness(tmp_path, mocked=True)

        result = _run(harness.run_round(
            inject_gate_failures={
                "automated_final_validation": {
                    "status": "automated_final_validation_failed",
                    "passed": False,
                    "report": {"passed": False, "failures": ["geometry_check"]},
                },
            }
        ))

        assert result.passed is False
        assert result.failure_stage == "automated_final_validation"
        assert "automated final validation" in result.failure_reason.lower()

    def test_failed_final_world_qa_produces_failure(self, tmp_path: Path):
        """When final-world QA fails, the round reports failure."""
        harness = QualificationHarness(tmp_path, mocked=True)

        result = _run(harness.run_round(
            inject_gate_failures={
                "final_world_qa": {
                    "status": "final_world_qa_failed",
                    "approved": False,
                    "report": {"passed": False, "failures": ["browser_world"]},
                },
            }
        ))

        assert result.passed is False
        assert result.failure_stage == "final_world_qa"
        assert "final-world" in result.failure_reason.lower()


# ---------------------------------------------------------------------------
# Test 6: Mocked vs live is correctly labeled
# ---------------------------------------------------------------------------


class TestMockedLabel:
    """Record whether each result is mocked or live."""

    def test_mocked_flag_on_harness(self, tmp_path: Path):
        harness_mocked = QualificationHarness(tmp_path / "m", mocked=True)
        harness_live = QualificationHarness(tmp_path / "l", mocked=False)

        assert harness_mocked.mocked is True
        assert harness_live.mocked is False

    def test_mocked_round_result_is_mocked_true(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        assert result.is_mocked is True

    def test_gpu_stages_labeled_as_mocked(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        for evidence in result.stage_results:
            if evidence.stage in GPU_STAGES:
                assert evidence.is_mocked is True, (
                    f"GPU stage {evidence.stage!r} should be labeled as mocked"
                )

    def test_non_gpu_stages_labeled_as_live(self, tmp_path: Path):
        harness = QualificationHarness(tmp_path, mocked=True)
        result = _run(harness.run_round())

        for evidence in result.stage_results:
            if evidence.stage not in GPU_STAGES:
                assert evidence.is_mocked is False, (
                    f"Non-GPU stage {evidence.stage!r} should be labeled as live"
                )

    def test_live_harness_labels_gpu_stages_as_live(self, tmp_path: Path):
        """When mocked=False, GPU stage evidence should be is_mocked=False."""
        harness = QualificationHarness(tmp_path, mocked=False)
        result = _run(harness.run_round())

        assert result.is_mocked is False
        for evidence in result.stage_results:
            # When harness.mocked=False, no stages are labeled as mocked
            assert evidence.is_mocked is False
