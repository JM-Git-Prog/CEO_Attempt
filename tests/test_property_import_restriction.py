"""Property-based tests for component source import restriction (Property 17).

**Validates: Requirements 10.4, 10.5**

Property 17: Component Source Import Restriction
- Parsing any component source AST SHALL yield only imports from allowed set:
  {bge, mathutils, math, json} + stdlib. No `bpy` or third-party imports.
"""

from __future__ import annotations

import ast
import sys

from hypothesis import given, settings, assume, strategies as st

from src.upbge_runtime import PLAYER_COMPONENT_SOURCE, DOOR_COMPONENT_SOURCE_050
from src.assembler.component_attach_050 import BOOTSTRAP_COMPONENT_SOURCE


# ---------------------------------------------------------------------------
# Allowed import set for component sources running inside bge/blenderplayer
# ---------------------------------------------------------------------------

# Modules allowed in component source (runtime environment)
ALLOWED_COMPONENT_IMPORTS = frozenset({
    "bge",
    "mathutils",
    "math",
    "json",
})

# Additional modules allowed in the bootstrap script only
ALLOWED_BOOTSTRAP_IMPORTS = frozenset({
    "bge",
    "importlib",
    "json",
})

# Forbidden: these are NOT available in blenderplayer runtime
FORBIDDEN_IMPORTS = frozenset({
    "bpy",
})

# Python standard library module names (common subset for validation)
# We use sys.stdlib_module_names on Python 3.10+ for authoritative list
STDLIB_MODULES: frozenset[str] = getattr(
    sys, "stdlib_module_names", frozenset()
)


# ---------------------------------------------------------------------------
# Import checker function
# ---------------------------------------------------------------------------


def check_import_restriction(
    source: str,
    allowed: frozenset[str] | None = None,
) -> tuple[bool, list[str]]:
    """Parse source AST and check all imports are from the allowed set.

    Args:
        source: Python source code string.
        allowed: Set of allowed top-level module names. If None, uses
            ALLOWED_COMPONENT_IMPORTS + STDLIB_MODULES.

    Returns:
        Tuple of (is_valid, list_of_violations).
        is_valid is True if all imports are allowed.
        list_of_violations contains any forbidden import names found.
    """
    if allowed is None:
        allowed = ALLOWED_COMPONENT_IMPORTS | STDLIB_MODULES

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Unparseable source is not a valid component
        return False, ["<SyntaxError>"]

    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Top-level module name (e.g., "bge" from "bge.logic")
                top_module = alias.name.split(".")[0]
                if top_module in FORBIDDEN_IMPORTS:
                    violations.append(top_module)
                elif top_module not in allowed:
                    violations.append(top_module)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                top_module = node.module.split(".")[0]
                if top_module in FORBIDDEN_IMPORTS:
                    violations.append(top_module)
                elif top_module not in allowed:
                    violations.append(top_module)

    return len(violations) == 0, violations


# ---------------------------------------------------------------------------
# Deterministic tests: actual component sources comply
# ---------------------------------------------------------------------------


def test_property_17_player_component_imports_are_allowed():
    """Property 17: PlayerComponent source imports only from allowed set.

    **Validates: Requirements 10.4, 10.5**

    PLAYER_COMPONENT_SOURCE SHALL contain only imports from {bge, mathutils,
    math, json} + stdlib. No `bpy` or third-party imports.
    """
    is_valid, violations = check_import_restriction(
        PLAYER_COMPONENT_SOURCE, ALLOWED_COMPONENT_IMPORTS | STDLIB_MODULES
    )
    assert is_valid, (
        f"PLAYER_COMPONENT_SOURCE has forbidden imports: {violations}"
    )


def test_property_17_door_component_imports_are_allowed():
    """Property 17: DoorComponent source imports only from allowed set.

    **Validates: Requirements 10.4, 10.5**

    DOOR_COMPONENT_SOURCE_050 SHALL contain only imports from {bge, mathutils,
    math, json} + stdlib. No `bpy` or third-party imports.
    """
    is_valid, violations = check_import_restriction(
        DOOR_COMPONENT_SOURCE_050, ALLOWED_COMPONENT_IMPORTS | STDLIB_MODULES
    )
    assert is_valid, (
        f"DOOR_COMPONENT_SOURCE_050 has forbidden imports: {violations}"
    )


def test_property_17_bootstrap_imports_are_allowed():
    """Property 17: Bootstrap source imports only from its allowed set.

    **Validates: Requirements 10.4, 10.5**

    BOOTSTRAP_COMPONENT_SOURCE SHALL contain only imports from {bge, importlib,
    json} + stdlib. No `bpy` or third-party imports.
    """
    is_valid, violations = check_import_restriction(
        BOOTSTRAP_COMPONENT_SOURCE, ALLOWED_BOOTSTRAP_IMPORTS | STDLIB_MODULES
    )
    assert is_valid, (
        f"BOOTSTRAP_COMPONENT_SOURCE has forbidden imports: {violations}"
    )


