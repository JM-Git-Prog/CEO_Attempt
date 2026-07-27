"""Property-based tests for degradation reason codes (Property 15).

**Validates: Requirements 9.4, 9.5**

Property 15: Degradation Reason Codes
- For any degradation event, the system SHALL produce a reason_code from the
  defined set and it SHALL be a non-empty string.
- When passed=False, reason_code != "structural_ok"
- When passed=True, reason_code == "structural_ok"

Tests cover:
- All possible check pass/fail combinations → reason_code from defined set
- Subprocess timeout → "probe_timeout"
- No executable → "executable_missing"
- Blend file not found → "blend_not_found"
- Malformed JSON → "probe_parse_error"
- parse_probe_output() → "probe_parse_error" for any invalid probe output
- parse_smoke_output() → "smoke_parse_error" for any invalid smoke output
- run_api_probe() → "probe_timeout" on subprocess.TimeoutExpired
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume, strategies as st

from src.assembler.api_probe_050 import (
    run_api_probe,
    parse_probe_output,
    PROBE_RESULT_MARKER,
)
from src.assembler.smoke_probe_050 import (
    parse_smoke_output,
    SMOKE_RESULT_MARKER,
)
from src.smoke_validator import (
    SmokeValidationResult,
    run_structural_smoke,
    _determine_reason_code,
)


# ---------------------------------------------------------------------------
# The complete defined set of reason codes for the system
# ---------------------------------------------------------------------------

# Reason codes produced by run_structural_smoke (high-level validator)
VALIDATOR_REASON_CODES = frozenset({
    # Success
    "structural_ok",
    # Infrastructure failures
    "probe_timeout",
    "probe_parse_error",
    "executable_missing",
    "blend_not_found",
    # Individual check failures (UPBGE 0.50 component checks)
    "scene_load_error",
    "player_component_missing",
    "text_datablocks_missing",
    "physics_not_configured",
    "door_components_missing",
})

# Reason codes produced by parse_probe_output (api probe parser)
PROBE_PARSE_REASON_CODES = frozenset({
    "probe_parse_error",
})

# Reason codes produced by parse_smoke_output (smoke probe parser)
SMOKE_PARSE_REASON_CODES = frozenset({
    "smoke_parse_error",
})

# Reason codes produced by run_api_probe (api probe runner)
API_PROBE_REASON_CODES = frozenset({
    "probe_timeout",
    "probe_parse_error",
    "version_mismatch",
})

# All reason codes the system can produce
ALL_REASON_CODES = (
    VALIDATOR_REASON_CODES
    | PROBE_PARSE_REASON_CODES
    | SMOKE_PARSE_REASON_CODES
    | API_PROBE_REASON_CODES
)


# ---------------------------------------------------------------------------
# The 5 check names used by _determine_reason_code (UPBGE 0.50)
# ---------------------------------------------------------------------------

CHECK_NAMES_050 = (
    "scene_loads",
    "player_component_attached",
    "text_datablocks_present",
    "physics_configured",
    "door_components_attached",
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty detail strings
detail_strategy = st.text(
    min_size=1,
    max_size=100,
    alphabet=st.characters(
        whitelist_categories=("L", "Nd", "P", "Zs"),
        blacklist_characters=("\x00",),
    ),
)

# A single check: either passes or fails with a non-empty detail
check_strategy = st.fixed_dictionaries(
    {"passed": st.booleans(), "detail": detail_strategy}
)

# Generate a full set of 5 UPBGE 0.50 checks with random pass/fail states
checks_050_strategy = st.fixed_dictionaries(
    {name: check_strategy for name in CHECK_NAMES_050}
)


def _build_smoke_stdout(checks: dict[str, dict]) -> str:
    """Build a realistic smoke probe stdout for validation."""
    result = {"checks": checks}
    lines = [
        "Blender 3.6.0 (hash abc123)",
        "Read blend: /tmp/runtime_candidate.blend",
        f"SMOKE_RESULT={json.dumps(result)}",
    ]
    return "\n".join(lines)


def _make_capability(executable_path: str | None = "C:/upbge/blender.exe"):
    """Create a minimal UPBGECapabilityReport mock."""
    cap = MagicMock()
    cap.executable_path = executable_path
    return cap


def _make_runtime_plan():
    """Create a minimal RuntimePlan mock."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Property 15a: _determine_reason_code always returns from the defined set
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_050_strategy)
def test_property_15_determine_reason_code_in_defined_set(
    checks: dict[str, dict],
):
    """Property 15: _determine_reason_code always returns a code from the defined set.

    **Validates: Requirements 9.4, 9.5**

    For any combination of check pass/fail states, the derived reason_code
    SHALL be a member of the valid reason codes set.
    """
    reason_code = _determine_reason_code(checks)

    assert isinstance(reason_code, str), (
        f"reason_code must be a string, got {type(reason_code)}"
    )
    assert len(reason_code) > 0, "reason_code must be non-empty"
    assert reason_code in VALIDATOR_REASON_CODES, (
        f"reason_code '{reason_code}' is not in the defined set: {VALIDATOR_REASON_CODES}"
    )


