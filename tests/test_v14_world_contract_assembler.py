"""Tests for V14WorldContractAssembler — verifies correct mapping to WorldContract schema.

Validates that V14 pipeline outputs (real meshes, PBR materials, dynamic physics,
room shell) map correctly into the formal WorldContract Pydantic model used by
the UPBGE compilation path, parity gates, and export adapters.

Requirements: 12.2, 12.3, 4.6
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
from src.world_contract import BodyMode, WorldContract


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_semantic_label(
    *,
    label: str = "wooden dining chair",
    material: str = "wood",
    category: str = "props",
    era: str = "mid-century modern",
    condition: str = "worn",
    is_architectural: bool = False,
) -> SemanticLabel:
    return SemanticLabel(
        semantic_label=label,
        primary_material=material,
        category=category,
        estimated_era=era,
        condition=condition,
        is_architectural=is_architectural,
    )


def _make_physics(
    *,
    body_mode: str = "DYNAMIC",
    mass_kg: float = 4.5,
    volume_m3: float = 0.172,
    material_density: float = 600.0,
    friction: float = 0.5,
    restitution: float = 0.2,
    can_topple: bool = True,
    override_reason: str | None = None,
) -> PhysicsClassification:
    return PhysicsClassification(
        body_mode=body_mode,
        mass_kg=mass_kg,
        volume_m3=volume_m3,
        material_density=material_density,
        friction=friction,
        restitution=restitution,
        can_topple=can_topple,
        override_reason=override_reason,
    )


def _make_material_pass(
    *,
    object_id: str = "obj_01",
    pass_number: int = 1,
    has_base_color: bool = True,
    has_metallic_roughness: bool = True,
    has_normal_map: bool = False,
    texture_resolution: tuple[int, int] = (512, 512),
) -> MaterialPassResult:
    return MaterialPassResult(
        object_id=object_id,
        pass_number=pass_number,
        has_base_color=has_base_color,
        has_metallic_roughness=has_metallic_roughness,
        has_normal_map=has_normal_map,
        texture_resolution=texture_resolution,
    )


def _make_room_shell(
    *,
    dimensions_m: tuple[float, float, float] = (4.0, 2.7, 5.0),
) -> RoomShellResult:
    return RoomShellResult(
        mesh_path=Path("/tmp/session/room_shell.glb"),
        dimensions_m=dimensions_m,
        vertex_count=50000,
        face_count=48000,
        grid_resolution=(300, 400),
        faces_removed_gradient=120,
        used_fallback=False,
    )


def _make_v14_object(
    *,
    mask_id: str = "obj_01",
    mesh_method: str = "hunyuan3d_v2.1",
    dimensions_m: tuple[float, float, float] = (0.45, 0.85, 0.45),
    position_m: tuple[float, float, float] = (1.0, 0.425, -2.0),
    rotation_deg: tuple[float, float, float] = (0.0, 30.0, 0.0),
    label: SemanticLabel | None = None,
    physics: PhysicsClassification | None = None,
    asset_registry_id: str | None = "asset:obj_01",
) -> V14ObjectEntry:
    return V14ObjectEntry(
        mask_id=mask_id,
        semantic_label=label or _make_semantic_label(),
        mesh_path=Path(f"/tmp/session/{mask_id}.glb"),
        mesh_method=mesh_method,
        mesh_generation_time_s=72.5,
        face_count=45000,
        vertex_count=23000,
        dimensions_m=dimensions_m,
        position_m=position_m,
        rotation_deg=rotation_deg,
        physics=physics or _make_physics(),
        material_pass1=_make_material_pass(object_id=mask_id),
        material_pass2=None,
        asset_warehouse_path=Path(f"/tmp/assets/props/{mask_id}.glb"),
        asset_registry_id=asset_registry_id,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestV14WorldContractAssembly:
    """Test that V14 outputs produce a valid WorldContract."""

    def test_assembles_valid_contract_single_object(self):
        """Single real-mesh object maps to a valid WorldContract."""
        room_shell = _make_room_shell()
        obj = _make_v14_object()

        assembler = V14WorldContractAssembler(
            session_id="test-v14-session-001",
            room_shell=room_shell,
            objects=[obj],
            source_image_hash="a" * 64,
        )
        contract = assembler.assemble()

        assert isinstance(contract, WorldContract)
        assert contract.schema_version == "world-contract/v1"
        assert len(contract.instances) == 1
        assert len(contract.physics.intents) == 1

    def test_geometry_strategy_asset_for_real_meshes(self):
        """Hunyuan3D/Trellis2 meshes → geometry_strategy='asset'."""
        room_shell = _make_room_shell()
        obj_h = _make_v14_object(mask_id="obj_01", mesh_method="hunyuan3d_v2.1")
        obj_t = _make_v14_object(
            mask_id="obj_02",
            mesh_method="trellis2",
            asset_registry_id="asset:obj_02",
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-geom",
            room_shell=room_shell,
            objects=[obj_h, obj_t],
        )
        contract = assembler.assemble()

        for instance in contract.instances:
            assert instance.geometry_strategy == "asset"
            assert instance.asset_registry_id is not None
            assert instance.primitive_shape is None

    def test_geometry_strategy_primitive_for_placeholder(self):
        """Placeholder meshes → geometry_strategy='primitive' + primitive_shape."""
        room_shell = _make_room_shell()
        obj = _make_v14_object(
            mask_id="obj_01",
            mesh_method="placeholder",
            asset_registry_id=None,
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-placeholder",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        instance = contract.instances[0]
        assert instance.geometry_strategy == "primitive"
        assert instance.primitive_shape is not None
        assert instance.asset_registry_id is None

    def test_transform_fields_mapped_correctly(self):
        """Object position/rotation/dimensions map to Transform and Dimensions."""
        room_shell = _make_room_shell()
        obj = _make_v14_object(
            position_m=(1.5, 0.85, -2.3),
            rotation_deg=(0.0, 45.0, 0.0),
            dimensions_m=(0.6, 1.2, 0.4),
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-transform",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        instance = contract.instances[0]
        assert instance.transform.position_m.x == 1.5
        assert instance.transform.position_m.y == 0.85
        assert instance.transform.position_m.z == -2.3
        assert instance.transform.rotation_deg.y == 45.0
        assert instance.dimensions.width_m == 0.6
        assert instance.dimensions.height_m == 1.2
        assert instance.dimensions.depth_m == 0.4

    def test_physics_intent_dynamic_with_mesh_collision(self):
        """Dynamic physics → body_mode=DYNAMIC, collision_shape='mesh'."""
        room_shell = _make_room_shell()
        obj = _make_v14_object(
            physics=_make_physics(
                body_mode="DYNAMIC",
                mass_kg=4.5,
                friction=0.5,
                restitution=0.2,
                can_topple=True,
            )
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-physics-dyn",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        intent = contract.physics.intents[0]
        assert intent.body_mode == BodyMode.DYNAMIC
        assert intent.collision_shape == "mesh"
        assert intent.mass_kg == 4.5
        assert intent.friction == 0.5
        assert intent.restitution == 0.2
        assert intent.can_topple is True

    def test_physics_intent_static_with_mesh_collision(self):
        """Static physics → body_mode=STATIC, collision_shape='mesh'."""
        room_shell = _make_room_shell()
        obj = _make_v14_object(
            physics=_make_physics(
                body_mode="STATIC",
                mass_kg=0.0,
                friction=0.6,
                restitution=0.1,
                can_topple=False,
            )
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-physics-static",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        intent = contract.physics.intents[0]
        assert intent.body_mode == BodyMode.STATIC
        assert intent.collision_shape == "mesh"
        assert intent.mass_kg == 0.0
        assert intent.can_topple is False

    def test_room_shell_dimensions_mapped(self):
        """Room shell dimensions map to RoomShell.dimensions."""
        room_shell = _make_room_shell(dimensions_m=(5.5, 3.0, 6.2))

        assembler = V14WorldContractAssembler(
            session_id="test-v14-room",
            room_shell=room_shell,
            objects=[],
        )
        contract = assembler.assemble()

        assert contract.room.dimensions.width_m == 5.5
        assert contract.room.dimensions.height_m == 3.0
        assert contract.room.dimensions.depth_m == 6.2

    def test_material_intent_per_object(self):
        """Each object gets a MaterialIntent with PBR values."""
        room_shell = _make_room_shell()
        obj = _make_v14_object(
            label=_make_semantic_label(material="metal")
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-material",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        # Find the object's material
        instance = contract.instances[0]
        material = next(m for m in contract.materials if m.id == instance.material_id)
        assert material.metallic == 0.3  # Metal gets non-zero metallic
        assert 0.0 <= material.roughness <= 1.0

    def test_canonical_bytes_produces_valid_output(self):
        """Assembled contract can produce canonical bytes for UPBGE compilation."""
        room_shell = _make_room_shell()
        obj = _make_v14_object()

        assembler = V14WorldContractAssembler(
            session_id="test-v14-canonical",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        # This must succeed — UPBGE compile path depends on it
        canonical = contract.canonical_bytes()
        assert isinstance(canonical, bytes)
        assert len(canonical) > 0

        # Content hash must be consistent
        hash1 = contract.content_hash()
        hash2 = contract.content_hash()
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex

    def test_multiple_objects_produce_unique_ids(self):
        """Multiple objects get unique instance/material/physics IDs."""
        room_shell = _make_room_shell()
        objects = [
            _make_v14_object(mask_id="obj_01", asset_registry_id="asset:obj_01"),
            _make_v14_object(mask_id="obj_02", asset_registry_id="asset:obj_02"),
            _make_v14_object(mask_id="obj_03", asset_registry_id="asset:obj_03"),
        ]

        assembler = V14WorldContractAssembler(
            session_id="test-v14-multi",
            room_shell=room_shell,
            objects=objects,
        )
        contract = assembler.assemble()

        instance_ids = [i.id for i in contract.instances]
        assert len(set(instance_ids)) == 3

        physics_ids = [p.id for p in contract.physics.intents]
        assert len(set(physics_ids)) == 3

    def test_architectural_objects_map_to_architectural_category(self):
        """Architectural objects map to WorldInstance category='architectural'."""
        room_shell = _make_room_shell()
        obj = _make_v14_object(
            label=_make_semantic_label(
                label="built-in bookshelf",
                category="architecture",
                is_architectural=True,
            ),
            physics=_make_physics(
                body_mode="STATIC",
                mass_kg=0.0,
                override_reason="architectural_function",
            ),
        )

        assembler = V14WorldContractAssembler(
            session_id="test-v14-arch",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        instance = contract.instances[0]
        assert instance.category == "architectural"

    def test_contract_round_trip_via_json(self):
        """WorldContract can be serialized and deserialized (UPBGE path needs this)."""
        room_shell = _make_room_shell()
        obj = _make_v14_object()

        assembler = V14WorldContractAssembler(
            session_id="test-v14-roundtrip",
            room_shell=room_shell,
            objects=[obj],
        )
        contract = assembler.assemble()

        # Serialize to JSON
        json_str = contract.model_dump_json()

        # Deserialize back
        restored = WorldContract.model_validate_json(json_str)

        assert restored.content_hash() == contract.content_hash()

    def test_export_policy_includes_upbge_and_threejs(self):
        """Export policy includes both UPBGE_RUNTIME and THREE_JS targets."""
        room_shell = _make_room_shell()
        assembler = V14WorldContractAssembler(
            session_id="test-v14-exports",
            room_shell=room_shell,
            objects=[],
        )
        contract = assembler.assemble()

        target_values = [t.value for t in contract.exports.targets]
        assert "upbge_runtime" in target_values
        assert "three_js" in target_values

    def test_interface_version_14_in_source(self):
        """Source binding records interface_version=14."""
        room_shell = _make_room_shell()
        assembler = V14WorldContractAssembler(
            session_id="test-v14-version",
            room_shell=room_shell,
            objects=[],
        )
        contract = assembler.assemble()

        assert contract.source.interface_version == 14
