"""
Smoke validator: structural .blend validation via bpy in headless mode.

Opens the Runtime_Candidate in UPBGE_Editor --background and verifies that
Python Components are attached, required text datablocks are present,
physics is configured, and the scene loads without error.

Does NOT enter game mode, does NOT open a visible window, does NOT launch blenderplayer.

Uses the UPBGE 0.50 smoke probe (smoke_probe_050.py) which verifies:
- scene_loads: .blend opens without bpy errors
- player_component_attached: player object has PlayerComponent (native or fallback)
- text_datablocks_present: required .py Text datablocks exist
- physics_configured: player has CHARACTER physics
- door_components_attached: door objects have DoorComponent registered
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from src.assembler.smoke_probe_050 import SMOKE_PROBE_SCRIPT_050, SMOKE_RESULT_MARKER
from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_runtime import RuntimePlan

_SMOKE_RESULT_MARKER = SMOKE_RESULT_MARKER


@dataclass(frozen=True)
class SmokeCheck:
    """Result of a single structural smoke check."""

    name: str  # "scene_loads", "player_component_attached", "text_datablocks_present", "physics_configured", "door_components_attached"
    passed: bool
    detail: str


@dataclass(frozen=True)
class SmokeValidationResult:
    """Aggregate result of all structural smoke checks on a .blend file."""

    passed: bool
    checks: tuple[SmokeCheck, ...]  # individual check results
    reason_code: str  # "structural_ok", "scene_load_error", "player_component_missing", etc.
    duration_ms: int


def _determine_reason_code(checks: dict[str, dict[str, object]]) -> str:
    """Derive a reason_code from the individual check results (UPBGE 0.50 checks)."""
    if not checks.get("scene_loads", {}).get("passed", False):
        return "scene_load_error"
    if not checks.get("player_component_attached", {}).get("passed", False):
        return "player_component_missing"
    if not checks.get("text_datablocks_present", {}).get("passed", False):
        return "text_datablocks_missing"
    if not checks.get("physics_configured", {}).get("passed", False):
        return "physics_not_configured"
    if not checks.get("door_components_attached", {}).get("passed", False):
        return "door_components_missing"
    return "structural_ok"


def run_structural_smoke(
    capability: UPBGECapabilityReport,
    blend_path: Path,
    runtime_plan: RuntimePlan,
    *,
    timeout_s: float = 15.0,
) -> SmokeValidationResult:
    """Run structural smoke checks on a .blend file via UPBGE_Editor headless mode.

    Invokes UPBGE_Editor with --background to run the smoke_probe_050.py script
    which performs 5 structural checks via bpy for UPBGE 0.50 component-based runtime.

    The blend path is passed as an argument after '--' so the probe can read it
    from sys.argv. Command: upbge --background --python <script_file> -- <blend_path>

    Does NOT enter game mode, does NOT open a visible window, does NOT launch blenderplayer.
    """
    started = time.monotonic()

    # Validate preconditions
    if not capability.executable_path:
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="executable_missing",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    executable = Path(capability.executable_path)
    if not blend_path.exists():
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="blend_not_found",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Write the probe script to a temp file for execution inside UPBGE
    try:
        probe_tmpfile = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            prefix="smoke_probe_050_",
            delete=False,
        )
        probe_tmpfile.write(SMOKE_PROBE_SCRIPT_050)
        probe_tmpfile.close()
        probe_script_path = probe_tmpfile.name
    except OSError:
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_parse_error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Build command: upbge --background --python <script_file> -- <blend_path>
    command = [
        str(executable),
        "--background",
        "--python",
        probe_script_path,
        "--",
        str(blend_path),
    ]

    # Run the probe subprocess
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            text=True,
            check=False,
        )
        stdout = completed.stdout
    except subprocess.TimeoutExpired:
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_timeout",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except OSError:
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="executable_missing",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    finally:
        # Clean up temp file
        try:
            Path(probe_script_path).unlink(missing_ok=True)
        except OSError:
            pass

    # Parse the SMOKE_RESULT= JSON line from stdout
    result_line: str | None = None
    for line in stdout.splitlines():
        if line.startswith(_SMOKE_RESULT_MARKER):
            result_line = line[len(_SMOKE_RESULT_MARKER):]
            break

    if result_line is None:
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_parse_error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    try:
        payload = json.loads(result_line)
    except (json.JSONDecodeError, ValueError):
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_parse_error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Extract checks from the probe output
    if not isinstance(payload, dict) or "checks" not in payload:
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_parse_error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    raw_checks = payload["checks"]
    if not isinstance(raw_checks, dict):
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_parse_error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Map to SmokeCheck instances
    smoke_checks: list[SmokeCheck] = []
    for name, check_data in raw_checks.items():
        if isinstance(check_data, dict):
            smoke_checks.append(SmokeCheck(
                name=str(name),
                passed=bool(check_data.get("passed", False)),
                detail=str(check_data.get("detail", "")),
            ))

    # Determine overall pass/fail and reason_code
    reason_code = _determine_reason_code(raw_checks)
    all_passed = reason_code == "structural_ok"

    duration_ms = int((time.monotonic() - started) * 1000)

    return SmokeValidationResult(
        passed=all_passed,
        checks=tuple(smoke_checks),
        reason_code=reason_code,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# UPBGE 0.50 standalone entry point (dict-returning interface)
# ---------------------------------------------------------------------------

# Evaluation order for reason_code determination
_SMOKE_CHECK_NAMES_050 = (
    "scene_loads",
    "player_component_attached",
    "text_datablocks_present",
    "physics_configured",
    "door_components_attached",
)


def run_structural_smoke_050(
    upbge_path: str,
    blend_path: str,
    *,
    timeout_s: float = 30.0,
) -> dict:
    """Run UPBGE 0.50 structural smoke checks and return a dict result.

    This is the standalone entry point that writes the probe script to a temp file,
    invokes UPBGE with ``--background --python <script> -- <blend_path>``, parses the
    SMOKE_RESULT= JSON output, and returns a structured dict.

    Args:
        upbge_path: Path to the UPBGE 0.50 executable.
        blend_path: Path to the runtime_candidate.blend file.
        timeout_s: Maximum seconds to wait for the probe subprocess.

    Returns:
        Dict with keys:
            passed (bool): True if all checks passed.
            reason_code (str): "smoke_passed" or the name of the first failed check.
            detail (str): Human-readable description of the result.
            checks (dict): The raw checks dict from the probe output.
    """
    import os
    import tempfile

    # Write probe script to temp file
    try:
        fd, probe_path = tempfile.mkstemp(suffix=".py", prefix="smoke_probe_050_")
        os.write(fd, SMOKE_PROBE_SCRIPT_050.encode("utf-8"))
        os.close(fd)
    except OSError as exc:
        return {
            "passed": False,
            "reason_code": "smoke_parse_error",
            "detail": f"Failed to write probe script: {exc}",
            "checks": {},
        }

    # Build command: upbge --background --python <script> -- <blend_path>
    command = [
        upbge_path,
        "--background",
        "--python",
        probe_path,
        "--",
        blend_path,
    ]

    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            text=True,
            check=False,
        )
        stdout = completed.stdout
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "reason_code": "smoke_timeout",
            "detail": f"Probe subprocess timed out after {timeout_s}s",
            "checks": {},
        }
    except OSError as exc:
        return {
            "passed": False,
            "reason_code": "smoke_parse_error",
            "detail": f"Failed to invoke UPBGE: {exc}",
            "checks": {},
        }
    finally:
        # Clean up temp file
        try:
            if os.path.exists(probe_path):
                os.unlink(probe_path)
        except OSError:
            pass

    # Parse SMOKE_RESULT= marker from stdout
    from src.assembler.smoke_probe_050 import parse_smoke_output

    try:
        payload = parse_smoke_output(stdout)
    except ValueError as exc:
        return {
            "passed": False,
            "reason_code": "smoke_parse_error",
            "detail": str(exc),
            "checks": {},
        }

    # Validate checks structure
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return {
            "passed": False,
            "reason_code": "smoke_parse_error",
            "detail": "Probe output 'checks' field is not a dict",
            "checks": {},
        }

    # Determine pass/fail and reason_code
    all_passed = all(
        isinstance(c, dict) and c.get("passed", False)
        for c in checks.values()
    )

    if all_passed:
        return {
            "passed": True,
            "reason_code": "smoke_passed",
            "detail": "All checks passed",
            "checks": checks,
        }

    # Find the first failed check in evaluation order
    first_failure_name = None
    first_failure_detail = ""
    for name in _SMOKE_CHECK_NAMES_050:
        check = checks.get(name, {})
        if isinstance(check, dict) and not check.get("passed", False):
            first_failure_name = name
            first_failure_detail = check.get("detail", "")
            break

    # Fallback: if somehow none matched in order, use generic
    if first_failure_name is None:
        first_failure_name = "unknown_failure"
        first_failure_detail = "A check failed but could not identify which"

    return {
        "passed": False,
        "reason_code": first_failure_name,
        "detail": first_failure_detail,
        "checks": checks,
    }
