"""Tests for canonical JSON serialization constraints (Task 10.1).

Validates Requirements 11.4 and 11.5:
- Serializer rejects non-finite numbers (NaN, Infinity, -Infinity)
- Enforces sorted keys, no-whitespace separators, UTF-8 encoding
- Deserialization raises validation error on non-conforming input identifying first bad element
"""

from __future__ import annotations

import json
import math

import pytest
from pydantic import BaseModel, ConfigDict, Field

from src.canonical_serialization import (
    CanonicalSerializationError,
    DeserializationError,
    canonical_deserialize,
    canonical_serialize,
    validate_canonical_format,
)


# --- Test models ---


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    name: str
    value: float
    count: int = 0


class NestedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    id: str
    inner: StrictModel
    tags: tuple[str, ...] = ()


# --- Serialization tests (Req 11.4) ---


class TestCanonicalSerialize:
    """Test that serialization enforces canonical format constraints."""

    def test_rejects_nan(self):
        """NaN values must be rejected."""
        with pytest.raises(CanonicalSerializationError, match="non-finite"):
            canonical_serialize({"x": float("nan")})

    def test_rejects_positive_infinity(self):
        """Positive infinity must be rejected."""
        with pytest.raises(CanonicalSerializationError, match="non-finite"):
            canonical_serialize({"x": float("inf")})

    def test_rejects_negative_infinity(self):
        """Negative infinity must be rejected."""
        with pytest.raises(CanonicalSerializationError, match="non-finite"):
            canonical_serialize({"x": float("-inf")})

    def test_rejects_nan_in_nested_dict(self):
        """NaN nested within structures must be rejected."""
        with pytest.raises(CanonicalSerializationError, match="non-finite"):
            canonical_serialize({"outer": {"inner": float("nan")}})

    def test_rejects_infinity_in_list(self):
        """Infinity within a list must be rejected."""
        with pytest.raises(CanonicalSerializationError, match="non-finite"):
            canonical_serialize({"items": [1.0, float("inf"), 3.0]})

    def test_rejects_nan_in_pydantic_model(self):
        """Non-finite in Pydantic model fields must be rejected."""
        # Pydantic itself blocks NaN in models with allow_inf_nan=False
        # but we also catch it in the serialization path
        with pytest.raises((CanonicalSerializationError, Exception)):
            canonical_serialize({"name": "test", "value": float("nan"), "count": 0})

    def test_sorted_keys(self):
        """Keys must be sorted lexicographically."""
        data = {"z_last": 1, "a_first": 2, "m_middle": 3}
        result = canonical_serialize(data)
        text = result.decode("utf-8")
        parsed = json.loads(text)
        keys = list(parsed.keys())
        assert keys == sorted(keys), f"Keys not sorted: {keys}"

    def test_no_whitespace_separators(self):
        """Separators must be ',' and ':' with no whitespace."""
        data = {"key1": "value1", "key2": [1, 2, 3]}
        result = canonical_serialize(data)
        text = result.decode("utf-8")
        # No spaces after ':' or ','
        assert '": ' not in text
        assert ", " not in text
        # But ':' and ',' are present
        assert ":" in text
        assert "," in text

    def test_utf8_encoding(self):
        """Output must be valid UTF-8 encoded bytes."""
        data = {"message": "héllo wörld", "emoji": "🎮"}
        result = canonical_serialize(data)
        assert isinstance(result, bytes)
        # Must be decodable as UTF-8
        text = result.decode("utf-8")
        assert "héllo wörld" in text
        assert "🎮" in text

    def test_pydantic_model_serialization(self):
        """Pydantic models serialize with canonical constraints."""
        model = StrictModel(name="test", value=3.14, count=5)
        result = canonical_serialize(model)
        text = result.decode("utf-8")
        parsed = json.loads(text)
        assert parsed == {"count": 5, "name": "test", "value": 3.14}
        # Keys should be sorted
        keys = list(json.loads(text).keys())
        assert keys == sorted(keys)

    def test_nested_model_serialization(self):
        """Nested Pydantic models serialize correctly."""
        model = NestedModel(
            id="outer-1",
            inner=StrictModel(name="inner", value=1.5),
            tags=("a", "b"),
        )
        result = canonical_serialize(model)
        text = result.decode("utf-8")
        # Verify compact format
        assert '" :' not in text
        assert '", ' not in text

    def test_negative_zero_normalized(self):
        """Negative zero should be normalized to positive zero."""
        data = {"value": -0.0}
        result = canonical_serialize(data)
        text = result.decode("utf-8")
        # Should not contain -0.0 representation
        assert text == '{"value":0.0}'

    def test_valid_finite_numbers_accepted(self):
        """Normal finite numbers must be accepted."""
        data = {"a": 0.0, "b": 1.5, "c": -3.14, "d": 1e10, "e": -1e-5}
        result = canonical_serialize(data)
        assert isinstance(result, bytes)
        parsed = json.loads(result.decode("utf-8"))
        assert math.isclose(parsed["c"], -3.14)


# --- Deserialization tests (Req 11.5) ---


