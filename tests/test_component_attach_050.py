"""Unit tests for src/assembler/component_attach_050.py.

Tests the _configure_physics_050(), _attach_component_050(), and
_embed_component_source() functions.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import (
    _attach_component_050,
    _configure_physics_050,
    _embed_component_source,
)


# ---------------------------------------------------------------------------
# Helpers: mock objects that simulate Blender's API
# ---------------------------------------------------------------------------


def _make_api_report(
    *,
    has_game_physics: bool = True,
    physics_api_path: str | None = "obj.game.physics_type",
    fallback_required: bool = False,
    component_api_path: str | None = "obj.game.components",
) -> UPBGEComponentAPI:
    """Create a UPBGEComponentAPI with sensible defaults for testing."""
    return UPBGEComponentAPI(
        has_game_attr=True,
        has_components_attr=True,
        component_api_path=component_api_path,
        component_add_method="obj.game.components.new()",
        has_logic_ops=True,
        physics_api_path=physics_api_path,
        has_game_physics=has_game_physics,
        blender_version=(5, 0, 1),
        upbge_detected=True,
        fallback_required=fallback_required,
    )


class MockGameSettings:
    """Simulates obj.game with physics attributes."""

    def __init__(self):
        self.physics_type: str = "NO_COLLISION"
        self.use_collision_bounds: bool = False
        self.collision_bounds_type: str = "BOX"
        self.mass: float = 0.0


class MockBlenderObject:
    """Simulates a Blender object with custom property storage."""

    def __init__(self, *, has_game: bool = True):
        self._props: dict[str, Any] = {}
        if has_game:
            self.game = MockGameSettings()

    def __setitem__(self, key: str, value: Any) -> None:
        self._props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)


class MockBlenderObjectNoGame:
    """Simulates a Blender object WITHOUT .game attribute (physics API removed)."""

    def __init__(self):
        self._props: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)


# ---------------------------------------------------------------------------
# Tests: _configure_physics_050
# ---------------------------------------------------------------------------


class TestConfigurePhysics050:
    """Tests for the _configure_physics_050() function."""

    def test_native_physics_configuration_success(self):
        """When physics API is available, should set physics via RNA and return True."""
        obj = MockBlenderObject(has_game=True)
        api_report = _make_api_report(has_game_physics=True)
        bpy = MagicMock()  # not used directly by _configure_physics_050

        result = _configure_physics_050(
            bpy, obj, "CHARACTER", "CAPSULE", 80.0, api_report
        )

        assert result is True
        assert obj.game.physics_type == "CHARACTER"
        assert obj.game.use_collision_bounds is True
        assert obj.game.collision_bounds_type == "CAPSULE"
        assert obj.game.mass == 80.0

    def test_native_physics_static_box(self):
        """Should correctly configure STATIC physics with BOX collision."""
        obj = MockBlenderObject(has_game=True)
        api_report = _make_api_report(has_game_physics=True)
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "STATIC", "BOX", 0.0, api_report
        )

        assert result is True
        assert obj.game.physics_type == "STATIC"
        assert obj.game.collision_bounds_type == "BOX"
        assert obj.game.mass == 0.0

    def test_native_physics_dynamic_sphere(self):
        """Should correctly configure DYNAMIC physics with SPHERE collision."""
        obj = MockBlenderObject(has_game=True)
        api_report = _make_api_report(has_game_physics=True)
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "DYNAMIC", "SPHERE", 5.0, api_report
        )

        assert result is True
        assert obj.game.physics_type == "DYNAMIC"
        assert obj.game.collision_bounds_type == "SPHERE"
        assert obj.game.mass == 5.0

    def test_fallback_when_no_physics_api(self):
        """When has_game_physics is False, should degrade gracefully."""
        obj = MockBlenderObject(has_game=True)
        api_report = _make_api_report(
            has_game_physics=False, physics_api_path=None
        )
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "CHARACTER", "CAPSULE", 80.0, api_report
        )

        assert result is False
        assert obj["kiro_physics_type"] == "CHARACTER"
        assert obj["kiro_collision_shape"] == "CAPSULE"
        assert obj["kiro_mass"] == 80.0

    def test_fallback_when_physics_path_is_none(self):
        """When physics_api_path is None, should degrade gracefully."""
        obj = MockBlenderObject(has_game=True)
        api_report = _make_api_report(
            has_game_physics=True, physics_api_path=None
        )
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "DYNAMIC", "BOX", 10.0, api_report
        )

        assert result is False
        assert obj["kiro_physics_type"] == "DYNAMIC"
        assert obj["kiro_collision_shape"] == "BOX"
        assert obj["kiro_mass"] == 10.0

    def test_fallback_when_obj_has_no_game_attr(self):
        """When obj doesn't have .game, should degrade without crashing."""
        obj = MockBlenderObjectNoGame()
        api_report = _make_api_report(has_game_physics=True)
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "CHARACTER", "CAPSULE", 75.0, api_report
        )

        assert result is False
        assert obj["kiro_physics_type"] == "CHARACTER"
        assert obj["kiro_collision_shape"] == "CAPSULE"
        assert obj["kiro_mass"] == 75.0

    def test_fallback_stores_correct_values_for_door(self):
        """Door objects should store STATIC/BOX in degradation mode."""
        obj = MockBlenderObjectNoGame()
        api_report = _make_api_report(
            has_game_physics=False, physics_api_path=None
        )
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "STATIC", "BOX", 0.0, api_report
        )

        assert result is False
        assert obj["kiro_physics_type"] == "STATIC"
        assert obj["kiro_collision_shape"] == "BOX"
        assert obj["kiro_mass"] == 0.0

    def test_return_false_on_attribute_error_at_runtime(self):
        """If obj.game exists but physics_type setter raises, should degrade."""
        obj = MockBlenderObject(has_game=True)

        # Make the physics_type property raise AttributeError on set
        class BrokenGameSettings:
            @property
            def physics_type(self):
                return "NO_COLLISION"

            @physics_type.setter
            def physics_type(self, value):
                raise AttributeError("physics_type is read-only in this build")

        obj.game = BrokenGameSettings()
        api_report = _make_api_report(has_game_physics=True)
        bpy = MagicMock()

        result = _configure_physics_050(
            bpy, obj, "CHARACTER", "CAPSULE", 80.0, api_report
        )

        assert result is False
        assert obj["kiro_physics_type"] == "CHARACTER"
        assert obj["kiro_collision_shape"] == "CAPSULE"
        assert obj["kiro_mass"] == 80.0


