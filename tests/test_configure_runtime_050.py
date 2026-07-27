"""Unit tests for _configure_runtime_050 orchestrator function.

Tests the full orchestration flow with mocked bpy, graceful degradation,
bootstrap embedding, text datablock creation, and camera parenting.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import (
    BOOTSTRAP_COMPONENT_SOURCE,
    _configure_runtime_050,
    _extract_door_args,
    _extract_player_args,
    _find_or_create_player,
)


# ---------------------------------------------------------------------------
# Fixtures: Mock bpy with realistic text/object/ops structure
# ---------------------------------------------------------------------------


def _make_api_report(
    *,
    fallback_required: bool = False,
    has_game_physics: bool = True,
    physics_api_path: str | None = "obj.game.physics_type",
    component_api_path: str | None = "obj.game.components",
) -> UPBGEComponentAPI:
    """Create a UPBGEComponentAPI for testing."""
    return UPBGEComponentAPI(
        has_game_attr=True,
        has_components_attr=not fallback_required,
        component_api_path=component_api_path,
        component_add_method="obj.game.components.new()" if component_api_path else None,
        has_logic_ops=True,
        physics_api_path=physics_api_path,
        has_game_physics=has_game_physics,
        blender_version=(5, 0, 1),
        upbge_detected=True,
        fallback_required=fallback_required,
    )


class MockTextDatablock:
    """Simulates a bpy.data.texts entry."""

    def __init__(self, name: str):
        self.name = name
        self.content = ""
        self.use_module = False

    def write(self, text: str) -> None:
        self.content += text


class MockTextsCollection:
    """Simulates bpy.data.texts (dict-like with .new/.remove/.get)."""

    def __init__(self):
        self._store: dict[str, MockTextDatablock] = {}

    def get(self, name: str) -> MockTextDatablock | None:
        return self._store.get(name)

    def new(self, name: str) -> MockTextDatablock:
        text = MockTextDatablock(name)
        self._store[name] = text
        return text

    def remove(self, text: MockTextDatablock) -> None:
        self._store.pop(text.name, None)

    def __contains__(self, name: str) -> bool:
        return name in self._store

    def __len__(self) -> int:
        return len(self._store)

    def keys(self) -> list[str]:
        return list(self._store.keys())


class MockGameComponent:
    """Simulates a single component entry."""

    def __init__(self, module: str, class_name: str):
        self.module = module
        self.name = class_name
        self.properties: dict[str, Any] = {}


class MockComponentsCollection:
    """Simulates obj.game.components."""

    def __init__(self):
        self._items: list[MockGameComponent] = []

    def new(self, module: str, class_name: str) -> MockGameComponent:
        comp = MockGameComponent(module, class_name)
        self._items.append(comp)
        return comp

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


class MockGameSettings:
    """Simulates obj.game with physics and components attributes."""

    def __init__(self):
        self.physics_type: str = "NO_COLLISION"
        self.use_collision_bounds: bool = False
        self.collision_bounds_type: str = "BOX"
        self.mass: float = 0.0
        self.components = MockComponentsCollection()


class MockBlenderObject:
    """Simulates a Blender object with game settings and custom properties."""

    def __init__(self, name: str):
        self.name = name
        self.game = MockGameSettings()
        self.parent: Any = None
        self.scale = (1.0, 1.0, 1.0)
        self._custom_props: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._custom_props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._custom_props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_props.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._custom_props


def _make_mock_bpy(
    *,
    filepath: str = "C:/test/project.blend",
    objects: dict[str, MockBlenderObject] | None = None,
    save_raises: Exception | None = None,
) -> MagicMock:
    """Create a fully-featured mock bpy module."""
    bpy = MagicMock()

    # bpy.data.texts
    texts = MockTextsCollection()
    bpy.data.texts = texts

    # bpy.data.filepath
    bpy.data.filepath = filepath

    # bpy.data.objects
    if objects:
        bpy.data.objects = objects
    else:
        bpy.data.objects = {}

    # bpy.ops.mesh.primitive_cube_add
    player_obj = MockBlenderObject("KiroPlayer")

    def mock_cube_add(**kwargs):
        bpy.context.active_object = player_obj

    bpy.ops.mesh.primitive_cube_add = mock_cube_add
    bpy.context.active_object = player_obj

    # bpy.ops.wm.save_as_mainfile
    if save_raises:
        bpy.ops.wm.save_as_mainfile.side_effect = save_raises
    else:
        bpy.ops.wm.save_as_mainfile.return_value = {"FINISHED"}

    return bpy


def _make_plan(
    *,
    interactions: list[dict] | None = None,
    player_args: dict | None = None,
) -> dict:
    """Create a plan dict for testing."""
    return {
        "interactions": interactions or [],
        "player_args": player_args or {
            "move_speed": 4.0,
            "look_speed": 0.0025,
            "gravity": 9.81,
            "max_grab_distance": 3.0,
            "grab_hold_distance": 1.5,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConfigureRuntime050FullFlow:
    """Test the full orchestration flow with mocked bpy."""

    def test_basic_flow_embeds_sources_and_returns_player(self):
        """Full flow with native API: embeds texts, attaches components, saves."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        result = _configure_runtime_050(bpy, plan, {}, camera, api_report)

        # Returns a player object
        assert result is not None
        assert result.name == "KiroPlayer"
        # Camera is parented to player
        assert camera.parent is result
        # Text datablocks were created
        assert "kiro_player_first_person.py" in bpy.data.texts
        assert "kiro_interaction_door.py" in bpy.data.texts
        # Save was called
        bpy.ops.wm.save_as_mainfile.assert_called_once()

    def test_uses_existing_player_from_object_by_id(self):
        """When object_by_id contains a 'player' key, uses that object."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")
        existing_player = MockBlenderObject("MyPlayer")

        result = _configure_runtime_050(
            bpy, plan, {"player": existing_player}, camera, api_report
        )

        assert result is existing_player
        assert camera.parent is existing_player

    def test_door_components_attached_to_door_objects(self):
        """Door interactions result in DoorComponent attachment on the door object."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        door_obj = MockBlenderObject("Door01")
        interactions = [
            {
                "kind": "door",
                "subject_id": "door_01",
                "parameters": [
                    ("open_angle_deg", 90.0),
                    ("speed_deg_s", 120.0),
                    ("initially_open", False),
                ],
            }
        ]
        plan = _make_plan(interactions=interactions)
        camera = MockBlenderObject("Camera")

        result = _configure_runtime_050(
            bpy, plan, {"door_01": door_obj}, camera, api_report
        )

        # Door object should have component attached (native path)
        assert len(door_obj.game.components) == 1
        comp = list(door_obj.game.components)[0]
        assert comp.name == "DoorComponent"

        # Door physics configured as STATIC
        assert door_obj.game.physics_type == "STATIC"
        assert door_obj.game.collision_bounds_type == "BOX"

    def test_non_door_interactions_ignored(self):
        """Non-door interactions (e.g. grab) are not processed."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        box_obj = MockBlenderObject("Box01")
        interactions = [
            {"kind": "grab", "subject_id": "box_01", "parameters": []},
        ]
        plan = _make_plan(interactions=interactions)
        camera = MockBlenderObject("Camera")

        result = _configure_runtime_050(
            bpy, plan, {"box_01": box_obj}, camera, api_report
        )

        # Box should NOT have any component attached
        assert len(box_obj.game.components) == 0

    def test_missing_door_object_is_skipped(self):
        """If a door's subject_id isn't in object_by_id, it's skipped gracefully."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        interactions = [
            {"kind": "door", "subject_id": "missing_door", "parameters": []},
        ]
        plan = _make_plan(interactions=interactions)
        camera = MockBlenderObject("Camera")

        # Should not raise
        result = _configure_runtime_050(bpy, plan, {}, camera, api_report)
        assert result is not None


