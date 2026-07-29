"""Property-based tests for V14 Pipeline Manifest JSON round-trip (V14).

# Feature: photo-to-real-3d-world-v14

## Property 18: Pipeline Manifest JSON Round-Trip

**Validates: Requirements 15.3**

For any V14PipelineManifest instance, serializing to JSON (sorted keys,
UTF-8) then deserializing SHALL produce a structurally equal manifest.

Uses Hypothesis to generate arbitrary valid V14PipelineManifest instances
covering all nested types: SemanticLabel, PhysicsClassification,
MaterialPassResult, RoomShellResult, V14ObjectEntry, and StageResult.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.models import StageResult
from src.photo_pipeline.models_v14 import (
    MaterialPassResult,
    PhysicsClassification,
    RoomShellResult,
    SemanticLabel,
    V14ObjectEntry,
    V14PipelineManifest,
    VALID_BODY_MODES,
    VALID_CATEGORIES,
    VALID_CONDITIONS,
    VALID_MATERIALS,
    VALID_MESH_METHODS,
    VALID_QUALITY_CLASSIFICATIONS,
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
    max_size=30,
)

# Posix-safe path segments (alphanumeric + limited punctuation)
_path_segments = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-.",
    ),
    min_size=1,
    max_size=20,
)

# File paths (posix-style for consistent round-trip via as_posix)
_file_paths = st.builds(
    lambda parts: Path("/".join(parts)),
    st.lists(_path_segments, min_size=1, max_size=4),
)

# SHA-256 hex strings (64 hex chars)
_sha256_hashes = st.text(
    alphabet="0123456789abcdef",
    min_size=64,
    max_size=64,
)

# Session IDs: alphanumeric with hyphens/underscores, non-empty
_session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=4,
    max_size=30,
)

# Positive floats (> 0)
_positive_floats = st.floats(
    min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# Non-negative floats (>= 0)
_non_negative_floats = st.floats(
    min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
)

# Positive integers (>= 1)
_positive_ints = st.integers(min_value=1, max_value=1_000_000)

# Non-negative integers (>= 0)
_non_negative_ints = st.integers(min_value=0, max_value=1_000_000)

# Constrained domain values
_categories = st.sampled_from(list(VALID_CATEGORIES))
_materials = st.sampled_from(list(VALID_MATERIALS))
_conditions = st.sampled_from(list(VALID_CONDITIONS))
_body_modes = st.sampled_from(list(VALID_BODY_MODES))
_mesh_methods = st.sampled_from(list(VALID_MESH_METHODS))
_quality_classifications = st.sampled_from(list(VALID_QUALITY_CLASSIFICATIONS))

# 3-tuples of positive floats (for dimensions)
_positive_3tuple = st.tuples(
    _positive_floats, _positive_floats, _positive_floats
)

# 3-tuples of arbitrary floats (for position/rotation)
_float_3tuple = st.tuples(
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)

# Texture resolution: pair of positive ints
_texture_resolution = st.tuples(
    st.sampled_from([256, 512, 1024, 2048]),
    st.sampled_from([256, 512, 1024, 2048]),
)

# Grid resolution: pair of positive ints
_grid_resolution = st.tuples(
    st.integers(min_value=1, max_value=500),
    st.integers(min_value=1, max_value=500),
)


@st.composite
def stage_results(draw: st.DrawFn) -> StageResult:
    """Generate a valid StageResult for manifest testing."""
    num_artifacts = draw(st.integers(min_value=0, max_value=3))
    artifacts = {}
    for _ in range(num_artifacts):
        key = draw(_safe_text)
        artifacts[key] = draw(_file_paths)

    return StageResult(
        stage_name=draw(_safe_text),
        success=draw(st.booleans()),
        duration_s=draw(_non_negative_floats),
        reason_code=draw(_safe_text),
        diagnostics=draw(_safe_text),
        artifacts=artifacts,
        fallback_used=draw(st.one_of(st.none(), _safe_text)),
    )


@st.composite
def room_shell_results(draw: st.DrawFn) -> RoomShellResult:
    """Generate a valid RoomShellResult."""
    return RoomShellResult(
        mesh_path=draw(_file_paths),
        dimensions_m=draw(_positive_3tuple),
        vertex_count=draw(_positive_ints),
        face_count=draw(_positive_ints),
        grid_resolution=draw(_grid_resolution),
        faces_removed_gradient=draw(_non_negative_ints),
        used_fallback=draw(st.booleans()),
    )


@st.composite
def semantic_labels(draw: st.DrawFn) -> SemanticLabel:
    """Generate a valid SemanticLabel."""
    return SemanticLabel(
        semantic_label=draw(_safe_text),
        primary_material=draw(_materials),
        category=draw(_categories),
        estimated_era=draw(_safe_text),
        condition=draw(_conditions),
        is_architectural=draw(st.booleans()),
    )


@st.composite
def physics_classifications(draw: st.DrawFn) -> PhysicsClassification:
    """Generate a valid PhysicsClassification."""
    return PhysicsClassification(
        body_mode=draw(_body_modes),
        mass_kg=draw(_non_negative_floats),
        volume_m3=draw(_non_negative_floats),
        material_density=draw(_non_negative_floats),
        friction=draw(_non_negative_floats),
        restitution=draw(_non_negative_floats),
        can_topple=draw(st.booleans()),
        override_reason=draw(st.one_of(st.none(), _safe_text)),
    )


@st.composite
def material_pass_results(draw: st.DrawFn, pass_number: int = 1) -> MaterialPassResult:
    """Generate a valid MaterialPassResult for a given pass number."""
    return MaterialPassResult(
        object_id=draw(_safe_text),
        pass_number=pass_number,
        has_base_color=draw(st.booleans()),
        has_metallic_roughness=draw(st.booleans()),
        has_normal_map=draw(st.booleans()),
        texture_resolution=draw(_texture_resolution),
    )


@st.composite
def v14_object_entries(draw: st.DrawFn) -> V14ObjectEntry:
    """Generate a valid V14ObjectEntry with all nested objects."""
    has_pass2 = draw(st.booleans())
    has_warehouse = draw(st.booleans())
    has_registry = draw(st.booleans())

    return V14ObjectEntry(
        mask_id=draw(_safe_text),
        semantic_label=draw(semantic_labels()),
        mesh_path=draw(_file_paths),
        mesh_method=draw(_mesh_methods),
        mesh_generation_time_s=draw(_non_negative_floats),
        face_count=draw(_positive_ints),
        vertex_count=draw(_positive_ints),
        dimensions_m=draw(_positive_3tuple),
        position_m=draw(_float_3tuple),
        rotation_deg=draw(_float_3tuple),
        physics=draw(physics_classifications()),
        material_pass1=draw(material_pass_results(pass_number=1)),
        material_pass2=draw(material_pass_results(pass_number=2)) if has_pass2 else None,
        asset_warehouse_path=draw(_file_paths) if has_warehouse else None,
        asset_registry_id=draw(_safe_text) if has_registry else None,
    )


@st.composite
def v14_pipeline_manifests(draw: st.DrawFn) -> V14PipelineManifest:
    """Generate a valid V14PipelineManifest with all nested objects."""
    has_world_contract = draw(st.booleans())

    return V14PipelineManifest(
        session_id=draw(_session_ids),
        source_image_path=draw(_file_paths),
        source_image_hash=draw(_sha256_hashes),
        interface_version=14,  # Must always be 14
        stages=draw(st.lists(stage_results(), min_size=0, max_size=5)),
        room_shell=draw(room_shell_results()),
        objects=draw(st.lists(v14_object_entries(), min_size=0, max_size=5)),
        depth_model_used=draw(_safe_text),
        quality_classification=draw(_quality_classifications),
        total_duration_s=draw(_non_negative_floats),
        world_contract_path=draw(_file_paths) if has_world_contract else None,
    )


# ---------------------------------------------------------------------------
# Property 18: Pipeline Manifest JSON Round-Trip
# ---------------------------------------------------------------------------


class TestV14PipelineManifestJsonRoundTrip:
    """Property 18: Pipeline Manifest JSON Round-Trip.

    **Validates: Requirements 15.3**

    For any V14PipelineManifest instance, serializing to JSON (sorted keys,
    UTF-8) then deserializing SHALL produce a structurally equal manifest.
    """

    @given(manifest=v14_pipeline_manifests())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_json_roundtrip_structural_equality(
        self, manifest: V14PipelineManifest
    ) -> None:
        """V14PipelineManifest.from_json(manifest.to_json()) == manifest.

        **Validates: Requirements 15.3**
        """
        serialized = manifest.to_json()
        deserialized = V14PipelineManifest.from_json(serialized)
        assert deserialized == manifest, (
            f"Round-trip failed:\n"
            f"  Original session_id:     {manifest.session_id}\n"
            f"  Deserialized session_id: {deserialized.session_id}\n"
            f"  Objects count: {len(manifest.objects)} vs {len(deserialized.objects)}"
        )

    @given(manifest=v14_pipeline_manifests())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_json_roundtrip_idempotent(
        self, manifest: V14PipelineManifest
    ) -> None:
        """serialize → deserialize → serialize produces identical JSON bytes.

        **Validates: Requirements 15.3**
        """
        first_json = manifest.to_json()
        deserialized = V14PipelineManifest.from_json(first_json)
        second_json = deserialized.to_json()
        assert first_json == second_json, (
            f"Idempotency failed:\n"
            f"  First JSON (truncated):  {first_json[:200]!r}...\n"
            f"  Second JSON (truncated): {second_json[:200]!r}..."
        )