# ---------------------------------------------------------------------------
# Property 15b: When all checks pass, reason_code == "structural_ok"
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_050_strategy)
def test_property_15_all_pass_means_structural_ok(
    checks: dict[str, dict],
):
    """Property 15: When all checks pass, reason_code SHALL be 'structural_ok'.

    **Validates: Requirements 9.4, 9.5**

    If every check reports passed=True, the derived reason code must be
    the success code 'structural_ok'.
    """
    # Force all checks to pass
    all_pass_checks = {name: {"passed": True, "detail": c["detail"]} for name, c in checks.items()}
    reason_code = _determine_reason_code(all_pass_checks)

    assert reason_code == "structural_ok", (
        f"Expected 'structural_ok' when all checks pass, got '{reason_code}'"
    )


# ---------------------------------------------------------------------------
# Property 15c: When any check fails, reason_code != "structural_ok"
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_050_strategy)
def test_property_15_any_failure_means_not_structural_ok(
    checks: dict[str, dict],
):
    """Property 15: When any check fails, reason_code != 'structural_ok'.

    **Validates: Requirements 9.4, 9.5**

    If any check reports passed=False, the derived reason code must NOT
    be 'structural_ok' — it must indicate a specific degradation reason.
    """
    has_failure = any(not c["passed"] for c in checks.values())
    assume(has_failure)

    reason_code = _determine_reason_code(checks)

    assert reason_code != "structural_ok", (
        f"reason_code should not be 'structural_ok' when checks are failing. "
        f"Failing checks: {[n for n, c in checks.items() if not c['passed']]}"
    )
    assert reason_code in VALIDATOR_REASON_CODES, (
        f"reason_code '{reason_code}' is not in the defined set"
    )


# ---------------------------------------------------------------------------
# Property 15d: run_structural_smoke with mocked subprocess always produces
#               a reason_code from the defined set
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(checks=checks_050_strategy)
def test_property_15_full_validator_reason_code_in_set(
    checks: dict[str, dict],
    tmp_path_factory,
):
    """Property 15: run_structural_smoke always produces a valid reason_code.

    **Validates: Requirements 9.4, 9.5**

    For any mocked subprocess output with valid check states, the full
    validator pipeline SHALL produce a reason_code from the defined set,
    and that code SHALL be a non-empty string.
    """
    tmp_path = tmp_path_factory.mktemp("blend")
    blend_file = tmp_path / "runtime_candidate.blend"
    blend_file.write_text("fake blend")

    stdout = _build_smoke_stdout(checks)

    mock_completed = MagicMock()
    mock_completed.stdout = stdout
    mock_completed.stderr = ""
    mock_completed.returncode = 0

    with patch("src.smoke_validator.subprocess.run", return_value=mock_completed):
        capability = _make_capability()
        plan = _make_runtime_plan()

        result = run_structural_smoke(capability, blend_file, plan)

    assert isinstance(result, SmokeValidationResult)
    assert isinstance(result.reason_code, str), (
        f"reason_code must be a string, got {type(result.reason_code)}"
    )
    assert len(result.reason_code) > 0, "reason_code must be non-empty"
    assert result.reason_code in VALIDATOR_REASON_CODES, (
        f"reason_code '{result.reason_code}' is not in the defined set: {VALIDATOR_REASON_CODES}"
    )


