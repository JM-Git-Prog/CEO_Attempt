"""Tests for auto_launch_game() with UPBGE 0.50 component-based runtime_candidate.

Validates task 8.1 requirements:
- blenderplayer is invoked WITHOUT --background flag
- Process remains running for minimum 3 seconds → success
- Process exits within 3 seconds → failure with exit code and stderr
- blenderplayer.exe not found → failure with reason_code
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import io

import pytest

from src.auto_launch import LaunchResult, auto_launch_game
from src.upbge_capabilities import UPBGECapabilityReport


# --- Helpers ---


def _make_capability(
    blenderplayer_path: str | None = r"C:\Program Files\UPBGE\upbge-0.50-windows-x64 (1)\upbge-0.50-windows-x64\blenderplayer.exe",
    blenderplayer_available: bool = True,
    blenderplayer_verified: bool = True,
    blenderplayer_reason_code: str = "blenderplayer_verified",
) -> UPBGECapabilityReport:
    """Create a capability report resembling the real UPBGE 0.50 install."""
    return UPBGECapabilityReport(
        available=True,
        verified=True,
        compatible=True,
        executable_path=r"C:\Program Files\UPBGE\upbge-0.50-windows-x64 (1)\upbge-0.50-windows-x64\blender.exe",
        product="UPBGE",
        product_version="upbge-0.50",
        supports_game_runtime=True,
        blenderplayer_path=blenderplayer_path,
        blenderplayer_available=blenderplayer_available,
        blenderplayer_verified=blenderplayer_verified,
        blenderplayer_reason_code=blenderplayer_reason_code,
        blenderplayer_diagnostics=(),
    )


def _make_runtime_candidate(tmp_path: Path) -> Path:
    """Create a dummy runtime_candidate.blend produced by the new compiler."""
    p = tmp_path / "runtime_candidate.blend"
    # Non-zero file simulating a .blend with embedded KX_PythonComponent
    p.write_bytes(b"\x00" * 4096)
    return p


# --- Test: process stays running for 3+ seconds → success ---


class TestProcessStaysRunningSuccess:
    """Requirement 8.2: Verify process remains running for minimum 3 seconds."""

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_running_for_3_seconds_is_success(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Process stays running for 3s → success (scene loaded)."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Always running
        mock_proc.pid = 54321
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close = MagicMock()
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=3.0)

        assert result.success is True
        assert result.reason_code == "launched"
        assert result.pid == 54321
        assert "running" in result.diagnostics.lower()


# --- Test: process exits immediately → failure with exit code ---


class TestProcessExitsEarlyFailure:
    """Requirement 8.3: Report failure with exit code and stderr if process exits within 3s."""

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_exits_immediately_with_exit_code(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Process exits with code 1 immediately → failure with exit code in diagnostics."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited with code 1
        mock_proc.pid = 11111
        # Simulate stderr pipe with error message
        mock_proc.stderr = io.BytesIO(b"Error: Scene has no active camera\n")
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "process_exited"
        assert result.pid == 11111
        assert "exited with code 1" in result.diagnostics
        assert "Scene has no active camera" in result.diagnostics

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_exits_with_segfault(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Process exits with signal-like code and GPU error → includes stderr."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = -11  # SIGSEGV
        mock_proc.pid = 22222
        mock_proc.stderr = io.BytesIO(b"FATAL: GPU not supported\n")
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "process_exited"
        assert "exited with code -11" in result.diagnostics
        assert "GPU not supported" in result.diagnostics

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_exits_with_empty_stderr(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Process exits with no stderr → still reports exit code."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 2
        mock_proc.pid = 33333
        mock_proc.stderr = io.BytesIO(b"")  # Empty stderr
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "process_exited"
        assert "exited with code 2" in result.diagnostics


# --- Test: --background NOT in command args ---


class TestNoBackgroundFlag:
    """Requirement 8.6: --background flag SHALL NOT be passed to blenderplayer."""

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_no_background_flag_fullscreen(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Fullscreen mode: command has NO --background."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close = MagicMock()
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        auto_launch_game(cap, blend, fullscreen=True, timeout_s=0.1)

        call_args = mock_popen.call_args[0][0]
        assert "--background" not in call_args
        assert "-b" not in call_args  # Short form also prohibited

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_no_background_flag_windowed(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Windowed mode: command has NO --background."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close = MagicMock()
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        auto_launch_game(cap, blend, fullscreen=False, timeout_s=0.1)

        call_args = mock_popen.call_args[0][0]
        assert "--background" not in call_args
        assert "-b" not in call_args

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_command_contains_blend_path(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Command includes the runtime_candidate.blend path."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.close = MagicMock()
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_runtime_candidate(tmp_path)

        auto_launch_game(cap, blend, fullscreen=False, timeout_s=0.1)

        call_args = mock_popen.call_args[0][0]
        assert str(blend) in call_args


# --- Test: blenderplayer.exe not found → failure ---


class TestBlenderplayerNotFound050:
    """Requirement 9.3: blenderplayer not found → graceful failure."""

    def test_blenderplayer_path_none(self, tmp_path: Path) -> None:
        """No blenderplayer in capability report → blenderplayer_not_found."""
        cap = _make_capability(
            blenderplayer_path=None,
            blenderplayer_available=False,
            blenderplayer_reason_code="blenderplayer_not_found",
        )
        blend = _make_runtime_candidate(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "blenderplayer_not_found"
        assert result.pid is None
        assert result.fallback_instructions is not None

    def test_blenderplayer_not_available(self, tmp_path: Path) -> None:
        """blenderplayer file exists but verification failed → not_found."""
        cap = _make_capability(
            blenderplayer_path=r"C:\some\path\blenderplayer.exe",
            blenderplayer_available=False,
            blenderplayer_reason_code="blenderplayer_gpu_error",
        )
        blend = _make_runtime_candidate(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "blenderplayer_not_found"
        assert "blenderplayer_gpu_error" in result.diagnostics


# --- Test: runtime_candidate.blend file verification ---


class TestRuntimeCandidateFileCheck:
    """Validate blend file checks work with runtime_candidate from new compiler."""

    def test_missing_runtime_candidate(self, tmp_path: Path) -> None:
        """Non-existent runtime_candidate.blend → file_missing."""
        cap = _make_capability()
        missing = tmp_path / "runtime_candidate.blend"

        result = auto_launch_game(cap, missing, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "file_missing"
        assert "runtime_candidate.blend" in result.diagnostics

    def test_empty_runtime_candidate(self, tmp_path: Path) -> None:
        """Zero-byte runtime_candidate.blend → file_missing."""
        cap = _make_capability()
        empty = tmp_path / "runtime_candidate.blend"
        empty.write_bytes(b"")

        result = auto_launch_game(cap, empty, timeout_s=3.0)

        assert result.success is False
        assert result.reason_code == "file_missing"
