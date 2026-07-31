"""Focused unit coverage for Task 9.3's config-backed mode switch.

**Validates: Requirements 25.1, 25.2, 25.3, 25.4, 25.5, 25.6**
"""
from __future__ import annotations

import copy
import json

import pytest

from src.unified_pipeline.mode_toggle import (
    ModeConfigError,
    ModeToggle,
    RewardDestination,
)
from src.unified_pipeline.models import GameOverlay
from src.unified_pipeline.modes import Mode, RealOverlay


def _overlays() -> tuple[GameOverlay, RealOverlay]:
    return (
        GameOverlay(
            theme="Kitchen Challenge",
            mechanics="Functional gameplay is deferred post-MVP.",
        ),
        RealOverlay(
            tool_bindings={
                "7d4bb58e-774d-4b5e-a817-eeb9e2440711": {
                    "tool_type": "static_data",
                    "surface_binding": "desk",
                    "read_only": True,
                }
            }
        ),
    )


def test_toggle_swaps_only_behavior_overlay_and_reward_channel(tmp_path) -> None:
    game, real = _overlays()
    toggle = ModeToggle(tmp_path / "modes.json")
    toggle.register_room("kitchen", game_overlay=game, real_overlay=real)
    visual_state = {
        "geometry": {"mesh": "room.glb"},
        "materials": {"wall": "plaster"},
        "lighting": {"temperature": 3200},
        "transforms": {"table": [1, 0, 2]},
    }
    before = copy.deepcopy(visual_state)

    initial = toggle.enter_room("kitchen")
    switched = toggle.toggle("kitchen")

    assert initial.mode is Mode.REAL
    assert initial.overlay is real
    assert initial.reward_destination is RewardDestination.REAL_BUDGET_AND_LAND
    assert switched.mode is Mode.GAME
    assert switched.overlay is game
    assert switched.reward_destination is RewardDestination.GAME_CONTENT_ONLY
    assert visual_state == before
    assert not (
        {"geometry", "materials", "lighting", "transforms"}
        & switched.to_dict().keys()
    )


def test_each_room_persists_its_mode_across_toggle_instances(tmp_path) -> None:
    config_path = tmp_path / "state" / "modes.json"
    game, real = _overlays()
    first = ModeToggle(config_path)
    first.register_room("kitchen", game_overlay=game, real_overlay=real)
    first.register_room("office", game_overlay=game, real_overlay=real)

    first.set_mode("kitchen", Mode.GAME)
    first.set_mode("office", Mode.REAL)

    restored = ModeToggle(config_path)
    restored.register_room("kitchen", game_overlay=game, real_overlay=real)
    restored.register_room("office", game_overlay=game, real_overlay=real)

    assert restored.get_state("kitchen").current_mode is Mode.GAME
    assert restored.get_state("kitchen").persisted is True
    assert restored.get_state("office").current_mode is Mode.REAL
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "rooms": {
            "kitchen": {"current_mode": "GAME"},
            "office": {"current_mode": "REAL"},
        },
        "version": 1,
    }


def test_enter_room_always_announces_current_mode(tmp_path) -> None:
    toggle = ModeToggle(tmp_path / "modes.json")
    game, real = _overlays()
    toggle.register_room("kitchen", game_overlay=game, real_overlay=real)
    toggle.set_mode("kitchen", "game")

    first_entry = toggle.enter_room("kitchen")
    second_entry = toggle.enter_room("kitchen")

    assert first_entry.announcement == "ROOM kitchen — GAME MODE ACTIVE"
    assert second_entry.announcement == first_entry.announcement
    assert toggle.get_state("kitchen").announced is True


def test_game_mode_has_honest_placeholder_when_no_designer_is_registered(tmp_path) -> None:
    toggle = ModeToggle(tmp_path / "modes.json")

    activation = toggle.set_mode("unconfigured-room", Mode.GAME)

    assert isinstance(activation.overlay, GameOverlay)
    assert activation.overlay.theme == "GAME placeholder"
    assert "deferred post-MVP" in activation.overlay.mechanics


def test_invalid_config_and_mode_fail_closed(tmp_path) -> None:
    config_path = tmp_path / "modes.json"
    config_path.write_text('{"version": 1, "rooms": {"kitchen": "GAME"}}', encoding="utf-8")

    with pytest.raises(ModeConfigError, match="must be an object"):
        ModeToggle(config_path)

    config_path.unlink()
    toggle = ModeToggle(config_path)
    with pytest.raises(ModeConfigError, match="unsupported room mode"):
        toggle.set_mode("kitchen", "sleep")