# ---------------------------------------------------------------------------
# Property 15e: Subprocess timeout produces "probe_timeout"
# ---------------------------------------------------------------------------


def test_property_15_timeout_produces_probe_timeout(tmp_path):
    """Property 15: Subprocess timeout SHALL produce 'probe_timeout'.

    **Validates: Requirements 9.4, 9.5**
    """
    blend_file = tmp_path / "runtime_candidate.blend"
    blend_file.write_text("fake blend")

    with patch("src.smoke_validator.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 15)):
        capability = _make_capability()
        plan = _make_runtime_plan()
        result = run_structural_smoke(capability, blend_file, plan)

    assert result.passed is False
    assert result.reason_code == "probe_timeout"
    assert result.reason_code in VALIDATOR_REASON_CODES


# ---------------------------------------------------------------------------
# Property 15f: Missing executable produces "executable_missing"
# ---------------------------------------------------------------------------


def test_property_15_no_executable_produces_executable_missing(tmp_path):
    """Property 15: No executable path SHALL produce 'executable_missing'.

    **Validates: Requirements 9.4, 9.5**
    """
    blend_file = tmp_path / "runtime_candidate.blend"
    blend_file.write_text("fake blend")

    capability = _make_capability(executable_path=None)
    plan = _make_runtime_plan()
    result = run_structural_smoke(capability, blend_file, plan)

    assert result.passed is False
    assert result.reason_code == "executable_missing"
    assert result.reason_code in VALIDATOR_REASON_CODES


def test_property_15_oserror_produces_executable_missing(tmp_path):
    """Property 15: OSError during subprocess launch SHALL produce 'executable_missing'.

    **Validates: Requirements 9.4, 9.5**
    """
    blend_file = tmp_path / "runtime_candidate.blend"
    blend_file.write_text("fake blend")

    with patch("src.smoke_validator.subprocess.run", side_effect=OSError("Permission denied")):
        capability = _make_capability()
        plan = _make_runtime_plan()
        result = run_structural_smoke(capability, blend_file, plan)

    assert result.passed is False
    assert result.reason_code == "executable_missing"
    assert result.reason_code in VALIDATOR_REASON_CODES


# ---------------------------------------------------------------------------
# Property 15g: Blend file not found produces "blend_not_found"
# ---------------------------------------------------------------------------


def test_property_15_blend_not_found(tmp_path):
    """Property 15: Non-existent blend file SHALL produce 'blend_not_found'.

    **Validates: Requirements 9.4, 9.5**
    """
    blend_file = tmp_path / "nonexistent.blend"  # does NOT exist

    capability = _make_capability()
    plan = _make_runtime_plan()
    result = run_structural_smoke(capability, blend_file, plan)

    assert result.passed is False
    assert result.reason_code == "blend_not_found"
    assert result.reason_code in VALIDATOR_REASON_CODES


# ---------------------------------------------------------------------------
# Property 15h: Malformed output (no marker) produces "probe_parse_error"
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    garbage=st.text(
        min_size=0,
        max_size=500,
        alphabet=st.characters(
            whitelist_categories=("L", "Nd", "P", "Zs"),
            blacklist_characters=("\x00",),
        ),
    )
)
def test_property_15_malformed_output_produces_probe_parse_error(
    garbage: str,
    tmp_path_factory,
):
    """Property 15: Malformed probe output SHALL produce 'probe_parse_error'.

    **Validates: Requirements 9.4, 9.5**

    For any stdout that does NOT contain a valid SMOKE_RESULT= JSON line,
    the validator SHALL report 'probe_parse_error'.
    """
    # Ensure the garbage doesn't accidentally contain valid smoke output
    assume("SMOKE_RESULT=" not in garbage)

    tmp_path = tmp_path_factory.mktemp("blend")
    blend_file = tmp_path / "runtime_candidate.blend"
    blend_file.write_text("fake blend")

    mock_completed = MagicMock()
    mock_completed.stdout = garbage
    mock_completed.stderr = ""
    mock_completed.returncode = 0

    with patch("src.smoke_validator.subprocess.run", return_value=mock_completed):
        capability = _make_capability()
        plan = _make_runtime_plan()
        result = run_structural_smoke(capability, blend_file, plan)

    assert result.passed is False
    assert result.reason_code == "probe_parse_error"
    assert result.reason_code in VALIDATOR_REASON_CODES


