"""Property-based tests for deserialization validation errors (Property 16).

**Validates: Requirements 11.5**

Property 16: Deserialization Validation Errors
- Non-conforming bytes raise validation error with identified element, never silently coerce
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, settings, assume, strategies as st
from pydantic import BaseModel, ConfigDict

from src.canonical_serialization import (
    DeserializationError,
    canonical_deserialize,
)


# ---------------------------------------------------------------------------
# Test models
# ---------------------------------------------------------------------------


class StrictModel(BaseModel):
    """A model with required fields, extra=forbid, and strict=True for testing.

    strict=True ensures Pydantic won't silently coerce types (e.g. bool→int).
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    age: int
    active: bool
    tags: list[str]


class SimpleModel(BaseModel):
    """A simpler model with required fields (allows extra by default)."""

    model_config = ConfigDict(strict=True)

    title: str
    count: int


class NestedModel(BaseModel):
    """A model with nested structure and extra=forbid."""

    model_config = ConfigDict(extra="forbid", strict=True)

    label: str
    value: int
    inner: SimpleModel


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "Nd"), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=10,
)

_valid_strict_model_data = st.fixed_dictionaries({
    "name": _safe_text,
    "age": st.integers(min_value=0, max_value=200),
    "active": st.booleans(),
    "tags": st.lists(_safe_text, min_size=0, max_size=5),
})


@st.composite
def valid_strict_json_bytes(draw: st.DrawFn) -> bytes:
    """Generate valid JSON bytes conforming to StrictModel."""
    data = draw(_valid_strict_model_data)
    return json.dumps(data).encode("utf-8")


@st.composite
def strict_model_missing_field(draw: st.DrawFn) -> tuple[bytes, str]:
    """Generate JSON bytes with one required field removed from StrictModel.

    Returns (modified_bytes, removed_field_name).
    """
    data = draw(_valid_strict_model_data)
    fields = list(data.keys())
    field_to_remove = draw(st.sampled_from(fields))
    del data[field_to_remove]
    return json.dumps(data).encode("utf-8"), field_to_remove


@st.composite
def strict_model_extra_field(draw: st.DrawFn) -> tuple[bytes, str]:
    """Generate JSON bytes with an unknown extra field added to StrictModel.

    Returns (modified_bytes, extra_field_name).
    """
    data = draw(_valid_strict_model_data)
    # Generate a field name that is NOT one of the known fields
    known_fields = {"name", "age", "active", "tags"}
    extra_field = draw(_safe_text.filter(lambda x: x not in known_fields))
    assume(extra_field not in known_fields)
    data[extra_field] = draw(st.one_of(st.integers(), _safe_text, st.booleans()))
    return json.dumps(data).encode("utf-8"), extra_field


# Type mismatch strategies: replace a field value with an incompatible type
_type_incompatible: dict[str, st.SearchStrategy] = {
    "name": st.one_of(st.integers(), st.booleans(), st.lists(st.integers(), max_size=2)),
    "age": st.one_of(_safe_text, st.booleans(), st.lists(st.integers(), max_size=2)),
    "active": st.one_of(st.integers(), _safe_text, st.lists(st.integers(), max_size=2)),
    "tags": st.one_of(st.integers(), _safe_text, st.booleans()),
}


@st.composite
def strict_model_type_mismatch(draw: st.DrawFn) -> tuple[bytes, str]:
    """Generate JSON bytes with one field value replaced with an incompatible type.

    Returns (modified_bytes, field_with_wrong_type).
    """
    data = draw(_valid_strict_model_data)
    field_to_corrupt = draw(st.sampled_from(list(_type_incompatible.keys())))
    data[field_to_corrupt] = draw(_type_incompatible[field_to_corrupt])
    return json.dumps(data).encode("utf-8"), field_to_corrupt


# ---------------------------------------------------------------------------
# Property 16a: Missing required fields raise DeserializationError
# ---------------------------------------------------------------------------


