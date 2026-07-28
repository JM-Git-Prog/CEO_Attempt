"""Unit and property-based tests for the photo pipeline WorldContract assembler.

Tests cover:
- Room-only (minimal) assembly with zero objects
- Full assembly with objects (various materials/sizes)
- Physics intent assignment (STATIC vs DYNAMIC threshold)
- Quality classification logic
- Mass estimation with material densities
- Light mapping from LightEstimateResult
- Validation failure reporting
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.photo_pipeline.models import (
    LightEstimateResult,
    ObjectManifestEntry,
    RoomMeshResult,
)
from src.photo_pipeline.stages.assembler import (
    PhotoWorldContractAssembler,
    classify_quality,
    _estimate_mass_kg,
    MATERIAL_DENSITIES,
)
from src.world_contract import (
    BodyMode,
    ExportTarget,
    WorldContract,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _room_mesh(
    width: float = 5.0, height: float = 3.0, depth: float = 4.0
) -> RoomMeshResult:
    return RoomMeshResult(
        mesh_path=Path("/tmp/room.glb"),
        dimensions_m=(width, height, depth),
        vertex_count=100,
        face_count=50,
        used_heuristic=False,
    )


def _light_estimate() -> LightEstimateResult:
    return LightEstimateResult(
        sun_direction=(0.5, -0.7, 0.5),
        color_temperature_k=5500,
        intensity=70.0,
        ambient_intensity=0.3,
        ambient_color="#E0DDD0",
        confidence=0.85,
    )


_SENTINEL = object()


def _object_entry(
    mask_id: str = "obj001",
    material_category: str = "wood",
    mesh_method: str | None = "hunyuan3d",
    scale_m: tuple[float, float, float] = (0.5, 0.8, 0.4),
    position_m: tuple[float, float, float] = (1.0, 0.0, 1.0),
    rotation_deg: tuple[float, float, float] = (0.0, 45.0, 0.0),
    mesh_path: Path | None | object = _SENTINEL,
) -> ObjectManifestEntry:
    if mesh_path is _SENTINEL:
        mesh_path = Path(f"/tmp/{mask_id}.glb") if mesh_method is not None else None
    return ObjectManifestEntry(
        mask_id=mask_id,
        bbox_px=(100, 100, 200, 300),
        area_px=60000,
        centroid_px=(200.0, 250.0),
        object_png_path=Path(f"/tmp/{mask_id}.png"),
        mesh_path=mesh_path,
        mesh_method=mesh_method,
        mesh_gen_time_s=5.0,
        audio_path=None,
        audio_method=None,
        material_category=material_category,
        scale_m=scale_m,
        scale_confidence=0.8,
        position_m=position_m,
        rotation_deg=rotation_deg,
        settled=True,
        collision_method="vhacd",
        lod_levels=4,
    )


# ---------------------------------------------------------------------------
# Tests: classify_quality
# ---------------------------------------------------------------------------


class TestClassifyQuality:
    def test_minimal_no_objects(self) -> None:
        assert classify_quality([]) == "minimal"

    def test_minimal_no_meshes(self) -> None:
        obj = _object_entry(mesh_method=None)
        # ObjectManifestEntry with mesh_path=None
        assert classify_quality([obj]) == "minimal"

    def test_full_all_primary(self) -> None:
        objects = [
            _object_entry(mask_id="a", mesh_method="hunyuan3d"),
            _object_entry(mask_id="b", mesh_method="hunyuan3d"),
        ]
        assert classify_quality(objects) == "full"

    def test_degraded_with_fallback(self) -> None:
        objects = [
            _object_entry(mask_id="a", mesh_method="hunyuan3d"),
            _object_entry(mask_id="b", mesh_method="triposr"),
        ]
        assert classify_quality(objects) == "degraded"

    def test_degraded_all_fallback(self) -> None:
        objects = [
            _object_entry(mask_id="a", mesh_method="unique3d"),
            _object_entry(mask_id="b", mesh_method="placeholder"),
        ]
        assert classify_quality(objects) == "degraded"


# ---------------------------------------------------------------------------
# Tests: _estimate_mass_kg
# ---------------------------------------------------------------------------


class TestEstimateMassKg:
    def test_wood_cube(self) -> None:
        # 1m³ of wood = 600 kg
        mass = _estimate_mass_kg((1.0, 1.0, 1.0), "wood")
        assert mass == pytest.approx(600.0)

    def test_metal_small(self) -> None:
        # 0.1 × 0.1 × 0.1 = 0.001 m³ of metal = 7.8 kg
        mass = _estimate_mass_kg((0.1, 0.1, 0.1), "metal")
        assert mass == pytest.approx(7.8)

    def test_unknown_material_uses_default(self) -> None:
        # Unknown material uses wood density (600)
        mass = _estimate_mass_kg((1.0, 1.0, 1.0), "unknown_material")
        assert mass == pytest.approx(600.0)

    def test_glass_density(self) -> None:
        mass = _estimate_mass_kg((1.0, 1.0, 1.0), "glass")
        assert mass == pytest.approx(2500.0)

    def test_fabric_density(self) -> None:
        mass = _estimate_mass_kg((1.0, 1.0, 1.0), "fabric")
        assert mass == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Tests: Assembler — minimal (room-only)
# ---------------------------------------------------------------------------


class TestAssemblerMinimal:
    def test_room_only_produces_valid_contract(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-001",
            room_mesh=_room_mesh(),
        )
        contract = assembler.assemble()
        assert isinstance(contract, WorldContract)

    def test_room_dimensions_match(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-002",
            room_mesh=_room_mesh(width=6.0, height=2.8, depth=5.0),
        )
        contract = assembler.assemble()
        assert contract.room.dimensions.width_m == 6.0
        assert contract.room.dimensions.height_m == 2.8
        assert contract.room.dimensions.depth_m == 5.0

    def test_no_instances_or_physics(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-003",
            room_mesh=_room_mesh(),
        )
        contract = assembler.assemble()
        assert len(contract.instances) == 0
        assert len(contract.physics.intents) == 0

    def test_export_includes_upbge_runtime(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-004",
            room_mesh=_room_mesh(),
        )
        contract = assembler.assemble()
        assert ExportTarget.UPBGE_RUNTIME in contract.exports.targets

    def test_has_lights_even_without_estimate(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-005",
            room_mesh=_room_mesh(),
            light_estimate=None,
        )
        contract = assembler.assemble()
        assert len(contract.lights) >= 2


# ---------------------------------------------------------------------------
# Tests: Assembler — with objects
# ---------------------------------------------------------------------------


class TestAssemblerWithObjects:
    def test_single_object_produces_valid_contract(self) -> None:
        obj = _object_entry()
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-010",
            room_mesh=_room_mesh(),
            objects=[obj],
            light_estimate=_light_estimate(),
        )
        contract = assembler.assemble()
        assert isinstance(contract, WorldContract)
        assert len(contract.instances) == 1

    def test_object_transform_matches_layout(self) -> None:
        obj = _object_entry(
            position_m=(2.0, 0.5, 1.5),
            rotation_deg=(0.0, 90.0, 0.0),
        )
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-011",
            room_mesh=_room_mesh(),
            objects=[obj],
        )
        contract = assembler.assemble()
        instance = contract.instances[0]
        assert instance.transform.position_m.x == 2.0
        assert instance.transform.position_m.y == 0.5
        assert instance.transform.position_m.z == 1.5
        assert instance.transform.rotation_deg.y == 90.0

    def test_object_dimensions_from_scale(self) -> None:
        obj = _object_entry(scale_m=(0.6, 1.2, 0.4))
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-012",
            room_mesh=_room_mesh(),
            objects=[obj],
        )
        contract = assembler.assemble()
        instance = contract.instances[0]
        assert instance.dimensions.width_m == 0.6
        assert instance.dimensions.height_m == 1.2
        assert instance.dimensions.depth_m == 0.4

    def test_geometry_strategy_is_asset(self) -> None:
        obj = _object_entry()
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-013",
            room_mesh=_room_mesh(),
            objects=[obj],
        )
        contract = assembler.assemble()
        instance = contract.instances[0]
        assert instance.geometry_strategy == "asset"
        assert instance.asset_registry_id is not None

    def test_multiple_objects(self) -> None:
        objects = [
            _object_entry(mask_id="chair1", material_category="wood"),
            _object_entry(mask_id="table1", material_category="metal"),
            _object_entry(mask_id="vase1", material_category="ceramic", scale_m=(0.1, 0.2, 0.1)),
        ]
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-014",
            room_mesh=_room_mesh(),
            objects=objects,
        )
        contract = assembler.assemble()
        assert len(contract.instances) == 3
        assert len(contract.physics.intents) == 3

    def test_objects_without_mesh_are_skipped(self) -> None:
        objects = [
            _object_entry(mask_id="has_mesh"),
            _object_entry(mask_id="no_mesh", mesh_method=None),
        ]
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-015",
            room_mesh=_room_mesh(),
            objects=objects,
        )
        contract = assembler.assemble()
        assert len(contract.instances) == 1


# ---------------------------------------------------------------------------
# Tests: Physics intent assignment
# ---------------------------------------------------------------------------


class TestPhysicsIntentAssignment:
    def test_heavy_object_is_static(self) -> None:
        # 1m³ of metal = 7800 kg >> 50kg threshold
        obj = _object_entry(
            mask_id="heavy1",
            material_category="metal",
            scale_m=(1.0, 1.0, 1.0),
        )
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-020",
            room_mesh=_room_mesh(),
            objects=[obj],
        )
        contract = assembler.assemble()
        intent = contract.physics.intents[0]
        assert intent.body_mode == BodyMode.STATIC
        assert intent.mass_kg == 0.0

    def test_light_object_is_dynamic(self) -> None:
        # Small wood object: 0.1*0.1*0.1 * 600 = 0.6 kg
        obj = _object_entry(
            mask_id="light1",
            material_category="wood",
            scale_m=(0.1, 0.1, 0.1),
        )
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-021",
            room_mesh=_room_mesh(),
            objects=[obj],
        )
        contract = assembler.assemble()
        intent = contract.physics.intents[0]
        assert intent.body_mode == BodyMode.DYNAMIC
        assert intent.mass_kg > 0.0

    def test_50kg_boundary_object_is_dynamic(self) -> None:
        # volume = 50/600 = 0.0833 m³ for wood at exactly 50kg
        # Use slightly less volume so mass < 50
        obj = _object_entry(
            mask_id="boundary1",
            material_category="wood",
            scale_m=(0.43, 0.43, 0.43),  # 0.43³ * 600 ≈ 47.6 kg
        )
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-022",
            room_mesh=_room_mesh(),
            objects=[obj],
        )
        contract = assembler.assemble()
        intent = contract.physics.intents[0]
        assert intent.body_mode == BodyMode.DYNAMIC


# ---------------------------------------------------------------------------
# Tests: Light estimation mapping
# ---------------------------------------------------------------------------


class TestLightMapping:
    def test_with_estimate_creates_two_lights(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-030",
            room_mesh=_room_mesh(),
            light_estimate=_light_estimate(),
        )
        contract = assembler.assemble()
        assert len(contract.lights) == 2
        types = [l.light_type for l in contract.lights]
        assert "directional" in types

    def test_without_estimate_uses_fallback(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-031",
            room_mesh=_room_mesh(),
            light_estimate=None,
        )
        contract = assembler.assemble()
        assert len(contract.lights) == 2

    def test_sun_direction_mapped(self) -> None:
        est = LightEstimateResult(
            sun_direction=(0.3, -0.9, 0.3),
            color_temperature_k=4000,
            intensity=60.0,
            ambient_intensity=0.2,
            ambient_color="#DDCCBB",
            confidence=0.9,
        )
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-032",
            room_mesh=_room_mesh(),
            light_estimate=est,
        )
        contract = assembler.assemble()
        sun = next(l for l in contract.lights if l.light_type == "directional")
        assert sun.direction.x == pytest.approx(0.3)
        assert sun.direction.y == pytest.approx(-0.9)
        assert sun.direction.z == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Tests: Camera binding
# ---------------------------------------------------------------------------


class TestCameraBinding:
    def test_camera_position_and_target_differ(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-040",
            room_mesh=_room_mesh(),
        )
        contract = assembler.assemble()
        cam = contract.camera
        assert cam.position_m != cam.target_m

    def test_camera_aspect_ratio(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-041",
            room_mesh=_room_mesh(),
            image_width_px=1920,
            image_height_px=1080,
        )
        contract = assembler.assemble()
        expected_aspect = 1920 / 1080
        assert contract.camera.aspect_ratio == pytest.approx(expected_aspect)

    def test_camera_fov_custom(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-042",
            room_mesh=_room_mesh(),
            vertical_fov_deg=75.0,
        )
        contract = assembler.assemble()
        assert contract.camera.vertical_fov_deg == 75.0


# ---------------------------------------------------------------------------
# Tests: WorldContract validation integrity
# ---------------------------------------------------------------------------


class TestValidationIntegrity:
    def test_all_material_refs_exist(self) -> None:
        objects = [_object_entry(mask_id=f"obj{i}") for i in range(3)]
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-050",
            room_mesh=_room_mesh(),
            objects=objects,
        )
        contract = assembler.assemble()
        material_ids = {m.id for m in contract.materials}
        # Room materials
        assert contract.room.floor_material_id in material_ids
        assert contract.room.wall_material_id in material_ids
        assert contract.room.ceiling_material_id in material_ids
        # Instance materials
        for instance in contract.instances:
            assert instance.material_id in material_ids

    def test_all_physics_refs_exist(self) -> None:
        objects = [_object_entry(mask_id=f"obj{i}") for i in range(3)]
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-051",
            room_mesh=_room_mesh(),
            objects=objects,
        )
        contract = assembler.assemble()
        physics_ids = {p.id for p in contract.physics.intents}
        for instance in contract.instances:
            assert instance.physics_intent_id in physics_ids

    def test_physics_subject_ids_reference_instances(self) -> None:
        objects = [_object_entry(mask_id=f"obj{i}") for i in range(2)]
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-052",
            room_mesh=_room_mesh(),
            objects=objects,
        )
        contract = assembler.assemble()
        instance_ids = {inst.id for inst in contract.instances}
        for intent in contract.physics.intents:
            assert intent.subject_id in instance_ids

    def test_schema_version_correct(self) -> None:
        assembler = PhotoWorldContractAssembler(
            session_id="test-session-053",
            room_mesh=_room_mesh(),
        )
        contract = assembler.assemble()
        assert contract.schema_version == "world-contract/v1"
