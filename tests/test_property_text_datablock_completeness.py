"""Property-based tests for text datablock embedding completeness (Property 12).

**Validates: Requirements 5.4, 10.1**

Property 12: Text Datablock Embedding Completeness
- For any set of component templates, the compiler SHALL embed exactly one
  Text datablock per template with correct name and byte-for-byte content match.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.assembler.component_attach_050 import _embed_component_source


# ---------------------------------------------------------------------------
# Mock bpy with a realistic MockTextsCollection
# ---------------------------------------------------------------------------


class MockText:
    """Simulates a Blender Text datablock."""

    def __init__(self, name: str):
        self.name = name
        self._content = ""

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


class MockBpy:
    """Simulates the bpy module for testing."""

    def __init__(self):
        self.data = MockBpyData()


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Module names: valid Python identifiers without the .py extension
module_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,30}", fullmatch=True)

# Source code: arbitrary text that could be Python source
source_strategy = st.text(
    min_size=1,
    max_size=2000,
    alphabet=st.characters(whitelist_categories=("L", "Nd", "P", "Zs", "Cc")),
)

# Template sets: 1 to 5 unique (module_name, source) pairs
template_set_strategy = st.lists(
    st.tuples(module_name_strategy, source_strategy),
    min_size=1,
    max_size=5,
    unique_by=lambda pair: pair[0],  # unique module names
)


# ---------------------------------------------------------------------------
# Property 12a: Each embed creates exactly one text datablock with correct name
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(templates=template_set_strategy)
def test_property_12_embed_creates_one_text_per_template(
    templates: list[tuple[str, str]],
):
    """Property 12: Embedding N templates produces exactly N text datablocks.

    **Validates: Requirements 5.4, 10.1**

    For any set of component templates (1-5), calling _embed_component_source
    for each SHALL produce exactly one Text datablock per template — no
    duplicates, no missing entries.
    """
    bpy = MockBpy()

    returned_names = []
    for module_name, source in templates:
        name = _embed_component_source(bpy, module_name, source)
        returned_names.append(name)

    # Exactly one text datablock per template
    assert len(bpy.data.texts) == len(templates), (
        f"Expected {len(templates)} text datablocks, got {len(bpy.data.texts)}. "
        f"Names: {bpy.data.texts.names}"
    )

    # Each returned name matches the expected pattern
    for i, (module_name, _source) in enumerate(templates):
        expected_name = module_name + ".py"
        assert returned_names[i] == expected_name, (
            f"Expected returned name '{expected_name}', got '{returned_names[i]}'"
        )

    # Each expected name exists in the collection
    for module_name, _source in templates:
        expected_name = module_name + ".py"
        assert expected_name in bpy.data.texts, (
            f"Text datablock '{expected_name}' not found in bpy.data.texts"
        )


# ---------------------------------------------------------------------------
# Property 12b: Content matches source byte-for-byte
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(templates=template_set_strategy)
def test_property_12_embedded_content_matches_source(
    templates: list[tuple[str, str]],
):
    """Property 12: Embedded content matches the source byte-for-byte.

    **Validates: Requirements 5.4, 10.1**

    For any set of component templates, the content written to each Text
    datablock SHALL exactly match the provided source string.
    """
    bpy = MockBpy()

    for module_name, source in templates:
        _embed_component_source(bpy, module_name, source)

    for module_name, source in templates:
        text_name = module_name + ".py"
        text_obj = bpy.data.texts.get(text_name)
        assert text_obj is not None, (
            f"Text datablock '{text_name}' not found after embedding"
        )
        assert text_obj.content == source, (
            f"Content mismatch for '{text_name}': "
            f"expected {len(source)} chars, got {len(text_obj.content)} chars"
        )


# ---------------------------------------------------------------------------
# Property 12c: Re-embedding same name replaces (no duplicates)
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    module_name=module_name_strategy,
    source_first=source_strategy,
    source_second=source_strategy,
)
def test_property_12_reembed_replaces_without_duplication(
    module_name: str,
    source_first: str,
    source_second: str,
):
    """Property 12: Calling embed twice with the same name replaces, not duplicates.

    **Validates: Requirements 5.4, 10.1**

    For any module name, embedding source A then embedding source B with the
    same module name SHALL result in exactly one text datablock whose content
    is source B (the replacement).
    """
    bpy = MockBpy()

    # First embed
    name1 = _embed_component_source(bpy, module_name, source_first)
    assert len(bpy.data.texts) == 1

    # Second embed with same name
    name2 = _embed_component_source(bpy, module_name, source_second)
    assert len(bpy.data.texts) == 1, (
        f"Expected 1 text datablock after re-embed, got {len(bpy.data.texts)}"
    )

    # Names are identical
    assert name1 == name2 == module_name + ".py"

    # Content is the second source (replacement)
    text_obj = bpy.data.texts.get(module_name + ".py")
    assert text_obj is not None
    assert text_obj.content == source_second, (
        f"After re-embed, content should be source_second "
        f"({len(source_second)} chars), got {len(text_obj.content)} chars"
    )


# ---------------------------------------------------------------------------
# Property 12d: Text datablock name follows naming convention
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    module_name=module_name_strategy,
    source=source_strategy,
)
def test_property_12_text_name_is_module_plus_py(
    module_name: str,
    source: str,
):
    """Property 12: Text datablock name == module_name + ".py".

    **Validates: Requirements 5.4, 10.1**

    For any module name, the text datablock SHALL be named exactly
    module_name + ".py".
    """
    bpy = MockBpy()
    returned_name = _embed_component_source(bpy, module_name, source)

    expected_name = module_name + ".py"
    assert returned_name == expected_name, (
        f"Expected name '{expected_name}', got '{returned_name}'"
    )

    # The text object in the collection also has this name
    text_obj = bpy.data.texts.get(expected_name)
    assert text_obj is not None
    assert text_obj.name == expected_name