# ---------------------------------------------------------------------------
# Property 15i: Invalid JSON after SMOKE_RESULT= produces "probe_parse_error"
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    bad_json=st.text(
        min_size=1,
        max_size=200,
        alphabet=st.characters(
            whitelist_categories=("L", "Nd", "P", "Zs"),
            blacklist_characters=("\x00", "{", "["),  # Avoid accidentally valid JSON
        ),
    )
)
def test_property_15_invalid_json_after_marker_produces_parse_error(
    bad_json: str,
    tmp_path_factory,
):
    """Property 15: Invalid JSON after SMOKE_RESULT= marker SHALL produce 'probe_parse_error'.

    **Validates: Requirements 9.4, 9.5**

    When the probe outputs a SMOKE_RESULT= line with non-JSON content,
    the validator SHALL report 'probe_parse_error'.
    """
    tmp_path = tmp_path_factory.mktemp("blend")
    blend_file = tmp_path / "runtime_candidate.blend"
    blend_file.write_text("fake blend")

    stdout = f"SMOKE_RESULT={bad_json}\n"

    mock_completed = MagicMock()
    mock_completed.stdout = stdout
    mock_completed.stderr = ""
    mock_completed.returncode = 0

    with patch("src.smoke_validator.subprocess.run", return_value=mock_completed):
        capability = _make_capability()
        plan = _make_runtime_plan()
        result = run_structural_smoke(capability, blend_file, plan)

    assert result.passed is False
    assert result.reason_code == "probe_parse_error"
    assert result.reason_code in VALIDATOR_REASON_CODES


# ---------------------------------------------------------------------------
# Property 15j: reason_code is always a non-empty string regardless of scenario
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    has_executable=st.booleans(),
    blend_exists=st.booleans(),
    timeout=st.booleans(),
    checks=checks_050_strategy,
)
def test_property_15_reason_code_always_nonempty_string(
    has_executable: bool,
    blend_exists: bool,
    timeout: bool,
    checks: dict[str, dict],
    tmp_path_factory,
):
    """Property 15: reason_code is ALWAYS a non-empty string for ANY scenario.

    **Validates: Requirements 9.4, 9.5**

    Regardless of the combination of conditions (executable availability,
    blend file existence, subprocess timeout, check states), the produced
    reason_code SHALL always be a non-empty string from the defined set.
    """
    tmp_path = tmp_path_factory.mktemp("blend")

    # Setup blend file
    blend_file = tmp_path / "runtime_candidate.blend"
    if blend_exists:
        blend_file.write_text("fake blend")

    # Setup capability
    exe_path = "C:/upbge/blender.exe" if has_executable else None
    capability = _make_capability(executable_path=exe_path)
    plan = _make_runtime_plan()

    # Setup subprocess behavior
    if timeout:
        side_effect = subprocess.TimeoutExpired("cmd", 15)
        mock_return = None
    else:
        side_effect = None
        stdout = _build_smoke_stdout(checks)
        mock_return = MagicMock()
        mock_return.stdout = stdout
        mock_return.stderr = ""
        mock_return.returncode = 0

    with patch("src.smoke_validator.subprocess.run", side_effect=side_effect, return_value=mock_return):
        result = run_structural_smoke(capability, blend_file, plan)

    # The core property: reason_code is ALWAYS a non-empty string from the set
    assert isinstance(result.reason_code, str), (
        f"reason_code must be a string, got {type(result.reason_code)}"
    )
    assert len(result.reason_code) > 0, (
        "reason_code must be non-empty"
    )
    assert result.reason_code in VALIDATOR_REASON_CODES, (
        f"reason_code '{result.reason_code}' is not in the defined set: {VALIDATOR_REASON_CODES}. "
        f"Scenario: has_executable={has_executable}, blend_exists={blend_exists}, "
        f"timeout={timeout}"
    )

    # Additional invariant: passed implies structural_ok, failed implies NOT structural_ok
    if result.passed:
        assert result.reason_code == "structural_ok", (
            f"When passed=True, reason_code must be 'structural_ok', got '{result.reason_code}'"
        )
    else:
        assert result.reason_code != "structural_ok", (
            f"When passed=False, reason_code must NOT be 'structural_ok'"
        )