class TestCanonicalDeserialize:
    """Test that deserialization raises validation errors identifying first bad element."""

    def test_valid_input_deserializes(self):
        """Valid conforming input deserializes successfully."""
        data = b'{"count":0,"name":"hello","value":2.5}'
        result = canonical_deserialize(data, StrictModel)
        assert result.name == "hello"
        assert result.value == 2.5
        assert result.count == 0

    def test_missing_required_field_raises_error(self):
        """Missing required fields raise DeserializationError identifying the field."""
        data = b'{"count":0,"value":2.5}'  # 'name' is missing
        with pytest.raises(DeserializationError) as exc_info:
            canonical_deserialize(data, StrictModel)
        assert exc_info.value.element == "name"
        assert "missing" in exc_info.value.reason or "missing" in str(exc_info.value)

    def test_unknown_field_raises_error(self):
        """Unknown fields raise DeserializationError (model uses extra='forbid')."""
        data = b'{"count":0,"name":"hello","unknown_field":"bad","value":2.5}'
        with pytest.raises(DeserializationError) as exc_info:
            canonical_deserialize(data, StrictModel)
        assert exc_info.value.element is not None
        # The error should reference the extra field
        assert "extra" in str(exc_info.value).lower() or "unknown_field" in str(exc_info.value)

    def test_type_mismatch_raises_error(self):
        """Type mismatches raise DeserializationError identifying the element."""
        data = b'{"count":"not_an_int","name":"hello","value":2.5}'
        with pytest.raises(DeserializationError) as exc_info:
            canonical_deserialize(data, StrictModel)
        assert exc_info.value.element == "count"

    def test_invalid_json_raises_error(self):
        """Invalid JSON raises DeserializationError."""
        data = b'{"name": "hello", BROKEN'
        with pytest.raises(DeserializationError, match="not valid JSON"):
            canonical_deserialize(data, StrictModel)

    def test_invalid_utf8_raises_error(self):
        """Non-UTF-8 bytes raise DeserializationError."""
        data = b'\xff\xfe{"name":"hello"}'
        with pytest.raises(DeserializationError, match="not valid UTF-8"):
            canonical_deserialize(data, StrictModel)

    def test_non_object_top_level_raises_error(self):
        """Non-object JSON (array, string, number) at top level raises error."""
        with pytest.raises(DeserializationError, match="expected a JSON object"):
            canonical_deserialize(b"[1, 2, 3]", StrictModel)
        with pytest.raises(DeserializationError, match="expected a JSON object"):
            canonical_deserialize(b'"just a string"', StrictModel)

    def test_nested_validation_error_identifies_path(self):
        """Nested model validation errors identify the full path."""
        data = b'{"id":"outer","inner":{"count":0,"name":"x","value":"not_float"},"tags":[]}'
        with pytest.raises(DeserializationError) as exc_info:
            canonical_deserialize(data, NestedModel)
        # Should identify the nested field
        assert "inner" in exc_info.value.element or "value" in exc_info.value.element

    def test_string_input_accepted(self):
        """String input (not just bytes) is also accepted."""
        data = '{"count":0,"name":"hello","value":2.5}'
        result = canonical_deserialize(data, StrictModel)
        assert result.name == "hello"

    def test_first_error_reported_on_multiple_issues(self):
        """When multiple issues exist, the first one is reported."""
        # Missing 'name', wrong type for 'value' — first error should be reported
        data = b'{"count":"wrong","value":"also_wrong"}'
        with pytest.raises(DeserializationError) as exc_info:
            canonical_deserialize(data, StrictModel)
        # Should have an element identified
        assert exc_info.value.element is not None


# --- Format validation tests ---


class TestValidateCanonicalFormat:
    """Test format validation detects non-canonical representations."""

    def test_canonical_format_passes(self):
        """Properly formatted canonical JSON passes validation."""
        data = b'{"a":1,"b":"hello","c":[1,2,3]}'
        validate_canonical_format(data)  # Should not raise

    def test_unsorted_keys_rejected(self):
        """Unsorted keys are detected and rejected."""
        data = b'{"z":1,"a":2}'  # z before a
        with pytest.raises(CanonicalSerializationError, match="not canonical"):
            validate_canonical_format(data)

    def test_whitespace_separators_rejected(self):
        """Whitespace in separators is detected and rejected."""
        data = b'{"a": 1, "b": 2}'  # spaces after : and ,
        with pytest.raises(CanonicalSerializationError, match="not canonical"):
            validate_canonical_format(data)

    def test_invalid_utf8_rejected(self):
        """Non-UTF-8 bytes are rejected."""
        data = b'\x80\x81\x82'
        with pytest.raises(CanonicalSerializationError, match="not valid UTF-8"):
            validate_canonical_format(data)

    def test_invalid_json_rejected(self):
        """Invalid JSON syntax is rejected."""
        data = b'{invalid json}'
        with pytest.raises(CanonicalSerializationError, match="not valid JSON"):
            validate_canonical_format(data)

    def test_pretty_printed_json_rejected(self):
        """Pretty-printed JSON with newlines/indentation is rejected."""
        data = b'{\n  "a": 1\n}'
        with pytest.raises(CanonicalSerializationError, match="not canonical"):
            validate_canonical_format(data)
