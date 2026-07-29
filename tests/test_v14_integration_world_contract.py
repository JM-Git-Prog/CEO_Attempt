"""Integration tests for end-to-end V14 WorldContract production.

Tests the V14WorldContractAssembler with 5 diverse objects covering:
- 2 Hunyuan3D meshes (wood, metal materials)
- 1 Trellis2 mesh (glass)
- 1 Placeholder (plastic)
- 1 Architectural element (static override)

Verifies field mapping, physics intent values, asset references,
V3-V13 coexistence, Pydantic round-trip, and UPBGE compilation path.

Requirements: 12.2, 12.3, 12.5
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.photo_pipeline.models_v14 import (
    MaterialPassResult,
    PhysicsClassification,
    RoomShellResult,
    SemanticLabel,
    V14ObjectEntry,
)
from src.photo_pipeline.stages.assembler_v14 import V14WorldContractAssembler
from src.world_contract import (
    BodyMode,
    WorldContract,
    WorldInstance,
    build_world_contract,
    canonical_world_contract,
    world_contract_from_json,
)


# ---------------------------------------------------------------------------
# Test fixture: 5 diverse objects
# ---------------------------------------------------------------------------

_SESSION_ID = "photo-v14-integration-test-001"
_SOURCE_HASH = "a1b2c3d4e5f6" + "0" * 52  # 64-char SHA-256 placeholder


def _room_shell() -> RoomShellResult:
    """Standard room shell: 5m wide × 2.7m tall × 6m deep."""
    return RoomShellResult(
        mesh_path=Path("/tmp/integration/room_shell.glb"),
        dimensions_m=(5.0, 2.7, 6.0),
        vertex_count=80000,
        face_count=75000,
        grid_resolution=(400, 500),
        faces_removed_gradient=200,
        used_fallback=False,
    )


def _obj_wood_chair() -> V14ObjectEntry:
    """Object 1: Hunyuan3D wood chair — dynamic, light (3.6 kg)."""
    return V14ObjectEntry(
        mask_id="obj_01",
        semantic_label=SemanticLabel(
            semantic_label="wooden dining chair",
            primary_material="wood",
            category="props",
            estimated_era="mid-century modern",
            condition="worn",
            is_architectural=False,
        ),
        mesh_path=Path("/tmp/integration/obj_01.glb"),
        mesh_method="hunyuan3d_v2.1",
        mesh_generation_time_s=72.5,
        face_count=45000,
        vertex_count=23000,
        dimensions_m=(0.45, 0.85, 0.45),
        position_m=(1.0, 0.425, -2.0),
        rotation_deg=(0.0, 30.0, 0.0),
        physics=PhysicsClassification(
            body_mode="DYNAMIC",
            mass_kg=3.6,
            volume_m3=0.006,
            material_density=600.0,
            friction=0.5,
            restitution=0.2,
            can_topple=True,
            override_reason=None,
        ),
        material_pass1=MaterialPassResult(
            object_id="obj_01",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=False,
            texture_resolution=(512, 512),
        ),
        material_pass2=None,
        asset_warehouse_path=Path("/tmp/assets/props/wooden_dining_chair_abc123_obj_01.glb"),
        asset_registry_id="asset:obj_01",
    )


def _obj_metal_lamp() -> V14ObjectEntry:
    """Object 2: Hunyuan3D metal lamp — dynamic, light (2.4 kg)."""
    return V14ObjectEntry(
        mask_id="obj_02",
        semantic_label=SemanticLabel(
            semantic_label="brushed steel desk lamp",
            primary_material="metal",
            category="hard-surface",
            estimated_era="contemporary",
            condition="new",
            is_architectural=False,
        ),
        mesh_path=Path("/tmp/integration/obj_02.glb"),
        mesh_method="hunyuan3d_v2.1",
        mesh_generation_time_s=65.0,
        face_count=32000,
        vertex_count=16000,
        dimensions_m=(0.15, 0.45, 0.15),
        position_m=(-1.2, 0.8, -1.5),
        rotation_deg=(0.0, 0.0, 0.0),
        physics=PhysicsClassification(
            body_mode="DYNAMIC",
            mass_kg=2.4,
            volume_m3=0.0003,
            material_density=7800.0,
            friction=0.5,
            restitution=0.2,
            can_topple=True,
            override_reason=None,
        ),
        material_pass1=MaterialPassResult(
            object_id="obj_02",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=False,
            texture_resolution=(256, 256),
        ),
        material_pass2=MaterialPassResult(
            object_id="obj_02",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=True,
            texture_resolution=(512, 512),
        ),
        asset_warehouse_path=Path("/tmp/assets/hard-surface/brushed_steel_desk_lamp_abc123_obj_02.glb"),
        asset_registry_id="asset:obj_02",
    )


def _obj_glass_vase() -> V14ObjectEntry:
    """Object 3: Trellis2 glass vase — dynamic, light (1.5 kg)."""
    return V14ObjectEntry(
        mask_id="obj_03",
        semantic_label=SemanticLabel(
            semantic_label="crystal flower vase",
            primary_material="glass",
            category="set-dressing",
            estimated_era="art deco",
            condition="new",
            is_architectural=False,
        ),
        mesh_path=Path("/tmp/integration/obj_03.glb"),
        mesh_method="trellis2",
        mesh_generation_time_s=28.0,
        face_count=12000,
        vertex_count=6500,
        dimensions_m=(0.12, 0.30, 0.12),
        position_m=(0.5, 0.75, -2.5),
        rotation_deg=(0.0, 15.0, 0.0),
        physics=PhysicsClassification(
            body_mode="DYNAMIC",
            mass_kg=1.5,
            volume_m3=0.0006,
            material_density=2500.0,
            friction=0.5,
            restitution=0.2,
            can_topple=True,
            override_reason=None,
        ),
        material_pass1=MaterialPassResult(
            object_id="obj_03",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(256, 256),
        ),
        material_pass2=None,
        asset_warehouse_path=Path("/tmp/assets/set-dressing/crystal_flower_vase_abc123_obj_03.glb"),
        asset_registry_id="asset:obj_03",
    )


def _obj_placeholder_box() -> V14ObjectEntry:
    """Object 4: Placeholder plastic storage box — dynamic, light (0.9 kg)."""
    return V14ObjectEntry(
        mask_id="obj_04",
        semantic_label=SemanticLabel(
            semantic_label="plastic storage container",
            primary_material="plastic",
            category="props",
            estimated_era="modern",
            condition="new",
            is_architectural=False,
        ),
        mesh_path=Path("/tmp/integration/obj_04.glb"),
        mesh_method="placeholder",
        mesh_generation_time_s=0.5,
        face_count=12,
        vertex_count=8,
        dimensions_m=(0.4, 0.3, 0.5),
        position_m=(-0.8, 0.15, -3.0),
        rotation_deg=(0.0, 0.0, 0.0),
        physics=PhysicsClassification(
            body_mode="DYNAMIC",
            mass_kg=0.9,
            volume_m3=0.001,
            material_density=950.0,
            friction=0.5,
            restitution=0.2,
            can_topple=True,
            override_reason=None,
        ),
        material_pass1=MaterialPassResult(
            object_id="obj_04",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(256, 256),
        ),
        material_pass2=None,
        asset_warehouse_path=None,
        asset_registry_id=None,
    )


def _obj_architectural_shelf() -> V14ObjectEntry:
    """Object 5: Architectural built-in shelf — static override (heavy, 80 kg)."""
    return V14ObjectEntry(
        mask_id="obj_05",
        semantic_label=SemanticLabel(
            semantic_label="built-in wall shelving unit",
            primary_material="wood",
            category="architecture",
            estimated_era="modern",
            condition="new",
            is_architectural=True,
        ),
        mesh_path=Path("/tmp/integration/obj_05.glb"),
        mesh_method="hunyuan3d_v2.1",
        mesh_generation_time_s=85.0,
        face_count=52000,
        vertex_count=26000,
        dimensions_m=(1.8, 2.2, 0.35),
        position_m=(2.0, 1.1, -2.8),
        rotation_deg=(0.0, 0.0, 0.0),
        physics=PhysicsClassification(
            body_mode="STATIC",
            mass_kg=0.0,
            volume_m3=1.386,
            material_density=600.0,
            friction=0.6,
            restitution=0.1,
            can_topple=False,
            override_reason="architectural_function",
        ),
        material_pass1=MaterialPassResult(
            object_id="obj_05",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=False,
            texture_resolution=(1024, 1024),
        ),
        material_pass2=None,
        asset_warehouse_path=Path("/tmp/assets/architecture/built_in_wall_shelving_abc123_obj_05.glb"),
        asset_registry_id="asset:obj_05",
    )


@pytest.fixture
def diverse_objects() -> list[V14ObjectEntry]:
    """5 diverse V14 objects for integration testing."""
    return [
        _obj_wood_chair(),
        _obj_metal_lamp(),
        _obj_glass_vase(),
        _obj_placeholder_box(),
        _obj_architectural_shelf(),
    ]


@pytest.fixture
def assembled_contract(diverse_objects: list[V14ObjectEntry]) -> WorldContract:
    """Pre-assembled WorldContract from 5 diverse objects."""
    assembler = V14WorldContractAssembler(
        session_id=_SESSION_ID,
        room_shell=_room_shell(),
        objects=diverse_objects,
        source_image_hash=_SOURCE_HASH,
        image_width_px=1920,
        image_height_px=1080,
    )
    return assembler.assemble()


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestEndToEndWorldContractProduction:
    """Integration tests verifying complete WorldContract production with 5 objects."""

    # 1. Real meshes → geometry_strategy="asset" with asset_registry_id

    def test_real_meshes_geometry_strategy_asset(
        self, assembled_contract: WorldContract
    ):
        """Hunyuan3D and Trellis2 meshes produce geometry_strategy='asset'
        with valid asset_registry_id."""
        real_mesh_ids = {"obj:obj_01", "obj:obj_02", "obj:obj_03", "obj:obj_05"}

        for instance in assembled_contract.instances:
            if instance.id in real_mesh_ids:
                assert instance.geometry_strategy == "asset", (
                    f"{instance.id} should have geometry_strategy='asset'"
                )
                assert instance.asset_registry_id is not None, (
                    f"{instance.id} must have asset_registry_id"
                )
                assert instance.primitive_shape is None, (
                    f"{instance.id} should not have primitive_shape"
                )

    # 2. Placeholder → geometry_strategy="primitive"

    def test_placeholder_geometry_strategy_primitive(
        self, assembled_contract: WorldContract
    ):
        """Placeholder object produces geometry_strategy='primitive'
        with a primitive_shape and no asset_registry_id."""
        placeholder_instance = next(
            i for i in assembled_contract.instances if i.id == "obj:obj_04"
        )
        assert placeholder_instance.geometry_strategy == "primitive"
        assert placeholder_instance.primitive_shape is not None
        assert placeholder_instance.primitive_shape in (
            "box", "cylinder", "sphere", "capsule"
        )
        assert placeholder_instance.asset_registry_id is None

    # 3. All physics intents have collision_shape="mesh"

    def test_all_physics_intents_collision_shape_mesh(
        self, assembled_contract: WorldContract
    ):
        """All V14 physics intents use collision_shape='mesh' for real geometry."""
        assert len(assembled_contract.physics.intents) == 5
        for intent in assembled_contract.physics.intents:
            assert intent.collision_shape == "mesh", (
                f"Physics intent {intent.id} should have collision_shape='mesh'"
            )

    # 4. Dynamic objects (mass ≤ 25kg) → body_mode=DYNAMIC, can_topple=True

    def test_dynamic_objects_body_mode_and_topple(
        self, assembled_contract: WorldContract
    ):
        """Light objects (wood chair, metal lamp, glass vase, plastic box)
        have DYNAMIC body_mode and can_topple=True."""
        dynamic_subjects = {"obj:obj_01", "obj:obj_02", "obj:obj_03", "obj:obj_04"}

        for intent in assembled_contract.physics.intents:
            if intent.subject_id in dynamic_subjects:
                assert intent.body_mode == BodyMode.DYNAMIC, (
                    f"{intent.subject_id} should be DYNAMIC"
                )
                assert intent.can_topple is True, (
                    f"{intent.subject_id} should be toppleable"
                )
                assert intent.mass_kg > 0, (
                    f"{intent.subject_id} dynamic body must have positive mass"
                )

    # 5. Static objects (mass > 25kg or architectural) → body_mode=STATIC

    def test_static_objects_body_mode_and_topple(
        self, assembled_contract: WorldContract
    ):
        """Architectural shelf (static override) has STATIC body_mode
        and can_topple=False."""
        static_intent = next(
            p for p in assembled_contract.physics.intents
            if p.subject_id == "obj:obj_05"
        )
        assert static_intent.body_mode == BodyMode.STATIC
        assert static_intent.can_topple is False
        assert static_intent.mass_kg == 0.0

    # 6. Room shell dimensions are correct

    def test_room_shell_dimensions_correct(
        self, assembled_contract: WorldContract
    ):
        """Room shell dimensions match input: 5.0m × 2.7m × 6.0m."""
        room = assembled_contract.room
        assert room.dimensions.width_m == 5.0
        assert room.dimensions.height_m == 2.7
        assert room.dimensions.depth_m == 6.0

    # 7. Materials have valid metallic/roughness values per material type

    def test_materials_valid_pbr_values_by_type(
        self, assembled_contract: WorldContract
    ):
        """Material intents have physically plausible metallic/roughness values.
        - Metal material → metallic=0.3
        - Non-metal materials → metallic=0.0
        - All roughness in [0.0, 1.0]
        """
        # Metal lamp material
        lamp_instance = next(
            i for i in assembled_contract.instances if i.id == "obj:obj_02"
        )
        lamp_material = next(
            m for m in assembled_contract.materials if m.id == lamp_instance.material_id
        )
        assert lamp_material.metallic == 0.3, "Metal should have metallic=0.3"
        assert 0.0 <= lamp_material.roughness <= 1.0

        # Wood chair material (non-metal)
        chair_instance = next(
            i for i in assembled_contract.instances if i.id == "obj:obj_01"
        )
        chair_material = next(
            m for m in assembled_contract.materials if m.id == chair_instance.material_id
        )
        assert chair_material.metallic == 0.0, "Wood should have metallic=0.0"
        assert 0.0 <= chair_material.roughness <= 1.0

        # Glass vase material (non-metal)
        vase_instance = next(
            i for i in assembled_contract.instances if i.id == "obj:obj_03"
        )
        vase_material = next(
            m for m in assembled_contract.materials if m.id == vase_instance.material_id
        )
        assert vase_material.metallic == 0.0, "Glass should have metallic=0.0"
        assert vase_material.roughness == pytest.approx(0.1), (
            "Glass should have low roughness (~0.1)"
        )

    # 8. Contract is valid Pydantic model (round-trip)

    def test_contract_pydantic_round_trip(
        self, assembled_contract: WorldContract
    ):
        """WorldContract model_dump_json → model_validate_json round-trip
        produces identical contract."""
        json_bytes = assembled_contract.model_dump_json()
        restored = WorldContract.model_validate_json(json_bytes)

        # Structural equality via content hash
        assert restored.content_hash() == assembled_contract.content_hash()

        # Field-level checks
        assert len(restored.instances) == len(assembled_contract.instances)
        assert len(restored.physics.intents) == len(assembled_contract.physics.intents)
        assert restored.room.dimensions == assembled_contract.room.dimensions
        assert restored.source.interface_version == 14
        assert restored.source.session_id == _SESSION_ID

    # 9. V3-V13 coexistence: no import conflicts, interface_version=14

    def test_v3_v13_import_coexistence(self):
        """Importing V14 modules does not break existing V3-V13 imports.
        Both the V14 assembler and the legacy build_world_contract coexist."""
        # V14 imports work
        from src.photo_pipeline.stages.assembler_v14 import V14WorldContractAssembler  # noqa: F811
        from src.photo_pipeline.models_v14 import V14ObjectEntry  # noqa: F811

        # Legacy build_world_contract is still importable
        from src.world_contract import build_world_contract  # noqa: F811

        # Both are callable (don't actually call build_world_contract — it needs
        # FloorPlan/SceneGraph which are V3-V13 specific)
        assert callable(V14WorldContractAssembler)
        assert callable(build_world_contract)

    def test_interface_version_14_in_source_binding(
        self, assembled_contract: WorldContract
    ):
        """Source binding carries interface_version=14 for V14 sessions."""
        assert assembled_contract.source.interface_version == 14
        assert assembled_contract.source.session_id == _SESSION_ID
        assert assembled_contract.source.profile_id == "photo-pipeline-v14"

    # 10. UPBGE compilation path: canonical_bytes() and content_hash() work

    def test_upbge_canonical_bytes_and_content_hash(
        self, assembled_contract: WorldContract
    ):
        """UPBGE compilation path requires canonical_bytes() and content_hash().
        Both must work on the assembled V14 contract."""
        # canonical_bytes produces valid UTF-8 JSON bytes
        canonical = assembled_contract.canonical_bytes()
        assert isinstance(canonical, bytes)
        assert len(canonical) > 100  # Non-trivial contract

        # Bytes are valid JSON that can be re-validated
        restored = world_contract_from_json(canonical)
        assert isinstance(restored, WorldContract)

        # content_hash is stable (deterministic)
        h1 = assembled_contract.content_hash()
        h2 = assembled_contract.content_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

        # canonical_world_contract also works on the assembled contract
        canonical2 = canonical_world_contract(assembled_contract)
        assert canonical == canonical2

    def test_upbge_canonical_bytes_round_trip_integrity(
        self, assembled_contract: WorldContract
    ):
        """Canonical bytes → parse → canonical bytes produces identical output
        (idempotent serialization for UPBGE)."""
        canonical1 = assembled_contract.canonical_bytes()
        restored = world_contract_from_json(canonical1)
        canonical2 = restored.canonical_bytes()
        assert canonical1 == canonical2

    # Additional integration checks

    def test_all_five_objects_present(
        self, assembled_contract: WorldContract
    ):
        """All 5 diverse objects are present as instances in the contract."""
        assert len(assembled_contract.instances) == 5
        ids = {i.id for i in assembled_contract.instances}
        expected = {"obj:obj_01", "obj:obj_02", "obj:obj_03", "obj:obj_04", "obj:obj_05"}
        assert ids == expected

    def test_physics_intents_match_instances(
        self, assembled_contract: WorldContract
    ):
        """Each instance has a corresponding physics intent with matching subject_id."""
        instance_ids = {i.id for i in assembled_contract.instances}
        physics_subjects = {p.subject_id for p in assembled_contract.physics.intents}
        assert physics_subjects == instance_ids

    def test_material_references_valid(
        self, assembled_contract: WorldContract
    ):
        """All instance material_id references exist in the materials list."""
        material_ids = {m.id for m in assembled_contract.materials}
        for instance in assembled_contract.instances:
            assert instance.material_id in material_ids, (
                f"{instance.id} references missing material {instance.material_id}"
            )

    def test_category_mapping_correct(
        self, assembled_contract: WorldContract
    ):
        """Categories map correctly from V14 semantic to WorldContract categories.
        - props → furniture
        - hard-surface → fixture
        - set-dressing → decor
        - architecture (is_architectural=True) → architectural
        """
        category_map = {
            i.id: i.category for i in assembled_contract.instances
        }
        # Wood chair (props, not architectural) → furniture
        assert category_map["obj:obj_01"] == "furniture"
        # Metal lamp (hard-surface) → fixture
        assert category_map["obj:obj_02"] == "fixture"
        # Glass vase (set-dressing) → decor
        assert category_map["obj:obj_03"] == "decor"
        # Plastic box (props) → furniture
        assert category_map["obj:obj_04"] == "furniture"
        # Architectural shelf (is_architectural=True) → architectural
        assert category_map["obj:obj_05"] == "architectural"

    def test_room_materials_present(
        self, assembled_contract: WorldContract
    ):
        """Room shell material references (floor, wall, ceiling) exist."""
        material_ids = {m.id for m in assembled_contract.materials}
        assert assembled_contract.room.floor_material_id in material_ids
        assert assembled_contract.room.wall_material_id in material_ids
        assert assembled_contract.room.ceiling_material_id in material_ids

    def test_export_policy_targets(
        self, assembled_contract: WorldContract
    ):
        """Export policy includes THREE_JS and UPBGE_RUNTIME targets."""
        target_values = {t.value for t in assembled_contract.exports.targets}
        assert "three_js" in target_values
        assert "upbge_runtime" in target_values
