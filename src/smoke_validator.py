"""
Smoke validator: structural .blend validation via bpy in headless mode.

Opens the Runtime_Candidate in UPBGE_Editor --background and verifies that
logic bricks are wired, player controller text datablocks are present,
physics bodies are configured, and the scene loads without error.

Does NOT enter game mode, does NOT open a visible window, does NOT launch blenderplayer.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_runtime import RuntimePlan

_SMOKE_RESULT_MARKER = "SMOKE_RESULT="
_PROBE_SCRIPT = Path(__file__).parent / "assembler" / "smoke_probe.py"


@dataclass(frozen=True)
class SmokeCheck:
    """Result of a single structural smoke check."""

    name: str  # "player_controller_exists", "character_physics", "logic_bricks_wired", "scene_loads"
    passed: bool
    detail: str


@dataclass(frozen=True)
class SmokeValidationResult:
    """Aggregate result of all structural smoke checks on a .blend file."""

    passed: bool
    checks: tuple[SmokeCheck, ...]  # individual check results
    reason_code: str  # "structural_ok", "missing_controller", "physics_misconfigured", etc.
    duration_ms: int


def _determine_reason_code(checks: dict[str, dict[str, object]]) -> str:
    """Derive a reason_code from the individual check results."""
    if not checks.get("scene_loads", {}).get("passed", False):
        return "scene_load_error"
    if not checks.get("player_controller_exists", {}).get("passed", False):
        return "missing_controller"
    if not checks.get("character_physics", {}).get("passed", False):
        return "character_physics_missing"
    if not checks.get("logic_bricks_wired", {}).get("passed", False):
        return "logic_bricks_unwired"
    return "structural_ok"


def run_structural_smoke(
    capability: UPBGECapabilityReport,
    blend_path: Path,
    runtime_plan: RuntimePlan,
    *,
    timeout_s: float = 15.0,
) -> SmokeValidationResult:
    """Run structural smoke checks on a .blend file via UPBGE_Editor headless mode.

    Invokes UPBGE_Editor with --background to open the blend file and run the
    smoke_probe.py script which performs 4 structural checks via bpy.

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

    # Locate the smoke probe script
    probe_script = _PROBE_SCRIPT
    if not probe_script.exists():
        return SmokeValidationResult(
            passed=False,
            checks=(),
            reason_code="probe_parse_error",
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    # Build command: upbge --background blend_path --python smoke_probe.py
    command = [
        str(executable),
        "--background",
        str(blend_path),
        "--python",
        str(probe_script),
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
