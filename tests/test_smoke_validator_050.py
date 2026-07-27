"""Tests for the UPBGE 0.50 smoke validator function (run_structural_smoke_050).

Verifies that:
- Successful validation returns passed=True with reason_code="smoke_passed"
- Failed validation returns the first failed check as reason_code
- Timeout errors are handled gracefully
- Parse errors are handled gracefully
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.smoke_validator import run_structural_smoke_050
from src.assembler.smoke_probe_050 import SMOKE_RESULT_MARKER


# ---------------------------------------------------------------------------
# Helpers to build probe output strings
# ---------------------------------------------------------------------------

def _build_probe_stdout(checks: dict, all_passed: bool) -> str:
    """Build a stdout string as if from the UPBGE 0.50 smoke probe."""
    payload = {
        "schema_version": "smoke-probe-050/v1",
        "checks": checks,
        "all_passed": all_passed,
    }
    # Simulate typical UPBGE startup noise before the result line
    return (
        "Blender 5.0.1 (UPBGE 0.50)\n"
        "Read prefs: C:\\Users\\test\\prefs\\userpref.blend\n"
        f"{SMOKE_RESULT_MARKER}{json.dumps(payload)}\n"
    )


def _all_passing_checks() -> dict:
    """Return a checks dict where all 5 checks pass."""
    return {
        "scene_loads": {"passed": True, "detail": "Scene loaded with 42 objects"},
        "player_component_attached": {"passed": True, "detail": "Native component on KiroPlayer"},
        "text_datablocks_present": {"passed": True, "detail": "All 2 required text datablocks present"},
        "physics_configured": {"passed": True, "detail": "Native CHARACTER physics on KiroPlayer"},
        "door_components_attached": {"passed": True, "detail": "All 2 doors have DoorComponent"},
    }


def _checks_with_failure(failed_check: str, detail: str) -> dict:
    """Return a checks dict where one specific check fails."""
    checks = _all_passing_checks()
    checks[failed_check] = {"passed": False, "detail": detail}
    return checks


# ---------------------------------------------------------------------------
# Tests: Successful validation
# ---------------------------------------------------------------------------

class TestRunStructuralSmoke050Success:
    """Tests for successful validation scenarios."""

    def test_all_checks_pass_returns_passed_true(self) -> None:
        """When all probe checks pass, returns passed=True with smoke_passed reason."""
        checks = _all_passing_checks()
        stdout = _build_probe_stdout(checks, all_passed=True)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=stdout, stderr=""
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is True
        assert result["reason_code"] == "smoke_passed"
        assert result["detail"] == "All checks passed"
        assert result["checks"] == checks

    def test_checks_dict_preserved_on_success(self) -> None:
        """The checks dict from the probe is returned as-is on success."""
        checks = _all_passing_checks()
        stdout = _build_probe_stdout(checks, all_passed=True)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=stdout, stderr=""
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert "scene_loads" in result["checks"]
        assert "player_component_attached" in result["checks"]
        assert "text_datablocks_present" in result["checks"]
        assert "physics_configured" in result["checks"]
        assert "door_components_attached" in result["checks"]


# ---------------------------------------------------------------------------
# Tests: Failed validation (first failed check reported)
# ---------------------------------------------------------------------------

class TestRunStructuralSmoke050Failure:
    """Tests for validation failure scenarios."""

    @pytest.mark.parametrize("failed_check,detail", [
        ("scene_loads", "Scene has no objects"),
        ("player_component_attached", "No player object found"),
        ("text_datablocks_present", "Missing: kiro_player_first_person.py"),
        ("physics_configured", "Player 'KiroPlayer' has no CHARACTER physics configured"),
        ("door_components_attached", "1/2 doors have components; missing: Door.001"),
    ])
    def test_reports_first_failed_check_as_reason_code(
        self, failed_check: str, detail: str
    ) -> None:
        """On failure, the first failed check name becomes the reason_code."""
        checks = _checks_with_failure(failed_check, detail)
        stdout = _build_probe_stdout(checks, all_passed=False)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=stdout, stderr=""
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == failed_check
        assert result["detail"] == detail
        assert result["checks"] == checks

    def test_first_failed_check_in_evaluation_order(self) -> None:
        """When multiple checks fail, the one earliest in evaluation order wins."""
        checks = _all_passing_checks()
        # Fail both physics and door checks — physics is earlier in order
        checks["physics_configured"] = {"passed": False, "detail": "No physics"}
        checks["door_components_attached"] = {"passed": False, "detail": "No doors"}
        stdout = _build_probe_stdout(checks, all_passed=False)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=stdout, stderr=""
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "physics_configured"

    def test_scene_load_failure_is_first_in_order(self) -> None:
        """scene_loads is the first check so its failure always takes priority."""
        checks = {
            "scene_loads": {"passed": False, "detail": "Scene load error: corrupt"},
            "player_component_attached": {"passed": False, "detail": "Skipped"},
            "text_datablocks_present": {"passed": False, "detail": "Skipped"},
            "physics_configured": {"passed": False, "detail": "Skipped"},
            "door_components_attached": {"passed": False, "detail": "Skipped"},
        }
        stdout = _build_probe_stdout(checks, all_passed=False)

        mock_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=stdout, stderr=""
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "scene_loads"
        assert "corrupt" in result["detail"]


# ---------------------------------------------------------------------------
# Tests: Timeout handling
# ---------------------------------------------------------------------------

class TestRunStructuralSmoke050Timeout:
    """Tests for timeout error handling."""

    def test_timeout_returns_smoke_timeout(self) -> None:
        """When subprocess times out, returns smoke_timeout reason_code."""
        with patch(
            "src.smoke_validator.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="upbge", timeout=30.0),
        ):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend", timeout_s=30.0
            )

        assert result["passed"] is False
        assert result["reason_code"] == "smoke_timeout"
        assert "30.0" in result["detail"]
        assert result["checks"] == {}


# ---------------------------------------------------------------------------
# Tests: Parse error handling
# ---------------------------------------------------------------------------

class TestRunStructuralSmoke050ParseError:
    """Tests for parse error handling."""

    def test_no_smoke_result_marker_returns_parse_error(self) -> None:
        """When stdout has no SMOKE_RESULT= marker, returns smoke_parse_error."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Blender startup log\nSome other output\nNo result here\n",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "smoke_parse_error"
        assert "marker not found" in result["detail"]
        assert result["checks"] == {}

    def test_invalid_json_returns_parse_error(self) -> None:
        """When JSON after marker is malformed, returns smoke_parse_error."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"{SMOKE_RESULT_MARKER}{{not valid json!!!",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "smoke_parse_error"
        assert result["checks"] == {}

    def test_checks_not_a_dict_returns_parse_error(self) -> None:
        """When checks field is not a dict, returns smoke_parse_error."""
        payload = {
            "schema_version": "smoke-probe-050/v1",
            "checks": "not-a-dict",
            "all_passed": False,
        }
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f"{SMOKE_RESULT_MARKER}{json.dumps(payload)}",
            stderr="",
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "smoke_parse_error"
        assert result["checks"] == {}

    def test_os_error_returns_parse_error(self) -> None:
        """When subprocess raises OSError (e.g. exe not found), returns smoke_parse_error."""
        with patch(
            "src.smoke_validator.subprocess.run",
            side_effect=OSError("No such file or directory"),
        ):
            result = run_structural_smoke_050(
                "C:/nonexistent/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "smoke_parse_error"
        assert "Failed to invoke UPBGE" in result["detail"]
        assert result["checks"] == {}

    def test_empty_stdout_returns_parse_error(self) -> None:
        """When stdout is empty, returns smoke_parse_error."""
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )

        with patch("src.smoke_validator.subprocess.run", return_value=mock_result):
            result = run_structural_smoke_050(
                "C:/upbge/blender.exe", "C:/scene/runtime.blend"
            )

        assert result["passed"] is False
        assert result["reason_code"] == "smoke_parse_error"
        assert result["checks"] == {}
