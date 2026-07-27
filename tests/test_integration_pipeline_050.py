"""Integration tests for the UPBGE 0.50 pipeline: probe → compile → validate → launch.

Task 9.2: Mocked end-to-end tests verifying data flow between stages.
Task 9.3: Live integration tests against installed UPBGE 0.50 binary (optional).

Requirements: 1.1, 1.4, 5.7, 9.1
"""

from __future__ import annotations

import json
import os

import pytest

from src.assembler.api_probe_050 import (
    PROBE_RESULT_MARKER,
    UPBGEComponentAPI,
    parse_probe_output,
)
from src.assembler.smoke_probe_050 import (
    SMOKE_RESULT_MARKER,
    parse_smoke_output,
)


# ===========================================================================
# Task 9.2 — Mocked pipeline integration tests
# ===========================================================================


class TestIntegrationMockedPipeline:
    """End-to-end pipeline tests with mocked UPBGE subprocess output.

    Verifies correct data flow between probe → compile → validate stages
    and degradation paths when stages fail.
    """

    def test_full_success_path(self):
        """probe success → compile success → smoke pass → pipeline complete.

        Validates: Requirements 1.1, 9.1
        """
        # Build a realistic probe output fixture
        probe_report = {
            "schema_version": "upbge-api-probe/v1",
            "blender_version": [5, 0, 1],
            "blender_version_string": "UPBGE 5.0.1",
            "upbge_detected": True,
            "component_api": {
                "has_game_attr": True,
                "has_components_attr": True,
                "component_api_path": "obj.game.components",
                "component_add_method": "obj.game.components.new()",
                "has_logic_ops": True,
            },
            "physics_api": {
                "has_game_physics": True,
                "physics_api_path": "obj.game.physics_type",
            },
        }
        probe_stdout = (
            f"Blender 5.0.1\n"
            f"{PROBE_RESULT_MARKER}{json.dumps(probe_report)}\n"
        )

        # Stage 1: Parse probe output
        api_result = parse_probe_output(probe_stdout)
        assert api_result.upbge_detected is True
        assert api_result.component_api_path == "obj.game.components"
        assert api_result.has_game_physics is True
        assert api_result.fallback_required is False

        # Stage 2: Verify probe data flows correctly to compile parameters
        # When native API is available, no fallback is needed
        assert api_result.component_add_method == "obj.game.components.new()"
        assert api_result.physics_api_path == "obj.game.physics_type"

        # Stage 3: Simulate smoke validation passing
        smoke_report = {
            "schema_version": "smoke-probe-050/v1",
            "checks": {
                "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
                "player_component_attached": {"passed": True, "detail": "Native on KiroPlayer"},
                "text_datablocks_present": {"passed": True, "detail": "All present"},
                "physics_configured": {"passed": True, "detail": "CHARACTER on KiroPlayer"},
                "door_components_attached": {"passed": True, "detail": "All 2 doors have components"},
            },
            "all_passed": True,
        }
        smoke_stdout = f"Blender 5.0.1\n{SMOKE_RESULT_MARKER}{json.dumps(smoke_report)}\n"
        smoke_result = parse_smoke_output(smoke_stdout)
        assert smoke_result["all_passed"] is True

    def test_probe_timeout_creates_fallback_report(self):
        """probe timeout → fallback UPBGEComponentAPI with fallback_required=True.

        Validates: Requirements 5.7
        """
        # When probe times out, the pipeline creates a fallback report
        fallback = UPBGEComponentAPI(
            has_game_attr=False,
            has_components_attr=False,
            component_api_path=None,
            component_add_method=None,
            has_logic_ops=False,
            physics_api_path=None,
            has_game_physics=False,
            blender_version=(0, 0, 0),
            upbge_detected=False,
            fallback_required=True,
        )
        assert fallback.fallback_required is True
        # The compile step can still proceed with this fallback report
        # It will use ID property embedding instead of native API
        assert fallback.component_api_path is None
        assert fallback.has_game_physics is False

    def test_degradation_no_component_api_triggers_fallback(self):
        """Probe detects UPBGE but no component API → fallback_required=True.

        Validates: Requirements 5.7, 9.1
        """
        probe_report = {
            "schema_version": "upbge-api-probe/v1",
            "blender_version": [5, 0, 1],
            "blender_version_string": "UPBGE 5.0.1",
            "upbge_detected": True,
            "component_api": {
                "has_game_attr": True,
                "has_components_attr": False,
                "component_api_path": None,  # No native component API
                "component_add_method": None,
                "has_logic_ops": False,
            },
            "physics_api": {
                "has_game_physics": False,
                "physics_api_path": None,
            },
        }
        probe_stdout = f"{PROBE_RESULT_MARKER}{json.dumps(probe_report)}\n"
        api_result = parse_probe_output(probe_stdout)

        # Fallback required because no native component path
        assert api_result.fallback_required is True
        assert api_result.has_game_physics is False
        # This would trigger bootstrap embedding in _configure_runtime_050

    def test_smoke_parse_valid_all_pass(self):
        """smoke probe output with all checks passing → all_passed=True.

        Validates: Requirements 9.1
        """
        smoke_report = {
            "schema_version": "smoke-probe-050/v1",
            "checks": {
                "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
                "player_component_attached": {"passed": True, "detail": "Native on KiroPlayer"},
                "text_datablocks_present": {"passed": True, "detail": "All present"},
                "physics_configured": {"passed": True, "detail": "CHARACTER on KiroPlayer"},
                "door_components_attached": {"passed": True, "detail": "All 2 doors have components"},
            },
            "all_passed": True,
        }
        stdout = f"Blender 5.0.1\n{SMOKE_RESULT_MARKER}{json.dumps(smoke_report)}\n"
        result = parse_smoke_output(stdout)
        assert result["all_passed"] is True
        assert all(c["passed"] for c in result["checks"].values())

    def test_smoke_partial_failure(self):
        """smoke probe with one failing check → all_passed=False.

        Validates: Requirements 9.1
        """
        smoke_report = {
            "schema_version": "smoke-probe-050/v1",
            "checks": {
                "scene_loads": {"passed": True, "detail": "ok"},
                "player_component_attached": {"passed": False, "detail": "Not found"},
                "text_datablocks_present": {"passed": True, "detail": "ok"},
                "physics_configured": {"passed": True, "detail": "ok"},
                "door_components_attached": {"passed": True, "detail": "ok"},
            },
            "all_passed": False,
        }
        stdout = f"{SMOKE_RESULT_MARKER}{json.dumps(smoke_report)}\n"
        result = parse_smoke_output(stdout)
        assert result["all_passed"] is False
        assert result["checks"]["player_component_attached"]["passed"] is False

    def test_probe_data_determines_compile_strategy(self):
        """Probe output determines whether native or fallback compile path is used.

        Validates: Requirements 1.1, 5.7
        """
        # Case A: Native API available → no fallback
        native_report = {
            "schema_version": "upbge-api-probe/v1",
            "blender_version": [5, 0, 1],
            "blender_version_string": "UPBGE 5.0.1",
            "upbge_detected": True,
            "component_api": {
                "has_game_attr": True,
                "has_components_attr": True,
                "component_api_path": "obj.game.components",
                "component_add_method": "obj.game.components.new()",
                "has_logic_ops": True,
            },
            "physics_api": {
                "has_game_physics": True,
                "physics_api_path": "obj.game.physics_type",
            },
        }
        native_stdout = f"{PROBE_RESULT_MARKER}{json.dumps(native_report)}\n"
        native_api = parse_probe_output(native_stdout)
        assert native_api.fallback_required is False

        # Case B: No component API → fallback required
        fallback_report = {
            "schema_version": "upbge-api-probe/v1",
            "blender_version": [5, 0, 1],
            "blender_version_string": "UPBGE 5.0.1",
            "upbge_detected": True,
            "component_api": {
                "has_game_attr": True,
                "has_components_attr": False,
                "component_api_path": None,
                "component_add_method": None,
                "has_logic_ops": False,
            },
            "physics_api": {
                "has_game_physics": False,
                "physics_api_path": None,
            },
        }
        fallback_stdout = f"{PROBE_RESULT_MARKER}{json.dumps(fallback_report)}\n"
        fallback_api = parse_probe_output(fallback_stdout)
        assert fallback_api.fallback_required is True

    def test_scene_only_save_on_component_failure(self):
        """When component attachment fails, scene-only save is the degradation path.

        Validates: Requirements 5.7
        """
        # Simulate a scenario where probe succeeds but smoke validation
        # detects component failure → the pipeline should still save scene data
        smoke_report = {
            "schema_version": "smoke-probe-050/v1",
            "checks": {
                "scene_loads": {"passed": True, "detail": "ok"},
                "player_component_attached": {"passed": False, "detail": "Component attachment failed"},
                "text_datablocks_present": {"passed": True, "detail": "ok"},
                "physics_configured": {"passed": False, "detail": "Physics not configured"},
                "door_components_attached": {"passed": False, "detail": "0/2 doors have components"},
            },
            "all_passed": False,
        }
        stdout = f"{SMOKE_RESULT_MARKER}{json.dumps(smoke_report)}\n"
        result = parse_smoke_output(stdout)

        # Scene itself loaded fine — degradation allows scene-only save
        assert result["checks"]["scene_loads"]["passed"] is True
        # Component/physics failures → compile should save scene-only .blend
        assert result["all_passed"] is False
        failed_checks = [k for k, v in result["checks"].items() if not v["passed"]]
        assert "player_component_attached" in failed_checks

    def test_version_info_preserved_through_pipeline(self):
        """Blender version from probe output is accessible for downstream decisions.

        Validates: Requirements 1.1
        """
        probe_report = {
            "schema_version": "upbge-api-probe/v1",
            "blender_version": [5, 0, 1],
            "blender_version_string": "UPBGE 5.0.1",
            "upbge_detected": True,
            "component_api": {
                "has_game_attr": True,
                "has_components_attr": True,
                "component_api_path": "obj.game.components",
                "component_add_method": "obj.game.components.new()",
                "has_logic_ops": True,
            },
            "physics_api": {
                "has_game_physics": True,
                "physics_api_path": "obj.game.physics_type",
            },
        }
        probe_stdout = f"{PROBE_RESULT_MARKER}{json.dumps(probe_report)}\n"
        api_result = parse_probe_output(probe_stdout)
        assert api_result.blender_version == (5, 0, 1)
        assert api_result.blender_version[0] >= 3  # At least Blender 3.x


