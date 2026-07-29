"""Property-based tests for Depth Map NumPy round-trip integrity (V14).

# Feature: photo-to-real-3d-world-v14

## Property 19: Depth Map NumPy Round-Trip

**Validates: Requirements 15.4**

For any float32 NumPy array representing a depth map, `np.save` followed
by `np.load` SHALL produce a bit-identical array.

Uses Hypothesis with hypothesis.extra.numpy for comprehensive float32
coverage including edge cases: zeros, infinities, NaN, negatives, subnormals,
and normal positive values representing realistic depth measurements.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def depth_map_float32(draw: st.DrawFn) -> np.ndarray:
    """Generate float32 2D arrays of reasonable depth map sizes.

    Shape: (H, W) where H in [1, 500], W in [1, 500].
    Values: any float32 including zeros, infinities, NaN, negatives,
    and normal positive values.
    """
    height = draw(st.integers(min_value=1, max_value=500))
    width = draw(st.integers(min_value=1, max_value=500))

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=st.floats(
                width=32,
                allow_nan=True,
                allow_infinity=True,
                allow_subnormal=True,
            ),
        )
    )

    return depth_map


@st.composite
def depth_map_mixed_values(draw: st.DrawFn) -> np.ndarray:
    """Generate depth maps with a mix of edge-case and realistic values.

    Includes: 0.0, -0.0, inf, -inf, nan, negative floats, subnormals,
    and typical indoor depth values (0.5m - 10m).
    """
    height = draw(st.integers(min_value=1, max_value=200))
    width = draw(st.integers(min_value=1, max_value=200))

    elements = st.one_of(
        # Realistic depth values (meters) - use float32-representable bounds
        st.floats(
            min_value=np.float32(0.125).item(),
            max_value=np.float32(20.0).item(),
            allow_nan=False, allow_infinity=False, width=32,
        ),
        # Edge cases
        st.sampled_from([
            np.float32(0.0),
            np.float32(-0.0),
            np.float32(np.inf),
            np.float32(-np.inf),
            np.float32(np.nan),
            np.finfo(np.float32).max,
            np.finfo(np.float32).min,
            np.finfo(np.float32).tiny,
            np.finfo(np.float32).smallest_subnormal,
        ]),
        # Negative values - use float32-representable bounds
        st.floats(
            min_value=np.float32(-100.0).item(),
            max_value=np.float32(-0.001953125).item(),
            allow_nan=False, allow_infinity=False, width=32,
        ),
    )

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=elements,
        )
    )

    return depth_map


# ---------------------------------------------------------------------------
# Property 19: Depth Map NumPy Round-Trip
# ---------------------------------------------------------------------------


class TestDepthMapNumpyRoundTripV14:
    """Property 19: Depth Map NumPy Round-Trip.

    **Validates: Requirements 15.4**

    For any float32 NumPy array representing a depth map, np.save followed
    by np.load SHALL produce a bit-identical array.
    """

    @given(depth_map=depth_map_float32())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_numpy_save_load_bit_identical(self, depth_map: np.ndarray) -> None:
        """np.save → np.load produces a bit-identical float32 array.

        **Validates: Requirements 15.4**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            # Shape must be preserved
            assert loaded.shape == depth_map.shape, (
                f"Shape mismatch: original {depth_map.shape} vs loaded {loaded.shape}"
            )

            # Dtype must be preserved as float32
            assert loaded.dtype == np.float32, (
                f"Dtype mismatch: expected float32, got {loaded.dtype}"
            )

            # Bit-identical comparison (handles NaN == NaN)
            assert np.array_equal(loaded, depth_map, equal_nan=True), (
                f"Arrays not bit-identical after round-trip. "
                f"Shape: {depth_map.shape}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=depth_map_mixed_values())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_numpy_save_load_byte_level_identical(
        self, depth_map: np.ndarray
    ) -> None:
        """np.save → np.load preserves exact byte representation.

        This covers negative zero vs positive zero, NaN bit patterns,
        subnormals, and all other float32 edge cases at the byte level.

        **Validates: Requirements 15.4**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            # Byte-level comparison: strictest possible equality check
            original_bytes = depth_map.tobytes()
            loaded_bytes = loaded.tobytes()
            assert original_bytes == loaded_bytes, (
                f"Byte-level mismatch after round-trip. "
                f"Shape: {depth_map.shape}, "
                f"Byte lengths: {len(original_bytes)} vs {len(loaded_bytes)}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)



# ---------------------------------------------------------------------------
# Property 18: Pipeline Manifest JSON Round-Trip
# ---------------------------------------------------------------------------
# (Appended to same file per task instructions)

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
# Strategies for Pipeline Manifest
# ---------------------------------------------------------------------------

# Safe text: no null bytes or surrogates (JSON-safe), non-empty
_pm_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude surrogates
        blacklist_characters=("\x00",),
    ),
    min_size=1,
    max_size=30,
)

# Posix-safe path segments (no special chars that break Path round-trip)
_pm_path_segments = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-.",
    ),
    min_size=1,
    max_size=20,
)

# File paths (posix-style for consistent round-trip via as_posix)
_pm_file_paths = st.builds(
    lambda parts: Path("/".join(parts)),
    st.lists(_pm_path_segments, min_size=1, max_size=4),
)

# SHA-256 hex strings (64 hex chars)
_pm_sha256_hashes = st.text(
    alphabet="0123456789abcdef",
    min_size=64,
    max_size=64,
)

# Session IDs: alphanumeric with hyphens/underscores, non-empty
_pm_session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=4,
    max_size=30,
)

# Positive floats (> 0)
_pm_positive_floats = st.floats(
    min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# Non-negative floats (>= 0)
_pm_non_negative_floats = st.floats(
    min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False
)

# Positive integers (>= 1)
_pm_positive_ints = st.integers(min_value=1, max_value=1_000_000)

# Non-negative integers (>= 0)
_pm_non_negative_ints = st.integers(min_value=0, max_value=1_000_000)

# Constrained domain values
_pm_categories = st.sampled_from(list(VALID_CATEGORIES))
_pm_materials = st.sampled_from(list(VALID_MATERIALS))
_pm_conditions = st.sampled_from(list(VALID_CONDITIONS))
_pm_body_modes = st.sampled_from(list(VALID_BODY_MODES))
_pm_mesh_methods = st.sampled_from(list(VALID_MESH_METHODS))
_pm_quality_classifications = st.sampled_from(list(VALID_QUALITY_CLASSIFICATIONS))

# 3-tuples of positive floats (for dimensions)
_pm_positive_3tuple = st.tuples(
    _pm_positive_floats, _pm_positive_floats, _pm_positive_floats
)

# 3-tuples of arbitrary floats (for position/rotation)
_pm_float_3tuple = st.tuples(
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)

# Texture resolution: pair of positive ints
_pm_texture_resolution = st.tuples(
    st.sampled_from([256, 512, 1024, 2048]),
    st.sampled_from([256, 512, 1024, 2048]),
)

# Grid resolution: pair of positive ints
_pm_grid_resolution = st.tuples(
    st.integers(min_value=1, max_value=500),
    st.integers(min_value=1, max_value=500),
)


@st.composite
def pm_stage_results(draw: st.DrawFn) -> StageResult:
    """Generate a valid StageResult for manifest testing."""
    num_artifacts = draw(st.integers(min_value=0, max_value=3))
    artifacts = {}
    for _ in range(num_artifacts):
        key = draw(_pm_safe_text)
        artifacts[key] = draw(_pm_file_paths)

    return StageResult(
        stage_name=draw(_pm_safe_text),
        success=draw(st.booleans()),
        duration_s=draw(_pm_non_negative_floats),
        reason_code=draw(_pm_safe_text),
        diagnostics=draw(_pm_safe_text),
        artifacts=artifacts,
        fallback_used=draw(st.one_of(st.none(), _pm_safe_text)),
    )


@st.composite
def pm_room_shell_results(draw: st.DrawFn) -> RoomShellResult:
    """Generate a valid RoomShellResult."""
    return RoomShellResult(
        mesh_path=draw(_pm_file_paths),
        dimensions_m=draw(_pm_positive_3tuple),
        vertex_count=draw(_pm_positive_ints),
        face_count=draw(_pm_positive_ints),
        grid_resolution=draw(_pm_grid_resolution),
        faces_removed_gradient=draw(_pm_non_negative_ints),
        used_fallback=draw(st.booleans()),
    )


@st.composite
def pm_semantic_labels(draw: st.DrawFn) -> SemanticLabel:
    """Generate a valid SemanticLabel."""
    return SemanticLabel(
        semantic_label=draw(_pm_safe_text),
        primary_material=draw(_pm_materials),
        category=draw(_pm_categories),
        estimated_era=draw(_pm_safe_text),
        condition=draw(_pm_conditions),
        is_architectural=draw(st.booleans()),
    )


@st.composite
def pm_physics_classifications(draw: st.DrawFn) -> PhysicsClassification:
    """Generate a valid PhysicsClassification."""
    return PhysicsClassification(
        body_mode=draw(_pm_body_modes),
        mass_kg=draw(_pm_non_negative_floats),
        volume_m3=draw(_pm_non_negative_floats),
        material_density=draw(_pm_non_negative_floats),
        friction=draw(_pm_non_negative_floats),
        restitution=draw(_pm_non_negative_floats),
        can_topple=draw(st.booleans()),
        override_reason=draw(st.one_of(st.none(), _pm_safe_text)),
    )


@st.composite
def pm_material_pass_results(
    draw: st.DrawFn, pass_number: int = 1
) -> MaterialPassResult:
    """Generate a valid MaterialPassResult for a given pass number."""
    return MaterialPassResult(
        object_id=draw(_pm_safe_text),
        pass_number=pass_number,
        has_base_color=draw(st.booleans()),
        has_metallic_roughness=draw(st.booleans()),
        has_normal_map=draw(st.booleans()),
        texture_resolution=draw(_pm_texture_resolution),
    )


@st.composite
def pm_v14_object_entries(draw: st.DrawFn) -> V14ObjectEntry:
    """Generate a valid V14ObjectEntry with all nested objects."""
    has_pass2 = draw(st.booleans())
    has_warehouse = draw(st.booleans())
    has_registry = draw(st.booleans())

    return V14ObjectEntry(
        mask_id=draw(_pm_safe_text),
        semantic_label=draw(pm_semantic_labels()),
        mesh_path=draw(_pm_file_paths),
        mesh_method=draw(_pm_mesh_methods),
        mesh_generation_time_s=draw(_pm_non_negative_floats),
        face_count=draw(_pm_positive_ints),
        vertex_count=draw(_pm_positive_ints),
        dimensions_m=draw(_pm_positive_3tuple),
        position_m=draw(_pm_float_3tuple),
        rotation_deg=draw(_pm_float_3tuple),
        physics=draw(pm_physics_classifications()),
        material_pass1=draw(pm_material_pass_results(pass_number=1)),
        material_pass2=draw(pm_material_pass_results(pass_number=2)) if has_pass2 else None,
        asset_warehouse_path=draw(_pm_file_paths) if has_warehouse else None,
        asset_registry_id=draw(_pm_safe_text) if has_registry else None,
    )


@st.composite
def pm_v14_pipeline_manifests(draw: st.DrawFn) -> V14PipelineManifest:
    """Generate a valid V14PipelineManifest with all nested objects."""
    has_world_contract = draw(st.booleans())

    return V14PipelineManifest(
        session_id=draw(_pm_session_ids),
        source_image_path=draw(_pm_file_paths),
        source_image_hash=draw(_pm_sha256_hashes),
        interface_version=14,  # Must always be 14
        stages=draw(st.lists(pm_stage_results(), min_size=0, max_size=5)),
        room_shell=draw(pm_room_shell_results()),
        objects=draw(st.lists(pm_v14_object_entries(), min_size=0, max_size=5)),
        depth_model_used=draw(_pm_safe_text),
        quality_classification=draw(_pm_quality_classifications),
        total_duration_s=draw(_pm_non_negative_floats),
        world_contract_path=draw(_pm_file_paths) if has_world_contract else None,
    )


class TestV14PipelineManifestJsonRoundTripProperty:
    """Property 18: Pipeline Manifest JSON Round-Trip.

    **Validates: Requirements 15.3**

    For any V14PipelineManifest instance, serializing to JSON (sorted keys,
    UTF-8) then deserializing SHALL produce a structurally equal manifest.
    """

    @given(manifest=pm_v14_pipeline_manifests())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_serialize_deserialize_equality(
        self, manifest: V14PipelineManifest
    ) -> None:
        """serialize → deserialize produces structurally equal instance.

        **Validates: Requirements 15.3**
        """
        serialized = manifest.to_json()
        deserialized = V14PipelineManifest.from_json(serialized)
        assert deserialized == manifest, (
            f"Round-trip failed:\n"
            f"  Original:      {manifest}\n"
            f"  Deserialized:  {deserialized}"
        )

    @given(manifest=pm_v14_pipeline_manifests())
    @settings(
        max_examples=30,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_serialize_deserialize_serialize_idempotent(
        self, manifest: V14PipelineManifest
    ) -> None:
        """serialize → deserialize → serialize produces identical bytes.

        **Validates: Requirements 15.3**
        """
        first_json = manifest.to_json()
        deserialized = V14PipelineManifest.from_json(first_json)
        second_json = deserialized.to_json()
        assert first_json == second_json, (
            f"Idempotency failed:\n"
            f"  First:   {first_json[:200]!r}...\n"
            f"  Second:  {second_json[:200]!r}..."
        )
