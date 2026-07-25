"""Canonical JSON serialization with strict validation constraints.

Implements Requirements 11.4 and 11.5:
- Rejects non-finite numbers (NaN, Infinity, -Infinity)
- Sorts keys lexicographically
- Uses no-whitespace separators (',' and ':')
- Encodes to UTF-8
- Deserialization raises validation error identifying the first non-conforming element
"""

from __future__ import annotations

import json
import math
from enum import Enum
from typing import Any, Mapping, Sequence, Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class CanonicalSerializationError(ValueError):
    """Raised when serialization encounters a non-canonical value."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        full_message = f"{message} at {path}" if path else message
        super().__init__(full_message)


class DeserializationError(ValueError):
    """Raised when deserialization encounters non-conforming input.

    Identifies the first non-conforming element rather than silently coercing.
    """

    def __init__(
        self,
        message: str,
        *,
        element: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.element = element
        self.reason = reason
        parts = []
        if element:
            parts.append(f"element={element!r}")
        if reason:
            parts.append(f"reason={reason!r}")
        detail = f" ({', '.join(parts)})" if parts else ""
        super().__init__(f"{message}{detail}")


def _check_value(value: Any, path: str = "$") -> Any:
    """Recursively validate and normalize a value for canonical JSON.

    Raises CanonicalSerializationError for non-finite numbers.
    Returns normalized value suitable for json.dumps.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalSerializationError(
                f"non-finite number ({value!r}) rejected", path=path
            )
        # Normalize -0.0 to 0.0
        return 0.0 if value == 0.0 else value
    if isinstance(value, str):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(k): _check_value(v, path=f"{path}.{k}")
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _check_value(item, path=f"{path}[{i}]")
            for i, item in enumerate(value)
        ]
    if isinstance(value, BaseModel):
        return _check_value(value.model_dump(mode="json"), path=path)
    raise CanonicalSerializationError(
        f"unsupported type {type(value).__name__}", path=path
    )


def canonical_serialize(value: Any) -> bytes:
    """Serialize a value to canonical JSON bytes.

    Constraints enforced (Req 11.4):
    - Non-finite numbers (NaN, Infinity, -Infinity) are rejected
    - Keys are sorted lexicographically
    - Separators are ',' and ':' (no whitespace)
    - Output is UTF-8 encoded

    Parameters:
        value: A Pydantic model, dict, list, or primitive value to serialize.

    Returns:
        UTF-8 encoded canonical JSON bytes.

    Raises:
        CanonicalSerializationError: If the value contains non-finite numbers
            or unsupported types.
    """
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    normalized = _check_value(value)
    try:
        text = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalSerializationError(
            f"value is not serializable: {exc}"
        ) from exc
    return text.encode("utf-8")


def canonical_deserialize(
    data: bytes | str,
    model: Type[T],
) -> T:
    """Deserialize canonical JSON bytes into a Pydantic model with strict validation.

    Constraints enforced (Req 11.5):
    - Missing required fields raise DeserializationError
    - Unknown fields raise DeserializationError (when model forbids extras)
    - Type mismatches raise DeserializationError
    - The FIRST non-conforming element is identified in the error

    Parameters:
        data: UTF-8 encoded JSON bytes or a JSON string.
        model: The Pydantic model class to validate against.

    Returns:
        A validated instance of the model.

    Raises:
        DeserializationError: If the input does not conform to the schema.
    """
    # Decode bytes to string if needed
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DeserializationError(
                "input is not valid UTF-8",
                element="<root>",
                reason=str(exc),
            ) from exc
    else:
        text = data

    # Parse JSON
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeserializationError(
            "input is not valid JSON",
            element=f"char {exc.pos}",
            reason=exc.msg,
        ) from exc

    # Check that the payload is a mapping (object) for model validation
    if not isinstance(payload, dict):
        raise DeserializationError(
            "expected a JSON object at top level",
            element="<root>",
            reason=f"got {type(payload).__name__}",
        )

    # Validate via Pydantic — this catches missing fields, unknown fields,
    # type mismatches, and constraint violations
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        # Extract the first error to identify the non-conforming element
        first_error = exc.errors()[0]
        location = ".".join(str(loc) for loc in first_error["loc"])
        error_type = first_error["type"]
        error_msg = first_error["msg"]
        raise DeserializationError(
            f"validation failed: {error_msg}",
            element=location or "<root>",
            reason=error_type,
        ) from exc


def validate_canonical_format(data: bytes) -> None:
    """Validate that bytes are in canonical JSON format.

    Checks:
    - Valid UTF-8
    - Valid JSON
    - No non-finite numbers
    - Keys are sorted
    - Separators are ',' and ':' (no whitespace between tokens)

    Raises:
        CanonicalSerializationError: If the format is not canonical.
    """
    # Check UTF-8
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CanonicalSerializationError(
            "not valid UTF-8", path="<encoding>"
        ) from exc

    # Parse JSON
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CanonicalSerializationError(
            f"not valid JSON: {exc.msg}", path=f"char {exc.pos}"
        ) from exc

    # Check non-finite numbers by re-serializing and comparing
    _check_value(parsed)

    # Verify canonical format: re-serialize and compare bytes
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    )
    if canonical != text:
        # Find the first difference to identify the location
        for i, (a, b) in enumerate(zip(text, canonical)):
            if a != b:
                context = text[max(0, i - 10):i + 20]
                raise CanonicalSerializationError(
                    f"not canonical format near position {i}: "
                    f"found {a!r}, expected {b!r} (context: {context!r})",
                    path=f"char {i}",
                )
        # Length differs
        if len(text) != len(canonical):
            raise CanonicalSerializationError(
                "not canonical format: trailing content",
                path=f"char {min(len(text), len(canonical))}",
            )
