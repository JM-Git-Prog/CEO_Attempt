"""Property-based tests for Asset Registry JSON round-trip serialization.

# Feature: photo-to-real-3d-world-v14

## Property 16: Asset Registry JSON Round-Trip

**Validates: Requirements 15.1, 15.5**

For any valid AssetRegistryEntry, serializing to JSON (sorted keys, 2-space
indent, UTF-8) then deserializing SHALL produce a structurally equal object
where every field value compares equal.

Additionally, serialize → deserialize → serialize produces identical bytes
(idempotent canonical form).

Uses Hypothesis with custom strategies to generate diverse AssetRegistryEntry
instances covering:
- All valid categories (props, architecture, foliage, hard-surface, set-dressing)
- All valid materials (wood, metal, glass, fabric, ceramic, plastic)
- All valid conditions (new, worn, broken)
- Both generation methods (hunyuan3d_v2.1, trellis2)
- Diverse dimensions, weights, face/vertex counts
- Various name formats, era strings, session IDs
- ISO timestamp strings
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.models_v14 import (
    AssetRegistryEntry,
    VALID_CATEGORIES,
    VALID_CONDITIONS,
    VALID_MATERIALS,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe text: no null bytes or surrogates (JSON-safe), non-empty
_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude surrogates
        blacklist_characters=("\x00",),
    ),
    min_size=1,
    max_size=40,
)

# Categories, materials, conditions from the model's valid sets
_categories = st.sampled_from(list(VALID_CATEGORIES))
_materials = st.sampled_from(list(VALID_MATERIALS))
_conditions = st.sampled_from(list(VALID_CONDITIONS))

# Generation methods: only hunyuan3d_v2.1 and trellis2 (not placeholder)
_generation_methods = st.sampled_from(["hunyuan3d_v2.1", "trellis2"])

# Positive floats for dimensions (must be > 0)
_positive_floats = st.floats(
    min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False
)

# Non-negative floats for weight
_non_negative_floats = st.floats(
    min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
)

# Positive integers for face/vertex counts (must be >= 1)
_positive_ints = st.integers(min_value=1, max_value=1_000_000)

# SHA-256 hex strings (64 hex chars)
_sha256_hashes = st.text(
    alphabet="0123456789abcdef",
    min_size=64,
    max_size=64,
)

# Session IDs: alphanumeric with hyphens/underscores
_session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=4,
    max_size=40,
)

# ISO timestamp strings (realistic format)
_iso_timestamps = st.from_regex(
    r"20[0-9]{2}-[01][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z",
    fullmatch=True,
)

# Working status values
_working_statuses = st.sampled_from(["working", "non-working", "not-applicable"])

# Dimensions tuple: 3 positive floats
_dimensions_3tuple = st.tuples(_positive_floats, _positive_floats, _positive_floats)


@st.composite
def asset_registry_entries(draw: st.DrawFn) -> AssetRegistryEntry:
    """Generate a valid AssetRegistryEntry with diverse field values."""
    return AssetRegistryEntry(
        name=draw(_safe_text),
        semantic_label=draw(_safe_text),
        category=draw(_categories),
        era=draw(_safe_text),
        condition=draw(_conditions),
        working_status=draw(_working_statuses),
        material_type=draw(_materials),
        dimensions_m=draw(_dimensions_3tuple),
        weight_estimate_kg=draw(_non_negative_floats),
        generation_method=draw(_generation_methods),
        source_photo_hash=draw(_sha256_hashes),
        source_session_id=draw(_session_ids),
        face_count=draw(_positive_ints),
        vertex_count=draw(_positive_ints),
        has_pbr_textures=draw(st.booleans()),
        created_at=draw(_iso_timestamps),
    )


# ---------------------------------------------------------------------------
# Property 16: Asset Registry JSON Round-Trip
# ---------------------------------------------------------------------------


class TestAssetRegistryJsonRoundTripProperty:
    """Property 16: Asset Registry JSON Round-Trip.

    **Validates: Requirements 15.1, 15.5**

    For any valid AssetRegistryEntry, serializing to JSON (sorted keys,
    2-space indent, UTF-8) then deserializing SHALL produce a structurally
    equal object where every field value compares equal.
    """

    @given(entry=asset_registry_entries())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_serialize_deserialize_equality(self, entry: AssetRegistryEntry) -> None:
        """serialize → deserialize produces structurally equal instance."""
        serialized = entry.to_json()
        deserialized = AssetRegistryEntry.from_json(serialized)
        assert deserialized == entry, (
            f"Round-trip failed:\n"
            f"  Original:      {entry}\n"
            f"  Deserialized:  {deserialized}"
        )

    @given(entry=asset_registry_entries())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_serialize_deserialize_serialize_idempotent(
        self, entry: AssetRegistryEntry
    ) -> None:
        """serialize → deserialize → serialize produces identical bytes."""
        first_json = entry.to_json()
        deserialized = AssetRegistryEntry.from_json(first_json)
        second_json = deserialized.to_json()
        assert first_json == second_json, (
            f"Idempotency failed:\n"
            f"  First:   {first_json[:200]!r}...\n"
            f"  Second:  {second_json[:200]!r}..."
        )
