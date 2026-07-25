"""
Structured stage result utilities for the MVP pipeline.

Every pipeline stage returns either a StageSuccess or a StageFailure —
no exceptions propagate to corrupt session state.

Implements Requirements 1.5, 1.8, 9.5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar, Generic

from src.models import StageFailure

T = TypeVar("T")


@dataclass(frozen=True)
class StageSuccess(Generic[T]):
    """Successful stage result with typed payload."""

    stage: str
    result: T


StageResult = StageSuccess[T] | StageFailure


def run_stage(stage_name: str, fn, *args, **kwargs) -> StageResult:
    """Execute a stage function with structured error handling.

    Wraps the function call in a try/except and returns either a
    StageSuccess or StageFailure. Never allows exceptions to propagate
    and corrupt session state.
    """
    try:
        result = fn(*args, **kwargs)
        return StageSuccess(stage=stage_name, result=result)
    except Exception as exc:
        return StageFailure(
            stage=stage_name,
            reason_code="unhandled_exception",
            diagnostic=f"{type(exc).__name__}: {exc}",
            recoverable=False,
        )


async def run_stage_async(stage_name: str, fn, *args, **kwargs) -> StageResult:
    """Async version of run_stage."""
    try:
        result = await fn(*args, **kwargs)
        return StageSuccess(stage=stage_name, result=result)
    except Exception as exc:
        return StageFailure(
            stage=stage_name,
            reason_code="unhandled_exception",
            diagnostic=f"{type(exc).__name__}: {exc}",
            recoverable=False,
        )


def format_failure_for_web(failure: StageFailure) -> dict:
    """Format a StageFailure for web interface display (Req 9.5).

    Returns a dict suitable for SSE delivery to the web client,
    reporting stage name, reason_code, and diagnostic message.
    """
    return {
        "status": "error",
        "stage": failure.stage,
        "reason_code": failure.reason_code,
        "message": failure.diagnostic,
        "recoverable": failure.recoverable,
    }


def determine_quality_label(parity_passed: bool, smoke_passed: bool) -> str:
    """Determine quality label from validation results.

    Graceful degradation chain (Req 1.8):
    - parity + smoke passed → "smoke_structural"
    - parity passed, smoke failed → "smoke_skipped"
    - parity failed → should not reach here (hard stop before this)
    """
    if parity_passed and smoke_passed:
        return "smoke_structural"
    elif parity_passed:
        return "smoke_skipped"
    else:
        return "parity_only"
