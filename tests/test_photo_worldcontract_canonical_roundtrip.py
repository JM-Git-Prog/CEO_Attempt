"""Property-based test for WorldContract canonical serialization round-trip.

# Feature: photo-to-playable-world

## Property 23: WorldContract Canonical Serialization Round-Trip

**Validates: Requirements 13.5**

For any WorldContract instance produced by the photo pipeline assembler,
calling canonical_bytes() SHALL produce bytes such that deserializing and
re-serializing produces identical bytes (serialize → deserialize → serialize = identity).
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.models import LightEstimateResult, ObjectManifestEntry, RoomMeshResult
from src.photo_pipeline.stages.assembler import PhotoWorldContractAssembler
from src.world_contract import (
    WorldContract,
    world_contract_from_json,
)


# ---------------------------------------------------------------------------
# Strategies (reuse patterns from test_photo_assembler_pbt)
# ---------------------------------------------------------------------------

# Room dimensions: positive, reasonable values in meters
room_dimension_values = st.floats(
    min_value=0.5, max_value=30.0, allow_nan=False, allow_infinity=False
)

# Object scale: positive, reasonable values in meters
object_scale_values = st.floats(
    min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False
)

# Position values in meters (reasonable room-interior positions)
position_values = st.floats(
    min_value=-15.0, max_value=15.0, allow_nan=False, allow_infinity=False
)

# Rotation degrees
rotation_values = st.floats(
    min_value=0.0, max_value=360.0, allow_nan=False, allow_infinity=False
)

# Valid material categories for objects
valid_material_categories = st.sampled_from(
    ["wood", "metal", "glass", "fabric", "ceramic", "plastic"]
)

# Valid mask IDs matching ^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$
valid_mask_ids = st.text(
    alphabet=st.characters(
        whitelist_categories=(),
        whitelist_characters="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
    ),
    min_size=1,
    max_size=8,
)


@st.composite
def room_mesh_results(draw: st.DrawFn) -> RoomMeshResult:
    """Generate a random valid RoomMeshResult with positive dimensions."""
    width = draw(room_dimension_values)
    height = draw(room_dimension_values)
    depth = draw(room_dimension_values)
    return RoomMeshResult(
        mesh_path=Path("/tmp/room.glb"),
        dimensions_m=(width, height, depth),
        vertex_count=100,
        face_count=50,
        used_heuristic=draw(st.booleans()),
    )


@st.composite
def valid_object_manifest_entries(
    draw: st.DrawFn, mask_id: str
) -> ObjectManifestEntry:
    """Generate a valid ObjectManifestEntry for assembly.

    Always has a mesh_path (only objects with meshes contribute to the contract).
    """
    scale_x = draw(object_scale_values)
    scale_y = draw(object_scale_values)
    scale_z = draw(object_scale_values)
    pos_x = draw(position_values)
    pos_y = draw(position_values)
    pos_z = draw(position_values)
    rot_x = draw(rotation_values)
    rot_y = draw(rotation_values)
    rot_z = draw(rotation_values)
    material = draw(valid_material_categories)

    return ObjectManifestEntry(
        mask_id=mask_id,
        bbox_px=(0, 0, 100, 100),
        area_px=10000,
        centroid_px=(50.0, 50.0),
        object_png_path=Path(f"/tmp/{mask_id}.png"),
        mesh_path=Path(f"/tmp/{mask_id}.glb"),
        mesh_method="hunyuan3d",
        mesh_gen_time_s=1.0,
        audio_path=None,
        audio_method=None,
        material_category=material,
        scale_m=(scale_x, scale_y, scale_z),
        scale_confidence=0.8,
        position_m=(pos_x, pos_y, pos_z),
        rotation_deg=(rot_x, rot_y, rot_z),
        settled=True,
        collision_method="vhacd",
        lod_levels=4,
    )


@st.composite
def unique_object_lists(draw: st.DrawFn) -> list[ObjectManifestEntry]:
    """Generate 0-5 ObjectManifestEntry instances with unique mask_ids."""
    num_objects = draw(st.integers(min_value=0, max_value=5))
    mask_ids = draw(
        st.lists(
            valid_mask_ids,
            min_size=num_objects,
            max_size=num_objects,
            unique=True,
        )
    )
    objects = []
    for mask_id in mask_ids:
        obj = draw(valid_object_manifest_entries(mask_id))
        objects.append(obj)
    return objects


@st.composite
def light_estimate_results(draw: st.DrawFn) -> LightEstimateResult:
    """Generate a valid LightEstimateResult with bounds-respecting values."""
    dx = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    dy = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    dz = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    # Ensure at least one component is non-zero
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        dy = -1.0

    color_temp = draw(st.integers(min_value=1800, max_value=12000))
    intensity = draw(st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False))
    ambient_intensity = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    r = draw(st.integers(min_value=0, max_value=255))
    g = draw(st.integers(min_value=0, max_value=255))
    b = draw(st.integers(min_value=0, max_value=255))
    ambient_color = f"#{r:02X}{g:02X}{b:02X}"

    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    return LightEstimateResult(
        sun_direction=(dx, dy, dz),
        color_temperature_k=color_temp,
        intensity=intensity,
        ambient_intensity=ambient_intensity,
        ambient_color=ambient_color,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Property 23: WorldContract Canonical Serialization Round-Trip
# ---------------------------------------------------------------------------


class TestWorldContractCanonicalRoundTrip:
    """Property 23: WorldContract Canonical Serialization Round-Trip.

    **Validates: Requirements 13.5**

    For any WorldContract instance produced by the photo pipeline assembler,
    canonical_bytes() → deserialize → canonical_bytes() produces identical bytes.
    """

    @given(
        room_mesh=room_mesh_results(),
        objects=unique_object_lists(),
        light_estimate=st.one_of(st.none(), light_estimate_results()),
        image_width=st.integers(min_value=512, max_value=4096),
        image_height=st.integers(min_value=512, max_value=4096),
        vertical_fov=st.floats(min_value=20.0, max_value=120.0, allow_nan=False, allow_infinity=False),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_canonical_bytes_roundtrip_identity(
        self,
        room_mesh: RoomMeshResult,
        objects: list[ObjectManifestEntry],
        light_estimate: LightEstimateResult | None,
        image_width: int,
        image_height: int,
        vertical_fov: float,
    ) -> None:
        """canonical_bytes() → deserialize → canonical_bytes() = identity."""
        # Assemble a WorldContract from photo pipeline stage outputs
        assembler = PhotoWorldContractAssembler(
            session_id="pbt-session-023",
            room_mesh=room_mesh,
            objects=objects,
            light_estimate=light_estimate,
            image_width_px=image_width,
            image_height_px=image_height,
            vertical_fov_deg=vertical_fov,
        )
        contract = assembler.assemble()

        # First serialization: contract → canonical bytes
        first_bytes = contract.canonical_bytes()

        # Deserialize from the canonical bytes
        reconstructed = world_contract_from_json(first_bytes)

        # Second serialization: reconstructed contract → canonical bytes
        second_bytes = reconstructed.canonical_bytes()

        # The two byte sequences must be identical
        assert first_bytes == second_bytes, (
            f"Canonical serialization round-trip failed.\n"
            f"First bytes length: {len(first_bytes)}\n"
            f"Second bytes length: {len(second_bytes)}\n"
            f"Objects in contract: {len(contract.instances)}\n"
            f"Diff starts at byte: {_first_diff_index(first_bytes, second_bytes)}"
        )


def _first_diff_index(a: bytes, b: bytes) -> int:
    """Find index of first byte difference between two byte strings."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))
