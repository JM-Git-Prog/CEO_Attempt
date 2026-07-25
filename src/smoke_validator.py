"""
Smoke validator data models for structural .blend validation via bpy.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SmokeCheck:
    """Result of a single structural smoke check."""

    name: str  # "player_controller_exists", "character_physics", "logic_bricks_wired", "scene_loads"
    passed: bool
    detail: str


@dataclass(frozen=True)
class SmokeValidationResult:
    """Aggregate result of all structural smoke checks on a .blend file."""

    passed: bool
    checks: tuple[SmokeCheck, ...]  # individual check results
    reason_code: str  # "structural_ok", "missing_controller", "physics_misconfigured", etc.
    duration_ms: int
