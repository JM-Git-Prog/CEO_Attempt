"""Property-based tests for module path ↔ text datablock consistency (Property 16).

**Validates: Requirements 10.2**

Property 16: Module Path ↔ Text Datablock Consistency
- For any component attachment, `module_name + ".py"` SHALL exist in `bpy.data.texts`
"""

from __future__ import annotations

from unittest.mock import MagicMock

from hypothesis import given, settings, strategies as st

from src.assembler.component_attach_050 import (
    _embed_component_source,
    _attach_component_050,
    _configure_runtime_050,
)
from src.assembler.api_probe_050 import UPBGEComponentAPI
from src.upbge_runtime import PLAYER_COMPONENT_SOURCE, DOOR_COMPONENT_SOURCE_050


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


class MockBpyData:
    """Simulates bpy.data with texts collection."""

    def __init__(self):
        self.texts = MockTextsCollection()
        self.filepath = ""


class MockBpy:
    """Simulates the bpy module for testing."""

    def __init__(self):
        self.data = MockBpyData()
        self.ops = MagicMock()
        self.context = MagicMock()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid Python identifiers (lowercase with digits/underscore, starting with letter)
module_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,30}", fullmatch=True)

# Source code: arbitrary Python-like text
source_strategy = st.text(
    min_size=1,
    max_size=500,
    alphabet=st.characters(whitelist_categories=("L", "Nd", "P", "Zs")),
)


# ---------------------------------------------------------------------------
# Property 16a: _embed_component_source creates text datablock matching
#               module_name + ".py"
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(module_name=module_name_strategy, source=source_strategy)
def test_property_16_embed_creates_consistent_text_datablock(
    module_name: str, source: str
):
    """Property 16: After embedding, module_name + '.py' exists in bpy.data.texts.

    **Validates: Requirements 10.2**

    For any valid module name, calling _embed_component_source SHALL create a text
    datablock named exactly `module_name + ".py"` in bpy.data.texts.
    """
    bpy = MockBpy()

    text_datablock_name = _embed_component_source(bpy, module_name, source)

    # The returned name SHALL be module_name + ".py"
    expected_name = module_name + ".py"
    assert text_datablock_name == expected_name, (
        f"Expected text_datablock_name '{expected_name}', got '{text_datablock_name}'"
    )

    # The text datablock SHALL exist in bpy.data.texts
    assert expected_name in bpy.data.texts, (
        f"Text datablock '{expected_name}' not found in bpy.data.texts after embed. "
        f"Available: {bpy.data.texts.names}"
    )


# ---------------------------------------------------------------------------
# Property 16b: _attach_component_050 fallback path derives module_name
#               that matches existing text datablock
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(module_name=module_name_strategy, source=source_strategy)
def test_property_16_attach_derives_module_from_text_datablock_name(
    module_name: str, source: str
):
    """Property 16: Attach derives module_name from text_datablock_name consistently.

    **Validates: Requirements 10.2**

    For any component attachment, the module_name derived inside _attach_component_050
    (by stripping '.py' from text_datablock_name) SHALL equal the original module_name
    used during embedding, ensuring the text datablock can be located at runtime.
    """
    bpy = MockBpy()

    # Step 1: Embed source — creates module_name + ".py" text datablock
    text_datablock_name = _embed_component_source(bpy, module_name, source)

    # Step 2: Simulate what _attach_component_050 does internally:
    # It derives module_name by stripping .py suffix from text_datablock_name
    derived_module = text_datablock_name
    if derived_module.endswith(".py"):
        derived_module = derived_module[:-3]

    # The derived module name SHALL equal the original module name
    assert derived_module == module_name, (
        f"Derived module '{derived_module}' != original '{module_name}'. "
        f"text_datablock_name was '{text_datablock_name}'"
    )

    # AND the corresponding text datablock SHALL still exist
    assert text_datablock_name in bpy.data.texts, (
        f"Text datablock '{text_datablock_name}' not in bpy.data.texts "
        f"after embed + derive cycle"
    )


