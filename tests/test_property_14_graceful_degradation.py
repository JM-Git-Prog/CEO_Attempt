"""Property-based tests for graceful degradation save (Property 14).

**Validates: Requirements 9.1**

Property 14: Graceful Degradation Save
- When component attachment fails, the compiler SHALL still produce a saved
  .blend with scene geometry and SHALL NOT raise an unhandled exception.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, PropertyMock

from hypothesis import given, settings, strategies as st, assume

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import _configure_runtime_050


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for api_report configurations
api_report_strategy = st.builds(
    UPBGEComponentAPI,
    has_game_attr=st.booleans(),
    has_components_attr=st.booleans(),
    component_api_path=st.one_of(
        st.none(),
        st.just("obj.game.components"),
        st.just("bpy.types.Object.components"),
    ),
    component_add_method=st.one_of(
        st.none(),
        st.just("obj.game.components.new()"),
    ),
    has_logic_ops=st.booleans(),
    physics_api_path=st.one_of(st.none(), st.just("obj.game.physics_type")),
    has_game_physics=st.booleans(),
    blender_version=st.tuples(
        st.integers(min_value=3, max_value=5),
        st.integers(min_value=0, max_value=5),
        st.integers(min_value=0, max_value=10),
    ),
    upbge_detected=st.booleans(),
    fallback_required=st.booleans(),
)

# Strategy for door interactions
door_interaction_strategy = st.fixed_dictionaries({
    "kind": st.just("door"),
    "subject_id": st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=10,
    ),
    "parameters": st.one_of(
        st.fixed_dictionaries({
            "open_angle_deg": st.floats(min_value=1.0, max_value=180.0),
            "speed_deg_s": st.floats(min_value=10.0, max_value=360.0),
            "initially_open": st.booleans(),
        }),
        st.just({}),
    ),
})

# Strategy for plan dictionaries
plan_strategy = st.fixed_dictionaries({
    "interactions": st.lists(door_interaction_strategy, min_size=0, max_size=3),
    "player_args": st.one_of(
        st.just({}),
        st.fixed_dictionaries({
            "move_speed": st.floats(min_value=1.0, max_value=20.0),
            "look_speed": st.floats(min_value=0.0001, max_value=0.01),
            "gravity": st.floats(min_value=1.0, max_value=20.0),
        }),
    ),
})


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_mock_bpy(primary_save_fails: bool = False):
    """Create a mock bpy module that simulates UPBGE 0.50 headless environment.

    Args:
        primary_save_fails: If True, the first call to save_as_mainfile raises
            an OSError (simulating primary save failure). The second call
            (fallback) succeeds.
    """
    bpy = MagicMock()

    # bpy.data.texts mock — tracks embedded Text datablocks
    texts_store = {}

    def texts_get(name):
        return texts_store.get(name)

    def texts_new(name):
        text = MagicMock()
        text.name = name
        text.use_module = False
        texts_store[name] = text
        return text

    def texts_remove(text):
        if text.name in texts_store:
            del texts_store[text.name]

    bpy.data.texts.get = MagicMock(side_effect=texts_get)
    bpy.data.texts.new = MagicMock(side_effect=texts_new)
    bpy.data.texts.remove = MagicMock(side_effect=texts_remove)

    # bpy.data.filepath — empty (no existing .blend)
    bpy.data.filepath = ""

    # bpy.ops.mesh.primitive_cube_add — creates a player object
    player_obj = MagicMock()
    player_obj.name = "KiroPlayer"
    player_obj.scale = (0.4, 0.4, 0.9)
    # Store custom properties in a dict
    player_props = {}
    player_obj.__setitem__ = MagicMock(side_effect=lambda k, v: player_props.__setitem__(k, v))
    player_obj.__getitem__ = MagicMock(side_effect=lambda k: player_props[k])
    player_obj.__contains__ = MagicMock(side_effect=lambda k: k in player_props)
    player_obj.get = MagicMock(side_effect=lambda k, d=None: player_props.get(k, d))
    player_obj._props = player_props  # exposed for test assertions

    bpy.context.active_object = player_obj

    # bpy.ops.wm.save_as_mainfile — conditionally fail on first call
    if primary_save_fails:
        call_count = {"n": 0}

        def save_side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("Simulated primary save failure")
            # Fallback save succeeds
            return None

        bpy.ops.wm.save_as_mainfile = MagicMock(side_effect=save_side_effect)
    else:
        bpy.ops.wm.save_as_mainfile = MagicMock(return_value=None)

    # Component attachment always uses fallback (native API raises)
    # This simulates component attachment "failing" — the function itself
    # handles this by storing props (never raises)

    return bpy, player_obj


def _make_object_by_id(plan: dict, player_obj: MagicMock) -> dict:
    """Build an object_by_id mapping from the plan, with mock door objects."""
    object_by_id: dict = {}

    for interaction in plan.get("interactions", []):
        subject_id = interaction.get("subject_id")
        if subject_id:
            door_obj = MagicMock()
            door_obj.name = f"Door_{subject_id}"
            door_props = {}
            door_obj.__setitem__ = MagicMock(
                side_effect=lambda k, v, p=door_props: p.__setitem__(k, v)
            )
            door_obj.__getitem__ = MagicMock(
                side_effect=lambda k, p=door_props: p[k]
            )
            door_obj.__contains__ = MagicMock(
                side_effect=lambda k, p=door_props: k in p
            )
            door_obj.get = MagicMock(
                side_effect=lambda k, d=None, p=door_props: p.get(k, d)
            )
            object_by_id[subject_id] = door_obj

    return object_by_id


# ---------------------------------------------------------------------------
# Property 14a: No unhandled exception when primary save fails but fallback
#               succeeds — compiler degrades gracefully.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    api_report=api_report_strategy,
    plan=plan_strategy,
)
def test_property_14_no_unhandled_exception_on_primary_save_failure(
    api_report: UPBGEComponentAPI,
    plan: dict,
):
    """Property 14: When primary save fails but fallback succeeds, no exception raised.

    **Validates: Requirements 9.1**

    For any api_report configuration and plan, if the primary save_as_mainfile
    raises an exception but the fallback save succeeds, _configure_runtime_050
    SHALL NOT raise an unhandled exception, and SHALL still return a player object.
    """
    bpy, player_obj = _make_mock_bpy(primary_save_fails=True)
    camera_obj = MagicMock()
    object_by_id = _make_object_by_id(plan, player_obj)

    # Execute — must NOT raise
    result = _configure_runtime_050(
        bpy=bpy,
        plan=plan,
        object_by_id=object_by_id,
        camera_obj=camera_obj,
        api_report=api_report,
    )

    # A player object must be returned
    assert result is not None, (
        "Expected _configure_runtime_050 to return a player object even "
        "when primary save fails, but got None"
    )

    # save_as_mainfile must have been called at least twice (primary + fallback)
    assert bpy.ops.wm.save_as_mainfile.call_count >= 2, (
        f"Expected at least 2 save attempts (primary + fallback), "
        f"got {bpy.ops.wm.save_as_mainfile.call_count}"
    )

    # Degradation info stored on the player
    assert "kiro_degradation_save" in player_obj._props, (
        "Expected kiro_degradation_save property on player after primary save failure"
    )


# ---------------------------------------------------------------------------
# Property 14b: Component attachment "failure" (fallback path used) still
#               produces a saved .blend — no exception.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    plan=plan_strategy,
)
def test_property_14_component_fallback_still_saves_blend(
    plan: dict,
):
    """Property 14: When component attachment uses fallback, a .blend is still saved.

    **Validates: Requirements 9.1**

    For any plan, when api_report.fallback_required=True (no native component
    API), _configure_runtime_050 SHALL still complete without exception and
    produce a saved .blend file.
    """
    # Force fallback_required=True — no native component API
    api_report = UPBGEComponentAPI(
        has_game_attr=False,
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

    bpy, player_obj = _make_mock_bpy(primary_save_fails=False)
    camera_obj = MagicMock()
    object_by_id = _make_object_by_id(plan, player_obj)

    # Execute — must NOT raise
    result = _configure_runtime_050(
        bpy=bpy,
        plan=plan,
        object_by_id=object_by_id,
        camera_obj=camera_obj,
        api_report=api_report,
    )

    # Returns a player object
    assert result is not None, (
        "Expected _configure_runtime_050 to return a player object "
        "with fallback_required=True, but got None"
    )

    # save_as_mainfile called exactly once (success on first try)
    assert bpy.ops.wm.save_as_mainfile.call_count == 1, (
        f"Expected exactly 1 save call when primary save succeeds, "
        f"got {bpy.ops.wm.save_as_mainfile.call_count}"
    )

    # Degradation info for component stored on player
    assert "kiro_degradation_component" in player_obj._props, (
        "Expected kiro_degradation_component property on player when "
        "fallback_required=True (native component attachment not used)"
    )


# ---------------------------------------------------------------------------
# Property 14c: Scene geometry preserved — component API unavailable but
#               physics also unavailable (full degradation), no exception.
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    plan=plan_strategy,
    primary_save_fails=st.booleans(),
)
def test_property_14_full_degradation_no_exception(
    plan: dict,
    primary_save_fails: bool,
):
    """Property 14: Full degradation (no physics + no component API) still saves.

    **Validates: Requirements 9.1**

    For any plan, when both physics and component APIs are unavailable and
    (optionally) primary save fails but fallback succeeds,
    _configure_runtime_050 SHALL NOT raise and SHALL return a player object.
    """
    # Full degradation: no native APIs at all
    api_report = UPBGEComponentAPI(
        has_game_attr=False,
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

    bpy, player_obj = _make_mock_bpy(primary_save_fails=primary_save_fails)
    camera_obj = MagicMock()
    object_by_id = _make_object_by_id(plan, player_obj)

    # Execute — must NOT raise
    result = _configure_runtime_050(
        bpy=bpy,
        plan=plan,
        object_by_id=object_by_id,
        camera_obj=camera_obj,
        api_report=api_report,
    )

    # Returns a player object
    assert result is not None, (
        "Expected _configure_runtime_050 to return a player object "
        "under full degradation, but got None"
    )

    # Both physics and component degradation stored
    assert "kiro_degradation_physics" in player_obj._props, (
        "Expected kiro_degradation_physics when has_game_physics=False"
    )
    assert "kiro_degradation_component" in player_obj._props, (
        "Expected kiro_degradation_component when fallback_required=True"
    )
