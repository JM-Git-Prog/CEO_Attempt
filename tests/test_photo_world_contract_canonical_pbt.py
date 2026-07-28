"""Property-based tests for WorldContract canonical serialization round-trip.

# Feature: photo-to-playable-world

## Property 23: WorldContract Canonical Serialization Round-Trip

**Validates: Requirements 13.5**

For any WorldContract produced by the photo pipeline assembler,
canonical_bytes() → deserialize → canonical_bytes() produces identical bytes.

Uses Hypothesis with @given decorator and @st.composite strategies.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.models import (
    LightEstimateResult,
    ObjectManifestEntry,
    RoomMeshResult,
)
from src.photo_pipeline.stages.assembler import PhotoWorldContractAssembler
from src.world_contract import (
    canonical_world_contract,
    world_contract_from_json,
    WorldContract,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid ID characters: starts with [A-Za-z0-9], followed by [A-Za-z0-9_.:@-]{0,127}
_ID_START_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_ID_BODY_CHARS = _ID_START_CHARS + "_.:@-"


@st.composite
def valid_mask_ids(draw: st.DrawFn) -> str:
    """Generate valid mask IDs matching ^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$."""
    start = draw(st.sampled_from(list(_ID_START_CHARS)))
    body_len = draw(st.integers(min_value=0, max_value=15))
    body = draw(
        st.text(alphabet=_ID_BODY_CHARS, min_size=body_len, max_size=body_len)
    )
    return start + body


@st.composite
def valid_room_mesh_results(draw: st.DrawFn) -> RoomMeshResult:
    """Generate valid RoomMeshResult with positive dimensions."""
    width = draw(st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False))
    height = draw(st.floats(min_value=2.0, max_value=5.0, allow_nan=False, allow_infinity=False))
    depth = draw(st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False))
    vertex_count = draw(st.integers(min_value=4, max_value=10000))
    face_count = draw(st.integers(min_value=2, max_value=5000))
    used_heuristic = draw(st.booleans())

    return RoomMeshResult(
        mesh_path=Path("room.glb"),
        dimensions_m=(width, height, depth),
        vertex_count=vertex_count,
        face_count=face_count,
        used_heuristic=used_heuristic,
    )


@st.composite
def valid_object_manifest_entries(draw: st.DrawFn) -> ObjectManifestEntry:
    """Generate valid ObjectManifestEntry with proper constraints."""
    mask_id = draw(valid_mask_ids())
    material = draw(st.sampled_from(["wood", "metal", "glass", "fabric", "ceramic", "plastic"]))

    # Positive scale dimensions
    scale_w = draw(st.floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False))
    scale_h = draw(st.floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False))
    scale_d = draw(st.floats(min_value=0.01, max_value=3.0, allow_nan=False, allow_infinity=False))

    # Finite position values
    pos_x = draw(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    pos_y = draw(st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False))
    pos_z = draw(st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False))

    # Rotation angles
    rot_x = draw(st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False))
    rot_y = draw(st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False))
    rot_z = draw(st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False))

    mesh_method = draw(st.sampled_from(["hunyuan3d", "unique3d", "triposr", "placeholder"]))

    return ObjectManifestEntry(
        mask_id=mask_id,
        bbox_px=(0, 0, 100, 100),
        area_px=10000,
        centroid_px=(50.0, 50.0),
        object_png_path=Path(f"objects/{mask_id}.png"),
        mesh_path=Path(f"meshes/{mask_id}.glb"),
        mesh_method=mesh_method,
        mesh_gen_time_s=1.5,
        audio_path=None,
        audio_method=None,
        material_category=material,
        scale_m=(scale_w, scale_h, scale_d),
        scale_confidence=0.8,
        position_m=(pos_x, pos_y, pos_z),
        rotation_deg=(rot_x, rot_y, rot_z),
        settled=True,
        collision_method="vhacd",
        lod_levels=4,
    )


@st.composite
def valid_light_estimate_results(draw: st.DrawFn) -> LightEstimateResult:
    """Generate valid LightEstimateResult with normalized direction and valid ranges."""
    # Generate a non-zero direction vector, then normalize it
    dx = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    dy = draw(st.floats(min_value=-1.0, max_value=-0.1, allow_nan=False, allow_infinity=False))
    dz = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    # Normalize direction (magnitude is guaranteed > 0 since dy >= 0.1)
    mag = (dx * dx + dy * dy + dz * dz) ** 0.5
    dx, dy, dz = dx / mag, dy / mag, dz / mag

    color_temp = draw(st.integers(min_value=1800, max_value=12000))
    intensity = draw(st.floats(min_value=1.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    ambient_intensity = draw(st.floats(min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False))
    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    return LightEstimateResult(
        sun_direction=(dx, dy, dz),
        color_temperature_k=color_temp,
        intensity=intensity,
        ambient_intensity=ambient_intensity,
        ambient_color="#E8E8E8",
        confidence=confidence,
    )


@st.composite
def assembler_world_contracts(draw: st.DrawFn) -> WorldContract:
    """Generate a valid WorldContract using the PhotoWorldContractAssembler.

    Combines room mesh, object manifest entries, and light estimates
    through the assembler to produce validated WorldContract instances.
    """
    room_mesh = draw(valid_room_mesh_results())

    # Generate 0-5 objects with unique mask_ids
    num_objects = draw(st.integers(min_value=0, max_value=5))
    objects: list[ObjectManifestEntry] = []
    used_ids: set[str] = set()

    for _ in range(num_objects):
        obj = draw(valid_object_manifest_entries())
        # Ensure unique mask_ids
        while obj.mask_id in used_ids:
            obj = draw(valid_object_manifest_entries())
        used_ids.add(obj.mask_id)
        objects.append(obj)

    # Optionally include a light estimate
    include_light = draw(st.booleans())
    light_estimate = draw(valid_light_estimate_results()) if include_light else None

    # Image dimensions
    width_px = draw(st.sampled_from([640, 1280, 1920, 3840]))
    height_px = draw(st.sampled_from([480, 720, 1080, 2160]))

    # FOV must be > 0 and < 180
    fov = draw(st.floats(min_value=30.0, max_value=120.0, allow_nan=False, allow_infinity=False))

    session_id = draw(valid_mask_ids())

    assembler = PhotoWorldContractAssembler(
        session_id=session_id,
        room_mesh=room_mesh,
        objects=objects,
        light_estimate=light_estimate,
        image_width_px=width_px,
        image_height_px=height_px,
        vertical_fov_deg=fov,
    )

    return assembler.assemble()


# ---------------------------------------------------------------------------
# Property 23: WorldContract Canonical Serialization Round-Trip
# ---------------------------------------------------------------------------


class TestWorldContractCanonicalRoundTrip:
    """Property 23: WorldContract Canonical Serialization Round-Trip.

    For any WorldContract from the photo assembler,
    canonical_bytes() → deserialize → canonical_bytes() produces identical bytes.
    """

    @given(contract=assembler_world_contracts())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_canonical_bytes_round_trip(self, contract: WorldContract):
        """serialize → deserialize → serialize produces identical bytes.

        **Validates: Requirements 13.5**
        """
        # First serialization
        bytes1 = contract.canonical_bytes()

        # Deserialize back to WorldContract
        deserialized = world_contract_from_json(bytes1)

        # Second serialization
        bytes2 = deserialized.canonical_bytes()

        # Must be byte-identical
        assert bytes1 == bytes2, (
            f"Canonical bytes differ after round-trip.\n"
            f"First {len(bytes1)} bytes, second {len(bytes2)} bytes.\n"
            f"First 200 chars: {bytes1[:200]!r}\n"
            f"Second 200 chars: {bytes2[:200]!r}"
        )

    @given(contract=assembler_world_contracts())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_canonical_world_contract_function_round_trip(self, contract: WorldContract):
        """canonical_world_contract() function also round-trips identically.

        **Validates: Requirements 13.5**
        """
        # Use the module-level function directly
        bytes1 = canonical_world_contract(contract)

        # Deserialize and re-serialize
        deserialized = world_contract_from_json(bytes1)
        bytes2 = canonical_world_contract(deserialized)

        assert bytes1 == bytes2, (
            "canonical_world_contract() output differs after round-trip"
        )

    @given(contract=assembler_world_contracts())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_deserialized_contract_equals_original(self, contract: WorldContract):
        """Deserialized contract is semantically equal to the original.

        **Validates: Requirements 13.5**
        """
        bytes1 = contract.canonical_bytes()
        deserialized = world_contract_from_json(bytes1)

        # Model equality (Pydantic frozen models support ==)
        assert contract == deserialized, (
            "Deserialized WorldContract is not equal to the original"
        )
