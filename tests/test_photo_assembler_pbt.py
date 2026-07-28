"""Property-based tests for the photo pipeline WorldContract assembler.

# Feature: photo-to-playable-world

## Property 15: WorldContract Assembly Validity

**Validates: Requirements 8.1, 8.2, 8.3**

For any valid combination of stage outputs (room mesh + zero or more object meshes
+ light params + camera), assembled WorldContract passes all Pydantic validators
(coordinate system, ID uniqueness, dangling references).

## Property 16: Physics Mode Assignment from Material and Volume

**Validates: Requirements 8.4**

For any object with estimated mass (volume × material_density) exceeding 50kg,
the physics intent SHALL have body_mode=STATIC. For any object with estimated
mass ≤ 50kg and not categorized as "architectural", the physics intent SHALL
have body_mode=DYNAMIC with mass_kg equal to volume × density (within tolerance).

## Property 19: Quality Classification Determinism

**Validates: Requirements 12.6**

For any pipeline result, classification SHALL be: "full" if all objects used
their primary generation method (hunyuan3d), "degraded" if at least one fallback
was triggered but at least one object mesh exists, "minimal" if zero object
meshes were successfully generated (room-only).

Uses Hypothesis with custom strategies for ObjectManifestEntry generation.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.models import LightEstimateResult, ObjectManifestEntry, RoomMeshResult
from src.photo_pipeline.stages.assembler import (
    classify_quality,
    _estimate_mass_kg,
    _infer_category,
    MATERIAL_DENSITIES,
    _STATIC_MASS_THRESHOLD_KG,
    PhotoWorldContractAssembler,
)
from src.world_contract import BodyMode, WorldContract


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

MESH_METHODS = ("hunyuan3d", "unique3d", "triposr", "placeholder")


@st.composite
def object_manifest_entries(draw: st.DrawFn) -> ObjectManifestEntry:
    """Generate a single ObjectManifestEntry with random mesh method.

    mesh_method is drawn from {hunyuan3d, unique3d, triposr, placeholder, None}.
    When mesh_method is None, mesh_path is also None.
    When mesh_method is not None, mesh_path is a valid Path.
    """
    mesh_method = draw(
        st.sampled_from([*MESH_METHODS, None])
    )

    if mesh_method is None:
        mesh_path = None
    else:
        mesh_path = Path(f"/tmp/mesh_{draw(st.integers(min_value=0, max_value=9999))}.glb")

    mask_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=8,
    ))

    return ObjectManifestEntry(
        mask_id=mask_id,
        bbox_px=(0, 0, 100, 100),
        area_px=10000,
        centroid_px=(50.0, 50.0),
        object_png_path=Path(f"/tmp/{mask_id}.png"),
        mesh_path=mesh_path,
        mesh_method=mesh_method,
        mesh_gen_time_s=1.0,
        audio_path=None,
        audio_method=None,
        material_category="wood",
        scale_m=(0.5, 0.5, 0.5),
        scale_confidence=0.8,
        position_m=(0.0, 0.0, 0.0),
        rotation_deg=(0.0, 0.0, 0.0),
        settled=True,
        collision_method="vhacd",
        lod_levels=4,
    )


# ---------------------------------------------------------------------------
# Property 19: Quality Classification Determinism
# ---------------------------------------------------------------------------


class TestQualityClassificationProperty:
    """Property 19: Quality Classification Determinism.

    For any list of ObjectManifestEntry, classify_quality SHALL return:
    - "minimal" if no objects have mesh_path not None
    - "full" if all objects with mesh_path not None used mesh_method == "hunyuan3d"
    - "degraded" if ≥1 object with mesh_path not None has mesh_method != "hunyuan3d"
      (but at least one mesh exists)
    """

    @given(objects=st.lists(object_manifest_entries(), min_size=0, max_size=10))
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_quality_classification_determinism(
        self, objects: list[ObjectManifestEntry]
    ) -> None:
        """Property 19: classification follows deterministic rules based on mesh methods."""
        result = classify_quality(objects)

        # Compute expected classification from first principles
        objects_with_mesh = [obj for obj in objects if obj.mesh_path is not None]

        if not objects_with_mesh:
            # No objects or no objects with meshes → minimal
            assert result == "minimal", (
                f"Expected 'minimal' when no objects have meshes, got '{result}'. "
                f"Total objects: {len(objects)}, with mesh: {len(objects_with_mesh)}"
            )
        elif all(obj.mesh_method == "hunyuan3d" for obj in objects_with_mesh):
            # All meshed objects used primary method → full
            assert result == "full", (
                f"Expected 'full' when all meshed objects used hunyuan3d, got '{result}'. "
                f"Methods: {[obj.mesh_method for obj in objects_with_mesh]}"
            )
        else:
            # At least one fallback but meshes exist → degraded
            assert result == "degraded", (
                f"Expected 'degraded' when fallback methods used, got '{result}'. "
                f"Methods: {[obj.mesh_method for obj in objects_with_mesh]}"
            )


# ---------------------------------------------------------------------------
# Strategies for Property 16
# ---------------------------------------------------------------------------

# Random dimension values (0.01 to 5.0 meters)
dimension_values = st.floats(
    min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False
)

# Random material categories
material_categories = st.sampled_from(
    ["wood", "metal", "glass", "fabric", "ceramic", "plastic"]
)


@st.composite
def object_dimensions(draw: st.DrawFn) -> tuple[float, float, float]:
    """Generate random object dimensions (width, height, depth) in meters."""
    w = draw(dimension_values)
    h = draw(dimension_values)
    d = draw(dimension_values)
    return (w, h, d)


def _make_physics_test_entry(
    dims: tuple[float, float, float],
    material: str,
) -> ObjectManifestEntry:
    """Create an ObjectManifestEntry for physics mode testing."""
    return ObjectManifestEntry(
        mask_id="test-obj-001",
        bbox_px=(0, 0, 100, 100),
        area_px=10000,
        centroid_px=(50.0, 50.0),
        object_png_path=Path("test_obj.png"),
        mesh_path=Path("test_obj.glb"),
        mesh_method="placeholder",
        mesh_gen_time_s=0.1,
        audio_path=None,
        audio_method=None,
        material_category=material,
        scale_m=dims,
        scale_confidence=0.9,
        position_m=(0.0, 0.0, 0.0),
        rotation_deg=(0.0, 0.0, 0.0),
        settled=True,
        collision_method="bounding_box",
        lod_levels=4,
        fallbacks_triggered=[],
    )


def _make_room_mesh_result() -> RoomMeshResult:
    """Create a minimal RoomMeshResult for assembler initialization."""
    return RoomMeshResult(
        mesh_path=Path("room.glb"),
        dimensions_m=(10.0, 3.0, 10.0),
        vertex_count=100,
        face_count=50,
        used_heuristic=False,
    )


# ---------------------------------------------------------------------------
# Property 16: Physics Mode Assignment from Material and Volume
# ---------------------------------------------------------------------------


class TestPhysicsModeAssignment:
    """Property 16: Physics Mode Assignment from Material and Volume.

    **Validates: Requirements 8.4**

    For any object with mass > 50kg → STATIC; mass ≤ 50kg and not
    architectural → DYNAMIC with mass = volume × density (±tolerance).
    """

    @given(
        dims=object_dimensions(),
        material=material_categories,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_heavy_objects_always_static(
        self,
        dims: tuple[float, float, float],
        material: str,
    ):
        """Objects with mass > 50kg always get STATIC body mode."""
        mass = _estimate_mass_kg(dims, material)

        if mass <= _STATIC_MASS_THRESHOLD_KG:
            return  # Skip — this test only covers heavy objects

        obj = _make_physics_test_entry(dims, material)

        assembler = PhotoWorldContractAssembler(
            session_id="test-session",
            room_mesh=_make_room_mesh_result(),
            objects=[obj],
        )
        contract = assembler.assemble()

        assert len(contract.physics.intents) == 1
        physics_intent = contract.physics.intents[0]

        assert physics_intent.body_mode == BodyMode.STATIC, (
            f"Expected STATIC for mass={mass:.2f}kg (> {_STATIC_MASS_THRESHOLD_KG}kg), "
            f"got {physics_intent.body_mode} "
            f"(dims={dims}, material={material})"
        )
        assert physics_intent.mass_kg == 0.0, (
            f"Expected mass_kg=0.0 for STATIC object, "
            f"got {physics_intent.mass_kg} "
            f"(dims={dims}, material={material})"
        )

    @given(
        dims=object_dimensions(),
        material=material_categories,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_light_non_architectural_objects_dynamic(
        self,
        dims: tuple[float, float, float],
        material: str,
    ):
        """Objects with mass ≤ 50kg and not architectural get DYNAMIC with correct mass."""
        mass = _estimate_mass_kg(dims, material)

        if mass > _STATIC_MASS_THRESHOLD_KG:
            return  # Skip — only covers light objects

        obj = _make_physics_test_entry(dims, material)
        category = _infer_category(obj)

        if category == "architectural":
            return  # Skip — architectural objects handled separately

        assembler = PhotoWorldContractAssembler(
            session_id="test-session",
            room_mesh=_make_room_mesh_result(),
            objects=[obj],
        )
        contract = assembler.assemble()

        assert len(contract.physics.intents) == 1
        physics_intent = contract.physics.intents[0]

        assert physics_intent.body_mode == BodyMode.DYNAMIC, (
            f"Expected DYNAMIC for mass={mass:.2f}kg (≤ {_STATIC_MASS_THRESHOLD_KG}kg), "
            f"category={category}, got {physics_intent.body_mode} "
            f"(dims={dims}, material={material})"
        )

        # mass_kg should equal volume × density (within tolerance)
        volume = dims[0] * dims[1] * dims[2]
        density = MATERIAL_DENSITIES[material]
        expected_mass = volume * density
        rounded_expected = round(expected_mass, 3)
        # When rounded mass is 0.0, assembler clamps to 0.001 minimum
        final_expected = rounded_expected if rounded_expected > 0 else 0.001

        assert abs(physics_intent.mass_kg - final_expected) <= 0.01, (
            f"Expected mass_kg≈{final_expected} (vol={volume:.6f} × "
            f"density={density}), got {physics_intent.mass_kg} "
            f"(dims={dims}, material={material})"
        )

    @given(
        dims=object_dimensions(),
        material=material_categories,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_architectural_objects_always_static(
        self,
        dims: tuple[float, float, float],
        material: str,
    ):
        """Objects classified as architectural always get STATIC body mode."""
        obj = _make_physics_test_entry(dims, material)
        category = _infer_category(obj)

        if category != "architectural":
            return  # Skip — only covers architectural classification

        assembler = PhotoWorldContractAssembler(
            session_id="test-session",
            room_mesh=_make_room_mesh_result(),
            objects=[obj],
        )
        contract = assembler.assemble()

        assert len(contract.physics.intents) == 1
        physics_intent = contract.physics.intents[0]

        assert physics_intent.body_mode == BodyMode.STATIC, (
            f"Expected STATIC for architectural object, "
            f"got {physics_intent.body_mode} "
            f"(dims={dims}, material={material}, category={category})"
        )
        assert physics_intent.mass_kg == 0.0, (
            f"Expected mass_kg=0.0 for STATIC architectural object, "
            f"got {physics_intent.mass_kg} "
            f"(dims={dims}, material={material})"
        )


# ---------------------------------------------------------------------------
# Strategies for Property 15: WorldContract Assembly Validity
# ---------------------------------------------------------------------------

# Room dimensions (positive, reasonable values in meters)
room_dimension_values = st.floats(
    min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False
)

# Object scale (positive, reasonable values in meters)
object_scale_values = st.floats(
    min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False
)

# Position values in meters (reasonable room-interior positions)
position_values = st.floats(
    min_value=-25.0, max_value=25.0, allow_nan=False, allow_infinity=False
)

# Rotation degrees
rotation_values = st.floats(
    min_value=0.0, max_value=360.0, allow_nan=False, allow_infinity=False
)

# Valid material categories for objects
valid_material_categories = st.sampled_from(
    ["wood", "metal", "glass", "fabric", "ceramic", "plastic"]
)

# Valid mask IDs: ASCII alphanumeric only, matching ^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$
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
        used_heuristic=False,
    )


@st.composite
def valid_object_manifest_entries(
    draw: st.DrawFn, mask_id: str
) -> ObjectManifestEntry:
    """Generate a valid ObjectManifestEntry for assembly testing.

    Always has a mesh_path (only objects with meshes contribute to the contract).
    Uses the provided mask_id for uniqueness.
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
    # Generate unique mask_ids first
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
    # Sun direction: each component -1 to 1, at least one non-zero
    dx = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    dy = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    dz = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    # Ensure at least one component is non-zero
    if dx == 0.0 and dy == 0.0 and dz == 0.0:
        dy = -1.0

    color_temp = draw(st.integers(min_value=1800, max_value=12000))
    intensity = draw(st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False))
    ambient_intensity = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    # Valid hex color for ambient
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
# Property 15: WorldContract Assembly Validity
# ---------------------------------------------------------------------------


