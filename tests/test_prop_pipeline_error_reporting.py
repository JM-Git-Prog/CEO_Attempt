"""Property-based tests for pipeline error reporting.

**Validates: Requirements 1.5**

Uses Hypothesis to verify that pipeline error reporting preserves session state:
- StageFailure fields propagate correctly to MVPPipelineResult
- Session state transitions to ERROR without corruption
- run_stage wraps exceptions into structured StageFailure
- format_failure_for_web always produces a complete dict
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models import (
    MVPPipelineResult,
    PipelineState,
    PlanValidationWarning,
    StageFailure,
    WorldSession,
)
from src.pipeline import WorldBuilder
from src.stage_result import format_failure_for_web, run_stage


# --- Strategies ---

non_empty_text = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())

stage_failure_strategy = st.builds(
    StageFailure,
    stage=non_empty_text,
    reason_code=non_empty_text,
    diagnostic=non_empty_text,
    recoverable=st.booleans(),
)


class TestHandleStageFailureResultFields:
    """Property: _handle_stage_failure produces MVPPipelineResult with correct failure fields."""

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_result_has_success_false(self, failure: StageFailure):
        """For any StageFailure, the result always has success=False."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            result = builder._handle_stage_failure(failure, plan_warnings=[])
            assert result.success is False, (
                f"Expected success=False, got {result.success}"
            )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_result_failure_stage_matches(self, failure: StageFailure):
        """For any StageFailure, result.failure_stage matches failure.stage."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            result = builder._handle_stage_failure(failure, plan_warnings=[])
            assert result.failure_stage == failure.stage, (
                f"Expected failure_stage={failure.stage!r}, got {result.failure_stage!r}"
            )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_result_failure_reason_code_matches(self, failure: StageFailure):
        """For any StageFailure, result.failure_reason_code matches failure.reason_code."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            result = builder._handle_stage_failure(failure, plan_warnings=[])
            assert result.failure_reason_code == failure.reason_code, (
                f"Expected failure_reason_code={failure.reason_code!r}, "
                f"got {result.failure_reason_code!r}"
            )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_result_failure_diagnostic_matches(self, failure: StageFailure):
        """For any StageFailure, result.failure_diagnostic matches failure.diagnostic."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            result = builder._handle_stage_failure(failure, plan_warnings=[])
            assert result.failure_diagnostic == failure.diagnostic, (
                f"Expected failure_diagnostic={failure.diagnostic!r}, "
                f"got {result.failure_diagnostic!r}"
            )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_result_failure_fields_non_empty(self, failure: StageFailure):
        """For any StageFailure with non-empty inputs, all result failure fields are non-empty strings."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            result = builder._handle_stage_failure(failure, plan_warnings=[])
            assert isinstance(result.failure_stage, str) and len(result.failure_stage) > 0
            assert isinstance(result.failure_reason_code, str) and len(result.failure_reason_code) > 0
            assert isinstance(result.failure_diagnostic, str) and len(result.failure_diagnostic) > 0


class TestHandleStageFailureSessionState:
    """Property: _handle_stage_failure sets session to ERROR state without corruption."""

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_session_state_is_error(self, failure: StageFailure):
        """After _handle_stage_failure, session.state is PipelineState.ERROR."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            builder._handle_stage_failure(failure, plan_warnings=[])
            assert builder.session.state == PipelineState.ERROR, (
                f"Expected state=ERROR, got {builder.session.state!r}"
            )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_session_error_field_set(self, failure: StageFailure):
        """After _handle_stage_failure, session.error is set (non-None)."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            builder._handle_stage_failure(failure, plan_warnings=[])
            assert builder.session.error is not None, (
                "Expected session.error to be set, got None"
            )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_session_remains_serializable(self, failure: StageFailure):
        """After _handle_stage_failure, session can be serialized/deserialized without error."""
        with tempfile.TemporaryDirectory() as tmp:
            builder = _make_builder(tmp)
            builder._handle_stage_failure(failure, plan_warnings=[])
            # Serialize to JSON and back — must not raise
            json_str = builder.session.model_dump_json()
            restored = WorldSession.model_validate_json(json_str)
            assert restored.state == PipelineState.ERROR
            assert restored.error == failure.diagnostic