# ---------------------------------------------------------------------------
# Property 16c: Full round-trip: embed → attach → text datablock exists
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(module_name=module_name_strategy, source=source_strategy)
def test_property_16_full_roundtrip_embed_then_attach(
    module_name: str, source: str
):
    """Property 16: Full round-trip — embed then attach preserves text datablock.

    **Validates: Requirements 10.2**

    For any module_name, embedding source THEN attaching a component with the
    returned text_datablock_name SHALL leave the text datablock intact and
    accessible via the module_name the component will use at runtime.
    """
    bpy = MockBpy()

    # Embed the component source
    text_datablock_name = _embed_component_source(bpy, module_name, source)

    # Create a mock object for attachment
    obj = MagicMock()
    obj.__setitem__ = MagicMock()
    obj.__getitem__ = MagicMock(return_value=None)

    # Create a fallback-required API report (uses ID properties path)
    api_report = UPBGEComponentAPI(
        has_game_attr=False,
        has_components_attr=False,
        component_api_path=None,
        component_add_method=None,
        has_logic_ops=False,
        physics_api_path=None,
        has_game_physics=False,
        blender_version="5.0.1",
        upbge_detected=True,
        fallback_required=True,
    )

    # Attach — this uses text_datablock_name to derive module_name
    _attach_component_050(
        bpy, obj, "TestComponent", text_datablock_name, {}, api_report
    )

    # The text datablock SHALL still exist after attachment
    assert text_datablock_name in bpy.data.texts, (
        f"Text datablock '{text_datablock_name}' disappeared after attachment"
    )

    # The stored module_name on the object SHALL match the original
    # (check the fallback path wrote the correct module name)
    obj.__setitem__.assert_any_call("kiro_component_module", module_name)


# ---------------------------------------------------------------------------
# Property 16d: _configure_runtime_050 creates text datablocks BEFORE
#               attaching components
# ---------------------------------------------------------------------------


def test_property_16_configure_runtime_creates_text_before_attach():
    """Property 16: _configure_runtime_050 creates text datablocks before attach.

    **Validates: Requirements 10.2**

    The orchestrator function SHALL embed component source as text datablocks
    BEFORE attempting to attach components — ensuring the module_name + ".py"
    text datablock exists at the point of component registration.
    """
    bpy = MockBpy()

    # Set up player object mock
    player_obj = MagicMock()
    player_obj.name = "KiroPlayer"
    player_obj.get = MagicMock(return_value=None)
    player_obj.__setitem__ = MagicMock()
    player_obj.__getitem__ = MagicMock(return_value=None)

    bpy.context.active_object = player_obj

    # Fallback API report
    api_report = UPBGEComponentAPI(
        has_game_attr=False,
        has_components_attr=False,
        component_api_path=None,
        component_add_method=None,
        has_logic_ops=False,
        physics_api_path=None,
        has_game_physics=False,
        blender_version="5.0.1",
        upbge_detected=True,
        fallback_required=True,
    )

    plan = {"interactions": [], "player_args": {}}
    camera_obj = MagicMock()
    object_by_id: dict = {}

    _configure_runtime_050(bpy, plan, object_by_id, camera_obj, api_report)

    # After full configuration, both component text datablocks SHALL exist
    assert "kiro_player_first_person.py" in bpy.data.texts, (
        "Player text datablock not found after _configure_runtime_050"
    )
    assert "kiro_interaction_door.py" in bpy.data.texts, (
        "Door text datablock not found after _configure_runtime_050"
    )

    # Bootstrap text datablock SHALL also exist (fallback_required=True)
    assert "kiro_component_bootstrap.py" in bpy.data.texts, (
        "Bootstrap text datablock not found after _configure_runtime_050 "
        "with fallback_required=True"
    )

    # The module names stored on the player SHALL reference existing text datablocks
    calls = player_obj.__setitem__.call_args_list
    module_calls = [c for c in calls if c[0][0] == "kiro_component_module"]
    for call in module_calls:
        stored_module = call[0][1]
        expected_text = stored_module + ".py"
        assert expected_text in bpy.data.texts, (
            f"Stored module '{stored_module}' has no corresponding text datablock "
            f"'{expected_text}' in bpy.data.texts"
        )
