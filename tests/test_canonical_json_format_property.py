"""Property-based tests for canonical JSON format constraints (Property 15).

**Validates: Requirements 11.4**

Property 15: Canonical JSON Format Constraints
- Non-finite numbers (NaN, Infinity, -Infinity) SHALL be rejected with an error
- Output keys SHALL be sorted lexicographically
- Separators SHALL be ',' and ':' with no whitespace
- Encoding SHALL be UTF-8
"""

from __future__ import annotations

import json
import math
import re

import pytest
from hypothesis import given, settings, assume, strategies as st

from src.canonical_serialization import (
    CanonicalSerializationError,
    canonical_serialize,
    validate_canonical_format,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Finite floats for valid cases
_finite_float = st.floats(allow_nan=False, allow_infinity=False)

# Non-finite float values
_non_finite_float = st.sampled_from([float("nan"), float("inf"), float("-inf")])

# Safe text keys (printable ASCII to avoid JSON encoding edge cases)
_safe_key = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Nd"), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=10,
)

# Simple JSON-serializable leaf values (no non-finite floats)
_leaf_value = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    _finite_float,
    st.text(min_size=0, max_size=20),
)


@st.composite
def nested_dict_with_non_finite(draw: st.DrawFn) -> dict:
    """Generate a dict that contains at least one non-finite float at some depth."""
    depth = draw(st.integers(min_value=0, max_value=3))
    non_finite = draw(_non_finite_float)

    # Build a nested structure that ends with the non-finite value
    value: object = non_finite
    for _ in range(depth):
        wrapper_type = draw(st.sampled_from(["dict", "list"]))
        if wrapper_type == "dict":
            key = draw(_safe_key)
            value = {key: value}
        else:
            value = [value]

    # Wrap in a top-level dict if not already one
    if not isinstance(value, dict):
        value = {"data": value}

    return value


@st.composite
def valid_dict_with_random_keys(draw: st.DrawFn) -> dict:
    """Generate a dict with multiple random string keys and valid values."""
    num_keys = draw(st.integers(min_value=2, max_value=8))
    keys = draw(
        st.lists(_safe_key, min_size=num_keys, max_size=num_keys, unique=True)
    )
    values = draw(st.lists(_leaf_value, min_size=num_keys, max_size=num_keys))
    return dict(zip(keys, values))


@st.composite
def nested_dict_with_random_keys(draw: st.DrawFn) -> dict:
    """Generate nested dicts with random keys at multiple levels."""
    outer = draw(valid_dict_with_random_keys())
    # Add a nested dict with its own random keys
    inner_keys = draw(st.lists(_safe_key, min_size=2, max_size=4, unique=True))
    inner_values = draw(st.lists(_leaf_value, min_size=len(inner_keys), max_size=len(inner_keys)))
    inner_dict = dict(zip(inner_keys, inner_values))
    # Attach the inner dict under a new key
    attach_key = draw(_safe_key)
    outer[attach_key] = inner_dict
    return outer


@st.composite
def valid_serializable_value(draw: st.DrawFn) -> object:
    """Generate any valid JSON-serializable value (no non-finite floats)."""
    return draw(st.one_of(
        _leaf_value,
        valid_dict_with_random_keys(),
        st.lists(_leaf_value, min_size=0, max_size=5),
        nested_dict_with_random_keys(),
    ))


@st.composite
def non_canonical_json_bytes(draw: st.DrawFn) -> bytes:
    """Generate valid JSON bytes that are NOT in canonical format.

    Produces JSON with either unsorted keys or extra whitespace.
    """
    strategy_choice = draw(st.sampled_from(["unsorted_keys", "extra_whitespace"]))

    if strategy_choice == "unsorted_keys":
        # Create a dict with at least 2 keys that would be in different order
        keys = draw(st.lists(_safe_key, min_size=2, max_size=5, unique=True))
        values = draw(st.lists(
            st.one_of(st.integers(min_value=0, max_value=100), st.text(min_size=1, max_size=5)),
            min_size=len(keys),
            max_size=len(keys),
        ))
        d = dict(zip(keys, values))
        sorted_keys = sorted(d.keys())
        # Only proceed if keys are not already sorted (otherwise it would be canonical)
        assume(list(d.keys()) != sorted_keys)
        # Serialize WITHOUT sort_keys to preserve insertion order
        text = json.dumps(d, separators=(",", ":"), ensure_ascii=False)
        return text.encode("utf-8")
    else:
        # extra_whitespace: use standard json.dumps with spaces
        d = draw(valid_dict_with_random_keys())
        # Use indent or space-after-colon to make it non-canonical
        text = json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False)
        return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Property 15a: Non-finite numbers are rejected