class TestBootstrapEmbedding:
    """Test that bootstrap is embedded when api_report.fallback_required."""

    def test_bootstrap_embedded_when_fallback_required(self):
        """When fallback_required is True, kiro_component_bootstrap.py is embedded."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report(
            fallback_required=True,
            component_api_path=None,
        )
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        _configure_runtime_050(bpy, plan, {}, camera, api_report)

        assert "kiro_component_bootstrap.py" in bpy.data.texts
        bootstrap_text = bpy.data.texts.get("kiro_component_bootstrap.py")
        assert bootstrap_text is not None
        assert "bootstrap" in bootstrap_text.content
        assert bootstrap_text.use_module is True

    def test_bootstrap_not_embedded_when_native_api_available(self):
        """When native API is available, bootstrap is NOT embedded."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report(fallback_required=False)
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        _configure_runtime_050(bpy, plan, {}, camera, api_report)

        assert "kiro_component_bootstrap.py" not in bpy.data.texts


class TestTextDatablocks:
    """Test that all expected text datablocks are created."""

    def test_player_and_door_texts_always_created(self):
        """Player and door text datablocks are always created."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        _configure_runtime_050(bpy, plan, {}, camera, api_report)

        texts = bpy.data.texts
        assert "kiro_player_first_person.py" in texts
        assert "kiro_interaction_door.py" in texts
        # Verify content is not empty
        player_text = texts.get("kiro_player_first_person.py")
        door_text = texts.get("kiro_interaction_door.py")
        assert player_text.content != ""
        assert door_text.content != ""

    def test_all_three_texts_with_fallback(self):
        """With fallback, all three text datablocks are created."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report(
            fallback_required=True, component_api_path=None
        )
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        _configure_runtime_050(bpy, plan, {}, camera, api_report)

        texts = bpy.data.texts
        assert len(texts) == 3
        assert "kiro_player_first_person.py" in texts
        assert "kiro_interaction_door.py" in texts
        assert "kiro_component_bootstrap.py" in texts


