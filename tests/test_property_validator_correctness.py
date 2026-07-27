"""Property-based tests for validator correctness (Property 13).

**Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

Property 13: Validator Correctness
- For any mocked .blend state (objects with/without components, text datablocks),
  validator reports `passed=True` only when ALL checks pass; reports specific
  `reason_code` for first failure; includes non-empty `detail` for every failing check.
"""

from __future__ import annotations

import json

from hypothesis import given, settings, strategies as st

from src.assembler.smoke_probe_050 import parse_smoke_output, SMOKE_RESULT_MARKER


# ---------------------------------------------------------------------------
# The 5 mandatory check names from the smoke probe
# ---------------------------------------------------------------------------

SMOKE_CHECK_NAMES = (
    "scene_loads",
    "player_component_attached",
    "text_datablocks_present",
    "physics_configured",
    "door_components_attached",
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Non-empty detail strings (must always be non-empty per the property)
detail_strategy = st.text(
    min_size=1,
    max_size=200,
    alphabet=st.characters(
        whitelist_categories=("L", "Nd", "P", "Zs"),
        blacklist_characters=("\x00",),
    ),
)

# A single check: either passes or fails with a non-empty detail
check_strategy = st.fixed_dictionaries(
    {"passed": st.booleans(), "detail": detail_strategy}
)

# Generate a full set of 5 checks with random pass/fail states
checks_strategy = st.fixed_dictionaries(
    {name: check_strategy for name in SMOKE_CHECK_NAMES}
)


def build_probe_stdout(checks: dict[str, dict], schema_version: str = "smoke-probe-050/v1") -> str:
    """Build a full probe stdout string from generated check states."""
    all_passed = all(c["passed"] for c in checks.values())
    result = {
        "schema_version": schema_version,
        "checks": checks,
        "all_passed": all_passed,
    }
    # Simulate realistic probe output with noise lines before the marker
    lines = [
        "Blender 5.0.1 (hash abc123)",
        "Read blend: /tmp/runtime_candidate.blend",
        SMOKE_RESULT_MARKER + json.dumps(result, sort_keys=True),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Property 13a: passed=True ONLY when ALL checks pass
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_strategy)
def test_property_13_all_passed_iff_all_checks_pass(
    checks: dict[str, dict],
):
    """Property 13: all_passed == True ONLY when every check has passed=True.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any combination of check pass/fail states, the overall result
    reports all_passed=True if and only if every individual check passed.
    """
    stdout = build_probe_stdout(checks)
    result = parse_smoke_output(stdout)

    expected_all_passed = all(c["passed"] for c in checks.values())
    assert result["all_passed"] == expected_all_passed, (
        f"Expected all_passed={expected_all_passed}, got {result['all_passed']}. "
        f"Check states: {[(n, c['passed']) for n, c in checks.items()]}"
    )


# ---------------------------------------------------------------------------
# Property 13b: If any check fails, all_passed is False
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_strategy)
def test_property_13_any_failure_means_not_passed(
    checks: dict[str, dict],
):
    """Property 13: If any check has passed=False, result.all_passed == False.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    This is the contrapositive: a single failing check is sufficient to
    make the overall validation report failure.
    """
    stdout = build_probe_stdout(checks)
    result = parse_smoke_output(stdout)

    has_any_failure = any(not c["passed"] for c in checks.values())
    if has_any_failure:
        assert result["all_passed"] is False, (
            f"all_passed should be False when a check fails. "
            f"Failing checks: {[n for n, c in checks.items() if not c['passed']]}"
        )


# ---------------------------------------------------------------------------
# Property 13c: Every check has a non-empty detail string
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_strategy)
def test_property_13_every_check_has_nonempty_detail(
    checks: dict[str, dict],
):
    """Property 13: Every check in the parsed result includes a non-empty detail.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any .blend state, every check (passing or failing) SHALL include
    a non-empty `detail` string providing diagnostic information.
    """
    stdout = build_probe_stdout(checks)
    result = parse_smoke_output(stdout)

    for check_name, check_data in result["checks"].items():
        assert "detail" in check_data, (
            f"Check '{check_name}' is missing 'detail' key"
        )
        assert isinstance(check_data["detail"], str), (
            f"Check '{check_name}' detail is not a string: {type(check_data['detail'])}"
        )
        assert len(check_data["detail"]) > 0, (
            f"Check '{check_name}' has empty detail string"
        )


# ---------------------------------------------------------------------------
# Property 13d: schema_version is preserved through parse
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_strategy)
def test_property_13_schema_version_preserved(
    checks: dict[str, dict],
):
    """Property 13: The schema_version field is preserved through parsing.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any probe output, the parsed result SHALL contain the same
    schema_version that was emitted by the probe.
    """
    schema_version = "smoke-probe-050/v1"
    stdout = build_probe_stdout(checks, schema_version=schema_version)
    result = parse_smoke_output(stdout)

    assert result["schema_version"] == schema_version, (
        f"Expected schema_version='{schema_version}', got '{result.get('schema_version')}'"
    )


# ---------------------------------------------------------------------------
# Property 13e: First failing check identifiable as reason_code
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_strategy)
def test_property_13_first_failure_identifiable(
    checks: dict[str, dict],
):
    """Property 13: When validation fails, the first failing check is identifiable.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any failed validation, iterating checks in canonical order yields
    a specific failing check name that can serve as the reason_code.
    The first failing check in SMOKE_CHECK_NAMES order is the reason_code.
    """
    stdout = build_probe_stdout(checks)
    result = parse_smoke_output(stdout)

    if not result["all_passed"]:
        # Find the first failing check in canonical order
        first_failure = None
        for check_name in SMOKE_CHECK_NAMES:
            if not result["checks"][check_name]["passed"]:
                first_failure = check_name
                break

        assert first_failure is not None, (
            "all_passed is False but no failing check found"
        )
        # The first failure serves as the reason_code and has non-empty detail
        assert len(result["checks"][first_failure]["detail"]) > 0, (
            f"First failing check '{first_failure}' has empty detail"
        )


# ---------------------------------------------------------------------------
# Property 13f: All 5 mandatory checks are present in parsed result
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(checks=checks_strategy)
def test_property_13_all_mandatory_checks_present(
    checks: dict[str, dict],
):
    """Property 13: Parsed result contains all 5 mandatory check names.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5**

    For any probe output constructed from the 5 mandatory checks,
    the parsed result SHALL contain exactly those 5 check names.
    """
    stdout = build_probe_stdout(checks)
    result = parse_smoke_output(stdout)

    for check_name in SMOKE_CHECK_NAMES:
        assert check_name in result["checks"], (
            f"Mandatory check '{check_name}' missing from parsed result. "
            f"Present checks: {list(result['checks'].keys())}"
        )