def test_property_17_no_bpy_in_player_component():
    """Property 17: PlayerComponent SHALL NOT import bpy.

    **Validates: Requirements 10.5**
    """
    tree = ast.parse(PLAYER_COMPONENT_SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "bpy", (
                    f"PLAYER_COMPONENT_SOURCE imports 'bpy' — forbidden at runtime"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                assert node.module.split(".")[0] != "bpy", (
                    f"PLAYER_COMPONENT_SOURCE uses 'from bpy...' — forbidden at runtime"
                )


def test_property_17_no_bpy_in_door_component():
    """Property 17: DoorComponent SHALL NOT import bpy.

    **Validates: Requirements 10.5**
    """
    tree = ast.parse(DOOR_COMPONENT_SOURCE_050)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "bpy", (
                    f"DOOR_COMPONENT_SOURCE_050 imports 'bpy' — forbidden at runtime"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                assert node.module.split(".")[0] != "bpy", (
                    f"DOOR_COMPONENT_SOURCE_050 uses 'from bpy...' — forbidden at runtime"
                )


# ---------------------------------------------------------------------------
# Hypothesis strategies for generating component-like sources
# ---------------------------------------------------------------------------

# Allowed imports for generation
_ALLOWED_MODULES = ["bge", "bge.logic", "bge.events", "bge.render", "bge.types",
                    "mathutils", "math", "json"]

# Forbidden imports for negative testing
_FORBIDDEN_MODULES = ["bpy", "bpy.data", "bpy.ops", "numpy", "requests", "flask",
                      "django", "tensorflow", "pandas"]

# Generate a valid import statement
valid_import_stmt = st.sampled_from(
    [f"import {m}" for m in _ALLOWED_MODULES]
    + [f"from {m} import *" for m in _ALLOWED_MODULES]
)

# Generate a forbidden import statement
forbidden_import_stmt = st.sampled_from(
    [f"import {m}" for m in _FORBIDDEN_MODULES]
    + [f"from {m} import something" for m in _FORBIDDEN_MODULES]
)

# Generate a simple class body
class_body = st.just("class Comp:\n    pass\n")

# Build a valid component source (only allowed imports)
valid_source_strategy = st.builds(
    lambda imports, body: "\n".join(imports) + "\n\n" + body,
    imports=st.lists(valid_import_stmt, min_size=1, max_size=4),
    body=class_body,
)

# Build an invalid component source (has at least one forbidden import)
invalid_source_strategy = st.builds(
    lambda valid_imports, bad_import, body: (
        "\n".join(valid_imports) + "\n" + bad_import + "\n\n" + body
    ),
    valid_imports=st.lists(valid_import_stmt, min_size=0, max_size=3),
    bad_import=forbidden_import_stmt,
    body=class_body,
)


# ---------------------------------------------------------------------------
# Property 17a: Valid component sources pass the import check
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(source=valid_source_strategy)
def test_property_17_valid_sources_pass_import_check(source: str):
    """Property 17: Sources with only allowed imports pass the check.

    **Validates: Requirements 10.4, 10.5**

    For any generated source containing only imports from the allowed set,
    check_import_restriction SHALL return is_valid=True with no violations.
    """
    is_valid, violations = check_import_restriction(
        source, ALLOWED_COMPONENT_IMPORTS | STDLIB_MODULES
    )
    assert is_valid, (
        f"Source with only allowed imports was rejected. Violations: {violations}\n"
        f"Source:\n{source}"
    )


# ---------------------------------------------------------------------------
# Property 17b: Sources with forbidden imports fail the import check
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(source=invalid_source_strategy)
def test_property_17_forbidden_imports_fail_check(source: str):
    """Property 17: Sources with forbidden imports fail the check.

    **Validates: Requirements 10.4, 10.5**

    For any generated source containing at least one import from the forbidden
    set (bpy, third-party), check_import_restriction SHALL return is_valid=False
    with at least one violation.
    """
    is_valid, violations = check_import_restriction(
        source, ALLOWED_COMPONENT_IMPORTS | STDLIB_MODULES
    )
    assert not is_valid, (
        f"Source with forbidden imports was incorrectly accepted.\n"
        f"Source:\n{source}"
    )
    assert len(violations) > 0, (
        "Expected at least one violation for source with forbidden imports"
    )


# ---------------------------------------------------------------------------
# Property 17c: bpy is always detected as forbidden regardless of import form
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(
    bpy_form=st.sampled_from([
        "import bpy",
        "import bpy.data",
        "import bpy.ops",
        "from bpy import data",
        "from bpy.ops import mesh",
        "from bpy.types import Object",
    ]),
    prefix=st.lists(valid_import_stmt, min_size=0, max_size=2),
)
def test_property_17_bpy_always_forbidden(bpy_form: str, prefix: list[str]):
    """Property 17: Any form of bpy import SHALL be detected as forbidden.

    **Validates: Requirements 10.5**

    Regardless of import style (import bpy, from bpy import X, import bpy.sub),
    the checker SHALL flag it as a violation.
    """
    source = "\n".join(prefix) + "\n" + bpy_form + "\nclass C:\n    pass\n"
    is_valid, violations = check_import_restriction(
        source, ALLOWED_COMPONENT_IMPORTS | STDLIB_MODULES
    )
    assert not is_valid, (
        f"bpy import form '{bpy_form}' was not detected as forbidden"
    )
    assert "bpy" in violations, (
        f"'bpy' not in violations list: {violations}"
    )
