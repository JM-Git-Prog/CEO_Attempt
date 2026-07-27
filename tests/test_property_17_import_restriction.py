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


# ---------------------------------------------------------------------------
# Allowed import set
# ---------------------------------------------------------------------------

# Explicit game-runtime allowed modules
ALLOWED_GAME_MODULES = {"bge", "mathutils", "math", "json"}

# Python standard library modules (3.10+)
if hasattr(sys, "stdlib_module_names"):
    STDLIB_MODULES = sys.stdlib_module_names
else:
    # Curated fallback for older Python versions
    STDLIB_MODULES = frozenset({
        "abc", "aifc", "argparse", "array", "ast", "asynchat", "asyncio",
        "asyncore", "atexit", "audioop", "base64", "bdb", "binascii",
        "binhex", "bisect", "builtins", "bz2", "calendar", "cgi", "cgitb",
        "chunk", "cmath", "cmd", "code", "codecs", "codeop", "collections",
        "colorsys", "compileall", "concurrent", "configparser", "contextlib",
        "contextvars", "copy", "copyreg", "cProfile", "crypt", "csv",
        "ctypes", "curses", "dataclasses", "datetime", "dbm", "decimal",
        "difflib", "dis", "distutils", "doctest", "email", "encodings",
        "enum", "errno", "faulthandler", "fcntl", "filecmp", "fileinput",
        "fnmatch", "fractions", "ftplib", "functools", "gc", "getopt",
        "getpass", "gettext", "glob", "grp", "gzip", "hashlib", "heapq",
        "hmac", "html", "http", "idlelib", "imaplib", "imghdr", "imp",
        "importlib", "inspect", "io", "ipaddress", "itertools", "json",
        "keyword", "lib2to3", "linecache", "locale", "logging", "lzma",
        "mailbox", "mailcap", "marshal", "math", "mimetypes", "mmap",
        "modulefinder", "multiprocessing", "netrc", "nis", "nntplib",
        "numbers", "operator", "optparse", "os", "ossaudiodev",
        "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
        "platform", "plistlib", "poplib", "posix", "posixpath", "pprint",
        "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
        "pydoc", "queue", "quopri", "random", "re", "readline", "reprlib",
        "resource", "rlcompleter", "runpy", "sched", "secrets", "select",
        "selectors", "shelve", "shlex", "shutil", "signal", "site",
        "smtpd", "smtplib", "sndhdr", "socket", "socketserver", "spwd",
        "sqlite3", "sre_compile", "sre_constants", "sre_parse", "ssl",
        "stat", "statistics", "string", "stringprep", "struct", "subprocess",
        "sunau", "symtable", "sys", "sysconfig", "syslog", "tabnanny",
        "tarfile", "telnetlib", "tempfile", "termios", "test", "textwrap",
        "threading", "time", "timeit", "tkinter", "token", "tokenize",
        "tomllib", "trace", "traceback", "tracemalloc", "tty", "turtle",
        "turtledemo", "types", "typing", "unicodedata", "unittest", "urllib",
        "uu", "uuid", "venv", "warnings", "wave", "weakref", "webbrowser",
        "winreg", "winsound", "wsgiref", "xdrlib", "xml", "xmlrpc",
        "zipapp", "zipfile", "zipimport", "zlib", "_thread",
    })

ALL_ALLOWED = ALLOWED_GAME_MODULES | set(STDLIB_MODULES)

# Known forbidden modules for testing
FORBIDDEN_MODULES = [
    "bpy", "numpy", "scipy", "requests", "flask", "django",
    "pandas", "matplotlib", "PIL", "cv2", "torch", "tensorflow",
    "sklearn", "setuptools", "pip", "wheel",
]


# ---------------------------------------------------------------------------
# Helper: extract all imports from a source string
# ---------------------------------------------------------------------------


def extract_imports(source: str) -> list[str]:
    """Parse source AST and return all top-level imported module names.

    For `import X` → returns "X"
    For `import X.Y` → returns "X" (top-level module)
    For `from X import Y` → returns "X"
    For `from X.Y import Z` → returns "X" (top-level module)
    """
    tree = ast.parse(source)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Take top-level module (e.g., "bge" from "bge.logic")
                top_module = alias.name.split(".")[0]
                modules.append(top_module)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                top_module = node.module.split(".")[0]
                modules.append(top_module)
    return modules


def check_forbidden_imports(source: str) -> list[str]:
    """Return list of forbidden imports found in the given source."""
    modules = extract_imports(source)
    forbidden = []
    for mod in modules:
        if mod not in ALL_ALLOWED:
            forbidden.append(mod)
    return forbidden


# ---------------------------------------------------------------------------
# Property 17a: PLAYER_COMPONENT_SOURCE has no forbidden imports
# ---------------------------------------------------------------------------


def test_property_17_player_component_no_forbidden_imports():
    """Property 17: PLAYER_COMPONENT_SOURCE imports only from the allowed set.

    **Validates: Requirements 10.4, 10.5**

    Parsing PLAYER_COMPONENT_SOURCE AST SHALL yield only imports from
    {bge, mathutils, math, json} + stdlib.
    """
    forbidden = check_forbidden_imports(PLAYER_COMPONENT_SOURCE)
    assert forbidden == [], (
        f"PLAYER_COMPONENT_SOURCE contains forbidden imports: {forbidden}. "
        f"Only {ALLOWED_GAME_MODULES} + stdlib are allowed."
    )


# ---------------------------------------------------------------------------
# Property 17b: DOOR_COMPONENT_SOURCE_050 has no forbidden imports
# ---------------------------------------------------------------------------


