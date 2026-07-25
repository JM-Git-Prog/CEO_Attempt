"""Tests for the smoke_validator module.

Verifies run_structural_smoke handles precondition failures, subprocess
outcomes, and result parsing correctly.
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


def _probe_success_output() -> str:
    """Produce a stdout string with a successful SMOKE_RESULT line."""
    payload = {
        "success": True,
        "checks": {
            "player_controller_exists": {"passed": True, "detail": "Found 1 text datablock(s)"},
            "character_physics": {"passed": True, "detail": "Found 1 object(s) with CHARACTER physics"},
            "logic_bricks_wired": {"passed": True, "detail": "Wired: 2, unwired: 0"},
            "scene_loads": {"passed": True, "detail": "Scene loaded successfully via bpy"},
        },
    }
    # Simulate engine startup noise plus the result line
    return f"Blender 3.6.0\nRead blend: /tmp/test.blend\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


def _probe_partial_failure_output() -> str:
    """Produce a stdout string where character_physics check fails."""
    payload = {
        "success": True,
        "checks": {
            "player_controller_exists": {"passed": True, "detail": "Found 1 text datablock(s)"},
            "character_physics": {"passed": False, "detail": "Found 0 object(s) with CHARACTER physics"},
            "logic_bricks_wired": {"passed": True, "detail": "Wired: 2, unwired: 0"},
            "scene_loads": {"passed": True, "detail": "Scene loaded successfully via bpy"},
        },
    }
    return f"Blender 3.6.0\n{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"


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
            stdout=_probe_success_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is True
        assert result.reason_code == "structural_ok"
        assert len(result.checks) == 4
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
            stdout="Blender 3.6.0\nSome startup log\nNo result here\n",
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

    def test_partial_check_failure_reports_correct_reason(self, tmp_path: Path) -> None:
        """run_structural_smoke reports character_physics_missing when that check fails."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_probe_partial_failure_output(),
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "character_physics_missing"
        assert len(result.checks) == 4
        # The character_physics check should be the one that failed
        physics_check = next(c for c in result.checks if c.name == "character_physics")
        assert physics_check.passed is False

    def test_handles_empty_checks_dict(self, tmp_path: Path) -> None:
        """run_structural_smoke returns probe_parse_error when checks dict is empty/missing."""
        capability = _make_capability()
        blend_path = tmp_path / "scene.blend"
        blend_path.write_bytes(b"BLENDER")

        payload = {"success": True, "checks": "not-a-dict"}
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"{_SMOKE_RESULT_MARKER}{json.dumps(payload)}\n",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke(capability, blend_path, _make_runtime_plan())

        assert result.passed is False
        assert result.reason_code == "probe_parse_error"
