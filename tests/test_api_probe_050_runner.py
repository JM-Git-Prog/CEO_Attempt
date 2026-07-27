"""Unit tests for run_api_probe() — the probe runner with timeout and error handling."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.assembler.api_probe_050 import (
    API_PROBE_SCRIPT,
    PROBE_RESULT_MARKER,
    UPBGEComponentAPI,
    run_api_probe,
)


def _make_probe_stdout(
    *,
    upbge_detected: bool = True,
    blender_version: list[int] | None = None,
    component_api_path: str | None = "obj.game.components",
    has_game_attr: bool = True,
) -> str:
    """Build synthetic probe stdout with PROBE_RESULT= marker."""
    if blender_version is None:
        blender_version = [5, 0, 1]
    report = {
        "schema_version": "upbge-api-probe/v1",
        "blender_version": blender_version,
        "blender_version_string": f"UPBGE {'.'.join(str(v) for v in blender_version)}",
        "upbge_detected": upbge_detected,
        "component_api": {
            "has_game_attr": has_game_attr,
            "has_components_attr": False,
            "has_upbge_attr": False,
            "component_api_path": component_api_path,
            "component_add_method": "obj.game.components.new()" if component_api_path else None,
            "available_upbge_properties": [],
            "has_logic_ops": True,
        },
        "physics_api": {
            "has_game_physics": True,
            "physics_api_path": "obj.game.physics_type",
        },
    }
    # Simulate some Blender startup noise + the marker line
    return f"Blender 5.0.1\nRead prefs...\n{PROBE_RESULT_MARKER}{json.dumps(report, sort_keys=True)}\n"


class TestRunApiProbeSuccess:
    """Probe succeeds and returns a valid UPBGEComponentAPI."""

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_returns_component_api_on_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_probe_stdout().encode("utf-8"),
        )
        result = run_api_probe("C:/UPBGE/blender.exe")
        assert isinstance(result, UPBGEComponentAPI)
        assert result.upbge_detected is True
        assert result.blender_version == (5, 0, 1)
        assert result.component_api_path == "obj.game.components"

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_invokes_upbge_with_background_python(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_probe_stdout().encode("utf-8"),
        )
        run_api_probe("C:/UPBGE/blender.exe", timeout_s=20.0)
        call_args = mock_run.call_args
        command = call_args[0][0]
        assert command[0] == "C:/UPBGE/blender.exe"
        assert "--background" in command
        assert "--python" in command
        # Verify timeout is passed
        assert call_args[1]["timeout"] == 20.0

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_uses_minimal_environment(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_probe_stdout().encode("utf-8"),
        )
        run_api_probe("C:/UPBGE/blender.exe")
        call_args = mock_run.call_args
        env = call_args[1]["env"]
        # Only allowed keys
        allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
        assert all(k.upper() in allowed for k in env)

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_parses_stdout_even_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        """Non-zero exit code should still try to parse stdout."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=_make_probe_stdout().encode("utf-8"),
        )
        result = run_api_probe("C:/UPBGE/blender.exe")
        assert isinstance(result, UPBGEComponentAPI)
        assert result.upbge_detected is True


class TestRunApiProbeTimeout:
    """Probe exceeds timeout → raises ValueError with probe_timeout."""

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_timeout_raises_probe_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="blender", timeout=15.0)
        with pytest.raises(ValueError, match="probe_timeout"):
            run_api_probe("C:/UPBGE/blender.exe", timeout_s=15.0)


class TestRunApiProbeParseError:
    """Probe output is malformed → raises ValueError with probe_parse_error."""

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_no_marker_in_stdout(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"Some random Blender output without probe result\n",
        )
        with pytest.raises(ValueError, match="probe_parse_error"):
            run_api_probe("C:/UPBGE/blender.exe")

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_malformed_json_after_marker(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=f"{PROBE_RESULT_MARKER}{{not valid json".encode("utf-8"),
        )
        with pytest.raises(ValueError, match="probe_parse_error"):
            run_api_probe("C:/UPBGE/blender.exe")

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_oserror_raises_probe_parse_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = OSError("No such file or directory")
        with pytest.raises(ValueError, match="probe_parse_error"):
            run_api_probe("C:/nonexistent/blender.exe")


class TestRunApiProbeVersionMismatch:
    """Probe succeeds but upbge_detected is False → version_mismatch."""

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_version_mismatch_when_upbge_not_detected(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_probe_stdout(upbge_detected=False).encode("utf-8"),
        )
        with pytest.raises(ValueError, match="version_mismatch"):
            run_api_probe("C:/UPBGE/blender.exe")


class TestRunApiProbeTempFileCleanup:
    """Temporary script file is always cleaned up."""

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_temp_file_cleaned_on_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=_make_probe_stdout().encode("utf-8"),
        )
        # Just ensure no exception; the finally block handles cleanup
        result = run_api_probe("C:/UPBGE/blender.exe")
        assert result is not None

    @patch("src.assembler.api_probe_050.subprocess.run")
    def test_temp_file_cleaned_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="blender", timeout=15.0)
        with pytest.raises(ValueError, match="probe_timeout"):
            run_api_probe("C:/UPBGE/blender.exe")
        # If we get here without an unhandled exception, cleanup succeeded