def test_property_17_door_component_no_forbidden_imports():
    """Property 17: DOOR_COMPONENT_SOURCE_050 imports only from the allowed set.

    **Validates: Requirements 10.4, 10.5**

    Parsing DOOR_COMPONENT_SOURCE_050 AST SHALL yield only imports from
    {bge, mathutils, math, json} + stdlib.
    """
    forbidden = check_forbidden_imports(DOOR_COMPONENT_SOURCE_050)
    assert forbidden == [], (
        f"DOOR_COMPONENT_SOURCE_050 contains forbidden imports: {forbidden}. "
        f"Only {ALLOWED_GAME_MODULES} + stdlib are allowed."
    )


# ---------------------------------------------------------------------------
# Property 17c: All imports in actual sources are in the allowed set
# ---------------------------------------------------------------------------


def test_property_17_all_actual_sources_allowed_only():
    """Property 17: All actual component sources use only allowed imports.

    **Validates: Requirements 10.4, 10.5**

    For each component source, every import SHALL be from the allowed set.
    This test explicitly verifies each imported module is in ALLOWED_GAME_MODULES
    or STDLIB_MODULES.
    """
    sources = {
        "PLAYER_COMPONENT_SOURCE": PLAYER_COMPONENT_SOURCE,
        "DOOR_COMPONENT_SOURCE_050": DOOR_COMPONENT_SOURCE_050,
    }

    for name, source in sources.items():
        modules = extract_imports(source)
        for mod in modules:
            assert mod in ALL_ALLOWED, (
                f"In {name}: import '{mod}' is not in the allowed set. "
                f"Allowed game modules: {ALLOWED_GAME_MODULES}. "
                f"Module must be one of these or a Python stdlib module."
            )


# ---------------------------------------------------------------------------
# Property 17d (PBT): Sources with only allowed imports pass validation
# ---------------------------------------------------------------------------

# Strategy: generate valid Python source with only allowed imports
allowed_module_strategy = st.sampled_from(sorted(ALLOWED_GAME_MODULES))

import_statement_strategy = st.one_of(
    # import <module>
    allowed_module_strategy.map(lambda m: f"import {m}"),
    # from <module> import <name>
    allowed_module_strategy.map(lambda m: f"from {m} import SomeName"),
    # import <module>.<sub>
    allowed_module_strategy.map(lambda m: f"import {m}.submodule"),
    # from <module>.<sub> import <name>
    allowed_module_strategy.map(lambda m: f"from {m}.submodule import Thing"),
)

valid_source_strategy = st.lists(
    import_statement_strategy,
    min_size=1,
    max_size=5,
).map(lambda imports: "\n".join(imports) + "\n\nclass Comp:\n    pass\n")


@settings(max_examples=200, deadline=None)
@given(source=valid_source_strategy)
def test_property_17_valid_sources_pass_check(source: str):
    """Property 17: Sources with only allowed imports pass validation.

    **Validates: Requirements 10.4, 10.5**

    For any generated source that imports only from {bge, mathutils, math, json},
    the import checker SHALL report zero forbidden imports.
    """
    forbidden = check_forbidden_imports(source)
    assert forbidden == [], (
        f"Source with only allowed imports was flagged: {forbidden}. "
        f"Source:\n{source}"
    )


# ---------------------------------------------------------------------------
# Property 17e (PBT): Sources with forbidden imports fail validation
# ---------------------------------------------------------------------------

forbidden_module_strategy = st.sampled_from(FORBIDDEN_MODULES)

forbidden_import_strategy = st.one_of(
    # import <forbidden>
    forbidden_module_strategy.map(lambda m: f"import {m}"),
    # from <forbidden> import <name>
    forbidden_module_strategy.map(lambda m: f"from {m} import something"),
)

source_with_forbidden_strategy = st.tuples(
    # Some allowed imports
    st.lists(import_statement_strategy, min_size=0, max_size=3),
    # At least one forbidden import
    st.lists(forbidden_import_strategy, min_size=1, max_size=3),
).map(
    lambda pair: "\n".join(pair[0] + pair[1]) + "\n\nclass Comp:\n    pass\n"
)


@settings(max_examples=200, deadline=None)
@given(source=source_with_forbidden_strategy)
def test_property_17_forbidden_imports_detected(source: str):
    """Property 17: Sources with forbidden imports are detected.

    **Validates: Requirements 10.4, 10.5**

    For any generated source containing at least one import from {bpy, numpy,
    scipy, requests, ...}, the import checker SHALL report at least one
    forbidden import.
    """
    forbidden = check_forbidden_imports(source)
    assert len(forbidden) > 0, (
        f"Source with forbidden imports was NOT flagged. Source:\n{source}"
    )


# ---------------------------------------------------------------------------
# Property 17f (PBT): No bpy import in any component source variation
# ---------------------------------------------------------------------------

# Strategy: inject 'import bpy' or 'from bpy import ...' into a valid component
bpy_injection_strategy = st.sampled_from([
    "import bpy",
    "from bpy import data",
    "from bpy import types",
    "import bpy.types",
    "from bpy.types import Object",
])


@settings(max_examples=100, deadline=None)
@given(injection=bpy_injection_strategy)
def test_property_17_bpy_always_detected(injection: str):
    """Property 17: Any bpy import variant is always detected as forbidden.

    **Validates: Requirements 10.4, 10.5**

    For any form of bpy import statement, the checker SHALL detect it as
    forbidden regardless of import style (import X, from X import Y, etc).
    """
    source = f"{injection}\nimport bge\n\nclass Comp:\n    pass\n"
    forbidden = check_forbidden_imports(source)
    assert "bpy" in forbidden, (
        f"'bpy' import via '{injection}' was not detected. "
        f"Detected forbidden: {forbidden}"
    )
