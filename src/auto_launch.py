"""
Auto-launch module for blenderplayer subprocess management.

Provides `auto_launch_game` which discovers blenderplayer from a capability report,
starts it as a non-blocking subprocess, and returns a structured LaunchResult.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src.upbge_capabilities import UPBGECapabilityReport


@dataclass(frozen=True)
class LaunchResult:
    """Immutable result of a blenderplayer auto-launch attempt."""

    success: bool
    pid: int | None
    executable: str  # path to blenderplayer
    blend_path: str
    reason_code: str  # "launched", "blenderplayer_not_found", "process_exited", "file_missing", "process_start_failed"
    diagnostics: str
    fallback_instructions: str | None  # Platform-specific manual launch instructions


def _platform() -> str:
    """Small seam for platform-specific tests."""
    return sys.platform


def _generate_fallback_instructions(
    executable: str,
    blend_path: str,
    fullscreen: bool,
) -> str:
    """Generate platform-specific manual launch instructions."""
    platform = _platform()

    if fullscreen:
        cmd = f'"{executable}" -f 0 0 "{blend_path}"'
    else:
        cmd = f'"{executable}" "{blend_path}"'

    if platform == "win32" or platform == "cygwin":
        return (
            "To launch the game manually on Windows:\n"
            f"  1. Open Command Prompt or PowerShell\n"
            f"  2. Run: {cmd}\n"
            f"\n"
            f"Or double-click the .blend file if blenderplayer is associated."
        )
    elif platform == "darwin":
        return (
            "To launch the game manually on macOS:\n"
            f"  1. Open Terminal\n"
            f"  2. Run: {cmd}\n"
        )
    else:
        return (
            "To launch the game manually on Linux:\n"
            f"  1. Open a terminal\n"
            f"  2. Run: {cmd}\n"
        )


def auto_launch_game(
    capability: UPBGECapabilityReport,
    blend_path: Path,
    *,
    fullscreen: bool = True,
    timeout_s: float = 10.0,
) -> LaunchResult:
    """Launch blenderplayer on the compiled .blend file.

    Strategy:
    1. Verify blend_path exists and is non-zero
    2. Discover blenderplayer from capability.blenderplayer_path
    3. Start subprocess (non-blocking — game runs independently)
    4. Wait up to timeout_s for process to NOT exit (confirms it's running)
    5. Return LaunchResult with PID for tracking

    CRITICAL: Uses blenderplayer (standalone game player), NOT the UPBGE editor.
    """
    blend_path = Path(blend_path)
    blend_str = str(blend_path)

    # 1. Verify blend_path exists and is non-zero bytes
    if not blend_path.exists() or blend_path.stat().st_size == 0:
        executable = capability.blenderplayer_path or ""
        return LaunchResult(
            success=False,
            pid=None,
            executable=executable,
            blend_path=blend_str,
            reason_code="file_missing",
            diagnostics=f"Blend file missing or empty: {blend_str}",
            fallback_instructions=None,
        )

    # 2. Discover blenderplayer from capability report
    if not capability.blenderplayer_path or not capability.blenderplayer_available:
        return LaunchResult(
            success=False,
            pid=None,
            executable=capability.blenderplayer_path or "",
            blend_path=blend_str,
            reason_code="blenderplayer_not_found",
            diagnostics=(
                f"blenderplayer not available. "
                f"Reason: {capability.blenderplayer_reason_code}. "
                f"Diagnostics: {'; '.join(capability.blenderplayer_diagnostics)}"
            ),
            fallback_instructions=_generate_fallback_instructions(
                capability.blenderplayer_path or "blenderplayer",
                blend_str,
                fullscreen,
            ),
        )

    executable = capability.blenderplayer_path

    # 3. Construct launch command
    cmd: list[str] = [executable]
    if fullscreen:
        cmd.extend(["-f", "0", "0"])
    cmd.append(blend_str)

    # 4. Start subprocess non-blocking
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return LaunchResult(
            success=False,
            pid=None,
            executable=executable,
            blend_path=blend_str,
            reason_code="process_start_failed",
            diagnostics=f"Failed to start blenderplayer: {exc}",
            fallback_instructions=_generate_fallback_instructions(
                executable, blend_str, fullscreen
            ),
        )

    # 5. Wait up to timeout_s; confirm process is still running
    poll_interval = min(0.2, timeout_s / 10) if timeout_s > 0 else 0.1
    elapsed = 0.0
    while elapsed < timeout_s:
        exit_code = process.poll()
        if exit_code is not None:
            # Process exited prematurely
            return LaunchResult(
                success=False,
                pid=process.pid,
                executable=executable,
                blend_path=blend_str,
                reason_code="process_exited",
                diagnostics=(
                    f"blenderplayer exited with code {exit_code} "
                    f"within {elapsed:.1f}s of launch"
                ),
                fallback_instructions=_generate_fallback_instructions(
                    executable, blend_str, fullscreen
                ),
            )
        time.sleep(poll_interval)
        elapsed += poll_interval

    # Process is still running after timeout_s — success
    return LaunchResult(
        success=True,
        pid=process.pid,
        executable=executable,
        blend_path=blend_str,
        reason_code="launched",
        diagnostics=f"blenderplayer running (PID {process.pid})",
        fallback_instructions=None,
    )
