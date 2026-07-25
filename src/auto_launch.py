"""
Auto-launch data models for blenderplayer subprocess management.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LaunchResult:
    """Immutable result of a blenderplayer auto-launch attempt."""

    success: bool
    pid: int | None
    executable: str  # path to blenderplayer
    blend_path: str
    reason_code: str  # "launched", "blenderplayer_not_found", "process_exited", "file_missing"
    diagnostics: str
    fallback_instructions: str | None  # Platform-specific manual launch instructions
