"""Property-based tests for sidecar structured failure (Property 9).

**Validates: Requirements 7.2, 7.4, 7.7**

Property 9: Sidecar Structured Failure
- For any invalid sidecar state (missing capability, non-zero exit code, absent output
  files, exceeded limits), the sidecar SHALL return a SidecarResult with success=False,
  a non-empty reason_code, and — for process failures — the exit code and up to 2MB of
  captured output.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st

import src.upbge_sidecar as sidecar
from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_compiler import CompilerOutputFlags
from src.upbge_sidecar import (
    SIDECAR_RESULT_VERSION,
    SidecarLimits,
    SidecarResult,
    run_upbge_sidecar,
)
from tests.upbge_test_support import build_test_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verified_capability(executable: Path) -> UPBGECapabilityReport:
    """Return a capability report that passes sidecar verification."""
    return UPBGECapabilityReport(
        available=True,
        verified=True,
        compatible=True,
        executable_path=str(executable),
        product="UPBGE",
        supports_game_runtime=True,
        supports_eevee=True,
        supports_gltf=True,
        reason_code="verified",
    )


def _unverified_capability() -> UPBGECapabilityReport:
    """Return a default (unverified) capability report."""
    return UPBGECapabilityReport()


def _valid_canonical_bytes() -> bytes:
    """Return a valid canonical contract as bytes."""
    return build_test_contract().canonical_bytes()


# ---------------------------------------------------------------------------
# Failure mode enum for strategy selection
# ---------------------------------------------------------------------------

FAILURE_MODES = [
    "unverified_upbge_executable",
    "noncanonical_world_contract",
    "canonical_input_must_be_bytes",
    "input_limit_exceeded",
    "resource_limit_exceeded",
    "process_start_failed",
    "sidecar_timeout",
    "compiler_process_failure",
]

failure_mode_st = st.sampled_from(FAILURE_MODES)

# Strategy for non-zero exit codes (used for compiler_process_failure)
nonzero_exit_code_st = st.integers(min_value=1, max_value=255)

# Strategy for stderr content (simulating captured process output)
stderr_content_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), min_codepoint=32, max_codepoint=126),
    min_size=1,
    max_size=200,
)


# ---------------------------------------------------------------------------
# Property 9: Sidecar Structured Failure
# ---------------------------------------------------------------------------


@given(
    failure_mode=failure_mode_st,
    exit_code=nonzero_exit_code_st,
    stderr_text=stderr_content_st,
)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_9_sidecar_structured_failure(
    tmp_path_factory,
    failure_mode: str,
    exit_code: int,
    stderr_text: str,
):
    """Property 9: Any invalid sidecar state returns structured failure.

    **Validates: Requirements 7.2, 7.4, 7.7**

    For any failure mode, verify:
    - result.success is False
    - result.reason_code is a non-empty string
    - result.schema_version == "upbge-sidecar-result/v1"
    - For process failures (non-zero exit, timeout): stdout_tail or stderr_tail
      contains captured output
    """
    tmp_path = tmp_path_factory.mktemp("sidecar_fail")
    canonical = _valid_canonical_bytes()

    if failure_mode == "unverified_upbge_executable":
        # Unverified capability → immediate rejection
        result = run_upbge_sidecar(_unverified_capability(), canonical, tmp_path)

    elif failure_mode == "noncanonical_world_contract":
        # Append garbage to make it non-canonical
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")
        bad_contract = canonical + b"\n"
        result = run_upbge_sidecar(
            _verified_capability(executable), bad_contract, tmp_path
        )

    elif failure_mode == "canonical_input_must_be_bytes":
        # Pass a non-bytes value (string)
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")
        result = run_upbge_sidecar(
            _verified_capability(executable),
            "not bytes",  # type: ignore[arg-type]
            tmp_path,
        )

    elif failure_mode == "input_limit_exceeded":
        # Set max_input_bytes to 1 so the valid contract exceeds it
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")
        result = run_upbge_sidecar(
            _verified_capability(executable),
            canonical,
            tmp_path,
            limits=SidecarLimits(max_input_bytes=1),
        )

    elif failure_mode == "resource_limit_exceeded":
        # Set max_objects=1 so the compiler plan exceeds it (test contract has multiple objects)
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")
        with patch.object(
            sidecar.subprocess,
            "Popen",
            side_effect=AssertionError("must not launch"),
        ):
            result = run_upbge_sidecar(
                _verified_capability(executable),
                canonical,
                tmp_path,
                limits=SidecarLimits(max_objects=1),
            )

    elif failure_mode == "process_start_failed":
        # Make Popen raise OSError
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")

        with patch.object(
            sidecar.subprocess,
            "Popen",
            side_effect=OSError(f"simulated: {stderr_text}"),
        ):
            result = run_upbge_sidecar(
                _verified_capability(executable), canonical, tmp_path
            )

    elif failure_mode == "sidecar_timeout":
        # Simulate a process that never finishes within a tiny wall_time
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")

        class TimeoutProcess:
            def __init__(self, command, **kwargs):
                self.returncode = None
                self.stdout = io.BytesIO(b"timeout stdout content")
                self.stderr = io.BytesIO(stderr_text.encode("utf-8", errors="replace"))
                self.pid = 12345

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        with patch.object(sidecar.subprocess, "Popen", TimeoutProcess):
            with patch.object(sidecar, "_terminate", lambda p: p.kill()):
                result = run_upbge_sidecar(
                    _verified_capability(executable),
                    canonical,
                    tmp_path,
                    limits=SidecarLimits(wall_time_s=0.001),
                )

    elif failure_mode == "compiler_process_failure":
        # Non-zero exit code with captured stderr
        executable = tmp_path / "upbge.exe"
        executable.write_bytes(b"fake")

        class FailedProcess:
            def __init__(self, command, **kwargs):
                self.returncode = exit_code
                self.stdout = io.BytesIO(b"stdout from failed compile")
                self.stderr = io.BytesIO(stderr_text.encode("utf-8", errors="replace"))
                self.pid = 54321

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def kill(self):
                self.returncode = -9

        with patch.object(sidecar.subprocess, "Popen", FailedProcess):
            result = run_upbge_sidecar(
                _verified_capability(executable), canonical, tmp_path
            )

    else:
        raise AssertionError(f"Unknown failure mode: {failure_mode}")

    # --- Universal assertions for ALL failure modes ---

    # 1. result.success must be False
    assert result.success is False, (
        f"Expected success=False for failure mode '{failure_mode}', got success=True"
    )

    # 2. result.reason_code must be a non-empty string
    assert isinstance(result.reason_code, str), (
        f"Expected reason_code to be str, got {type(result.reason_code)}"
    )
    assert len(result.reason_code) > 0, (
        f"Expected non-empty reason_code for failure mode '{failure_mode}'"
    )

    # 3. result.schema_version must match the expected version
    assert result.schema_version == SIDECAR_RESULT_VERSION, (
        f"Expected schema_version '{SIDECAR_RESULT_VERSION}', "
        f"got '{result.schema_version}'"
    )

    # --- Process failure-specific assertions ---

    if failure_mode == "sidecar_timeout":
        # Timeout must report status="timed_out" and violated_limit="wall_time_s"
        assert result.status == "timed_out", (
            f"Expected status='timed_out', got '{result.status}'"
        )
        assert result.violated_limit == "wall_time_s", (
            f"Expected violated_limit='wall_time_s', got '{result.violated_limit}'"
        )
        # Must have captured output (stdout or stderr)
        assert result.stdout_tail or result.stderr_tail, (
            "Timeout failure must capture process output (stdout_tail or stderr_tail)"
        )

    elif failure_mode == "compiler_process_failure":
        # Non-zero exit must report status="failed" and capture stderr
        assert result.status == "failed", (
            f"Expected status='failed', got '{result.status}'"
        )
        assert result.return_code == exit_code, (
            f"Expected return_code={exit_code}, got {result.return_code}"
        )
        # Must have captured output (stdout or stderr)
        assert result.stdout_tail or result.stderr_tail, (
            "Non-zero exit failure must capture process output"
        )

    elif failure_mode == "input_limit_exceeded":
        # Input limit exceeded must report the violated limit
        assert result.violated_limit == "max_input_bytes", (
            f"Expected violated_limit='max_input_bytes', got '{result.violated_limit}'"
        )

    elif failure_mode == "resource_limit_exceeded":
        # Resource limit exceeded must identify which limit
        assert result.violated_limit is not None and result.violated_limit != "", (
            "Resource limit failure must identify the violated limit"
        )
