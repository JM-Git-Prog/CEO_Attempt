"""Task 9.4 integration tests for the REAL/GAME mode boundary.

**Validates: Requirements 25.2, 25.5, 24.4**
"""
from __future__ import annotations

import copy

from src.unified_pipeline.mode_toggle import ModeToggle
from src.unified_pipeline.models import GameOverlay
from src.unified_pipeline.modes import Mode
from src.unified_pipeline.real_binder import RealBinder

SURFACE_UUID = "7d4bb58e-774d-4b5e-a817-eeb9e2440711"
GAME = GameOverlay(theme="Kitchen Challenge", mechanics="Stubbed for MVP")


def _registered_toggle(config_path, real_overlay):
    toggle = ModeToggle(config_path)
    toggle.register_room("kitchen", game_overlay=GAME, real_overlay=real_overlay)
    return toggle


def test_room_mode_persists_across_new_toggle_instances(tmp_path) -> None:
    binder = RealBinder([SURFACE_UUID])
    binder.bind_static(SURFACE_UUID, "Inbox: 3 unread", surface_binding="desk")
    path = tmp_path / "mode-state.json"
    first = _registered_toggle(path, binder.to_overlay())
    first.set_mode("kitchen", Mode.GAME)

    restored = _registered_toggle(path, binder.to_overlay())

    assert restored.get_state("kitchen").current_mode is Mode.GAME
    assert restored.get_state("kitchen").persisted is True


def test_toggle_preserves_world_visual_state(tmp_path) -> None:
    binder = RealBinder([SURFACE_UUID])
    toggle = _registered_toggle(tmp_path / "modes.json", binder.to_overlay())
    visuals = {"geometry": "room.glb", "materials": {"wall": "plaster"}, "lighting": 3200}
    before = copy.deepcopy(visuals)

    activation = toggle.toggle("kitchen")

    assert activation.mode is Mode.GAME
    assert visuals == before
    assert not ({"geometry", "materials", "lighting"} & activation.to_dict().keys())


def test_real_binding_displays_data_on_active_surface_without_visual_changes(tmp_path) -> None:
    binder = RealBinder([SURFACE_UUID])
    binder.bind_static(SURFACE_UUID, {"unread": 3}, surface_binding="desk")
    toggle = _registered_toggle(tmp_path / "modes.json", binder.to_overlay())
    visuals = {"geometry": "desk.glb", "materials": {"desk": "oak"}}
    before = copy.deepcopy(visuals)

    activation = toggle.enter_room("kitchen")
    display = binder.display(SURFACE_UUID)

    assert activation.mode is Mode.REAL
    assert activation.overlay == binder.to_overlay()
    assert display.to_dict()["data"] == {"unread": 3}
    assert display.to_dict()["surface_uuid"] == SURFACE_UUID
    assert visuals == before
