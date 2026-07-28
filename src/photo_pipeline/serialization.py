"""Pipeline manifest JSON serialization with canonical format.

Provides lossless round-trip serialization for PipelineManifest and all
nested dataclass models. Uses the same canonical JSON format as the
existing WorldContract serialization (sorted keys, no whitespace, UTF-8).

Handles:
- Path objects → POSIX-style strings
- Enum values → their .value
- Tuples → JSON arrays (deserialized back as tuples)
- None → JSON null
- Recursive dataclass fields
"""

from __future__ import annotations

import dataclasses
import json
import math
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, get_type_hints

from src.photo_pipeline.models import (
    ObjectManifestEntry,
    PipelineManifest,
    StageResult,
)


class ManifestSerializationError(Exception):
    """Raised when serialization or deserialization fails."""


# ---------------------------------------------------------------------------
# Serialization: dataclass → canonical JSON bytes
# ---------------------------------------------------------------------------


def _normalize_value(value: Any) -> Any:
    """Recursively normalize a value into JSON-compatible primitives."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _normalize_value(getattr(value, f.name))
            for f in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ManifestSerializationError(
                "canonical JSON rejects non-finite float values"
            )
        return 0.0 if value == 0.0 else value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ManifestSerializationError(
        f"unsupported value type for serialization: {type(value).__name__}"
    )


def serialize_manifest(manifest: PipelineManifest) -> bytes:
    """Serialize a PipelineManifest to canonical JSON bytes.

    Uses sorted keys, no whitespace separators, UTF-8 encoding — matching
    the canonical format used by WorldContract serialization.
    """
    normalized = _normalize_value(manifest)
    try:
        text = json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ManifestSerializationError(
            f"manifest is not serializable to canonical JSON: {exc}"
        ) from exc
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Deserialization: canonical JSON bytes → PipelineManifest
# ---------------------------------------------------------------------------

# Type annotation cache for resolving field types during deserialization.
_TYPE_HINTS_CACHE: dict[type, dict[str, Any]] = {}


def _get_type_hints_cached(cls: type) -> dict[str, Any]:
    """Get resolved type hints for a dataclass, with caching."""
    if cls not in _TYPE_HINTS_CACHE:
        _TYPE_HINTS_CACHE[cls] = get_type_hints(cls)
    return _TYPE_HINTS_CACHE[cls]


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """Check if annotation is Optional[X] (i.e. X | None) and return (True, X)."""
    import types
    import typing

    origin = getattr(annotation, "__origin__", None)

    # Python 3.10+ pipe syntax: Path | None → types.UnionType (origin is None)
    if isinstance(annotation, types.UnionType):
        args = annotation.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return True, non_none[0]

    # typing.Optional[X] / typing.Union[X, None]
    if origin is typing.Union:
        args = annotation.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return True, non_none[0]

    return False, annotation


def _is_literal(annotation: Any) -> bool:
    """Check if annotation is a Literal type."""
    origin = getattr(annotation, "__origin__", None)
    import typing

    return origin is typing.Literal


def _get_tuple_element_types(annotation: Any) -> tuple[type, ...] | None:
    """If annotation is tuple[X, Y, ...], return the element types."""
    origin = getattr(annotation, "__origin__", None)
    if origin is tuple:
        args = getattr(annotation, "__args__", None)
        if args and args[-1] is not Ellipsis:
            return args
        if args and len(args) == 2 and args[-1] is Ellipsis:
            # tuple[X, ...] — variable length, return single type
            return args[:1]
    return None


def _get_list_element_type(annotation: Any) -> type | None:
    """If annotation is list[X], return X."""
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        args = getattr(annotation, "__args__", None)
        if args:
            return args[0]
    return None


def _get_dict_types(annotation: Any) -> tuple[type, type] | None:
    """If annotation is dict[K, V], return (K, V)."""
    origin = getattr(annotation, "__origin__", None)
    if origin is dict:
        args = getattr(annotation, "__args__", None)
        if args and len(args) == 2:
            return args[0], args[1]
    return None


def _reconstruct_value(value: Any, annotation: Any) -> Any:
    """Reconstruct a typed Python value from a JSON-decoded primitive."""
    if value is None:
        return None

    # Handle Optional[X]
    is_opt, inner_type = _is_optional(annotation)
    if is_opt:
        return _reconstruct_value(value, inner_type)

    # Handle Literal types — return the string value as-is
    if _is_literal(annotation):
        return value

    # Handle Path
    if annotation is Path or (isinstance(annotation, type) and issubclass(annotation, Path)):
        return Path(value)

    # Handle dataclass types
    if isinstance(annotation, type) and dataclasses.is_dataclass(annotation):
        return _reconstruct_dataclass(value, annotation)

    # Handle tuple[X, Y, ...]
    tuple_types = _get_tuple_element_types(annotation)
    if tuple_types is not None:
        if isinstance(value, list):
            if len(tuple_types) == 1:
                # tuple[X, ...] — variable length
                return tuple(
                    _reconstruct_value(item, tuple_types[0]) for item in value
                )
            return tuple(
                _reconstruct_value(item, t) for item, t in zip(value, tuple_types)
            )
        return value

    # Handle list[X]
    list_elem_type = _get_list_element_type(annotation)
    if list_elem_type is not None:
        if isinstance(value, list):
            return [_reconstruct_value(item, list_elem_type) for item in value]
        return value

    # Handle dict[K, V]
    dict_types = _get_dict_types(annotation)
    if dict_types is not None:
        key_type, val_type = dict_types
        if isinstance(value, dict):
            return {
                _reconstruct_value(k, key_type): _reconstruct_value(v, val_type)
                for k, v in value.items()
            }
        return value

    # Handle int/str coercion for dict keys
    if annotation is int and isinstance(value, str):
        return int(value)

    # Primitives (str, int, float, bool) — return as-is
    return value


def _reconstruct_dataclass(data: dict[str, Any], cls: type) -> Any:
    """Reconstruct a frozen dataclass instance from a dictionary."""
    hints = _get_type_hints_cached(cls)
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in data:
            kwargs[f.name] = _reconstruct_value(data[f.name], hints[f.name])
        # If field has a default and is missing from data, skip (dataclass handles it)
    return cls(**kwargs)


def deserialize_manifest(data: bytes) -> PipelineManifest:
    """Deserialize canonical JSON bytes back to a PipelineManifest.

    Reconstructs Path objects, tuples, and typed fields from the JSON
    representation. Ensures round-trip: deserialize(serialize(m)) == m.
    """
    try:
        raw = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestSerializationError(
            f"invalid manifest JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise ManifestSerializationError(
            f"expected JSON object at top level, got {type(raw).__name__}"
        )

    return _reconstruct_dataclass(raw, PipelineManifest)
