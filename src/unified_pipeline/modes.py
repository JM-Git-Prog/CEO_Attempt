"""Mode system data models for the Unified World Pipeline.

Defines GAME and REAL overlays as behavior layers on top of a stable
WorldContract. The toggle is per-room, persists across sessions, and
NEVER alters geometry, materials, or lighting — only behavior and
interaction affordances.

Requirements: 23.1, 23.2, 23.3, 24.1, 24.2, 24.3, 25.1, 25.2, 25.5
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


# ─── Mode Enum ─────────────────────────────────────────────────────────────────


class Mode(Enum):
    """Active mode for a room. Req 25.1."""

    GAME = "GAME"
    REAL = "REAL"


# ─── GameOverlay ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GameOverlay:
    """GAME mode behavior overlay.

    Frozen (immutable) — defines rules, scoring, win condition, and
    object role bindings by UUID. Does NOT alter geometry, materials,
    or lighting (Req 23.3).

    Req 23.1: rules, scoring, win_condition, object_role_bindings
    Req 23.2: bindings reference objects by stable UUID from Brief
    Req 23.3: overlay does NOT alter geometry/materials/lighting
    """

    rules: str = ""
    scoring: dict[str, Any] = field(default_factory=dict)
    win_condition: str = ""
    object_role_bindings: dict[str, str] = field(default_factory=dict)
    # object_role_bindings: UUID → role (e.g. "abc-123" → "target")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rules": self.rules,
            "scoring": dict(self.scoring),
            "win_condition": self.win_condition,
            "object_role_bindings": dict(self.object_role_bindings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GameOverlay:
        return cls(
            rules=data.get("rules", ""),
            scoring=dict(data.get("scoring", {})),
            win_condition=data.get("win_condition", ""),
            object_role_bindings=dict(data.get("object_role_bindings", {})),
        )


# ─── RealOverlay ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RealOverlay:
    """REAL mode behavior overlay.

    Frozen (immutable) — defines tool bindings by surface UUID.
    v1 is read-only: live data displayed on surfaces, no sending/paying/deleting.

    Req 24.1: read-only v1
    Req 24.2: bindings map surface UUIDs to tool types
    Req 24.3: bindings reference objects by stable UUID
    """

    tool_bindings: dict[str, dict[str, Any]] = field(default_factory=dict)
    # tool_bindings: UUID → {tool_type, surface_binding, read_only}
    # e.g. "desk-uuid" → {"tool_type": "inbox", "surface_binding": "desk", "read_only": True}
    read_only: bool = True  # v1 is always read-only (Req 24.1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_bindings": {
                k: dict(v) for k, v in self.tool_bindings.items()
            },
            "read_only": self.read_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RealOverlay:
        return cls(
            tool_bindings={
                k: dict(v) for k, v in data.get("tool_bindings", {}).items()
            },
            read_only=data.get("read_only", True),
        )


# ─── ModeState ─────────────────────────────────────────────────────────────────


@dataclass
class ModeState:
    """Mutable per-room mode state.

    NOT frozen — tracks the current mode, whether it has been persisted,
    and whether entry announcement has been made.

    Req 25.1: per-room (room_id identifies which room)
    Req 25.5: persists across sessions (persisted flag)
    """

    current_mode: Mode = Mode.REAL
    persisted: bool = False
    announced: bool = False
    room_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_mode": self.current_mode.value,
            "persisted": self.persisted,
            "announced": self.announced,
            "room_id": self.room_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeState:
        mode_value = data.get("current_mode", "REAL")
        return cls(
            current_mode=Mode(mode_value),
            persisted=data.get("persisted", False),
            announced=data.get("announced", False),
            room_id=data.get("room_id", ""),
        )


# ─── ModeToggle ───────────────────────────────────────────────────────────────


class ModeToggle:
    """Per-room mode toggle logic.

    Manages switching between GAME and REAL modes for a specific room.
    Switching does NOT change geometry, materials, lighting, or any
    visual property (Req 25.2). Each room remembers its own mode (Req 25.1).
    Mode state persists across sessions (Req 25.5).

    Methods:
        toggle() — switch to the other mode
        get_state() — return current ModeState
        persist() — mark state as persisted (for session save)
        announce_on_entry() — mark that entry announcement was made
    """

    def __init__(self, room_id: str, initial_mode: Mode = Mode.REAL) -> None:
        self._state = ModeState(
            current_mode=initial_mode,
            persisted=False,
            announced=False,
            room_id=room_id,
        )

    def toggle(self) -> Mode:
        """Switch to the other mode. Returns the new mode.

        Req 25.2: does NOT change geometry, materials, lighting, or
        any visual property — only behavior overlays swap.
        """
        if self._state.current_mode == Mode.GAME:
            self._state.current_mode = Mode.REAL
        else:
            self._state.current_mode = Mode.GAME
        # After toggle, state needs re-persistence and re-announcement
        self._state.persisted = False
        self._state.announced = False
        return self._state.current_mode

    def get_state(self) -> ModeState:
        """Return current mode state."""
        return self._state

    def persist(self) -> None:
        """Mark state as persisted to storage.

        Req 25.5: mode state persists across sessions.
        """
        self._state.persisted = True

    def announce_on_entry(self) -> str:
        """Mark entry announcement and return announcement message.

        Req 25.3: entering a room SHALL loudly announce its current mode.
        """
        self._state.announced = True
        return f"Mode: {self._state.current_mode.value} (room: {self._state.room_id})"

    def to_dict(self) -> dict[str, Any]:
        """Serialize toggle state for persistence."""
        return self._state.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModeToggle:
        """Restore toggle from persisted state."""
        state = ModeState.from_dict(data)
        toggle = cls(room_id=state.room_id, initial_mode=state.current_mode)
        toggle._state.persisted = state.persisted
        toggle._state.announced = state.announced
        return toggle
