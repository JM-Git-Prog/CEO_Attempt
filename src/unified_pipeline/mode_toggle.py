"""Config-backed per-room REAL/GAME behavior switch.

The switch persists only behavior mode. It has no API for geometry, materials,
lighting, transforms, or other visual state, so changing modes cannot rewrite the
WorldContract presentation.

Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Mapping

from .models import GameOverlay
from .modes import Mode, ModeState, RealOverlay


class ModeConfigError(ValueError):
    """Raised when persisted mode configuration is invalid or cannot be saved."""


class RewardDestination(str, Enum):
    """Allowed progression destination for activity in the active mode."""

    REAL_BUDGET_AND_LAND = "real_budget_and_land"
    GAME_CONTENT_ONLY = "game_content_only"


@dataclass(frozen=True)
class ModeActivation:
    """Renderer-neutral result of selecting a room behavior overlay."""

    room_id: str
    mode: Mode
    overlay: GameOverlay | RealOverlay
    reward_destination: RewardDestination
    announcement: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "room_id": self.room_id,
            "mode": self.mode.value,
            "behavior_overlay": self.overlay.to_dict(),
            "reward_destination": self.reward_destination.value,
            "announcement": self.announcement,
        }


class ModeToggle:
    """Persist and activate one independent behavior mode per room."""

    CONFIG_VERSION = 1

    def __init__(
        self,
        config_path: str | Path,
        *,
        default_mode: Mode | str = Mode.REAL,
        game_overlays: Mapping[str, GameOverlay] | None = None,
        real_overlays: Mapping[str, RealOverlay] | None = None,
    ) -> None:
        self._config_path = Path(config_path)
        self._default_mode = self._coerce_mode(default_mode)
        self._game_overlays = dict(game_overlays or {})
        self._real_overlays = dict(real_overlays or {})
        self._states: dict[str, ModeState] = {}
        self._lock = RLock()
        self._load()

    @staticmethod
    def _room_id(room_id: str) -> str:
        if not isinstance(room_id, str) or not room_id.strip():
            raise ModeConfigError("room_id must be a non-empty string")
        return room_id.strip()

    @staticmethod
    def _coerce_mode(mode: Mode | str) -> Mode:
        if isinstance(mode, Mode):
            return mode
        try:
            return Mode(str(mode).strip().upper())
        except ValueError as exc:
            raise ModeConfigError(f"unsupported room mode: {mode!r}") from exc

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            document = json.loads(self._config_path.read_text(encoding="utf-8"))
            if document.get("version") != self.CONFIG_VERSION:
                raise ModeConfigError("unsupported mode config version")
            rooms = document.get("rooms", {})
            if not isinstance(rooms, dict):
                raise ModeConfigError("mode config rooms must be an object")
            for raw_room_id, record in rooms.items():
                room_id = self._room_id(raw_room_id)
                if not isinstance(record, dict):
                    raise ModeConfigError(f"mode config for {room_id!r} must be an object")
                self._states[room_id] = ModeState(
                    current_mode=self._coerce_mode(record.get("current_mode", "")),
                    persisted=True,
                    announced=False,
                    room_id=room_id,
                )
        except ModeConfigError:
            raise
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise ModeConfigError(f"could not load mode config: {self._config_path}") from exc

    def _document(self) -> dict[str, object]:
        return {
            "version": self.CONFIG_VERSION,
            "rooms": {
                room_id: {"current_mode": state.current_mode.value}
                for room_id, state in sorted(self._states.items())
            },
        }

    def _persist(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._config_path.parent,
                prefix=f".{self._config_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                json.dump(self._document(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self._config_path)
        except OSError as exc:
            raise ModeConfigError(f"could not persist mode config: {self._config_path}") from exc
        finally:
            if temporary_name and os.path.exists(temporary_name):
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
        for state in self._states.values():
            state.persisted = True

    def _state(self, room_id: str) -> ModeState:
        canonical = self._room_id(room_id)
        if canonical not in self._states:
            self._states[canonical] = ModeState(
                current_mode=self._default_mode,
                persisted=False,
                announced=False,
                room_id=canonical,
            )
        return self._states[canonical]

    def register_room(
        self,
        room_id: str,
        *,
        game_overlay: GameOverlay,
        real_overlay: RealOverlay,
    ) -> None:
        """Attach behavior-only overlays to a room without changing its mode."""
        canonical = self._room_id(room_id)
        with self._lock:
            self._game_overlays[canonical] = game_overlay
            self._real_overlays[canonical] = real_overlay
            self._state(canonical)

    def get_state(self, room_id: str) -> ModeState:
        """Return a detached snapshot so callers cannot bypass persistence."""
        with self._lock:
            state = self._state(room_id)
            return ModeState.from_dict(state.to_dict())

    def active_overlay(self, room_id: str) -> GameOverlay | RealOverlay:
        """Return only the selected behavior overlay for the room."""
        with self._lock:
            state = self._state(room_id)
            if state.current_mode is Mode.GAME:
                return self._game_overlays.get(
                    state.room_id,
                    GameOverlay(
                        theme="GAME placeholder",
                        mechanics="Functional gameplay is deferred post-MVP.",
                    ),
                )
            return self._real_overlays.get(state.room_id, RealOverlay())

    @staticmethod
    def _reward_destination(mode: Mode) -> RewardDestination:
        if mode is Mode.REAL:
            return RewardDestination.REAL_BUDGET_AND_LAND
        return RewardDestination.GAME_CONTENT_ONLY

    def _activation(self, room_id: str, announcement: str = "") -> ModeActivation:
        state = self._state(room_id)
        return ModeActivation(
            room_id=state.room_id,
            mode=state.current_mode,
            overlay=self.active_overlay(state.room_id),
            reward_destination=self._reward_destination(state.current_mode),
            announcement=announcement,
        )

    def set_mode(self, room_id: str, mode: Mode | str) -> ModeActivation:
        """Set and atomically persist a room's behavior mode."""
        with self._lock:
            state = self._state(room_id)
            previous = ModeState.from_dict(state.to_dict())
            state.current_mode = self._coerce_mode(mode)
            state.persisted = False
            state.announced = False
            try:
                self._persist()
            except ModeConfigError:
                self._states[state.room_id] = previous
                raise
            return self._activation(state.room_id)

    def toggle(self, room_id: str) -> ModeActivation:
        """Swap REAL/GAME behavior while leaving all visual state out of scope."""
        with self._lock:
            current = self._state(room_id).current_mode
            target = Mode.GAME if current is Mode.REAL else Mode.REAL
            return self.set_mode(room_id, target)

    def enter_room(self, room_id: str) -> ModeActivation:
        """Activate and loudly announce the room's current persisted mode."""
        with self._lock:
            state = self._state(room_id)
            state.announced = True
            announcement = f"ROOM {state.room_id} — {state.current_mode.value} MODE ACTIVE"
            return self._activation(state.room_id, announcement)

    def persist(self) -> None:
        """Persist default states created by reads or room registration."""
        with self._lock:
            self._persist()
