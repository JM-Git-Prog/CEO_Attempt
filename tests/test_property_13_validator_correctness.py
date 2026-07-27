"""Property-based tests for validator correctness (Property 13).

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

Property 13: Validator Correctness
- For any mocked .blend state (objects with/without components, text datablocks),
  validator reports `passed=True` only when ALL checks pass; reports specific
  `reason_code` for first failure; includes non-empty `detail` for every failing check.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, strategies as st

from src.smoke_validator import run_structural_smoke_050

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SMOKE_CHECK_NAMES_050 = (
    "scene_loads",
    "player_component_attached",
    "text_datablocks_present",
    "physics_configured",
    "door_components_attached",
)

SMOKE_RESULT_MARKER = "SMOKE_RESULT="


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for a single check's detail text (always non-empty)
detail_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=50,
)

# Strategy for the pass/fail state of each of the 5 checks
check_states_strategy = st.fixed_dictionaries({
    name: st.fixed_dictionaries({
        "passed": st.booleans(),
        "detail": detail_strategy,
    })
    for name in _SMOKE_CHECK_NAMES_050
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_probe_stdout(checks: dict[str, dict[str, object]]) -> str:
    """Build synthetic probe stdout with SMOKE_RESULT= marker.

    Mimics the output format of smoke_probe_050.py running inside UPBGE 0.50.
    """
    all_passed = all(c["passed"] for c in checks.values())
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": checks,
        "all_passed": all_passed,
    }
    # Include some typical UPBGE noise lines before the marker
    lines = [
        "Blender 5.0.1 (hash abc123)",
        "Read prefs: /home/user/.config/blender/5.0/userpref.blend",
        SMOKE_RESULT_MARKER + json.dumps(payload, sort_keys=True),
    ]
    return "\n".join(lines)


def _mock_subprocess_run(stdout: str):
    """Create a mock for subprocess.run that returns the given stdout."""
    mock_result = MagicMock()
    mock_result.stdout = stdout
    mock_result.stderr = ""
    mock_result.returncode = 0
    return MagicMock(return_value=mock_result)


# ---------------------------------------------------------------------------
# Property 13a: passed=True if and only if ALL checks pass
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(check_states=check_states_strategy)
def test_property_13_passed_iff_all_checks_pass(
    check_states: dict[str, dict[str, object]],
):
    """Property 13: Validator reports passed=True only when ALL 5 checks pass.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any combination of check pass/fail states, the validator SHALL report
    passed=True if and only if every single check reports passed=True.
    """
    stdout = _build_probe_stdout(check_states)
    all_should_pass = all(c["passed"] for c in check_states.values())

    with patch("subprocess.run", _mock_subprocess_run(stdout)):
        with patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.write") as mock_write, \
             patch("os.close") as mock_close, \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):
            mock_mkstemp.return_value = (99, "/tmp/fake_probe.py")

            result = run_structural_smoke_050(
                upbge_path="C:\\fake\\blender.exe",
                blend_path="C:\\fake\\test.blend",
                timeout_s=10.0,
            )

    assert result["passed"] == all_should_pass, (
        f"Expected passed={all_should_pass} but got passed={result['passed']}. "
        f"Check states: {check_states}"
    )


# ---------------------------------------------------------------------------
# Property 13b: When any check fails, reason_code is a non-empty string
#               identifying the first failed check (not "smoke_passed")
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(check_states=check_states_strategy)
def test_property_13_failure_has_specific_reason_code(
    check_states: dict[str, dict[str, object]],
):
    """Property 13: When any check fails, reason_code identifies the failure.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    When at least one check fails, the validator SHALL report a reason_code
    that is a non-empty string different from "smoke_passed".
    """
    any_failure = any(not c["passed"] for c in check_states.values())
    if not any_failure:
        # Skip cases where all pass — this property concerns failures
        return

    stdout = _build_probe_stdout(check_states)

    with patch("subprocess.run", _mock_subprocess_run(stdout)):
        with patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.write") as mock_write, \
             patch("os.close") as mock_close, \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):
            mock_mkstemp.return_value = (99, "/tmp/fake_probe.py")

            result = run_structural_smoke_050(
                upbge_path="C:\\fake\\blender.exe",
                blend_path="C:\\fake\\test.blend",
                timeout_s=10.0,
            )

    assert result["reason_code"] != "smoke_passed", (
        f"Expected reason_code != 'smoke_passed' when checks fail, "
        f"but got '{result['reason_code']}'. Check states: {check_states}"
    )
    assert isinstance(result["reason_code"], str) and len(result["reason_code"]) > 0, (
        f"Expected non-empty string reason_code, got: {result['reason_code']!r}"
    )
    # The reason_code should be one of the known check names (the first failure)
    assert result["reason_code"] in _SMOKE_CHECK_NAMES_050, (
        f"Expected reason_code to be a check name from {_SMOKE_CHECK_NAMES_050}, "
        f"but got '{result['reason_code']}'. Check states: {check_states}"
    )


# ---------------------------------------------------------------------------
# Property 13c: Every failing check includes non-empty detail
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(check_states=check_states_strategy)
def test_property_13_failing_checks_have_nonempty_detail(
    check_states: dict[str, dict[str, object]],
):
    """Property 13: Each failing check includes non-empty detail string.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any combination of check states, the validator's reported detail
    SHALL be a non-empty string whenever the overall result is a failure.
    """
    any_failure = any(not c["passed"] for c in check_states.values())
    if not any_failure:
        # When all pass, detail is "All checks passed" which is non-empty
        return

    stdout = _build_probe_stdout(check_states)

    with patch("subprocess.run", _mock_subprocess_run(stdout)):
        with patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.write") as mock_write, \
             patch("os.close") as mock_close, \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):
            mock_mkstemp.return_value = (99, "/tmp/fake_probe.py")

            result = run_structural_smoke_050(
                upbge_path="C:\\fake\\blender.exe",
                blend_path="C:\\fake\\test.blend",
                timeout_s=10.0,
            )

    # The detail field should be non-empty for any failure
    assert isinstance(result["detail"], str) and len(result["detail"]) > 0, (
        f"Expected non-empty detail string for failing validation, "
        f"got: {result['detail']!r}. Check states: {check_states}"
    )


# ---------------------------------------------------------------------------
# Property 13d: When all checks pass, reason_code is "smoke_passed"
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    details=st.tuples(
        detail_strategy, detail_strategy, detail_strategy,
        detail_strategy, detail_strategy,
    ),
)
def test_property_13_all_pass_gives_smoke_passed(
    details: tuple[str, str, str, str, str],
):
    """Property 13: When ALL checks pass, reason_code is "smoke_passed".

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any set of detail strings, when all 5 checks report passed=True,
    the validator SHALL report passed=True and reason_code="smoke_passed".
    """
    check_states = {
        name: {"passed": True, "detail": detail}
        for name, detail in zip(_SMOKE_CHECK_NAMES_050, details)
    }
    stdout = _build_probe_stdout(check_states)

    with patch("subprocess.run", _mock_subprocess_run(stdout)):
        with patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.write") as mock_write, \
             patch("os.close") as mock_close, \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):
            mock_mkstemp.return_value = (99, "/tmp/fake_probe.py")

            result = run_structural_smoke_050(
                upbge_path="C:\\fake\\blender.exe",
                blend_path="C:\\fake\\test.blend",
                timeout_s=10.0,
            )

    assert result["passed"] is True, (
        f"Expected passed=True when all checks pass, got {result['passed']}"
    )
    assert result["reason_code"] == "smoke_passed", (
        f"Expected reason_code='smoke_passed', got '{result['reason_code']}'"
    )


# ---------------------------------------------------------------------------
# Property 13e: The reason_code corresponds to the FIRST failed check
#               in evaluation order
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(check_states=check_states_strategy)
def test_property_13_reason_code_is_first_failed_check(
    check_states: dict[str, dict[str, object]],
):
    """Property 13: reason_code matches the FIRST failing check in evaluation order.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    The validator evaluates checks in the defined order. When multiple checks
    fail, the reason_code SHALL correspond to the first one that fails.
    """
    any_failure = any(not c["passed"] for c in check_states.values())
    if not any_failure:
        return

    # Determine expected first failure in evaluation order
    expected_first_failure = None
    for name in _SMOKE_CHECK_NAMES_050:
        if not check_states[name]["passed"]:
            expected_first_failure = name
            break

    stdout = _build_probe_stdout(check_states)

    with patch("subprocess.run", _mock_subprocess_run(stdout)):
        with patch("tempfile.mkstemp") as mock_mkstemp, \
             patch("os.write") as mock_write, \
             patch("os.close") as mock_close, \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):
            mock_mkstemp.return_value = (99, "/tmp/fake_probe.py")

            result = run_structural_smoke_050(
                upbge_path="C:\\fake\\blender.exe",
                blend_path="C:\\fake\\test.blend",
                timeout_s=10.0,
            )

    assert result["reason_code"] == expected_first_failure, (
        f"Expected reason_code='{expected_first_failure}' (first failed check), "
        f"but got '{result['reason_code']}'. Check states: {check_states}"
    )
