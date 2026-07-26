"""Property-based tests for WorldContract serialization round-trip (Property 12).

**Validates: Requirements 11.1**

Property 12: WorldContract Serialization Round-Trip
- For any valid WorldContract, serialize → deserialize produces structurally equal instance.
- Structural equality is verified by Pydantic model equality (all field values compare equal).
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.canonical_serialization import canonical_deserialize, canonical_serialize
from src.world_contract import (
    AppearanceIntent,
    BodyMode,
    CameraBinding,
    ExportPolicy,
    MaterialIntent,
    PhysicsIntent,
    PhysicsPolicy,
    RoomShell,
    SourceBinding,
    Transform,
    Vector3,
    Wall,
    WorldContract,
    WorldInstance,
    WorldLight,
    WorldOpening,
    canonical_world_contract,
    world_contract_from_json,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies for WorldContract sub-models
# ---------------------------------------------------------------------------

# Finite float strategies with constrained ranges
_pos_float = st.floats(min_value=0.01, max_value=50.0, allow_nan=False, allow_infinity=False)
_small_pos_float = st.floats(min_value=0.1, max_value=5.0, allow_nan=False, allow_infinity=False)
_unit_float = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_angle_float = st.floats(min_value=0.0, max_value=359.9, allow_nan=False, allow_infinity=False)
_coord_float = st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False)

# Valid IDs matching the _ID_PATTERN: ^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$
_valid_id = st.from_regex(r"[A-Za-z][A-Za-z0-9_.-]{2,15}", fullmatch=True)

# SHA-256 hash pattern
_sha256_hash = st.from_regex(r"[0-9a-f]{64}", fullmatch=True)

# Hex color
_hex_color = st.from_regex(r"#[0-9a-fA-F]{6}", fullmatch=True)


@st.composite
def vector3_st(draw: st.DrawFn) -> Vector3:
    """Generate a valid Vector3."""
    return Vector3(
        x=draw(_coord_float),
        y=draw(_coord_float),
        z=draw(_coord_float),
    )


@st.composite
def source_binding_st(draw: st.DrawFn) -> SourceBinding:
    """Generate a valid SourceBinding."""
    return SourceBinding(
        session_id=draw(_valid_id),
        interface_version=draw(st.integers(min_value=1, max_value=100)),
        profile_id=draw(_valid_id),
        plan_revision=draw(st.integers(min_value=0, max_value=100)),
        plan_hash=draw(_sha256_hash),
        scene_graph_hash=draw(_sha256_hash),
        camera_contract_id=draw(_valid_id),
        camera_contract_hash=draw(_sha256_hash),
        appearance_intent_hash=draw(_sha256_hash),
        canon_hash=draw(st.one_of(st.none(), _sha256_hash)),
    )


@st.composite
def material_intent_st(draw: st.DrawFn, material_id: str | None = None) -> MaterialIntent:
    """Generate a valid MaterialIntent."""
    return MaterialIntent(
        id=material_id or draw(_valid_id),
        base_color=draw(_hex_color),
        metallic=draw(_unit_float),
        roughness=draw(_unit_float),
        emission_color=draw(st.one_of(st.none(), _hex_color)),
        emission_strength=draw(st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def camera_binding_st(draw: st.DrawFn) -> CameraBinding:
    """Generate a valid CameraBinding with non-degenerate frustum."""
    pos = Vector3(
        x=draw(st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
        y=draw(st.floats(min_value=1.0, max_value=5.0, allow_nan=False, allow_infinity=False)),
        z=draw(st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False)),
    )
    # Target must differ from position
    target = Vector3(x=0.0, y=1.0, z=0.0)
    near = draw(st.floats(min_value=0.01, max_value=0.5, allow_nan=False, allow_infinity=False))
    far = draw(st.floats(min_value=10.0, max_value=1000.0, allow_nan=False, allow_infinity=False))

    return CameraBinding(
        id=draw(_valid_id),
        source_schema_version="camera-contract/v1",
        projection="perspective",
        position_m=pos,
        target_m=target,
        up=Vector3(x=0.0, y=1.0, z=0.0),
        vertical_fov_deg=draw(st.floats(min_value=10.0, max_value=120.0, allow_nan=False, allow_infinity=False)),
        aspect_ratio=draw(st.floats(min_value=0.5, max_value=3.0, allow_nan=False, allow_infinity=False)),
        image_width_px=draw(st.integers(min_value=320, max_value=3840)),
        image_height_px=draw(st.integers(min_value=240, max_value=2160)),
        near_plane_m=near,
        far_plane_m=far,
    )


@st.composite
def appearance_intent_st(draw: st.DrawFn) -> AppearanceIntent:
    """Generate a valid AppearanceIntent."""
    return AppearanceIntent(
        id=draw(_valid_id),
        era=draw(st.text(min_size=0, max_size=20, alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")))),
        mood=draw(st.text(min_size=0, max_size=20, alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")))),
        palette=draw(st.text(min_size=0, max_size=20, alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")))),
        architecture_notes="",
        lighting_notes="",
        key_objects=(),
        image_prompt="",
    )


@st.composite
def world_contract_st(draw: st.DrawFn) -> WorldContract:
    """Generate a valid WorldContract with consistent cross-references.

    This strategy builds a self-consistent contract where all material,
    physics, and instance references are valid.
    """
    # Room dimensions
    room_width = draw(st.floats(min_value=3.0, max_value=15.0, allow_nan=False, allow_infinity=False))
    room_height = draw(st.floats(min_value=2.5, max_value=5.0, allow_nan=False, allow_infinity=False))
    room_depth = draw(st.floats(min_value=3.0, max_value=15.0, allow_nan=False, allow_infinity=False))

    # Generate base material IDs for room surfaces
    floor_mat_id = "mat-floor"
    wall_mat_id = "mat-wall"
    ceiling_mat_id = "mat-ceiling"

    # Create room materials
    floor_mat = draw(material_intent_st(material_id=floor_mat_id))
    wall_mat = draw(material_intent_st(material_id=wall_mat_id))
    ceiling_mat = draw(material_intent_st(material_id=ceiling_mat_id))

    materials = [floor_mat, wall_mat, ceiling_mat]

    # Generate 0-3 additional instance materials
    num_instance_mats = draw(st.integers(min_value=0, max_value=3))
    instance_mat_ids = []
    for i in range(num_instance_mats):
        mat_id = f"mat-inst-{i}"
        instance_mat_ids.append(mat_id)
        materials.append(draw(material_intent_st(material_id=mat_id)))

    # Room shell
    room = RoomShell(
        id="room",
        dimensions=draw(st.just(
            __import__("src.world_contract", fromlist=["Dimensions"]).Dimensions(
                width_m=room_width, height_m=room_height, depth_m=room_depth
            )
        )),
        floor_material_id=floor_mat_id,
        wall_material_id=wall_mat_id,
        ceiling_material_id=ceiling_mat_id,
    )

    # Generate 0-2 instances with consistent references
    num_instances = draw(st.integers(min_value=0, max_value=2))
    instances = []
    physics_intents = []

    for i in range(num_instances):
        inst_id = f"inst-{i}"
        phys_id = f"phys-{i}"

        # Pick a material (use room materials if no instance materials)
        if instance_mat_ids:
            mat_id = draw(st.sampled_from(instance_mat_ids))
        else:
            mat_id = draw(st.sampled_from([floor_mat_id, wall_mat_id, ceiling_mat_id]))

        # Position safely within room
        max_dim = 1.0
        pos_x = draw(st.floats(
            min_value=-(room_width / 2 - max_dim),
            max_value=(room_width / 2 - max_dim),
            allow_nan=False, allow_infinity=False,
        ))
        pos_z = draw(st.floats(
            min_value=-(room_depth / 2 - max_dim),
            max_value=(room_depth / 2 - max_dim),
            allow_nan=False, allow_infinity=False,
        ))

        instance = WorldInstance(
            id=inst_id,
            name=f"Object {i}",
            category="furniture",
            mount="floor",
            transform=Transform(
                position_m=Vector3(x=pos_x, y=0.0, z=pos_z),
                rotation_deg=Vector3(x=0.0, y=draw(_angle_float), z=0.0),
                scale=Vector3(x=1.0, y=1.0, z=1.0),
            ),
            dimensions=__import__("src.world_contract", fromlist=["Dimensions"]).Dimensions(
                width_m=draw(st.floats(min_value=0.1, max_value=max_dim, allow_nan=False, allow_infinity=False)),
                height_m=draw(st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False)),
                depth_m=draw(st.floats(min_value=0.1, max_value=max_dim, allow_nan=False, allow_infinity=False)),
            ),
            material_id=mat_id,
            physics_intent_id=phys_id,
            primitive_shape="box",
        )
        instances.append(instance)

        # Create matching physics intent
        physics_intents.append(PhysicsIntent(
            id=phys_id,
            subject_id=inst_id,
            body_mode=BodyMode.STATIC,
            collision_shape="box",
            mass_kg=0.0,
            friction=0.5,
            restitution=0.1,
        ))

    # Physics policy
    physics = PhysicsPolicy(
        gravity_m_s2=Vector3(x=0.0, y=-9.81, z=0.0),
        intents=tuple(physics_intents),
    )

    # Camera binding
    camera = draw(camera_binding_st())

    # Appearance intent
    appearance = draw(appearance_intent_st())

    # Source binding
    source = draw(source_binding_st())

    # Export policy (use defaults)
    exports = ExportPolicy()

    return WorldContract(
        source=source,
        room=room,
        openings=(),
        instances=tuple(instances),
        materials=tuple(materials),
        lights=(),
        camera=camera,
        appearance=appearance,
        physics=physics,
        interactions=(),
        exports=exports,
    )


# ---------------------------------------------------------------------------
# Property 12: WorldContract Serialization Round-Trip
# ---------------------------------------------------------------------------


@given(contract=world_contract_st())
@settings(max_examples=200)
def test_property_12_canonical_serialize_roundtrip(contract: WorldContract):
    """Property 12: serialize → deserialize produces structurally equal WorldContract.

    **Validates: Requirements 11.1**

    For any valid WorldContract, serializing to canonical JSON bytes via
    canonical_serialize and then deserializing via canonical_deserialize
    SHALL produce a structurally equal WorldContract where every field value
    compares equal by Pydantic model equality.
    """
    # Serialize to canonical JSON bytes
    serialized = canonical_serialize(contract)

    # Deserialize back to a WorldContract instance
    deserialized = canonical_deserialize(serialized, WorldContract)

    # Structural equality: Pydantic model equality checks all field values
    assert contract == deserialized, (
        f"Round-trip failed: serialized {len(serialized)} bytes but "
        f"deserialized contract is not equal to original"
    )


@given(contract=world_contract_st())
@settings(max_examples=200)
def test_property_12_world_contract_specific_roundtrip(contract: WorldContract):
    """Property 12: canonical_world_contract → world_contract_from_json roundtrip.

    **Validates: Requirements 11.1**

    Validates the domain-specific serialization path (canonical_world_contract
    and world_contract_from_json) also preserves structural equality.
    """
    # Serialize using the WorldContract-specific canonical function
    serialized = canonical_world_contract(contract)

    # Deserialize using the WorldContract-specific loader
    deserialized = world_contract_from_json(serialized)

    # Structural equality via Pydantic model equality
    assert contract == deserialized, (
        f"Domain-specific round-trip failed: serialized {len(serialized)} bytes but "
        f"deserialized contract is not equal to original"
    )