@given(data=strict_model_missing_field())
@settings(max_examples=200)
def test_property_16a_missing_required_field(data: tuple[bytes, str]):
    """Property 16a: Missing required fields raise DeserializationError.

    **Validates: Requirements 11.5**

    For any Pydantic model with required fields, if any required field is removed
    from valid JSON input, canonical_deserialize SHALL raise DeserializationError
    with the missing field identified in element.
    """
    json_bytes, removed_field = data

    with pytest.raises(DeserializationError) as exc_info:
        canonical_deserialize(json_bytes, StrictModel)

    error = exc_info.value
    assert error.element is not None, "element must be set on DeserializationError"
    assert removed_field in error.element, (
        f"Expected element to identify '{removed_field}', got '{error.element}'"
    )


# ---------------------------------------------------------------------------
# Property 16b: Unknown/extra fields raise DeserializationError
# ---------------------------------------------------------------------------


@given(data=strict_model_extra_field())
@settings(max_examples=200)
def test_property_16b_unknown_extra_field(data: tuple[bytes, str]):
    """Property 16b: Unknown/extra fields raise DeserializationError.

    **Validates: Requirements 11.5**

    For any Pydantic model configured with extra="forbid", if an unknown field
    is added to valid JSON, canonical_deserialize SHALL raise DeserializationError
    with the unknown field identified in element.
    """
    json_bytes, extra_field = data

    with pytest.raises(DeserializationError) as exc_info:
        canonical_deserialize(json_bytes, StrictModel)

    error = exc_info.value
    assert error.element is not None, "element must be set on DeserializationError"
    assert extra_field in error.element, (
        f"Expected element to identify '{extra_field}', got '{error.element}'"
    )


# ---------------------------------------------------------------------------
# Property 16c: Type mismatches raise DeserializationError
# ---------------------------------------------------------------------------


@given(data=strict_model_type_mismatch())
@settings(max_examples=200)
def test_property_16c_type_mismatch(data: tuple[bytes, str]):
    """Property 16c: Type mismatches raise DeserializationError.

    **Validates: Requirements 11.5**

    For any required field of a specific type (int, str, bool, list), if the value
    is replaced with an incompatible type, canonical_deserialize SHALL raise
    DeserializationError with the field identified in element.
    """
    json_bytes, corrupted_field = data

    with pytest.raises(DeserializationError) as exc_info:
        canonical_deserialize(json_bytes, StrictModel)

    error = exc_info.value
    assert error.element is not None, "element must be set on DeserializationError"
    assert corrupted_field in error.element, (
        f"Expected element to identify '{corrupted_field}', got '{error.element}'"
    )


# ---------------------------------------------------------------------------
# Property 16d: Invalid UTF-8 bytes raise DeserializationError
# ---------------------------------------------------------------------------


@given(
    data=st.binary(min_size=1, max_size=100).filter(
        lambda b: _is_invalid_utf8(b)
    )
)
@settings(max_examples=200)
def test_property_16d_invalid_utf8(data: bytes):
    """Property 16d: Invalid UTF-8 bytes raise DeserializationError.

    **Validates: Requirements 11.5**

    For any non-UTF-8 byte sequences, canonical_deserialize SHALL raise
    DeserializationError.
    """
    with pytest.raises(DeserializationError) as exc_info:
        canonical_deserialize(data, StrictModel)

    error = exc_info.value
    assert error.element is not None, "element must be set on DeserializationError"


def _is_invalid_utf8(data: bytes) -> bool:
    """Return True if the bytes cannot be decoded as UTF-8."""
    try:
        data.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


# ---------------------------------------------------------------------------
# Property 16e: Invalid JSON syntax raises DeserializationError
# ---------------------------------------------------------------------------