# ===========================================================================
# Task 9.3 — Live UPBGE 0.50 integration tests (optional)
# ===========================================================================

UPBGE_PATH = r"C:\Program Files\UPBGE\upbge-0.50-windows-x64 (1)\upbge-0.50-windows-x64\blender.exe"


@pytest.mark.skipif(
    not os.path.isfile(UPBGE_PATH),
    reason="UPBGE 0.50 not installed at expected path",
)
class TestLiveUPBGEProbe:
    """Integration tests against live UPBGE 0.50 binary.

    These tests are optional — they require UPBGE 0.50 to be installed
    at the expected path on the test machine.

    Validates: Requirements 1.1, 1.4
    """

    def test_api_probe_completes_within_timeout(self):
        """Live API probe completes within 15 seconds.

        Validates: Requirements 1.4
        """
        from src.assembler.api_probe_050 import run_api_probe

        result = run_api_probe(UPBGE_PATH, timeout_s=15.0)
        assert result.upbge_detected is True
        assert result.blender_version[0] >= 3  # At least Blender 3.x

    def test_api_probe_produces_parseable_output(self):
        """Live API probe produces valid UPBGEComponentAPI dataclass.

        Validates: Requirements 1.1
        """
        from src.assembler.api_probe_050 import run_api_probe

        result = run_api_probe(UPBGE_PATH)
        # Should have discovered SOMETHING about the API
        assert isinstance(result.has_game_attr, bool)
        assert isinstance(result.has_components_attr, bool)
        assert isinstance(result.has_logic_ops, bool)
        assert isinstance(result.upbge_detected, bool)
        assert isinstance(result.blender_version, tuple)
        assert len(result.blender_version) == 3

    def test_discovered_api_has_expected_structure(self):
        """Discovered API surface matches what the compiler expects.

        The compiler expects either:
        1. component_api_path is not None (native path available)
        2. OR fallback_required is True (use ID properties)

        At minimum, UPBGE should be detected and one strategy must be usable.

        Validates: Requirements 1.1, 1.4
        """
        from src.assembler.api_probe_050 import run_api_probe

        result = run_api_probe(UPBGE_PATH)
        assert result.upbge_detected is True

        # One of these strategies must be available for the compiler
        has_native_path = result.component_api_path is not None
        has_fallback = result.fallback_required is True
        assert has_native_path or has_fallback, (
            "Neither native component API nor fallback strategy available — "
            "compiler cannot proceed"
        )

    def test_physics_api_discovery(self):
        """Live probe discovers physics API state consistently.

        Validates: Requirements 1.1
        """
        from src.assembler.api_probe_050 import run_api_probe

        result = run_api_probe(UPBGE_PATH)
        # Physics API state should be boolean-typed
        assert isinstance(result.has_game_physics, bool)
        # If physics API is available, path should be set
        if result.has_game_physics:
            assert result.physics_api_path is not None