# ---------------------------------------------------------------------------
# Tests: _embed_component_source
# ---------------------------------------------------------------------------


class TestEmbedComponentSource:
    """Tests for the _embed_component_source() function."""

    def test_creates_text_datablock(self):
        """Should create a new text datablock with the given source."""
        mock_text = MagicMock()
        mock_texts = MagicMock()
        mock_texts.get.return_value = None
        mock_texts.new.return_value = mock_text

        bpy = MagicMock()
        bpy.data.texts = mock_texts

        result = _embed_component_source(bpy, "kiro_player_first_person", "# source")

        assert result == "kiro_player_first_person.py"
        mock_texts.new.assert_called_once_with("kiro_player_first_person.py")
        mock_text.write.assert_called_once_with("# source")

    def test_replaces_existing_text_datablock(self):
        """Should remove existing text datablock before creating new one."""
        existing_text = MagicMock()
        mock_text = MagicMock()
        mock_texts = MagicMock()
        mock_texts.get.return_value = existing_text
        mock_texts.new.return_value = mock_text

        bpy = MagicMock()
        bpy.data.texts = mock_texts

        result = _embed_component_source(bpy, "kiro_interaction_door", "# door code")

        assert result == "kiro_interaction_door.py"
        mock_texts.remove.assert_called_once_with(existing_text)
        mock_texts.new.assert_called_once_with("kiro_interaction_door.py")
        mock_text.write.assert_called_once_with("# door code")


# ---------------------------------------------------------------------------
# Tests: _attach_component_050
# ---------------------------------------------------------------------------


class TestAttachComponent050:
    """Tests for the _attach_component_050() function."""

    def test_native_attachment_via_game_components(self):
        """Should use obj.game.components.new() when native API is available."""
        mock_comp = MagicMock()
        mock_comp.properties = {"move_speed": 4.0, "gravity": 9.81}

        obj = MagicMock()
        obj.game.components.new.return_value = mock_comp

        api_report = _make_api_report(
            fallback_required=False,
            component_api_path="obj.game.components",
        )
        bpy = MagicMock()

        result = _attach_component_050(
            bpy,
            obj,
            "PlayerComponent",
            "kiro_player_first_person.py",
            {"move_speed": 6.0, "gravity": 15.0},
            api_report,
        )

        assert result is True
        obj.game.components.new.assert_called_once_with(
            "kiro_player_first_person", "PlayerComponent"
        )

    def test_fallback_when_api_required(self):
        """Should store component metadata as properties when fallback required."""
        obj = MockBlenderObjectNoGame()

        api_report = _make_api_report(
            fallback_required=True,
            component_api_path=None,
        )
        bpy = MagicMock()

        result = _attach_component_050(
            bpy,
            obj,
            "DoorComponent",
            "kiro_interaction_door.py",
            {"open_angle_deg": 90.0},
            api_report,
        )

        assert result is False
        assert obj["kiro_component_module"] == "kiro_interaction_door"
        assert obj["kiro_component_class"] == "DoorComponent"
        assert json.loads(obj["kiro_component_args"]) == {"open_angle_deg": 90.0}

    def test_fallback_on_native_failure(self):
        """Should fall back to properties when native API raises AttributeError."""
        obj = MagicMock()
        obj.game.components.new.side_effect = AttributeError("no components")
        # Make obj support __setitem__ for property storage
        obj._props = {}
        obj.__setitem__ = lambda self, k, v: self._props.__setitem__(k, v)
        obj.__getitem__ = lambda self, k: self._props.__getitem__(k)

        # Use a simple dict-based mock for the fallback property storage
        obj_fallback = MockBlenderObject(has_game=True)
        obj_fallback.game.components = MagicMock()
        obj_fallback.game.components.new.side_effect = AttributeError("broken")

        api_report = _make_api_report(
            fallback_required=False,
            component_api_path="obj.game.components",
        )
        bpy = MagicMock()

        result = _attach_component_050(
            bpy,
            obj_fallback,
            "PlayerComponent",
            "kiro_player_first_person.py",
            {"move_speed": 4.0},
            api_report,
        )

        assert result is False
        assert obj_fallback["kiro_component_module"] == "kiro_player_first_person"
        assert obj_fallback["kiro_component_class"] == "PlayerComponent"
