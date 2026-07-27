"""Tests for the smoke_validator module.

Verifies run_structural_smoke handles precondition failures, subprocess
outcomes, and result parsing correctly for UPBGE 0.50 component-based checks.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.smoke_validator import (
    SmokeCheck,
    SmokeValidationResult,
    run_structural_smoke,
    _SMOKE_RESULT_MARKER,
)
from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_runtime import RuntimePlan


def _make_capability(executable_path: str | None = "C:/upbge/upbge.exe") -> UPBGECapabilityReport:
    """Create a minimal capability report for testing."""
    return UPBGECapabilityReport(
        available=True,
        verified=True,
        compatible=True,
        executable_path=executable_path,
        product="UPBGE",
        supports_game_runtime=True,
    )


def _make_runtime_plan() -> RuntimePlan:
    """Create a minimal runtime plan for testing."""
    return RuntimePlan(
        schema_version="upbge-runtime/v1",
        world_contract_hash="a" * 64,
        player_template_id="player.first_person",
        template_hashes=(("player.first_person", "b" * 64),),
        template_sources=(("player.first_person", "main", "print('hello')"),),
        gravity_upbge=(0.0, 0.0, -9.81),
        interactions=(),
        dynamic_state_schema="upbge-runtime-state/v1",
    )


def _probe_success_output_050() -> str:
    """Produce a stdout string with a successful SMOKE_RESULT line (UPBGE 0.50 format)."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": {
            "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
            "player_component_attached": {"passed": True, "detail": "Fallback component on KiroPlayer: kiro_player_first_person.PlayerComponent"},
            "text_datablocks_present": {"passed": True, "detail": "All 2 required text datablocks present"},
            "physics_configured": {"passed": True, "detail": "Fallback CHARACTER physics on KiroPlayer (runtime bootstrap required)"},
            "door_components_attached": {"passed": True, "detail": "All 1 doors have DoorComponent"},
        },
        "all_passed": True,
    }
    return f"Blender 5.0.1\nRead blend: /tmp/test.blend\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


def _probe_player_component_failure_output() -> str:
    """Produce a stdout string where player_component_attached check fails."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": {
            "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
            "player_component_attached": {"passed": False, "detail": "Player object 'KiroPlayer' has no component (native or fallback)"},
            "text_datablocks_present": {"passed": True, "detail": "All 2 required text datablocks present"},
            "physics_configured": {"passed": True, "detail": "Fallback CHARACTER physics on KiroPlayer"},
            "door_components_attached": {"passed": True, "detail": "No doors in scene (vacuously true)"},
        },
        "all_passed": False,
    }
    return f"Blender 5.0.1\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


def _probe_physics_failure_output() -> str:
    """Produce a stdout string where physics_configured check fails."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": {
            "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
            "player_component_attached": {"passed": True, "detail": "Fallback component on KiroPlayer"},
            "text_datablocks_present": {"passed": True, "detail": "All 2 required text datablocks present"},
            "physics_configured": {"passed": False, "detail": "Player 'KiroPlayer' has no CHARACTER physics configured"},
            "door_components_attached": {"passed": True, "detail": "No doors in scene (vacuously true)"},
        },
        "all_passed": False,
    }
    return f"Blender 5.0.1\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


def _probe_text_datablocks_failure_output() -> str:
    """Produce a stdout string where text_datablocks_present check fails."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": {
            "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
            "player_component_attached": {"passed": True, "detail": "Fallback component on KiroPlayer"},
            "text_datablocks_present": {"passed": False, "detail": "Missing: kiro_player_first_person.py"},
            "physics_configured": {"passed": True, "detail": "Fallback CHARACTER physics on KiroPlayer"},
            "door_components_attached": {"passed": True, "detail": "No doors in scene (vacuously true)"},
        },
        "all_passed": False,
    }
    return f"Blender 5.0.1\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


def _probe_door_components_failure_output() -> str:
    """Produce a stdout string where door_components_attached check fails."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": {
            "scene_loads": {"passed": True, "detail": "Scene loaded with 5 objects"},
            "player_component_attached": {"passed": True, "detail": "Fallback component on KiroPlayer"},
            "text_datablocks_present": {"passed": True, "detail": "All 2 required text datablocks present"},
            "physics_configured": {"passed": True, "detail": "Fallback CHARACTER physics on KiroPlayer"},
            "door_components_attached": {"passed": False, "detail": "1/2 doors have components; missing: Door.002"},
        },
        "all_passed": False,
    }
    return f"Blender 5.0.1\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


def _probe_scene_load_failure_output() -> str:
    """Produce a stdout string where scene_loads check fails."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": {
            "scene_loads": {"passed": False, "detail": "Scene load error: FileNotFoundError"},
            "player_component_attached": {"passed": False, "detail": "Skipped (scene failed to load)"},
            "text_datablocks_present": {"passed": False, "detail": "Skipped (scene failed to load)"},
            "physics_configured": {"passed": False, "detail": "Skipped (scene failed to load)"},
            "door_components_attached": {"passed": False, "detail": "Skipped (scene failed to load)"},
        },
        "all_passed": False,
    }
    return f"Blender 5.0.1\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


class TestRunStructuralSmokePreConditions:
    """Tests for early-return precondition failures."""

    def test_returns_failure_when_no_executable_path(self, tmp_path: Path) -> None:
        """run_structural_smoke returns failure when capability has no executable_path."""
        capability = _make_capability(executable_path=None)
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "executable_missing"
        assert result.checks == ()
        assert result.duration_ms >= 0

    def test_returns_failure_when_blend_path_not_exists(self, tmp_path: Path) -> None:
        """run_structural_smoke returns failure when blend_path doesn't exist."""
        capability = _make_capability()
        blend_path = tmp_path / "nonexistent.blend"

        result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "blend_not_found"
        assert result.checks == ()