class TestWorldContractAssemblyValidity:
    """Property 15: WorldContract Assembly Validity.

    **Validates: Requirements 8.1, 8.2, 8.3**

    For any valid combination of stage outputs (room mesh + zero or more object
    meshes + light params + camera), assembled WorldContract passes all Pydantic
    validators (coordinate system, ID uniqueness, dangling references).
    """

    @given(
        room_mesh=room_mesh_results(),
        objects=unique_object_lists(),
        light_estimate=st.one_of(st.none(), light_estimate_results()),
        image_width=st.integers(min_value=100, max_value=8000),
        image_height=st.integers(min_value=100, max_value=8000),
        vertical_fov=st.floats(min_value=10.0, max_value=170.0, allow_nan=False, allow_infinity=False),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_assembled_contract_is_valid_world_contract(
        self,
        room_mesh: RoomMeshResult,
        objects: list[ObjectManifestEntry],
        light_estimate: LightEstimateResult | None,
        image_width: int,
        image_height: int,
        vertical_fov: float,
    ) -> None:
        """Assembled WorldContract always passes Pydantic validation."""
        assembler = PhotoWorldContractAssembler(
            session_id="pbt-session-015",
            room_mesh=room_mesh,
            objects=objects,
            light_estimate=light_estimate,
            image_width_px=image_width,
            image_height_px=image_height,
            vertical_fov_deg=vertical_fov,
        )

        # Should not raise ValidationError
        contract = assembler.assemble()

        # Verify the result is a WorldContract instance
        assert isinstance(contract, WorldContract)

        # Verify coordinate system is correct
        assert contract.coordinate_system == "right-handed-x-right-y-up-z-depth"

        # Verify all instance IDs are unique
        instance_ids = [inst.id for inst in contract.instances]
        assert len(instance_ids) == len(set(instance_ids)), (
            f"Duplicate instance IDs found: {instance_ids}"
        )

        # Verify all physics intent subject_ids reference existing instances
        instance_id_set = {inst.id for inst in contract.instances}
        for intent in contract.physics.intents:
            assert intent.subject_id in instance_id_set, (
                f"Physics intent {intent.id} references non-existent "
                f"instance {intent.subject_id}. "
                f"Available: {instance_id_set}"
            )

        # Verify all instance material_ids reference existing materials
        material_id_set = {mat.id for mat in contract.materials}
        for inst in contract.instances:
            assert inst.material_id in material_id_set, (
                f"Instance {inst.id} references non-existent "
                f"material {inst.material_id}. "
                f"Available: {material_id_set}"
            )

        # Verify room material IDs reference existing materials
        assert contract.room.floor_material_id in material_id_set, (
            f"Room floor_material_id {contract.room.floor_material_id} "
            f"not in materials: {material_id_set}"
        )
        assert contract.room.wall_material_id in material_id_set, (
            f"Room wall_material_id {contract.room.wall_material_id} "
            f"not in materials: {material_id_set}"
        )
        assert contract.room.ceiling_material_id in material_id_set, (
            f"Room ceiling_material_id {contract.room.ceiling_material_id} "
            f"not in materials: {material_id_set}"
        )