# ---------------------------------------------------------------------------


@given(data=nested_dict_with_non_finite())
@settings(max_examples=200)
def test_property_15a_non_finite_numbers_rejected(data: dict):
    """Property 15a: Non-finite numbers (NaN, Infinity, -Infinity) are rejected.

    **Validates: Requirements 11.4**

    For any data structure containing a non-finite float at any nesting depth,
    canonical_serialize SHALL raise CanonicalSerializationError.
    """
    with pytest.raises(CanonicalSerializationError):
        canonical_serialize(data)


# ---------------------------------------------------------------------------
# Property 15b: Keys are sorted lexicographically
# ---------------------------------------------------------------------------


def _keys_are_sorted(obj: object) -> bool:
    """Recursively check that all dict keys are in sorted order."""
    if isinstance(obj, dict):
        keys = list(obj.keys())
        if keys != sorted(keys):
            return False
        return all(_keys_are_sorted(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_keys_are_sorted(item) for item in obj)
    return True


@given(data=nested_dict_with_random_keys())
@settings(max_examples=200)
def test_property_15b_keys_sorted_lexicographically(data: dict):
    """Property 15b: Output keys are sorted lexicographically at every level.

    **Validates: Requirements 11.4**

    For any dict with random string keys (possibly nested), the canonical JSON
    output SHALL have keys in lexicographic order at every nesting level.
    """
    serialized = canonical_serialize(data)
    # Parse the output back and check key ordering
    parsed = json.loads(serialized.decode("utf-8"))
    assert _keys_are_sorted(parsed), (
        f"Keys are not sorted in canonical output: {serialized!r}"
    )


# ---------------------------------------------------------------------------
# Property 15c: Separators are ',' and ':' (no whitespace)
# ---------------------------------------------------------------------------


@given(data=valid_serializable_value())
@settings(max_examples=200)
def test_property_15c_no_whitespace_separators(data: object):
    """Property 15c: Separators are ',' and ':' with no whitespace.

    **Validates: Requirements 11.4**

    For any valid serializable value, the canonical JSON output SHALL NOT
    contain ': ' (colon-space) or ', ' (comma-space) outside of string values.
    The separators used are ':' and ',' with no surrounding whitespace.
    """
    serialized = canonical_serialize(data)
    text = serialized.decode("utf-8")

    # Remove string literals before checking for whitespace separators
    # This avoids false positives from strings containing ": " or ", "
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)

    assert ": " not in stripped, (
        f"Found ': ' (colon-space) in non-string portion of output: {text!r}"
    )
    assert ", " not in stripped, (
        f"Found ', ' (comma-space) in non-string portion of output: {text!r}"
    )


# ---------------------------------------------------------------------------
# Property 15d: Output is always UTF-8 encoded bytes
# ---------------------------------------------------------------------------


@given(data=valid_serializable_value())
@settings(max_examples=200)
def test_property_15d_output_is_utf8_bytes(data: object):
    """Property 15d: Output is always bytes and always valid UTF-8.

    **Validates: Requirements 11.4**

    For any valid serializable value, canonical_serialize SHALL return bytes
    that decode successfully as UTF-8 without errors.
    """
    serialized = canonical_serialize(data)

    # Must be bytes
    assert isinstance(serialized, bytes), (
        f"Expected bytes output, got {type(serialized).__name__}"
    )

    # Must decode as valid UTF-8
    try:
        serialized.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(f"Output is not valid UTF-8: {exc}")


# ---------------------------------------------------------------------------
# Property 15e: validate_canonical_format rejects non-canonical input
# ---------------------------------------------------------------------------


@given(data=non_canonical_json_bytes())
@settings(max_examples=200)
def test_property_15e_validate_rejects_non_canonical(data: bytes):
    """Property 15e: validate_canonical_format rejects non-canonical JSON.

    **Validates: Requirements 11.4**

    For any bytes that are valid JSON but NOT in canonical format (unsorted
    keys or extra whitespace), validate_canonical_format SHALL raise
    CanonicalSerializationError.
    """
    # Confirm the input is valid JSON
    try:
        json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        assume(False)

    with pytest.raises(CanonicalSerializationError):
        validate_canonical_format(data)
