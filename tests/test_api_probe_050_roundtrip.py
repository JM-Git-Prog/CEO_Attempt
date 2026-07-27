"""Property-based test: Probe Report Parsing Round-Trip (Property 1).

**Validates: Requirements 1.2**

For any valid JSON probe output containing probe fields, parsing into
UPBGEComponentAPI and serializing back to dict SHALL preserve all field values.
"""

from __future__ import annotations

import json
import dataclasses

from hypothesis import given, settings
from hypothesis import strategies as st

from src.assembler.api_probe_050 import (
    PROBE_RESULT_MARKER,
    UPBGEComponentAPI,
    parse_probe_output,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Optional string fields: None or a non-empty text string (avoiding control chars
# that could break JSON or line splitting).
_optional_str = st.none() | st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S"), whitelist_characters="._/ "),
    min_size=1,
    max_size=60,
)

# Blender version: 3-tuple of small non-negative ints
_blender_version = st.tuples(
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
    st.integers(min_value=0, max_value=99),
)

# Random noise lines (simulates Blender startup output before the marker)
_noise_line = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=0,
    max_size=80,
).filter(lambda s: PROBE_RESULT_MARKER not in s)

_noise_lines = st.lists(_noise_line, min_size=0, max_size=5)


@st.composite
def probe_stdout_strategy(draw):
    """Generate a valid probe stdout string with random field values."""
    # Draw field values
    has_game_attr = draw(st.booleans())
    has_components_attr = draw(st.booleans())
    component_api_path = draw(_optional_str)
    component_add_method = draw(_optional_str)
    has_logic_ops = draw(st.booleans())
    physics_api_path = draw(_optional_str)
    has_game_physics = draw(st.booleans())
    blender_version = draw(_blender_version)
    upbge_detected = draw(st.booleans())

    # Build the JSON structure that parse_probe_output expects
    report = {
        "schema_version": "upbge-api-probe/v1",
        "blender_version": list(blender_version),
        "blender_version_string": f"UPBGE {blender_version[0]}.{blender_version[1]}.{blender_version[2]}",
        "upbge_detected": upbge_detected,
        "component_api": {
            "has_game_attr": has_game_attr,
            "has_components_attr": has_components_attr,
            "component_api_path": component_api_path,
            "component_add_method": component_add_method,
            "has_logic_ops": has_logic_ops,
        },
        "physics_api": {
            "has_game_physics": has_game_physics,
            "physics_api_path": physics_api_path,
        },
    }

    # Build stdout with optional noise lines before the marker
    noise = draw(_noise_lines)
    lines = noise + [f"{PROBE_RESULT_MARKER}{json.dumps(report, sort_keys=True)}"]
    stdout = "\n".join(lines) + "\n"

    # Expected parsed values for verification
    expected = {
        "has_game_attr": has_game_attr,
        "has_components_attr": has_components_attr,
        "component_api_path": component_api_path,
        "component_add_method": component_add_method,
        "has_logic_ops": has_logic_ops,
        "physics_api_path": physics_api_path,
        "has_game_physics": has_game_physics,
        "blender_version": blender_version,
        "upbge_detected": upbge_detected,
        "fallback_required": component_api_path is None,
    }

    return stdout, expected


# ---------------------------------------------------------------------------
# Property test
# ---------------------------------------------------------------------------


@given(data=probe_stdout_strategy())
@settings(max_examples=200)
def test_probe_report_roundtrip_preserves_all_fields(data):
    """Property 1: Parsing probe JSON and serializing back preserves all fields.

    **Validates: Requirements 1.2**
    """
    stdout, expected = data

    # Parse the probe output
    result: UPBGEComponentAPI = parse_probe_output(stdout)

    # Serialize back to dict
    result_dict = dataclasses.asdict(result)

    # Verify every field is preserved
    assert result_dict["has_game_attr"] == expected["has_game_attr"]
    assert result_dict["has_components_attr"] == expected["has_components_attr"]
    assert result_dict["component_api_path"] == expected["component_api_path"]
    assert result_dict["component_add_method"] == expected["component_add_method"]
    assert result_dict["has_logic_ops"] == expected["has_logic_ops"]
    assert result_dict["physics_api_path"] == expected["physics_api_path"]
    assert result_dict["has_game_physics"] == expected["has_game_physics"]
    assert result_dict["blender_version"] == expected["blender_version"]
    assert result_dict["upbge_detected"] == expected["upbge_detected"]

    # Verify derived field consistency
    assert result_dict["fallback_required"] == expected["fallback_required"]
    assert result_dict["fallback_required"] == (result_dict["component_api_path"] is None)
