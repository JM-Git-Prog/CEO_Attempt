"""Property-based tests for Pipeline Manifest JSON round-trip serialization.

# Feature: photo-to-playable-world

## Property 20: Pipeline Manifest JSON Round-Trip

**Validates: Requirements 13.1, 13.4**

For any valid PipelineManifest instance, serializing to JSON (sorted keys,
no extra whitespace, UTF-8) then deserializing SHALL produce a structurally
equal manifest where every field value compares equal.

Additionally, serialize → deserialize → serialize produces identical bytes
(idempotent canonical form).

Uses Hypothesis with custom strategies to generate diverse PipelineManifest
instances covering:
- Random session IDs, paths, durations
- Variable numbers of stages and objects
- Random quality classifications ("full", "degraded", "minimal")
- Optional None fields (mesh_path, audio_path, world_contract_path, etc.)
- Various mesh methods, audio methods, material categories
- Random tuples for positions, rotations, scales
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.models import (
    ObjectManifestEntry,
    PipelineManifest,
    StageResult,
)
from src.photo_pipeline.serialization import (
    deserialize_manifest,
    serialize_manifest,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe text that doesn't include null bytes or surrogates (JSON-safe)
_safe_text = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # exclude surrogates
        blacklist_characters=("\x00",),
    ),
    min_size=1,
    max_size=30,
)

# Session IDs: alphanumeric with hyphens (realistic UUID-like strings)
_session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
    min_size=4,
    max_size=40,
)

# Paths: forward-slash separated segments (POSIX-style for round-trip safety)
_path_segments = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_./"),
    min_size=1,
    max_size=50,
).filter(lambda s: not s.startswith("/") or len(s) > 1)

_paths = _path_segments.map(Path)

# Optional paths
_optional_paths = st.one_of(st.none(), _paths)

# Finite positive floats (no NaN, inf)
_durations = st.floats(min_value=0.0, max_value=10000.0, allow_nan=False, allow_infinity=False)
_positive_floats = st.floats(min_value=0.001, max_value=10000.0, allow_nan=False, allow_infinity=False)
_confidences = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Tuples of floats for positions, rotations, scales
_float_3tuple = st.tuples(
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
)

# Tuples of ints for bounding boxes (x, y, width, height)
_int_4tuple = st.tuples(
    st.integers(min_value=0, max_value=8192),
    st.integers(min_value=0, max_value=8192),
    st.integers(min_value=1, max_value=4096),
    st.integers(min_value=1, max_value=4096),
)

# 2-float tuple for centroids
_float_2tuple = st.tuples(
    st.floats(min_value=0.0, max_value=8192.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.0, max_value=8192.0, allow_nan=False, allow_infinity=False),
)

# Mesh methods
_mesh_methods = st.sampled_from(["hunyuan3d", "unique3d", "triposr", "placeholder"])
_optional_mesh_methods = st.one_of(st.none(), _mesh_methods)

# Audio methods
_audio_methods = st.sampled_from(["comfyui_audio", "sound_bank", "default"])
_optional_audio_methods = st.one_of(st.none(), _audio_methods)

# Material categories
_material_categories = st.sampled_from(["wood", "metal", "glass", "fabric", "ceramic", "plastic"])

# Collision methods
_collision_methods = st.sampled_from(["vhacd", "convex_hull", "bounding_box"])
_optional_collision_methods = st.one_of(st.none(), _collision_methods)

# Quality classifications
_quality_classifications = st.sampled_from(["full", "degraded", "minimal"])

# Reason codes
_reason_codes = st.sampled_from(["COMPLETED", "FAILED", "TIMEOUT", "FALLBACK_USED", "SKIPPED"])

# Fallback lists
_fallback_lists = st.lists(
    st.sampled_from(["hunyuan3d_timeout", "unique3d_failed", "triposr_failed", "audio_failed", "depth_low_confidence"]),
    min_size=0,
    max_size=4,
)


@st.composite
def artifact_dicts(draw: st.DrawFn) -> dict[str, Path]:
    """Generate a small dictionary of artifact_name → Path."""
    num_artifacts = draw(st.integers(min_value=0, max_value=5))
    artifacts = {}
    for i in range(num_artifacts):
        key = draw(st.sampled_from([
            "room_plate", "depth_map", "normal_map", "mesh", "audio",
            "collision", "lod0", "lod1", "lod2", "lod3",
        ]))
        artifacts[key] = draw(_paths)
    return artifacts


@st.composite
def stage_results(draw: st.DrawFn) -> StageResult:
    """Generate a random StageResult with diverse field values."""
    stage_name = draw(st.sampled_from([
        "scene_parse", "depth_estimation", "object_generation",
        "audio_synthesis", "light_estimation", "scale_calibration",
        "layout_estimation", "physics_settle", "assembly",
    ]))

    return StageResult(
        stage_name=stage_name,
        success=draw(st.booleans()),
        duration_s=draw(_durations),
        reason_code=draw(_reason_codes),
        diagnostics=draw(_safe_text),
        artifacts=draw(artifact_dicts()),
        fallback_used=draw(st.one_of(st.none(), st.sampled_from([
            "unique3d", "triposr", "placeholder", "flat_floor", "sound_bank", "default_audio",
        ]))),
    )


@st.composite
def object_manifest_entries(draw: st.DrawFn) -> ObjectManifestEntry:
    """Generate a random ObjectManifestEntry with diverse field values.

    Handles the constraint: when mesh_method is None, mesh_path is also None.
    When audio_method is None, audio_path is also None.
    """
    mesh_method = draw(_optional_mesh_methods)
    mesh_path = draw(_paths) if mesh_method is not None else None

    audio_method = draw(_optional_audio_methods)
    audio_path = draw(_paths) if audio_method is not None else None

    mask_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="-_"),
        min_size=1,
        max_size=12,
    ))

    return ObjectManifestEntry(
        mask_id=mask_id,
        bbox_px=draw(_int_4tuple),
        area_px=draw(st.integers(min_value=1, max_value=67108864)),
        centroid_px=draw(_float_2tuple),
        object_png_path=draw(_paths),
        mesh_path=mesh_path,
        mesh_method=mesh_method,
        mesh_gen_time_s=draw(_durations),
        audio_path=audio_path,
        audio_method=audio_method,
        material_category=draw(_material_categories),
        scale_m=draw(_float_3tuple),
        scale_confidence=draw(_confidences),
        position_m=draw(_float_3tuple),
        rotation_deg=draw(_float_3tuple),
        settled=draw(st.booleans()),
        collision_method=draw(_optional_collision_methods),
        lod_levels=draw(st.integers(min_value=0, max_value=4)),
        fallbacks_triggered=draw(_fallback_lists),
    )


@st.composite
def pipeline_manifests(draw: st.DrawFn) -> PipelineManifest:
    """Generate a random PipelineManifest with diverse field values.

    Produces manifests with:
    - Random session IDs
    - Variable numbers of stages (0-8) and objects (0-10)
    - Random quality classifications
    - Optional world_contract_path (None or Path)
    """
    return PipelineManifest(
        session_id=draw(_session_ids),
        source_image_path=draw(_paths),
        stages=draw(st.lists(stage_results(), min_size=0, max_size=8)),
        objects=draw(st.lists(object_manifest_entries(), min_size=0, max_size=10)),
        quality_classification=draw(_quality_classifications),
        total_duration_s=draw(_durations),
        source_type="photo",
        world_contract_path=draw(_optional_paths),
    )


# ---------------------------------------------------------------------------
# Property 20: Pipeline Manifest JSON Round-Trip
# ---------------------------------------------------------------------------


class TestManifestJsonRoundTripProperty:
    """Property 20: Pipeline Manifest JSON Round-Trip.

    **Validates: Requirements 13.1, 13.4**

    For any valid PipelineManifest, serialize → deserialize produces a
    structurally equal instance (all fields compare equal).

    Serialize → deserialize → serialize produces identical bytes
    (idempotent canonical form).
    """

    @given(manifest=pipeline_manifests())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_serialize_deserialize_equality(self, manifest: PipelineManifest) -> None:
        """serialize → deserialize produces structurally equal instance."""
        serialized = serialize_manifest(manifest)
        deserialized = deserialize_manifest(serialized)
        assert deserialized == manifest, (
            f"Round-trip failed:\n"
            f"  Original:      {manifest}\n"
            f"  Deserialized:  {deserialized}"
        )

    @given(manifest=pipeline_manifests())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_serialize_deserialize_serialize_idempotent(self, manifest: PipelineManifest) -> None:
        """serialize → deserialize → serialize produces identical bytes."""
        first_bytes = serialize_manifest(manifest)
        deserialized = deserialize_manifest(first_bytes)
        second_bytes = serialize_manifest(deserialized)
        assert first_bytes == second_bytes, (
            f"Idempotency failed:\n"
            f"  First:   {first_bytes[:200]!r}...\n"
            f"  Second:  {second_bytes[:200]!r}..."
        )