class TestCameraParenting:
    """Test that camera is parented to player."""

    def test_camera_parent_set_to_player(self):
        """Camera object's parent is set to the player object."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        player = _configure_runtime_050(bpy, plan, {}, camera, api_report)

        assert camera.parent is player

    def test_camera_parent_with_existing_player(self):
        """Camera is parented to existing player from object_by_id."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")
        player = MockBlenderObject("ExistingPlayer")

        result = _configure_runtime_050(
            bpy, plan, {"player": player}, camera, api_report
        )

        assert camera.parent is player
        assert result is player


class TestGracefulDegradation:
    """Test graceful degradation when component attachment fails."""

    def test_save_failure_triggers_fallback_save(self):
        """When primary save fails, a scene-only fallback save is attempted."""
        # First call raises, second call (fallback) succeeds
        bpy = _make_mock_bpy()
        call_count = [0]
        original_save = bpy.ops.wm.save_as_mainfile

        def save_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated save failure")
            return {"FINISHED"}

        bpy.ops.wm.save_as_mainfile = MagicMock(side_effect=save_side_effect)

        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        result = _configure_runtime_050(bpy, plan, {}, camera, api_report)

        # Should still return a player (degradation not fatal)
        assert result is not None
        # Save was attempted twice (primary + fallback)
        assert call_count[0] == 2
        # Degradation info stored on player
        assert "kiro_degradation_save" in result

    def test_double_save_failure_raises_value_error(self):
        """When both primary and fallback saves fail, ValueError is raised."""
        bpy = _make_mock_bpy()
        bpy.ops.wm.save_as_mainfile = MagicMock(
            side_effect=RuntimeError("Cannot save")
        )

        api_report = _make_api_report()
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        with pytest.raises(ValueError, match="Unrecoverable save failure"):
            _configure_runtime_050(bpy, plan, {}, camera, api_report)

    def test_fallback_mode_stores_degradation_info(self):
        """When fallback is used for components, degradation info is stored."""
        bpy = _make_mock_bpy()
        api_report = _make_api_report(
            fallback_required=True,
            component_api_path=None,
            has_game_physics=False,
            physics_api_path=None,
        )
        plan = _make_plan()
        camera = MockBlenderObject("Camera")

        result = _configure_runtime_050(bpy, plan, {}, camera, api_report)

        # Degradation info should be stored
        assert "kiro_degradation_component" in result
        assert "kiro_degradation_physics" in result


class TestExtractPlayerArgs:
    """Test _extract_player_args helper."""

    def test_extracts_args_from_plan(self):
        plan = {"player_args": {"move_speed": 5.0, "gravity": 10.0}}
        args = _extract_player_args(plan)
        assert args["move_speed"] == 5.0
        assert args["gravity"] == 10.0
        # Defaults for missing keys
        assert args["look_speed"] == 0.0025
        assert args["max_grab_distance"] == 3.0
        assert args["grab_hold_distance"] == 1.5

    def test_returns_defaults_when_no_player_args(self):
        plan = {}
        args = _extract_player_args(plan)
        assert args["move_speed"] == 4.0
        assert args["gravity"] == 9.81


class TestExtractDoorArgs:
    """Test _extract_door_args helper."""

    def test_extracts_from_tuple_list(self):
        interaction = {
            "parameters": [
                ("open_angle_deg", 45.0),
                ("speed_deg_s", 60.0),
                ("initially_open", True),
            ]
        }
        args = _extract_door_args(interaction)
        assert args["open_angle_deg"] == 45.0
        assert args["speed_deg_s"] == 60.0
        assert args["initially_open"] is True

    def test_extracts_from_dict(self):
        interaction = {
            "parameters": {"open_angle_deg": 120.0}
        }
        args = _extract_door_args(interaction)
        assert args["open_angle_deg"] == 120.0
        # Defaults for missing
        assert args["speed_deg_s"] == 120.0
        assert args["initially_open"] is False

    def test_returns_defaults_when_no_parameters(self):
        interaction = {}
        args = _extract_door_args(interaction)
        assert args["open_angle_deg"] == 90.0
        assert args["speed_deg_s"] == 120.0
        assert args["initially_open"] is False


class TestFindOrCreatePlayer:
    """Test _find_or_create_player helper."""

    def test_finds_player_by_key(self):
        bpy = _make_mock_bpy()
        player = MockBlenderObject("ExistingPlayer")
        result = _find_or_create_player(bpy, {"player": player})
        assert result is player

    def test_finds_player_by_capital_key(self):
        bpy = _make_mock_bpy()
        player = MockBlenderObject("Player")
        result = _find_or_create_player(bpy, {"Player": player})
        assert result is player

    def test_creates_cube_when_no_player_found(self):
        bpy = _make_mock_bpy()
        result = _find_or_create_player(bpy, {})
        assert result.name == "KiroPlayer"