class TestRunStageWrapsExceptions:
    """Property: run_stage wraps any exception into a StageFailure with correct fields."""

    @given(
        stage_name=non_empty_text,
        exc_message=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=200, deadline=None)
    def test_run_stage_captures_exception(self, stage_name: str, exc_message: str):
        """run_stage wraps an exception into a StageFailure with matching stage name."""
        def raising_fn():
            raise ValueError(exc_message)

        result = run_stage(stage_name, raising_fn)
        assert isinstance(result, StageFailure), (
            f"Expected StageFailure, got {type(result).__name__}"
        )
        assert result.stage == stage_name, (
            f"Expected stage={stage_name!r}, got {result.stage!r}"
        )

    @given(
        stage_name=non_empty_text,
        exc_message=st.text(min_size=1, max_size=200),
    )
    @settings(max_examples=200, deadline=None)
    def test_run_stage_failure_has_non_empty_reason_code(self, stage_name: str, exc_message: str):
        """run_stage produces a StageFailure with a non-empty reason_code."""
        def raising_fn():
            raise RuntimeError(exc_message)

        result = run_stage(stage_name, raising_fn)
        assert isinstance(result, StageFailure)
        assert isinstance(result.reason_code, str) and len(result.reason_code) > 0, (
            f"Expected non-empty reason_code, got {result.reason_code!r}"
        )

    @given(
        stage_name=non_empty_text,
        exc_message=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
    )
    @settings(max_examples=200, deadline=None)
    def test_run_stage_failure_diagnostic_contains_message(self, stage_name: str, exc_message: str):
        """run_stage produces a StageFailure whose diagnostic contains the exception message."""
        def raising_fn():
            raise TypeError(exc_message)

        result = run_stage(stage_name, raising_fn)
        assert isinstance(result, StageFailure)
        assert isinstance(result.diagnostic, str) and len(result.diagnostic) > 0
        assert exc_message in result.diagnostic, (
            f"Expected diagnostic to contain {exc_message!r}, got {result.diagnostic!r}"
        )


class TestFormatFailureForWeb:
    """Property: format_failure_for_web always produces a dict with required keys."""

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_output_has_required_keys(self, failure: StageFailure):
        """For any StageFailure, format_failure_for_web returns a dict with all required keys."""
        result = format_failure_for_web(failure)
        required_keys = {"status", "stage", "reason_code", "message", "recoverable"}
        assert isinstance(result, dict), f"Expected dict, got {type(result).__name__}"
        missing = required_keys - set(result.keys())
        assert not missing, f"Missing keys: {missing}"

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_output_status_is_error(self, failure: StageFailure):
        """For any StageFailure, the output status is always 'error'."""
        result = format_failure_for_web(failure)
        assert result["status"] == "error", (
            f"Expected status='error', got {result['status']!r}"
        )

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_output_stage_matches(self, failure: StageFailure):
        """For any StageFailure, the output stage matches the input stage."""
        result = format_failure_for_web(failure)
        assert result["stage"] == failure.stage

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_output_reason_code_matches(self, failure: StageFailure):
        """For any StageFailure, the output reason_code matches the input reason_code."""
        result = format_failure_for_web(failure)
        assert result["reason_code"] == failure.reason_code

    @given(stage_failure_strategy)
    @settings(max_examples=200, deadline=None)
    def test_output_recoverable_matches(self, failure: StageFailure):
        """For any StageFailure, the output recoverable matches the input recoverable."""
        result = format_failure_for_web(failure)
        assert result["recoverable"] == failure.recoverable


# --- Helpers ---


def _make_builder(tmp_dir: str) -> WorldBuilder:
    """Create a minimal WorldBuilder instance for testing _handle_stage_failure."""
    import src.pipeline as pipeline_mod

    # Temporarily override OUTPUT_BASE so WorldBuilder writes to our temp dir
    original_base = pipeline_mod.OUTPUT_BASE
    pipeline_mod.OUTPUT_BASE = Path(tmp_dir)
    try:
        builder = WorldBuilder()
        # Set _mvp_started_at so duration_ms calculation doesn't error
        builder._mvp_started_at = time.monotonic()
        return builder
    finally:
        pipeline_mod.OUTPUT_BASE = original_base