class TestRunStructuralSmokeSubprocess:
    """Tests for subprocess invocation and parsing."""

    def test_parses_successful_probe_result(self, tmp_path: Path) -> None:
        """run_structural_smoke correctly parses a successful probe result."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_probe_success_output_050(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is True
        assert result.reason_code == "structural_ok"
        assert len(result.checks) == 5
        assert all(check.passed for check in result.checks)
        assert result.duration_ms >= 0

    def test_handles_timeout_gracefully(self, tmp_path: Path) -> None:
        """run_structural_smoke returns probe_timeout on subprocess timeout."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        with patch(
            "src.smoke_validator.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="upbge", timeout=15.0),
        ):
            result = run_structural_smoke(
                capability, blend_path, _make_runtime_plan(), timeout_s=15.0
            )

        assert result.passed is False
        assert result.reason_code == "probe_timeout"
        assert result.checks == ()

    def test_handles_missing_smoke_result_marker(self, tmp_path: Path) -> None:
        """run_structural_smoke returns probe_parse_error when no SMOKE_RESULT= in output."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Blender 5.0.1\nSome startup log\nNo result here\n",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "probe_parse_error"
        assert result.checks == ()

    def test_handles_invalid_json_in_result_line(self, tmp_path: Path) -> None:
        """run_structural_smoke returns probe_parse_error on malformed JSON."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"{_SMOKE_RESULT_MARKER}not-valid-json{{{{",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "probe_parse_error"

    def test_handles_os_error_on_subprocess(self, tmp_path: Path) -> None:
        """run_structural_smoke returns executable_missing on OSError."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        with patch(
            "src.smoke_validator.subprocess.run",
            side_effect=OSError("No such file or directory"),
        ):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "executable_missing"

    def test_player_component_failure_reports_correct_reason(self, tmp_path: Path) -> None:
        """run_structural_smoke reports player_component_missing when that check fails."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_probe_player_component_failure_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "player_component_missing"
        assert len(result.checks) == 5
        player_check = next(c for c in result.checks if c.name == "player_component_attached")
        assert player_check.passed is False
        assert "no component" in player_check.detail

    def test_physics_failure_reports_correct_reason(self, tmp_path: Path) -> None:
        """run_structural_smoke reports physics_not_configured when physics check fails."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_probe_physics_failure_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "physics_not_configured"
        physics_check = next(c for c in result.checks if c.name == "physics_configured")
        assert physics_check.passed is False

    def test_text_datablocks_failure_reports_correct_reason(self, tmp_path: Path) -> None:
        """run_structural_smoke reports text_datablocks_missing when check fails."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_probe_text_datablocks_failure_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "text_datablocks_missing"
        text_check = next(c for c in result.checks if c.name == "text_datablocks_present")
        assert text_check.passed is False
        assert "Missing" in text_check.detail

    def test_door_components_failure_reports_correct_reason(self, tmp_path: Path) -> None:
        """run_structural_smoke reports door_components_missing when check fails."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_probe_door_components_failure_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "door_components_missing"
        door_check = next(c for c in result.checks if c.name == "door_components_attached")
        assert door_check.passed is False

    def test_scene_load_failure_reports_correct_reason(self, tmp_path: Path) -> None:
        """run_structural_smoke reports scene_load_error when scene fails to load."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout=_probe_scene_load_failure_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "scene_load_error"
        scene_check = next(c for c in result.checks if c.name == "scene_loads")
        assert scene_check.passed is False

    def test_handles_empty_checks_dict(self, tmp_path: Path) -> None:
        """run_structural_smoke returns probe_parse_error when checks dict is empty/missing."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        payload = {"schema_version": "smoke-probe-050/v1", "checks": "not-a-dict", "all_passed": False}
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "probe_parse_error"

    def test_command_uses_correct_argument_order(self, tmp_path: Path) -> None:
        """run_structural_smoke passes blend_path after '--' not as positional arg."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        captured_command = []

        def mock_run(cmd, **kwargs):
            captured_command.extend(cmd)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0,
                stdout=_probe_success_output_050(),
                stderr="",
            )

        with patch("src.smoke_validator.subprocess.run", side_effect=mock_run):
            run_structural_smoke(capability, blend_path, _make_runtime_plan())

        # Verify command structure: upbge --background --python <script> -- <blend>
        assert Path(captured_command[0]) == Path("C:/upbge/upbge.exe")
        assert captured_command[1] == "--background"
        assert captured_command[2] == "--python"
        # captured_command[3] is the temp file path (variable)
        assert captured_command[4] == "--"
        assert captured_command[5] == str(blend_path)
