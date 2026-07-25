"""Tests for the auto_launch module.

Covers all failure modes and the success case for auto_launch_game,
using mocked subprocess to avoid spawning real processes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.auto_launch import LaunchResult, auto_launch_game, _generate_fallback_instructions
from src.upbge_capabilities import UPBGECapabilityReport


# --- Helpers ---


def _make_capability(
    blenderplayer_path: str | None = "C:/upbge/blenderplayer.exe",
    blenderplayer_available: bool = True,
    blenderplayer_verified: bool = True,
    blenderplayer_reason_code: str = "verified",
) -> UPBGECapabilityReport:
    """Create a minimal capability report for auto-launch testing."""
    return UPBGECapabilityReport(
        available=True,
        verified=True,
        compatible=True,
        executable_path="C:/upbge/upbge.exe",
        product="UPBGE",
        supports_game_runtime=True,
        blenderplayer_path=blenderplayer_path,
        blenderplayer_available=blenderplayer_available,
        blenderplayer_verified=blenderplayer_verified,
        blenderplayer_reason_code=blenderplayer_reason_code,
        blenderplayer_diagnostics=(),
    )


def _make_blend_file(tmp_path: Path, name: str = "game.blend", size: int = 1024) -> Path:
    """Create a dummy .blend file in tmp_path."""
    p = tmp_path / name
    p.write_bytes(b"\x00" * size)
    return p


# --- Tests: file_missing ---


class TestFileMissing:
    """Tests for the file_missing reason code."""

    def test_blend_path_does_not_exist(self, tmp_path: Path) -> None:
        """Non-existent blend_path returns file_missing."""
        cap = _make_capability()
        missing = tmp_path / "nonexistent.blend"

        result = auto_launch_game(cap, missing)

        assert result.success is False
        assert result.reason_code == "file_missing"
        assert result.pid is None
        assert "missing or empty" in result.diagnostics

    def test_blend_path_is_zero_bytes(self, tmp_path: Path) -> None:
        """Zero-byte blend file returns file_missing."""
        cap = _make_capability()
        empty_file = tmp_path / "empty.blend"
        empty_file.write_bytes(b"")

        result = auto_launch_game(cap, empty_file)

        assert result.success is False
        assert result.reason_code == "file_missing"
        assert result.pid is None


# --- Tests: blenderplayer_not_found ---


class TestBlenderplayerNotFound:
    """Tests for the blenderplayer_not_found reason code."""

    def test_blenderplayer_path_is_none(self, tmp_path: Path) -> None:
        """None blenderplayer_path returns blenderplayer_not_found."""
        cap = _make_capability(
            blenderplayer_path=None,
            blenderplayer_available=False,
            blenderplayer_reason_code="not_found",
        )
        blend = _make_blend_file(tmp_path)

        result = auto_launch_game(cap, blend)

        assert result.success is False
        assert result.reason_code == "blenderplayer_not_found"
        assert result.pid is None
        assert result.fallback_instructions is not None

    def test_blenderplayer_not_available(self, tmp_path: Path) -> None:
        """blenderplayer_available=False returns blenderplayer_not_found."""
        cap = _make_capability(
            blenderplayer_path="C:/upbge/blenderplayer.exe",
            blenderplayer_available=False,
            blenderplayer_reason_code="verification_failed",
        )
        blend = _make_blend_file(tmp_path)

        result = auto_launch_game(cap, blend)

        assert result.success is False
        assert result.reason_code == "blenderplayer_not_found"
        assert "verification_failed" in result.diagnostics
        assert result.fallback_instructions is not None


# --- Tests: process_start_failed ---


class TestProcessStartFailed:
    """Tests for the process_start_failed reason code (OSError)."""

    @patch("src.auto_launch.subprocess.Popen")
    def test_os_error_on_popen(self, mock_popen: MagicMock, tmp_path: Path) -> None:
        """OSError during Popen returns process_start_failed."""
        mock_popen.side_effect = OSError("Permission denied")
        cap = _make_capability()
        blend = _make_blend_file(tmp_path)

        result = auto_launch_game(cap, blend)

        assert result.success is False
        assert result.reason_code == "process_start_failed"
        assert result.pid is None
        assert "Permission denied" in result.diagnostics
        assert result.fallback_instructions is not None


# --- Tests: process_exited ---


class TestProcessExited:
    """Tests for the process_exited reason code."""

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_exits_immediately(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Process that exits immediately returns process_exited."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Exited with code 1
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_blend_file(tmp_path)

        result = auto_launch_game(cap, blend, timeout_s=2.0)

        assert result.success is False
        assert result.reason_code == "process_exited"
        assert result.pid == 12345
        assert "exited with code 1" in result.diagnostics
        assert result.fallback_instructions is not None


# --- Tests: launched (success) ---


class TestLaunched:
    """Tests for the launched reason code (success)."""

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_stays_running_fullscreen(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Process that stays running returns launched with PID."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running
        mock_proc.pid = 99999
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_blend_file(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=True, timeout_s=0.5)

        assert result.success is True
        assert result.reason_code == "launched"
        assert result.pid == 99999
        assert result.fallback_instructions is None
        # Verify fullscreen command construction
        call_args = mock_popen.call_args[0][0]
        assert "-f" in call_args
        assert "0" in call_args

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_process_stays_running_windowed(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Windowed mode does not pass -f flag."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 88888
        mock_popen.return_value = mock_proc
        cap = _make_capability()
        blend = _make_blend_file(tmp_path)

        result = auto_launch_game(cap, blend, fullscreen=False, timeout_s=0.5)

        assert result.success is True
        assert result.reason_code == "launched"
        # Verify windowed command construction — no -f flag
        call_args = mock_popen.call_args[0][0]
        assert "-f" not in call_args
        assert str(blend) in call_args


# --- Tests: command construction ---


class TestCommandConstruction:
    """Verify the launch command is correctly assembled."""

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_fullscreen_command(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Fullscreen command: blenderplayer -f 0 0 path/to/file.blend"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1
        mock_popen.return_value = mock_proc
        cap = _make_capability(blenderplayer_path="/usr/bin/blenderplayer")
        blend = _make_blend_file(tmp_path)

        auto_launch_game(cap, blend, fullscreen=True, timeout_s=0.1)

        expected_cmd = ["/usr/bin/blenderplayer", "-f", "0", "0", str(blend)]
        mock_popen.assert_called_once()
        actual_cmd = mock_popen.call_args[0][0]
        assert actual_cmd == expected_cmd

    @patch("src.auto_launch.subprocess.Popen")
    @patch("src.auto_launch.time.sleep")
    def test_windowed_command(
        self, mock_sleep: MagicMock, mock_popen: MagicMock, tmp_path: Path
    ) -> None:
        """Windowed command: blenderplayer path/to/file.blend"""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1
        mock_popen.return_value = mock_proc
        cap = _make_capability(blenderplayer_path="/usr/bin/blenderplayer")
        blend = _make_blend_file(tmp_path)

        auto_launch_game(cap, blend, fullscreen=False, timeout_s=0.1)

        expected_cmd = ["/usr/bin/blenderplayer", str(blend)]
        actual_cmd = mock_popen.call_args[0][0]
        assert actual_cmd == expected_cmd


# --- Tests: fallback instructions ---


class TestFallbackInstructions:
    """Verify platform-specific fallback instructions generation."""

    @patch("src.auto_launch._platform", return_value="win32")
    def test_windows_instructions(self, _mock_platform: MagicMock) -> None:
        """Windows fallback mentions Command Prompt."""
        instructions = _generate_fallback_instructions(
            "C:/upbge/blenderplayer.exe", "C:/output/game.blend", True
        )
        assert "Command Prompt" in instructions
        assert "blenderplayer.exe" in instructions
        assert "game.blend" in instructions

    @patch("src.auto_launch._platform", return_value="darwin")
    def test_macos_instructions(self, _mock_platform: MagicMock) -> None:
        """macOS fallback mentions Terminal."""
        instructions = _generate_fallback_instructions(
            "/Applications/blenderplayer", "/tmp/game.blend", False
        )
        assert "Terminal" in instructions
        assert "blenderplayer" in instructions

    @patch("src.auto_launch._platform", return_value="linux")
    def test_linux_instructions(self, _mock_platform: MagicMock) -> None:
        """Linux fallback mentions terminal."""
        instructions = _generate_fallback_instructions(
            "/usr/bin/blenderplayer", "/home/user/game.blend", True
        )
        assert "terminal" in instructions
        assert "blenderplayer" in instructions
        assert "-f 0 0" in instructions


# --- Tests: LaunchResult dataclass ---


class TestLaunchResultDataclass:
    """Verify LaunchResult is frozen and properly typed."""

    def test_frozen(self) -> None:
        """LaunchResult instances are immutable."""
        result = LaunchResult(
            success=True,
            pid=1,
            executable="blenderplayer",
            blend_path="game.blend",
            reason_code="launched",
            diagnostics="ok",
            fallback_instructions=None,
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            result.success = False  # type: ignore[misc]
