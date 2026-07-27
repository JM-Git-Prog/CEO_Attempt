"""Property-based tests for graceful degradation save (Property 14).

**Validates: Requirements 9.1**

Property 14: Graceful Degradation Save
- When component attachment fails, the compiler SHALL still produce a saved
  .blend with scene geometry and SHALL NOT raise an unhandled exception.
- The function always returns a player object regardless of api_report config.
- Primary save failure triggers fallback save; scene data is preserved.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch, call

from hypothesis import given, settings, assume, strategies as st

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import _configure_runtime_050


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

api_report_strategy = st.builds(
    UPBGEComponentAPI,
    has_game_attr=st.booleans(),
    has_components_attr=st.booleans(),
    component_api_path=st.sampled_from([
        None,
        "obj.game.components",
        "bpy.types.Object.components",
    ]),
    component_add_method=st.sampled_from([
        None,
        "obj.game.components.new()",
        "obj.components.new()",
    ]),
    has_logic_ops=st.booleans(),
    physics_api_path=st.sampled_from([None, "obj.game.physics_type"]),
    has_game_physics=st.booleans(),
    blender_version=st.tuples(
        st.integers(min_value=3, max_value=6),
        st.integers(min_value=0, max_value=9),
        st.integers(min_value=0, max_value=9),
    ),
    upbge_detected=st.booleans(),
    fallback_required=st.booleans(),
)

interaction_strategy = st.fixed_dictionaries({
    "kind": st.sampled_from(["door", "grab", "switch"]),
    "subject_id": st.text(
        min_size=1, max_size=20,
        alphabet=st.characters(whitelist_categories=("L", "Nd"), whitelist_characters="_-"),
    ),
    "parameters": st.fixed_dictionaries({
        "open_angle_deg": st.floats(min_value=10.0, max_value=170.0, allow_nan=False, allow_infinity=False),
        "speed_deg_s": st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    }),
})

plan_strategy = st.fixed_dictionaries({
    "interactions": st.lists(interaction_strategy, min_size=0, max_size=5),
    "player_args": st.fixed_dictionaries({
        "move_speed": st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
        "look_speed": st.floats(min_value=0.0001, max_value=0.02, allow_nan=False, allow_infinity=False),
        "gravity": st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    }),
})


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class MockBlenderObject:
    """Simulates a Blender object with custom property storage and .game."""

    def __init__(self, name: str = "KiroPlayer"):
        self._props: dict[str, Any] = {}
        self.name = name
        self.parent = None
        self.scale = (1.0, 1.0, 1.0)
        self.game = MockGameSettings()

    def __setitem__(self, key: str, value: Any) -> None:
        self._props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._props


class MockGameSettings:
    """Simulates obj.game with physics attributes."""

    def __init__(self):
        self.physics_type: str = "NO_COLLISION"
        self.use_collision_bounds: bool = False
        self.collision_bounds_type: str = "BOX"
        self.mass: float = 0.0
        self.components = MagicMock()


class MockTextDatablock:
    """Simulates a bpy text datablock."""

    def __init__(self, name: str):
        self.name = name
        self.use_module = False
        self._content = ""

    def write(self, text: str) -> None:
        self._content = text


def _make_mock_bpy(*, save_succeeds: bool = True) -> MagicMock:
    """Create a mock bpy module that behaves enough like Blender's API.

    Args:
        save_succeeds: If True, bpy.ops.wm.save_as_mainfile succeeds.
                       If False, it raises RuntimeError on first call.
    """
    bpy = MagicMock()

    # --- bpy.data.texts: text datablock storage ---
    texts_store: dict[str, MockTextDatablock] = {}

    def texts_get(name: str) -> MockTextDatablock | None:
        return texts_store.get(name)

    def texts_new(name: str) -> MockTextDatablock:
        t = MockTextDatablock(name)
        texts_store[name] = t
        return t

    def texts_remove(text: MockTextDatablock) -> None:
        texts_store.pop(text.name, None)

    bpy.data.texts = MagicMock()
    bpy.data.texts.get = MagicMock(side_effect=texts_get)
    bpy.data.texts.new = MagicMock(side_effect=texts_new)
    bpy.data.texts.remove = MagicMock(side_effect=texts_remove)
    # Store reference for assertions
    bpy._texts_store = texts_store

    # --- bpy.data.filepath ---
    bpy.data.filepath = "C:\\test\\scene.blend"

    # --- bpy.ops.wm.save_as_mainfile ---
    if save_succeeds:
        bpy.ops.wm.save_as_mainfile = MagicMock()
    else:
        bpy.ops.wm.save_as_mainfile = MagicMock(
            side_effect=RuntimeError("Primary save failed")
        )

    # --- bpy.ops.mesh.primitive_cube_add ---
    player_obj = MockBlenderObject("KiroPlayer")
    bpy.ops.mesh.primitive_cube_add = MagicMock()
    bpy.context.active_object = player_obj

    return bpy


def _make_mock_bpy_fallback_save() -> MagicMock:
    """Create a mock bpy where primary save fails but fallback succeeds."""
    bpy = _make_mock_bpy(save_succeeds=True)

    call_count = {"n": 0}

    def save_side_effect(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Primary save failed: disk full")
        # Second call (fallback) succeeds
        return None

    bpy.ops.wm.save_as_mainfile = MagicMock(side_effect=save_side_effect)
    return bpy


# ---------------------------------------------------------------------------
# Property 14, Test 1: fallback_required never raises during normal save
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(api_report=api_report_strategy)
def test_property_14_no_exception_regardless_of_api_report(
    api_report: UPBGEComponentAPI,
):
    """Property 14: _configure_runtime_050 never raises with a working save.

    **Validates: Requirements 9.1**

    For any api_report configuration (fallback_required=True/False,
    has_game_physics=True/False), when the bpy save succeeds, the function
    completes without exception and returns a player object.
    """
    bpy = _make_mock_bpy(save_succeeds=True)
    plan = {"interactions": [], "player_args": {}}
    object_by_id: dict[str, Any] = {}
    camera_obj = MagicMock()

    # Should not raise regardless of api_report configuration
    result = _configure_runtime_050(bpy, plan, object_by_id, camera_obj, api_report)

    # Must always return a player object (never None)
    assert result is not None
    assert hasattr(result, "name")


# ---------------------------------------------------------------------------
# Property 14, Test 2: primary save failure triggers fallback save
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(plan=plan_strategy)
def test_property_14_primary_save_failure_triggers_fallback(
    plan: dict,
):
    """Property 14: Primary save failure triggers fallback, no unhandled exception.

    **Validates: Requirements 9.1**

    When bpy.ops.wm.save_as_mainfile fails on the first call but succeeds on
    the second, _configure_runtime_050 does NOT raise an unhandled exception,
    returns a player object, and the player has kiro_degradation_save set.
    """
    bpy = _make_mock_bpy_fallback_save()

    # Build object_by_id from interactions — use MockBlenderObjects for door subjects
    object_by_id: dict[str, Any] = {}
    for interaction in plan.get("interactions", []):
        subject_id = interaction.get("subject_id", "")
        if subject_id and subject_id not in object_by_id:
            object_by_id[subject_id] = MockBlenderObject(subject_id)

    camera_obj = MagicMock()

    # Use a report with fallback_required to exercise the degradation path
    api_report = UPBGEComponentAPI(
        has_game_attr=True,
        has_components_attr=False,
        component_api_path=None,
        component_add_method=None,
        has_logic_ops=False,
        physics_api_path=None,
        has_game_physics=False,
        blender_version=(5, 0, 1),
        upbge_detected=True,
        fallback_required=True,
    )

    # Should not raise — graceful degradation via fallback save
    result = _configure_runtime_050(bpy, plan, object_by_id, camera_obj, api_report)

    # Must return a player object
    assert result is not None
    assert hasattr(result, "name")

    # Player must have degradation save marker
    assert "kiro_degradation_save" in result

    # Save must have been called twice (primary failed, fallback succeeded)
    assert bpy.ops.wm.save_as_mainfile.call_count == 2


# ---------------------------------------------------------------------------
# Property 14, Test 3: scene data preserved in degradation mode
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(api_report=api_report_strategy)
def test_property_14_text_datablocks_created_even_in_degradation(
    api_report: UPBGEComponentAPI,
):
    """Property 14: Text datablocks are always embedded regardless of degradation.

    **Validates: Requirements 9.1**

    When using any api_report configuration (including fallback_required=True),
    the embedded text datablocks for player and door components are still
    created, preserving scene data even in degradation scenarios.
    """
    bpy = _make_mock_bpy(save_succeeds=True)
    plan = {"interactions": [], "player_args": {}}
    object_by_id: dict[str, Any] = {}
    camera_obj = MagicMock()

    result = _configure_runtime_050(bpy, plan, object_by_id, camera_obj, api_report)

    # Text datablocks must have been created regardless of degradation mode
    texts_store = bpy._texts_store
    assert "kiro_player_first_person.py" in texts_store, (
        "Player component text datablock not embedded in degradation mode"
    )
    assert "kiro_interaction_door.py" in texts_store, (
        "Door component text datablock not embedded in degradation mode"
    )

    # Text datablocks should have non-empty content
    player_text = texts_store["kiro_player_first_person.py"]
    assert player_text._content, "Player text datablock has empty content"

    door_text = texts_store["kiro_interaction_door.py"]
    assert door_text._content, "Door text datablock has empty content"
