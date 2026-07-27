"""Unit tests for src/assembler/smoke_probe_050.py.

Tests cover:
1. SMOKE_PROBE_SCRIPT_050 is valid Python (compiles without error)
2. parse_smoke_output() correctly extracts JSON after the SMOKE_RESULT= marker
3. parse_smoke_output() raises ValueError on missing/malformed output
4. Module exports the expected constants and functions
"""

from __future__ import annotations

import json

import pytest

from src.assembler.smoke_probe_050 import (
    SMOKE_PROBE_SCRIPT_050,
    SMOKE_RESULT_MARKER,
    parse_smoke_output,
)


# ---------------------------------------------------------------------------
# Test: Script constant is valid Python
# ---------------------------------------------------------------------------

class TestSmokeProbeSyntax:
    """SMOKE_PROBE_SCRIPT_050 must be syntactically valid Python."""

    def test_script_compiles_without_error(self) -> None:
        """The embedded script string should compile as valid Python."""
        # compile() raises SyntaxError if invalid
        code = compile(SMOKE_PROBE_SCRIPT_050, "<smoke_probe_050>", "exec")
        assert code is not None

    def test_script_contains_marker(self) -> None:
        """Script must define and use the SMOKE_RESULT= marker."""
        assert "SMOKE_RESULT=" in SMOKE_PROBE_SCRIPT_050

    def test_script_imports_bpy(self) -> None:
        """Script must import bpy (runs inside UPBGE)."""
        assert "import bpy" in SMOKE_PROBE_SCRIPT_050

    def test_script_does_not_import_bge(self) -> None:
        """Script must NOT import bge (headless validation only)."""
        assert "import bge" not in SMOKE_PROBE_SCRIPT_050

    def test_script_uses_open_mainfile(self) -> None:
        """Script should open blend via bpy.ops.wm.open_mainfile."""
        assert "bpy.ops.wm.open_mainfile" in SMOKE_PROBE_SCRIPT_050

    def test_script_does_not_enter_game_mode(self) -> None:
        """Script must NOT start the game engine."""
        assert "bge.logic.startGame" not in SMOKE_PROBE_SCRIPT_050
        assert "bpy.ops.view3d.game_start" not in SMOKE_PROBE_SCRIPT_050

    def test_script_uses_sys_argv_for_blend_path(self) -> None:
        """Script must accept blend path via sys.argv after '--'."""
        assert 'sys.argv' in SMOKE_PROBE_SCRIPT_050
        assert '"--"' in SMOKE_PROBE_SCRIPT_050


# ---------------------------------------------------------------------------
# Test: parse_smoke_output() success cases
# ---------------------------------------------------------------------------

def _make_smoke_stdout(
    *,
    all_passed: bool = True,
    scene_loads: bool = True,
    player_attached: bool = True,
    texts_present: bool = True,
    physics_ok: bool = True,
    doors_ok: bool = True,
) -> str:
    """Build synthetic smoke probe stdout with SMOKE_RESULT= marker."""
    checks = {
        "scene_loads": {
            "passed": scene_loads,
            "detail": "Scene loaded with 5 objects" if scene_loads else "Scene load error",
        },
        "player_component_attached": {
            "passed": player_attached,
            "detail": "Fallback component on KiroPlayer" if player_attached else "No player found",
        },
        "text_datablocks_present": {
            "passed": texts_present,
            "detail": "All 2 required text datablocks present" if texts_present else "Missing: kiro_player_first_person.py",
        },
        "physics_configured": {
            "passed": physics_ok,
            "detail": "Fallback CHARACTER physics on KiroPlayer" if physics_ok else "No CHARACTER physics",
        },
        "door_components_attached": {
            "passed": doors_ok,
            "detail": "All 2 doors have DoorComponent" if doors_ok else "0/2 doors have components",
        },
    }
    report = {
        "schema_version": "smoke-probe-050/v1",
        "checks": checks,
        "all_passed": all_passed,
    }
    # Simulate noisy stdout with marker line
    return f"Blender 5.0.1\nRead prefs...\n{SMOKE_RESULT_MARKER}{json.dumps(report, sort_keys=True)}\n"


class TestParseSmokOutputSuccess:
    """parse_smoke_output() extracts valid JSON from marker line."""

    def test_all_passed(self) -> None:
        stdout = _make_smoke_stdout(all_passed=True)
        result = parse_smoke_output(stdout)
        assert result["all_passed"] is True
        assert result["schema_version"] == "smoke-probe-050/v1"
        assert len(result["checks"]) == 5

    def test_some_failed(self) -> None:
        stdout = _make_smoke_stdout(all_passed=False, player_attached=False)
        result = parse_smoke_output(stdout)
        assert result["all_passed"] is False
        assert result["checks"]["player_component_attached"]["passed"] is False

    def test_returns_dict(self) -> None:
        stdout = _make_smoke_stdout()
        result = parse_smoke_output(stdout)
        assert isinstance(result, dict)

    def test_check_keys_present(self) -> None:
        stdout = _make_smoke_stdout()
        result = parse_smoke_output(stdout)
        expected_keys = {
            "scene_loads",
            "player_component_attached",
            "text_datablocks_present",
            "physics_configured",
            "door_components_attached",
        }
        assert set(result["checks"].keys()) == expected_keys

    def test_each_check_has_passed_and_detail(self) -> None:
        stdout = _make_smoke_stdout()
        result = parse_smoke_output(stdout)
        for check_name, check_data in result["checks"].items():
            assert "passed" in check_data, f"{check_name} missing 'passed'"
            assert "detail" in check_data, f"{check_name} missing 'detail'"

    def test_marker_found_amid_noise(self) -> None:
        """Marker should be found even with lots of Blender startup noise."""
        noise = "\n".join([
            "Blender 5.0.1 (sub 0)",
            "Read prefs: /home/.config/blender",
            "Warning: modifier disabled",
            "Info: Read new prefs",
        ])
        report = {
            "schema_version": "smoke-probe-050/v1",
            "checks": {"scene_loads": {"passed": True, "detail": "OK"}},
            "all_passed": True,
        }
        stdout = f"{noise}\n{SMOKE_RESULT_MARKER}{json.dumps(report)}\nMore output\n"
        result = parse_smoke_output(stdout)
        assert result["all_passed"] is True


# ---------------------------------------------------------------------------
# Test: parse_smoke_output() error cases
# ---------------------------------------------------------------------------

class TestParseSmokeOutputErrors:
    """parse_smoke_output() raises ValueError on bad input."""

    def test_no_marker_raises(self) -> None:
        with pytest.raises(ValueError, match="smoke_parse_error"):
            parse_smoke_output("Some random Blender output without marker\n")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="smoke_parse_error"):
            parse_smoke_output("")

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(ValueError, match="smoke_parse_error"):
            parse_smoke_output(f"{SMOKE_RESULT_MARKER}{{not valid json")

    def test_partial_marker_not_matched(self) -> None:
        """A line containing only part of the marker should not match."""
        with pytest.raises(ValueError, match="smoke_parse_error"):
            parse_smoke_output("SMOKE_RESULT\n")  # missing =


# ---------------------------------------------------------------------------
# Test: Module-level exports
# ---------------------------------------------------------------------------

class TestModuleExports:
    """Module exports the expected public API."""

    def test_marker_value(self) -> None:
        assert SMOKE_RESULT_MARKER == "SMOKE_RESULT="

    def test_script_constant_is_string(self) -> None:
        assert isinstance(SMOKE_PROBE_SCRIPT_050, str)

    def test_script_not_empty(self) -> None:
        assert len(SMOKE_PROBE_SCRIPT_050) > 100
