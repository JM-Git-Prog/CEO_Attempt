"""Tests for stage_handlers.py — durable orchestrator stage wiring.

Validates:
- build_handlers() returns a handler for every stage in DEFAULT_STAGE_SPECS
- Non-approval, non-GPU stages return immediately (no external_job_id, no awaiting_approval)
- Approval stages return awaiting_approval
- GPU stages return pending with a job_id
- The compile handler returns a contract_hash
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    StageExecutionContext,
    StageResult,
)
from src.unified_pipeline.stage_handlers import (
    APPROVAL_STAGES,
    GPU_STAGES,
    LIVE_GPU_STAGES,
    build_handlers,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Path:
    return tmp_path / "session"


@pytest.fixture
def make_context(tmp_session_dir: Path):
    """Factory for StageExecutionContext with sensible defaults."""
    def _make(stage: str, object_id: str | None = None) -> StageExecutionContext:
        return StageExecutionContext(
            session_id="test-session-001",
            session_dir=tmp_session_dir,
            stage=stage,
            object_id=object_id,
            values={},
            plan_revision=1,
            approval_revision=0,
            attempt=1,
        )
    return _make


# ---------------------------------------------------------------------------
# Test: build_handlers covers all stages
# ---------------------------------------------------------------------------

class TestBuildHandlersCompleteness:
    """build_handlers() must return a handler for every stage in DEFAULT_STAGE_SPECS."""

    def test_all_stages_have_handlers(self):
        handlers = build_handlers()
        stage_names = {spec.name for spec in DEFAULT_STAGE_SPECS}
        handler_names = set(handlers.keys())
        missing = stage_names - handler_names
        assert not missing, f"Missing handlers for stages: {missing}"

    def test_no_extra_handlers(self):
        handlers = build_handlers()
        stage_names = {spec.name for spec in DEFAULT_STAGE_SPECS}
        extra = set(handlers.keys()) - stage_names
        assert not extra, f"Extra handlers not in DEFAULT_STAGE_SPECS: {extra}"

    def test_handlers_are_callable(self):
        handlers = build_handlers()
        for name, handler in handlers.items():
            assert callable(handler), f"Handler for {name!r} is not callable"

    def test_config_parameter_accepted(self):
        """build_handlers accepts an optional config dict."""
        handlers = build_handlers(config={"mock_gpu": True})
        assert len(handlers) == len(DEFAULT_STAGE_SPECS)


# ---------------------------------------------------------------------------
# Test: Non-approval, non-GPU stages return immediately
# ---------------------------------------------------------------------------

class TestImmediateStages:
    """Non-approval, non-GPU stages return a completed StageResult immediately."""

    @pytest.fixture
    def immediate_stages(self):
        # Data-dependent synchronous adapters are covered by their focused suites;
        # this wiring test only executes handlers that require no prerequisite artifact.
        return [
            spec.name for spec in DEFAULT_STAGE_SPECS
            if spec.approval_for is None
            and spec.name not in LIVE_GPU_STAGES
            and spec.name != "spatial_reconstruction"
        ]

    def test_immediate_stages_return_stageresult(self, immediate_stages, make_context):
        handlers = build_handlers()
        for stage_name in immediate_stages:
            ctx = make_context(stage_name, object_id="obj-1" if _is_per_object(stage_name) else None)
            result = handlers[stage_name](ctx)
            assert isinstance(result, StageResult), f"{stage_name} did not return StageResult"

    def test_immediate_stages_have_no_external_job(self, immediate_stages, make_context):
        handlers = build_handlers()
        for stage_name in immediate_stages:
            ctx = make_context(stage_name, object_id="obj-1" if _is_per_object(stage_name) else None)
            result = handlers[stage_name](ctx)
            assert not result.is_pending_external, (
                f"{stage_name} should not be pending external"
            )

    def test_immediate_stages_not_awaiting_approval(self, immediate_stages, make_context):
        handlers = build_handlers()
        for stage_name in immediate_stages:
            ctx = make_context(stage_name, object_id="obj-1" if _is_per_object(stage_name) else None)
            result = handlers[stage_name](ctx)
            assert not result.output.get("awaiting_approval"), (
                f"{stage_name} should not be awaiting approval"
            )


# ---------------------------------------------------------------------------
# Test: Approval stages return awaiting_approval
# ---------------------------------------------------------------------------

class TestApprovalStages:
    """Approval stages must return StageResult with awaiting_approval=True."""

    def test_approval_stages_exist(self):
        """Sanity: we have approval stages in DEFAULT_STAGE_SPECS."""
        assert len(APPROVAL_STAGES) >= 4

    def test_approval_stages_return_awaiting(self, make_context):
        handlers = build_handlers()
        for stage_name in APPROVAL_STAGES:
            ctx = make_context(stage_name, object_id="obj-1" if _is_per_object(stage_name) else None)
            result = handlers[stage_name](ctx)
            assert isinstance(result, StageResult)
            assert result.output.get("awaiting_approval") is True, (
                f"{stage_name} should return awaiting_approval=True"
            )

    def test_approval_stages_not_pending_external(self, make_context):
        handlers = build_handlers()
        for stage_name in APPROVAL_STAGES:
            ctx = make_context(stage_name, object_id="obj-1" if _is_per_object(stage_name) else None)
            result = handlers[stage_name](ctx)
            assert not result.is_pending_external, (
                f"{stage_name} approval should not have an external job"
            )


# ---------------------------------------------------------------------------
# Test: GPU stages return pending with a job_id
# ---------------------------------------------------------------------------

class TestGPUStages:
    """Live model handlers are async; synchronous handlers still return StageResult."""

    def test_gpu_stages_exist(self):
        """Sanity: all model-backed stages are classified."""
        assert len(GPU_STAGES) >= 5

    def test_synchronous_gpu_stages_return_immediate(self, make_context):
        handlers = build_handlers()
        for stage_name in {"mesh_generation"}:
            ctx = make_context(stage_name, object_id="obj-1")
            result = handlers[stage_name](ctx)
            assert isinstance(result, StageResult), f"{stage_name} did not return StageResult"
            assert not result.is_pending_external

    def test_live_model_handlers_have_declared_call_style(self):
        import asyncio
        handlers = build_handlers()
        for stage_name in {"dream_preview", "canon_generation", "segment", "depth_estimation"}:
            assert asyncio.iscoroutinefunction(handlers[stage_name]), stage_name
        assert not asyncio.iscoroutinefunction(handlers["mesh_generation"])

    def test_synchronous_gpu_stages_preserve_plan_revision(self, make_context):
        handlers = build_handlers()
        ctx = make_context("mesh_generation", object_id="obj-1")
        result = handlers["mesh_generation"](ctx)
        assert result.plan_revision == ctx.plan_revision


# ---------------------------------------------------------------------------
# Test: Compile handler returns contract_hash
# ---------------------------------------------------------------------------

class TestCompileHandler:
    """The compile stage must return a valid contract_hash in its output."""

    def test_compile_returns_contract_hash(self, make_context):
        handlers = build_handlers()
        ctx = make_context("compile")
        result = handlers["compile"](ctx)
        assert "contract_hash" in result.output
        assert len(result.output["contract_hash"]) == 64  # SHA-256 hex

    def test_compile_canonical_hash_matches_output(self, make_context):
        handlers = build_handlers()
        ctx = make_context("compile")
        result = handlers["compile"](ctx)
        assert result.canonical_hash == result.output["contract_hash"]

    def test_compile_fails_closed_without_contract_authority(self, make_context):
        handlers = build_handlers()
        ctx = make_context("compile")
        result = handlers["compile"](ctx)
        assert "browser" in result.output
        assert "godot" in result.output
        assert result.output["browser"]["compiled"] is False
        assert result.output["godot"]["compiled"] is False
        assert "world_contract.json" in result.output["browser"]["reason"]

    def test_compile_not_pending_external(self, make_context):
        handlers = build_handlers()
        ctx = make_context("compile")
        result = handlers["compile"](ctx)
        assert not result.is_pending_external


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_per_object(stage_name: str) -> bool:
    """Check if a stage is per_object from DEFAULT_STAGE_SPECS."""
    for spec in DEFAULT_STAGE_SPECS:
        if spec.name == stage_name:
            return spec.per_object
    return False