@st.composite
def invalid_json_bytes(draw: st.DrawFn) -> bytes:
    """Generate bytes that are valid UTF-8 but not valid JSON."""
    strategy = draw(st.sampled_from([
        "truncated_object",
        "trailing_comma",
        "missing_quotes",
        "unbalanced_braces",
        "random_text",
    ]))

    if strategy == "truncated_object":
        # Valid start but truncated
        data = draw(_valid_strict_model_data)
        full_json = json.dumps(data)
        cut_at = draw(st.integers(min_value=1, max_value=max(1, len(full_json) - 2)))
        return full_json[:cut_at].encode("utf-8")
    elif strategy == "trailing_comma":
        return b'{"name": "test", "age": 5,}'
    elif strategy == "missing_quotes":
        return b'{name: "test", age: 5}'
    elif strategy == "unbalanced_braces":
        data = draw(_valid_strict_model_data)
        full_json = json.dumps(data)
        # Remove the closing brace
        return full_json[:-1].encode("utf-8")
    else:
        # Random non-JSON text
        text = draw(_safe_text.filter(lambda t: not _is_valid_json(t)))
        return text.encode("utf-8")


def _is_valid_json(text: str) -> bool:
    """Return True if the text is valid JSON."""
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


@given(data=invalid_json_bytes())
@settings(max_examples=200)
def test_property_16e_invalid_json_syntax(data: bytes):
    """Property 16e: Invalid JSON syntax raises DeserializationError.

    **Validates: Requirements 11.5**

    For any bytes that are valid UTF-8 but not valid JSON, canonical_deserialize
    SHALL raise DeserializationError.
    """
    # Verify precondition: it's valid UTF-8 but not valid JSON
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        assume(False)
        return

    try:
        json.loads(text)
        # If it's valid JSON, skip this example
        assume(False)
    except json.JSONDecodeError:
        pass

    with pytest.raises(DeserializationError) as exc_info:
        canonical_deserialize(data, StrictModel)

    error = exc_info.value
    assert error.element is not None, "element must be set on DeserializationError"


# ---------------------------------------------------------------------------
# Property 16f: Never silently coerce
# ---------------------------------------------------------------------------


@st.composite
def mutated_strict_model_data(draw: st.DrawFn) -> tuple[dict, dict, str]:
    """Generate valid StrictModel data and a single mutation.

    Returns (original_data, mutated_data, mutation_type).
    Mutation types: 'remove_field', 'add_field', 'change_type'
    """
    original = draw(_valid_strict_model_data)
    mutation_type = draw(st.sampled_from(["remove_field", "add_field", "change_type"]))

    mutated = dict(original)

    if mutation_type == "remove_field":
        field = draw(st.sampled_from(list(mutated.keys())))
        del mutated[field]
    elif mutation_type == "add_field":
        known_fields = {"name", "age", "active", "tags"}
        extra_field = draw(_safe_text.filter(lambda x: x not in known_fields))
        assume(extra_field not in known_fields)
        mutated[extra_field] = draw(st.one_of(st.integers(), _safe_text))
    else:  # change_type
        field = draw(st.sampled_from(list(_type_incompatible.keys())))
        mutated[field] = draw(_type_incompatible[field])

    return original, mutated, mutation_type


@given(data=mutated_strict_model_data())
@settings(max_examples=200)
def test_property_16f_never_silently_coerce(data: tuple[dict, dict, str]):
    """Property 16f: Never silently coerce.

    **Validates: Requirements 11.5**

    For any valid model and valid JSON with one mutation (type change, field
    removal, field addition on extra=forbid model), the function either raises
    DeserializationError OR produces an instance equal to what would be produced
    from the original valid data (no partial/silent coercion).
    """
    original_data, mutated_data, mutation_type = data
    mutated_bytes = json.dumps(mutated_data).encode("utf-8")

    # Get the reference instance from the original valid data
    original_bytes = json.dumps(original_data).encode("utf-8")
    reference = canonical_deserialize(original_bytes, StrictModel)

    try:
        result = canonical_deserialize(mutated_bytes, StrictModel)
    except DeserializationError:
        # Correctly raised error — this is fine
        return

    # If no error was raised, the result must be equal to the reference
    # (i.e., the mutation had no semantic effect — not a silent coercion)
    assert result == reference, (
        f"Silent coercion detected! Mutation type: {mutation_type}. "
        f"Original data: {original_data}, Mutated data: {mutated_data}, "
        f"Reference: {reference}, Got: {result}"
    )
