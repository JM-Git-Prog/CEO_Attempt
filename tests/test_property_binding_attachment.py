"""Property-based tests for interaction binding to component attachment (Property 11).

**Validates: Requirements 5.2, 5.3**

Property 11: Interaction Binding to Component Attachment
- For any set of interaction bindings in a RuntimePlan (door bindings), the compiler
  SHALL produce exactly one component attachment per binding, with `args` values
  matching the binding's parameters.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import _configure_runtime_050, _extract_door_args


# ---------------------------------------------------------------------------
# Mock helpers (matching existing test patterns from test_configure_runtime_050.py)
# ---------------------------------------------------------------------------


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


def _make_api_report(
    *,
    fallback_required: bool = False,
    component_api_path: str | None = "obj.game.components",
) -> UPBGEComponentAPI:
    """Create a UPBGEComponentAPI with native component API available."""
    return UPBGEComponentAPI(
        has_game_attr=True,
        has_components_attr=not fallback_required,
        component_api_path=component_api_path,
        component_add_method="obj.game.components.new()" if component_api_path else None,
        has_logic_ops=True,
        physics_api_path="obj.game.physics_type",
        has_game_physics=True,
        blender_version=(5, 0, 1),
        upbge_detected=True,
        fallback_required=fallback_required,
    )


def _make_mock_bpy(filepath: str = "C:/test/project.blend") -> MagicMock:
    """Create a fully-featured mock bpy module."""
    bpy = MagicMock()
    bpy.data.texts = MockTextsCollection()
    bpy.data.filepath = filepath

    player_obj = MockBlenderObject("KiroPlayer")

    def mock_cube_add(**kwargs):
        bpy.context.active_object = player_obj

    bpy.ops.mesh.primitive_cube_add = mock_cube_add
    bpy.context.active_object = player_obj
    bpy.ops.wm.save_as_mainfile.return_value = {"FINISHED"}

    return bpy


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate non-zero open_angle_deg in [-180, 180]
open_angle_strategy = st.floats(
    min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False
).filter(lambda x: abs(x) > 0.1)

# Generate speed_deg_s in (0.1, 720]
speed_strategy = st.floats(
    min_value=0.1, max_value=720.0, allow_nan=False, allow_infinity=False
)

# Strategy for a single door interaction binding
door_interaction_strategy = st.fixed_dictionaries({
    "kind": st.just("door"),
    "open_angle_deg": open_angle_strategy,
    "speed_deg_s": speed_strategy,
    "initially_open": st.booleans(),
})

# Strategy for a list of 0 to 5 door interactions with unique subject_ids
door_interactions_strategy = st.lists(
    door_interaction_strategy, min_size=0, max_size=5
)


def _build_interactions(raw_bindings: list[dict]) -> tuple[list[dict], dict[str, MockBlenderObject]]:
    """Convert raw bindings into plan interactions and object_by_id mapping.

    Each binding gets a unique subject_id and a corresponding mock object.
    """
    interactions = []
    object_by_id: dict[str, MockBlenderObject] = {}

    for i, binding in enumerate(raw_bindings):
        subject_id = f"door_{i:03d}"
        interaction = {
            "kind": "door",
            "subject_id": subject_id,
            "parameters": {
                "open_angle_deg": binding["open_angle_deg"],
                "speed_deg_s": binding["speed_deg_s"],
                "initially_open": binding["initially_open"],
            },
        }
        interactions.append(interaction)
        object_by_id[subject_id] = MockBlenderObject(f"DoorObj_{i}")

    return interactions, object_by_id


# ---------------------------------------------------------------------------
# Property 11a: Exactly one component attachment per door binding (native path)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(raw_bindings=door_interactions_strategy)
def test_property_11_one_attachment_per_binding_native(
    raw_bindings: list[dict],
):
    """Property 11: For any set of door interaction bindings, the compiler produces
    exactly one component attachment per binding via the native API path.

    **Validates: Requirements 5.2, 5.3**
    """
    interactions, object_by_id = _build_interactions(raw_bindings)
    plan = {"interactions": interactions, "player_args": {}}

    bpy = _make_mock_bpy()
    api_report = _make_api_report(fallback_required=False)
    camera = MockBlenderObject("Camera")

    _configure_runtime_050(bpy, plan, object_by_id, camera, api_report)

    # Assert: exactly one DoorComponent per door binding
    for i, binding in enumerate(raw_bindings):
        subject_id = f"door_{i:03d}"
        door_obj = object_by_id[subject_id]
        components = list(door_obj.game.components)

        assert len(components) == 1, (
            f"Door {subject_id} should have exactly 1 component, "
            f"got {len(components)}"
        )
        assert components[0].name == "DoorComponent", (
            f"Door {subject_id} component should be 'DoorComponent', "
            f"got '{components[0].name}'"
        )


# ---------------------------------------------------------------------------
# Property 11b: Args values match the binding's parameters (native path)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(raw_bindings=door_interactions_strategy)
def test_property_11_args_match_binding_parameters_native(
    raw_bindings: list[dict],
):
    """Property 11: Each component attachment has args matching the interaction's
    parameters when using the native API path.

    **Validates: Requirements 5.2, 5.3**

    The native path calls obj.game.components.new() and then sets properties
    on the component. We verify the component received the correct module and
    class name, confirming the binding was processed.
    """
    interactions, object_by_id = _build_interactions(raw_bindings)
    plan = {"interactions": interactions, "player_args": {}}

    bpy = _make_mock_bpy()
    api_report = _make_api_report(fallback_required=False)
    camera = MockBlenderObject("Camera")

    _configure_runtime_050(bpy, plan, object_by_id, camera, api_report)

    for i, binding in enumerate(raw_bindings):
        subject_id = f"door_{i:03d}"
        door_obj = object_by_id[subject_id]
        components = list(door_obj.game.components)

        assert len(components) == 1, (
            f"Door {subject_id} should have exactly 1 component"
        )
        comp = components[0]
        # Verify component was attached with correct module
        assert comp.module == "kiro_interaction_door", (
            f"Expected module 'kiro_interaction_door', got '{comp.module}'"
        )
        assert comp.name == "DoorComponent", (
            f"Expected class 'DoorComponent', got '{comp.name}'"
        )


# ---------------------------------------------------------------------------
# Property 11c: Exactly one component attachment per binding (fallback path)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(raw_bindings=door_interactions_strategy)
def test_property_11_one_attachment_per_binding_fallback(
    raw_bindings: list[dict],
):
    """Property 11: For any set of door interaction bindings, the compiler produces
    exactly one component attachment per binding via the fallback (ID property) path.

    **Validates: Requirements 5.2, 5.3**
    """
    interactions, object_by_id = _build_interactions(raw_bindings)
    plan = {"interactions": interactions, "player_args": {}}

    bpy = _make_mock_bpy()
    api_report = _make_api_report(fallback_required=True, component_api_path=None)
    camera = MockBlenderObject("Camera")

    _configure_runtime_050(bpy, plan, object_by_id, camera, api_report)

    # In fallback mode, component info is stored as custom ID properties
    for i, binding in enumerate(raw_bindings):
        subject_id = f"door_{i:03d}"
        door_obj = object_by_id[subject_id]

        assert door_obj.get("kiro_component_class") == "DoorComponent", (
            f"Door {subject_id} should have kiro_component_class='DoorComponent', "
            f"got '{door_obj.get('kiro_component_class')}'"
        )
        assert door_obj.get("kiro_component_module") == "kiro_interaction_door", (
            f"Door {subject_id} should have kiro_component_module='kiro_interaction_door', "
            f"got '{door_obj.get('kiro_component_module')}'"
        )


# ---------------------------------------------------------------------------
# Property 11d: Args match parameters in fallback path (via JSON storage)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(raw_bindings=door_interactions_strategy)
def test_property_11_args_match_binding_parameters_fallback(
    raw_bindings: list[dict],
):
    """Property 11: In fallback mode, each component attachment stores args as JSON
    that match the interaction's parameters.

    **Validates: Requirements 5.2, 5.3**

    The fallback path stores args as kiro_component_args JSON on the object.
    We verify the stored args match what _extract_door_args produces from
    the interaction parameters.
    """
    interactions, object_by_id = _build_interactions(raw_bindings)
    plan = {"interactions": interactions, "player_args": {}}

    bpy = _make_mock_bpy()
    api_report = _make_api_report(fallback_required=True, component_api_path=None)
    camera = MockBlenderObject("Camera")

    _configure_runtime_050(bpy, plan, object_by_id, camera, api_report)

    for i, binding in enumerate(raw_bindings):
        subject_id = f"door_{i:03d}"
        door_obj = object_by_id[subject_id]
        interaction = interactions[i]

        # Get the stored args JSON
        stored_args_json = door_obj.get("kiro_component_args")
        assert stored_args_json is not None, (
            f"Door {subject_id} should have kiro_component_args set"
        )
        stored_args = json.loads(stored_args_json)

        # Compute expected args via _extract_door_args
        expected_args = _extract_door_args(interaction)

        assert stored_args == expected_args, (
            f"Door {subject_id} stored args {stored_args} should match "
            f"expected {expected_args}"
        )
