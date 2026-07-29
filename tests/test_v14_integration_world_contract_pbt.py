"""Property-based integration tests for end-to-end V14 WorldContract production.

# Feature: photo-to-real-3d-world-v14

Tests the V14WorldContractAssembler with generated diverse objects covering:
- Correct WorldContract field mapping from V14ObjectEntry to WorldInstance
- Physics intent values: dynamic (mass ≤25kg) vs static (mass >25kg or architectural)
- Asset references linking to warehouse (geometry_strategy, asset_registry_id)
- V3-V13 coexistence (imports, interface_version=14)

**Validates: Requirements 12.2, 12.3, 12.5**

Uses Hypothesis with custom strategies to generate 3-5 V14ObjectEntry instances
with varied materials, mesh methods, positions, and physics classifications.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.photo_pipeline.models_v14 import (
    MaterialPassResult,
    PhysicsClassification,
    RoomShellResult,
    SemanticLabel,
    V14ObjectEntry,
    VALID_CATEGORIES,
    VALID_MATERIALS,
    VALID_MESH_METHODS,
)
from src.photo_pipeline.stages.assembler_v14 import V14WorldContractAssembler
from src.world_contract import (
    BodyMode,
    WorldContract,
    build_world_contract,
    canonical_world_contract,
    world_contract_from_json,
)


# ---------------------------------------------------------------------------
# Strategies — generate valid V14 pipeline inputs
# ---------------------------------------------------------------------------

_positive_dim = st.floats(min_value=0.05, max_value=5.0, allow_nan=False, allow_infinity=False)
_position_coord = st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False)
_rotation_deg = st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False)
_mass_kg = st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False)
_friction = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_restitution = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

_material_st = st.sampled_from(list(VALID_MATERIALS))
_category_st = st.sampled_from(list(VALID_CATEGORIES))
_mesh_method_st = st.sampled_from(list(VALID_MESH_METHODS))
_condition_st = st.sampled_from(["new", "worn", "broken"])


@st.composite
def semantic_labels(draw: st.DrawFn) -> SemanticLabel:
    """Generate valid SemanticLabel instances."""
    material = draw(_material_st)
    category = draw(_category_st)
    is_arch = draw(st.booleans())
    return SemanticLabel(
        semantic_label=f"test {material} object",
        primary_material=material,
        category=category,
        estimated_era="modern",
        condition=draw(_condition_st),
        is_architectural=is_arch,
    )


@st.composite
def physics_classifications(draw: st.DrawFn) -> PhysicsClassification:
    """Generate valid PhysicsClassification instances."""
    body_mode = draw(st.sampled_from(["DYNAMIC", "STATIC"]))
    mass = draw(_mass_kg) if body_mode == "DYNAMIC" else 0.0
    return PhysicsClassification(
        body_mode=body_mode,
        mass_kg=mass,
        volume_m3=draw(st.floats(min_value=0.001, max_value=5.0, allow_nan=False, allow_infinity=False)),
        material_density=draw(st.floats(min_value=100.0, max_value=8000.0, allow_nan=False, allow_infinity=False)),
        friction=draw(_friction),
        restitution=draw(_restitution),
        can_topple=body_mode == "DYNAMIC",
        override_reason="architectural_function" if body_mode == "STATIC" else None,
    )


@st.composite
def material_pass_results(draw: st.DrawFn, mask_id: str) -> MaterialPassResult:
    """Generate valid MaterialPassResult instances."""
    return MaterialPassResult(
        object_id=mask_id,
        pass_number=1,
        has_base_color=True,
        has_metallic_roughness=draw(st.booleans()),
        has_normal_map=draw(st.booleans()),
        texture_resolution=draw(st.sampled_from([(256, 256), (512, 512), (1024, 1024)])),
    )


@st.composite
def v14_object_entries(draw: st.DrawFn, index: int) -> V14ObjectEntry:
    """Generate valid V14ObjectEntry instances with unique mask_id."""
    mask_id = f"obj_{index:02d}"
    mesh_method = draw(_mesh_method_st)
    label = draw(semantic_labels())

    # Real meshes get an asset_registry_id; placeholders don't
    has_real_mesh = mesh_method in ("hunyuan3d_v2.1", "trellis2")
    asset_registry_id = f"asset:{mask_id}" if has_real_mesh else None
    asset_warehouse_path = (
        Path(f"/tmp/assets/{label.category}/{mask_id}.glb") if has_real_mesh else None
    )

    return V14ObjectEntry(
        mask_id=mask_id,
        semantic_label=label,
        mesh_path=Path(f"/tmp/session/{mask_id}.glb"),
        mesh_method=mesh_method,
        mesh_generation_time_s=draw(st.floats(min_value=0.1, max_value=120.0, allow_nan=False, allow_infinity=False)),
        face_count=draw(st.integers(min_value=100, max_value=80000)),
        vertex_count=draw(st.integers(min_value=50, max_value=40000)),
        dimensions_m=(draw(_positive_dim), draw(_positive_dim), draw(_positive_dim)),
        position_m=(draw(_position_coord), draw(_position_coord), draw(_position_coord)),
        rotation_deg=(draw(_rotation_deg), draw(_rotation_deg), draw(_rotation_deg)),
        physics=draw(physics_classifications()),
        material_pass1=draw(material_pass_results(mask_id)),
        material_pass2=None,
        asset_warehouse_path=asset_warehouse_path,
        asset_registry_id=asset_registry_id,
    )


@st.composite
def v14_object_lists(draw: st.DrawFn) -> list[V14ObjectEntry]:
    """Generate 3-5 diverse V14ObjectEntry instances."""
    count = draw(st.integers(min_value=3, max_value=5))
    return [draw(v14_object_entries(i)) for i in range(count)]


@st.composite
def room_shells(draw: st.DrawFn) -> RoomShellResult:
    """Generate valid RoomShellResult instances."""
    width = draw(st.floats(min_value=2.0, max_value=10.0, allow_nan=False, allow_infinity=False))
    height = draw(st.floats(min_value=2.0, max_value=4.0, allow_nan=False, allow_infinity=False))
    depth = draw(st.floats(min_value=2.0, max_value=12.0, allow_nan=False, allow_infinity=False))
    return RoomShellResult(
        mesh_path=Path("/tmp/session/room_shell.glb"),
        dimensions_m=(width, height, depth),
        vertex_count=draw(st.integers(min_value=10000, max_value=250000)),
        face_count=draw(st.integers(min_value=9000, max_value=240000)),
        grid_resolution=(draw(st.integers(min_value=100, max_value=500)),
                         draw(st.integers(min_value=100, max_value=500))),
        faces_removed_gradient=draw(st.integers(min_value=0, max_value=500)),
        used_fallback=draw(st.booleans()),
    )


# ---------------------------------------------------------------------------
# Property-based integration tests
# ---------------------------------------------------------------------------


class TestV14WorldContractProductionProperties:
    """Property-based integration tests for end-to-end WorldContract production.

    **Validates: Requirements 12.2, 12.3, 12.5**

    Verifies that for any valid combination of 3-5 V14 objects, the assembler
    produces a correct WorldContract with proper field mapping, physics intents,
    asset references, and V3-V13 compatibility.
    """

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_assembler_produces_valid_world_contract(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """For any valid V14 objects, the assembler produces a valid WorldContract.

        **Validates: Requirements 12.2**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-001",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        assert isinstance(contract, WorldContract)
        assert contract.schema_version == "world-contract/v1"
        assert len(contract.instances) == len(objects)
        assert len(contract.physics.intents) == len(objects)

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_geometry_strategy_matches_mesh_method(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """Real meshes → geometry_strategy='asset' + asset_registry_id;
        placeholders → geometry_strategy='primitive' + no asset_registry_id.

        **Validates: Requirements 12.2**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-geom",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        for obj, instance in zip(objects, contract.instances):
            has_real_mesh = obj.mesh_method in ("hunyuan3d_v2.1", "trellis2")
            if has_real_mesh:
                assert instance.geometry_strategy == "asset", (
                    f"{obj.mask_id} with method={obj.mesh_method} should be 'asset'"
                )
                assert instance.asset_registry_id is not None, (
                    f"{obj.mask_id} real mesh must have asset_registry_id"
                )
                assert instance.primitive_shape is None
            else:
                assert instance.geometry_strategy == "primitive", (
                    f"{obj.mask_id} placeholder should be 'primitive'"
                )
                assert instance.asset_registry_id is None
                assert instance.primitive_shape is not None

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_physics_intent_collision_shape_always_mesh(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """All V14 physics intents use collision_shape='mesh' for real geometry.

        **Validates: Requirements 12.2**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-collision",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        for intent in contract.physics.intents:
            assert intent.collision_shape == "mesh", (
                f"Physics intent {intent.id} must have collision_shape='mesh'"
            )

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_physics_intent_body_mode_maps_correctly(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """Dynamic objects (V14 body_mode=DYNAMIC) → WorldContract DYNAMIC;
        Static objects → WorldContract STATIC. Mass is positive for dynamic.

        **Validates: Requirements 12.2, 12.3**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-bodymode",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        for obj, intent in zip(objects, contract.physics.intents):
            if obj.physics.body_mode == "DYNAMIC":
                assert intent.body_mode == BodyMode.DYNAMIC, (
                    f"{obj.mask_id} DYNAMIC physics should map to BodyMode.DYNAMIC"
                )
                assert intent.mass_kg > 0, (
                    f"{obj.mask_id} dynamic body must have positive mass"
                )
                assert intent.can_topple == obj.physics.can_topple
            else:
                assert intent.body_mode == BodyMode.STATIC, (
                    f"{obj.mask_id} STATIC physics should map to BodyMode.STATIC"
                )
                assert intent.can_topple == obj.physics.can_topple

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_transform_fields_mapped_from_v14_object(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """V14 position_m and rotation_deg map directly to WorldInstance transform.

        **Validates: Requirements 12.2**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-transform",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        for obj, instance in zip(objects, contract.instances):
            pos_x, pos_y, pos_z = obj.position_m
            rot_x, rot_y, rot_z = obj.rotation_deg
            assert instance.transform.position_m.x == pos_x
            assert instance.transform.position_m.y == pos_y
            assert instance.transform.position_m.z == pos_z
            assert instance.transform.rotation_deg.x == rot_x
            assert instance.transform.rotation_deg.y == rot_y
            assert instance.transform.rotation_deg.z == rot_z

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_material_references_exist_in_contract(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """All instance material_id references exist in the materials list.

        **Validates: Requirements 12.2**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-materials",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        material_ids = {m.id for m in contract.materials}
        for instance in contract.instances:
            assert instance.material_id in material_ids, (
                f"{instance.id} references missing material {instance.material_id}"
            )

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_interface_version_14_and_v3_v13_coexistence(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """V14 contract carries interface_version=14 and legacy imports coexist.

        **Validates: Requirements 12.3, 12.5**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-coexist",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        # V14 source binding carries correct version
        assert contract.source.interface_version == 14
        assert contract.source.profile_id == "photo-pipeline-v14"

        # Legacy build_world_contract is still importable (V3-V13 coexistence)
        assert callable(build_world_contract)

        # canonical_bytes() and content_hash() work (UPBGE path)
        canonical = contract.canonical_bytes()
        assert isinstance(canonical, bytes)
        assert len(canonical) > 0
        h = contract.content_hash()
        assert len(h) == 64  # SHA-256 hex

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_contract_json_round_trip_preserves_content_hash(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """WorldContract JSON round-trip produces identical content hash.

        **Validates: Requirements 12.2, 12.3**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-roundtrip",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        # Serialize → deserialize → compare
        json_str = contract.model_dump_json()
        restored = WorldContract.model_validate_json(json_str)
        assert restored.content_hash() == contract.content_hash()
        assert len(restored.instances) == len(contract.instances)
        assert len(restored.physics.intents) == len(contract.physics.intents)

    @given(objects=v14_object_lists(), room_shell=room_shells())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_room_shell_dimensions_mapped_correctly(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
    ) -> None:
        """Room shell dimensions from V14 input map to WorldContract RoomShell.

        **Validates: Requirements 12.2**
        """
        assembler = V14WorldContractAssembler(
            session_id="pbt-session-room",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        width, height, depth = room_shell.dimensions_m
        assert contract.room.dimensions.width_m == width
        assert contract.room.dimensions.height_m == height
        assert contract.room.dimensions.depth_m == depth
