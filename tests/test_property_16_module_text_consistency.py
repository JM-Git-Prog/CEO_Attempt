"""Property-based tests for module path ↔ text datablock consistency (Property 16).

**Validates: Requirements 10.2**

Property 16: Module Path ↔ Text Datablock Consistency
- For any component attachment, `module_name + ".py"` SHALL exist in
  `bpy.data.texts`.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given, settings, strategies as st

from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.assembler.component_attach_050 import (
    _attach_component_050,
    _embed_component_source,
    _configure_runtime_050,
)


# ---------------------------------------------------------------------------
# Mock bpy infrastructure
# ---------------------------------------------------------------------------


class MockText:
    """Simulates a Blender Text datablock."""

    def __init__(self, name: str):
        self.name = name
        self._content = ""
        self.use_module = False

    def write(self, text: str) -> None:
        self._content += text

    @property
    def content(self) -> str:
        return self._content


class MockTextsCollection:
    """Dict-like store simulating bpy.data.texts."""

    def __init__(self):
        self._store: dict[str, MockText] = {}

    def get(self, name: str) -> MockText | None:
        return self._store.get(name)

    def new(self, name: str) -> MockText:
        text = MockText(name)
        self._store[name] = text
        return text

    def remove(self, text: MockText) -> None:
        if text.name in self._store:
            del self._store[text.name]

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, name: str) -> bool:
        return name in self._store

    def __iter__(self):
        return iter(self._store.values())

    @property
    def names(self) -> list[str]:
        return list(self._store.keys())


class MockObject:
    """Simulates a Blender object with custom properties."""

    def __init__(self, name: str = "TestObject"):
        self.name = name
        self._props: dict[str, Any] = {}
        self.parent = None
        self.scale = (1.0, 1.0, 1.0)

    def __setitem__(self, key: str, value: Any) -> None:
        self._props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._props[key]

    def __contains__(self, key: str) -> bool:
        return key in self._props

    def get(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)


class MockBpyData:
    """Simulates bpy.data with texts collection."""

    def __init__(self):
        self.texts = MockTextsCollection()
        self.filepath = ""


class MockContext:
    """Simulates bpy.context."""

    def __init__(self):
        self.active_object = None


class MockOps:
    """Simulates bpy.ops for save operations."""

    class wm:
        @staticmethod
        def save_as_mainfile(filepath: str = "") -> None:
            pass

    class mesh:
        @staticmethod
        def primitive_cube_add(size: float = 1.0, location: tuple = (0, 0, 0)) -> None:
            pass


class MockBpy:
    """Simulates the bpy module for testing."""

    def __init__(self):
        self.data = MockBpyData()
        self.context = MockContext()
        self.ops = MockOps()


def _make_fallback_api_report() -> UPBGEComponentAPI:
    """Create a fallback API report (no native component API)."""
    return UPBGEComponentAPI(
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


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Module names: valid Python identifiers without .py extension
module_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,30}", fullmatch=True)

# Source code: arbitrary text that could be Python source
source_strategy = st.text(
    min_size=1,
    max_size=500,
    alphabet=st.characters(whitelist_categories=("L", "Nd", "P", "Zs", "Cc")),
)

# Component class names: valid Python class names
class_name_strategy = st.from_regex(r"[A-Z][A-Za-z0-9]{0,20}", fullmatch=True)

# Component args: simple key-value dicts with JSON-safe values
args_strategy = st.dictionaries(
    keys=st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True),
    values=st.one_of(
        st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        st.integers(min_value=-1000, max_value=1000),
        st.booleans(),
    ),
    min_size=0,
    max_size=5,
)


# ---------------------------------------------------------------------------
# Property 16a: After embed + attach, module_name + ".py" exists in texts
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    module_name=module_name_strategy,
    source=source_strategy,
    class_name=class_name_strategy,
    args=args_strategy,
)
def test_property_16_embed_then_attach_text_exists(
    module_name: str,
    source: str,
    class_name: str,
    args: dict[str, Any],
):
    """Property 16: After embed + attach (fallback), module_name + ".py" exists.

    **Validates: Requirements 10.2**

    For any component attachment, the module path stored on the object
    SHALL correspond to an existing text datablock in bpy.data.texts.
    """
    bpy = MockBpy()
    api_report = _make_fallback_api_report()
    obj = MockObject("TestObj")

    # Step 1: Embed the component source (creates text datablock)
    text_name = _embed_component_source(bpy, module_name, source)

    # Step 2: Attach the component (fallback stores module_name on object)
    _attach_component_050(bpy, obj, class_name, text_name, args, api_report)

    # Invariant: obj["kiro_component_module"] + ".py" exists in bpy.data.texts
    stored_module = obj["kiro_component_module"]
    expected_text_name = stored_module + ".py"

    assert expected_text_name in bpy.data.texts, (
        f"Text datablock '{expected_text_name}' not found in bpy.data.texts. "
        f"Available: {bpy.data.texts.names}"
    )


# ---------------------------------------------------------------------------
# Property 16b: The stored module name matches the embedded text name
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    module_name=module_name_strategy,
    source=source_strategy,
    class_name=class_name_strategy,
    args=args_strategy,
)
def test_property_16_stored_module_matches_text_datablock(
    module_name: str,
    source: str,
    class_name: str,
    args: dict[str, Any],
):
    """Property 16: stored module_name + ".py" == text_datablock_name.

    **Validates: Requirements 10.2**

    For any component attachment in fallback mode, the module name stored
    on the object (kiro_component_module) plus ".py" SHALL equal the
    text_datablock_name that was passed to _attach_component_050.
    """
    bpy = MockBpy()
    api_report = _make_fallback_api_report()
    obj = MockObject("TestObj")

    # Embed and attach
    text_name = _embed_component_source(bpy, module_name, source)
    _attach_component_050(bpy, obj, class_name, text_name, args, api_report)

    # The stored module_name + ".py" must equal the text_datablock_name
    stored_module = obj["kiro_component_module"]
    assert stored_module + ".py" == text_name, (
        f"Stored module '{stored_module}' + '.py' != text name '{text_name}'"
    )


# ---------------------------------------------------------------------------
# Property 16c: _configure_runtime_050 ensures consistency for all objects
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    door_count=st.integers(min_value=0, max_value=3),
)
def test_property_16_configure_runtime_all_objects_consistent(
    door_count: int,
):
    """Property 16: After _configure_runtime_050, all objects with
    kiro_component_module have a matching text datablock.

    **Validates: Requirements 10.2**

    After running _configure_runtime_050(), every object that has a
    kiro_component_module property SHALL have a corresponding
    module_name + ".py" text datablock in bpy.data.texts.
    """
    bpy = MockBpy()
    api_report = _make_fallback_api_report()

    # Create player and camera objects
    player_obj = MockObject("KiroPlayer")
    camera_obj = MockObject("Camera")

    # MockBpy needs context.active_object for _find_or_create_player fallback
    bpy.context.active_object = player_obj

    # Build object_by_id with player and doors
    object_by_id: dict[str, Any] = {"player": player_obj}
    interactions = []
    door_objects = []
    for i in range(door_count):
        door = MockObject(f"Door_{i}")
        door_id = f"door_{i}"
        object_by_id[door_id] = door
        door_objects.append(door)
        interactions.append({
            "kind": "door",
            "subject_id": door_id,
            "parameters": {
                "open_angle_deg": 90.0,
                "speed_deg_s": 120.0,
                "initially_open": False,
            },
        })

    plan = {
        "interactions": interactions,
        "player_args": {
            "move_speed": 4.0,
            "look_speed": 0.0025,
            "gravity": 9.81,
            "max_grab_distance": 3.0,
            "grab_hold_distance": 1.5,
        },
    }

    # Run the full configure function
    _configure_runtime_050(bpy, plan, object_by_id, camera_obj, api_report)

    # Check the invariant on all objects (player + doors)
    all_objects = [player_obj] + door_objects
    for obj in all_objects:
        if "kiro_component_module" in obj:
            stored_module = obj["kiro_component_module"]
            expected_text = stored_module + ".py"
            assert expected_text in bpy.data.texts, (
                f"Object '{obj.name}' has kiro_component_module='{stored_module}' "
                f"but '{expected_text}' not found in bpy.data.texts. "
                f"Available: {bpy.data.texts.names}"
            )
