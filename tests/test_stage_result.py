"""
Tests for src/stage_result.py — structured error reporting and graceful degradation.

Validates Requirements 1.5, 1.8, 9.5.
"""

import pytest

from src.models import StageFailure
from src.stage_result import (
    StageSuccess,
    determine_quality_label,
    format_failure_for_web,
    run_stage,
    run_stage_async,
)


# --- run_stage tests ---


def test_run_stage_success():
    """Function returns normally → StageSuccess."""

    def add(a, b):
        return a + b

    result = run_stage("math", add, 2, 3)
    assert isinstance(result, StageSuccess)
    assert result.stage == "math"


def test_run_stage_exception():
    """Function raises → StageFailure with stage name and diagnostic."""

    def explode():
        raise ValueError("boom")

    result = run_stage("exploding_stage", explode)
    assert isinstance(result, StageFailure)
    assert result.stage == "exploding_stage"
    assert result.reason_code == "unhandled_exception"
    assert "ValueError: boom" in result.diagnostic
    assert result.recoverable is False


def test_run_stage_preserves_result():
    """Successful result payload is correct."""

    def build_data():
        return {"key": "value", "count": 42}

    result = run_stage("data_stage", build_data)
    assert isinstance(result, StageSuccess)
    assert result.result == {"key": "value", "count": 42}


# --- format_failure_for_web tests ---


def test_format_failure_for_web():
    """StageFailure formats to correct dict for SSE delivery."""
    failure = StageFailure(
        stage="compiling",
        reason_code="timeout",
        diagnostic="Compilation timed out after 30s",
        recoverable=True,
    )
    web_dict = format_failure_for_web(failure)
    assert web_dict == {
        "status": "error",
        "stage": "compiling",
        "reason_code": "timeout",
        "message": "Compilation timed out after 30s",
        "recoverable": True,
    }


# --- determine_quality_label tests ---


def test_determine_quality_label_all_pass():
    """Parity + smoke passed → 'smoke_structural'."""
    assert determine_quality_label(parity_passed=True, smoke_passed=True) == "smoke_structural"


def test_determine_quality_label_smoke_fail():
    """Parity passed, smoke failed → 'smoke_skipped'."""
    assert determine_quality_label(parity_passed=True, smoke_passed=False) == "smoke_skipped"


def test_determine_quality_label_parity_fail():
    """Parity failed → 'parity_only'."""
    assert determine_quality_label(parity_passed=False, smoke_passed=False) == "parity_only"


# --- run_stage_async tests ---


@pytest.mark.asyncio
async def test_run_stage_async_success():
    """Async function returns normally → StageSuccess."""

    async def fetch_data():
        return [1, 2, 3]

    result = await run_stage_async("fetch", fetch_data)
    assert isinstance(result, StageSuccess)
    assert result.stage == "fetch"
    assert result.result == [1, 2, 3]


@pytest.mark.asyncio
async def test_run_stage_async_exception():
    """Async exception → StageFailure with correct diagnostics."""

    async def fail_async():
        raise RuntimeError("network timeout")

    result = await run_stage_async("network_stage", fail_async)
    assert isinstance(result, StageFailure)
    assert result.stage == "network_stage"
    assert result.reason_code == "unhandled_exception"
    assert "RuntimeError: network timeout" in result.diagnostic
    assert result.recoverable is False


# --- _handle_stage_failure integration test ---


def test_handle_stage_failure_sets_session_error():
    """WorldBuilder._handle_stage_failure sets session to ERROR and returns structured result."""
    from unittest.mock import patch, MagicMock
    import time

    with patch("src.pipeline.snapshot_session"):
        from src.pipeline import WorldBuilder

        builder = WorldBuilder(session_id="test-err")
        builder._mvp_started_at = time.monotonic()

        failure = StageFailure(
            stage="compiling",
            reason_code="timeout",
            diagnostic="Compilation timed out after 30s",
            recoverable=False,
        )
        result = builder._handle_stage_failure(
            failure, plan_warnings=[], model_used="lane-A", attempts=2,
        )

        assert result.success is False
        assert result.failure_stage == "compiling"
        assert result.failure_reason_code == "timeout"
        assert result.failure_diagnostic == "Compilation timed out after 30s"
        assert result.model_used == "lane-A"
        assert result.attempts == 2
        assert result.quality_label == "parity_only"
        assert builder.session.error == "Compilation timed out after 30s"


def test_handle_stage_failure_preserves_artifact_path():
    """_handle_stage_failure passes artifact_path through to result."""
    from unittest.mock import patch
    from pathlib import Path
    import time

    with patch("src.pipeline.snapshot_session"):
        from src.pipeline import WorldBuilder

        builder = WorldBuilder(session_id="test-art")
        builder._mvp_started_at = time.monotonic()

        failure = StageFailure(
            stage="validating",
            reason_code="parity_failed",
            diagnostic="Object count mismatch",
            recoverable=False,
        )
        result = builder._handle_stage_failure(
            failure,
            plan_warnings=[],
            model_used="",
            attempts=1,
            artifact_path=Path("/tmp/world.blend"),
        )

        assert result.artifact_path == Path("/tmp/world.blend")
        assert result.failure_stage == "validating"