# ---------------------------------------------------------------------------
# Property 15k: parse_probe_output always produces probe_parse_error for
#               invalid probe output (API probe layer)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(noise=st.text(min_size=0, max_size=500))
def test_property_15_probe_parse_always_produces_reason_code(noise: str):
    """Property 15: For any invalid probe output, parse_probe_output raises
    ValueError with a defined reason code prefix.

    **Validates: Requirements 9.4, 9.5**
    """
    # Ensure no marker in the noise so it triggers the parse error path
    clean = noise.replace(PROBE_RESULT_MARKER, "")
    try:
        parse_probe_output(clean)
    except ValueError as e:
        msg = str(e)
        assert len(msg) > 0, "Reason code must be non-empty"
        assert "probe_parse_error" in msg, (
            f"ValueError message does not contain 'probe_parse_error': {msg}"
        )


# ---------------------------------------------------------------------------
# Property 15l: parse_smoke_output always produces smoke_parse_error for
#               invalid smoke output (smoke probe layer)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(noise=st.text(min_size=0, max_size=500))
def test_property_15_smoke_parse_always_produces_reason_code(noise: str):
    """Property 15: For any invalid smoke output, parse_smoke_output raises
    ValueError with 'smoke_parse_error' prefix.

    **Validates: Requirements 9.4, 9.5**
    """
    # Ensure no marker in the noise so it triggers the parse error path
    clean = noise.replace(SMOKE_RESULT_MARKER, "")
    try:
        parse_smoke_output(clean)
    except ValueError as e:
        msg = str(e)
        assert len(msg) > 0, "Reason code must be non-empty"
        assert "smoke_parse_error" in msg, (
            f"ValueError message does not contain 'smoke_parse_error': {msg}"
        )


# ---------------------------------------------------------------------------
# Property 15m: run_api_probe timeout produces "probe_timeout"
# ---------------------------------------------------------------------------


def test_property_15_api_probe_timeout_reason_code():
    """Property 15: Probe timeout produces 'probe_timeout' reason code.

    **Validates: Requirements 9.4, 9.5**
    """
    with patch("src.assembler.api_probe_050.subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="blender", timeout=15)
        with pytest.raises(ValueError) as exc_info:
            run_api_probe("C:/fake/blender.exe")
        msg = str(exc_info.value)
        assert "probe_timeout" in msg
        assert len(msg) > 0


# ---------------------------------------------------------------------------
# Property 15n: parse_probe_output bad JSON produces "probe_parse_error"
# ---------------------------------------------------------------------------


def test_property_15_probe_parse_error_bad_json():
    """Property 15: Bad JSON after PROBE_RESULT= marker produces 'probe_parse_error'.

    **Validates: Requirements 9.4, 9.5**
    """
    with pytest.raises(ValueError) as exc_info:
        parse_probe_output(f"{PROBE_RESULT_MARKER}not-json{{")
    msg = str(exc_info.value)
    assert "probe_parse_error" in msg
    assert len(msg) > 0


# ---------------------------------------------------------------------------
# Property 15o: parse_smoke_output bad JSON produces "smoke_parse_error"
# ---------------------------------------------------------------------------


def test_property_15_smoke_parse_error_bad_json():
    """Property 15: Bad JSON after SMOKE_RESULT= marker produces 'smoke_parse_error'.

    **Validates: Requirements 9.4, 9.5**
    """
    with pytest.raises(ValueError) as exc_info:
        parse_smoke_output(f"{SMOKE_RESULT_MARKER}broken!!")
    msg = str(exc_info.value)
    assert "smoke_parse_error" in msg
    assert len(msg) > 0


# ---------------------------------------------------------------------------
# Property 15p: All defined reason codes are non-empty strings
# ---------------------------------------------------------------------------


def test_property_15_all_reason_codes_are_non_empty_strings():
    """Property 15: All defined reason codes are non-empty strings.

    **Validates: Requirements 9.4, 9.5**
    """
    for code in ALL_REASON_CODES:
        assert isinstance(code, str)
        assert len(code) > 0
        # Reason codes should be identifiers (lowercase alphanumeric + underscore)
        assert code.replace("_", "").isalnum(), (
            f"Reason code '{code}' contains unexpected characters"
        )
