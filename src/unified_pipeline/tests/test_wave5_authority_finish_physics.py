"""Cross-component and property tests for Unified Pipeline Task 5.6.

**Validates: Requirements 16.1, 16.5, 17.1, 17.5, 18.6, 18.7,
31.1-31.7, 32.2-32.4, 33.1-33.4, 34.1, and 35.2**
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings, strategies as st

from src.photo_pipeline.stages.physics_settle import PhysicsSettleResult
from src.unified_pipeline.approval_gates import ApprovalGate
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.depth_bridge import (
    CameraAnchoredSimilarity,
    DepthEvidence,
    DepthEvidenceProvenance,
)
from src.unified_pipeline.door_physics import configure_door_physics
from src.unified_pipeline.finish_pass import FinishPass
from src.unified_pipeline.models import ArtBible, MetricPlan, PlanRevision
from src.unified_pipeline.parametric_room import (
    AuthorityClaim,
    AuthorityConflictError,
    DepthDerivedMesh,
    DepthReferenceError,
    build_authoritative_parametric_room,
)
from src.unified_pipeline.physics_bridge import PlanPhysicsInput, UnifiedPhysicsClassifier
from src.unified_pipeline.physics_settle import (
    MAX_SETTLE_ITERATIONS,
    MAX_SETTLE_SECONDS,
    PLAN_BOUNDS_MARGIN_M,
    UnifiedPhysicsSettle,
    _circulation_conflicts,
    _rotated_half_extents,
)
from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
from src.unified_pipeline.plan_validator import _compute_plan_hash
from src.world_contract import (
    AppearanceIntent, BodyMode, CameraBinding, Dimensions, MaterialIntent, Mount,
    PhysicsIntent, PhysicsPolicy, RoomShell, SourceBinding, Transform, Vector3,
    WorldContract, WorldInstance, WorldOpening,
)

_HASH = "f" * 64
_PLAN_TO_WORLD_CATEGORY = {
    # Plan/semantic classification owns the "props" category. WorldContract uses
    # its own semantic taxonomy, so the test adapter translates at this boundary.
    "props": "decor",
}


def _world_plan_hash(plan: MetricPlan) -> str:
    """Expand the unified Plan's authoritative hash prefix for WorldContract."""
    payload = replace(plan, revisions=()).to_dict()
    full_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    assert full_hash.startswith(plan.revisions[-1].plan_hash)
    return full_hash


def _camera() -> CameraContract:
    return CameraContract(position=(0.0, 1.6, -1.2), target=(0.0, 1.1, 0.0))


def _plan(
    *,
    width: float = 4.0,
    depth: float = 4.0,
    revision: int = 7,
    door_id: str | None = None,
    object_id: str | None = None,
    door_parameter: float = 0.5,
) -> MetricPlan:
    door_id = door_id or str(uuid4())
    object_id = object_id or str(uuid4())
    walls = [dict(wall) for wall in _build_walls_from_dimensions(width, depth, 3.0)]
    north = next(wall for wall in walls if wall["id"] == "north")
    north["finish_fixtures"] = (
        {"id": "outlet-n", "kind": "outlet", "parameter": 0.18, "elevation_m": 0.30},
        {"id": "switch-n", "kind": "switch", "parameter": 0.82, "elevation_m": 1.20},
    )
    base = MetricPlan(
        room_dimensions=(width, depth, 3.0),
        walls=tuple(walls),
        openings=(
            {"id": door_id, "type": "door", "wall": "south", "parameter": door_parameter,
             "width": 0.9, "height": 2.1},
            {"id": "window-east", "type": "window", "wall": "east", "parameter": 0.5,
             "width": 1.0, "height": 1.1, "sill_height": 0.9},
        ),
        object_placements=(
            {"id": object_id, "object_id": object_id, "name": "cup", "category": "props",
             "x": 1.0, "y": 1.0, "width": 0.2, "height": 0.2, "depth": 0.2,
             "rotation_deg": 0.0},
        ),
        circulation_paths=(
            {"id": "entry-to-center", "start": (2.0, 0.0), "end": (2.0, depth),
             "min_width": 0.6},
        ),
        template_id="wave5-cross-component",
    )
    return replace(base, revisions=(PlanRevision(
        revision=revision,
        changed="approved normalized Wave 5 plan",
        reason="Task 5.6 test",
        plan_hash=_compute_plan_hash(base),
    ),))


def _approval(plan: MetricPlan, camera: CameraContract) -> ApprovalGate:
    gate = ApprovalGate("blockout", "plan_blockout")
    gate.present({
        "plan_revision": plan.revisions[-1].revision,
        "camera_hash": camera.compute_hash(),
    })
    gate.approve()
    return gate


def _art_bible(*exclusions: str, era: str = "1950s diner") -> ArtBible:
    return ArtBible(
        era_rules={"belongs": [era], "excludes": list(exclusions)},
        era_exclusions=tuple(exclusions),
        immutable=True,
    )


def _depth_mesh(tmp_path: Path, camera: CameraContract) -> DepthDerivedMesh:
    mesh_path = tmp_path / "aligned-depth.glb"
    mesh_path.write_bytes(b"appearance-only depth mesh")
    evidence = DepthEvidence(
        depth_map_path=str(tmp_path / "depth.npy"),
        normal_map_path=str(tmp_path / "normal.npy"),
        valid_pixel_ratio=0.9,
        depth_range_m=(0.5, 6.0),
        provenance=DepthEvidenceProvenance(
            session_id="wave5-task-5-6",
            source_image_path=str(tmp_path / "canon.png"),
            source_image_sha256="a" * 64,
            source_resolution=(1024, 768),
            depth_artifact_sha256="b" * 64,
        ),
        alignment=CameraAnchoredSimilarity(
            camera_hash=camera.compute_hash(),
            uniform_scale=1.1,
            translation_to_fit_m=(0.1, 0.0, -0.1),
        ),
        evidence_kind="aligned_appearance_reference",
    )
    return DepthDerivedMesh(mesh_path=str(mesh_path), evidence=evidence)

def _world_contract(
    plan: MetricPlan,
    camera: CameraContract,
    classification,
    *,
    position: tuple[float, float, float] | None = None,
    rotation_y: float = 0.0,
) -> WorldContract:
    placement = plan.object_placements[0]
    object_id = classification.object_id
    plan_category = classification.category
    assert plan_category == placement["category"]
    world_category = _PLAN_TO_WORLD_CATEGORY[plan_category]
    position = position or (float(placement["x"]), 1.0, float(placement["y"]))
    material_id = f"material:{object_id}"
    instance = WorldInstance(
        id=object_id,
        name="cup",
        category=world_category,
        mount=Mount.FLOOR,
        transform=Transform(
            position_m=Vector3(x=position[0], y=position[1], z=position[2]),
            rotation_deg=Vector3(x=0.0, y=rotation_y, z=0.0),
        ),
        dimensions=Dimensions(
            width_m=classification.dimensions_m[0],
            height_m=classification.dimensions_m[1],
            depth_m=classification.dimensions_m[2],
        ),
        fixed=False,
        material_id=material_id,
        physics_intent_id=f"physics:{object_id}",
        geometry_strategy="primitive",
        primitive_shape="box",
    )
    width, depth, height = plan.room_dimensions
    return WorldContract(
        source=SourceBinding(
            session_id="wave5-task-5-6",
            interface_version=16,
            profile_id="unified-v16",
            plan_revision=plan.revisions[-1].revision,
            plan_hash=_world_plan_hash(plan),
            scene_graph_hash=_HASH,
            camera_contract_id="camera-wave5",
            camera_contract_hash=camera.compute_hash(),
            appearance_intent_hash=_HASH,
        ),
        room=RoomShell(
            dimensions=Dimensions(width_m=width, height_m=height, depth_m=depth),
            floor_material_id="material:floor",
            wall_material_id="material:wall",
            ceiling_material_id="material:ceiling",
        ),
        openings=tuple(WorldOpening(
            id=str(item["id"]), kind=str(item["type"]), wall=str(item["wall"]),
            offset_m=0.0, width_m=float(item["width"]), height_m=float(item["height"]),
            sill_height_m=float(item.get("sill_height", 0.0)),
        ) for item in plan.openings),
        instances=(instance,),
        materials=(
            MaterialIntent(id="material:floor"), MaterialIntent(id="material:wall"),
            MaterialIntent(id="material:ceiling"), MaterialIntent(id=material_id),
        ),
        camera=CameraBinding(
            id="camera-wave5",
            source_schema_version="camera-contract/v1",
            position_m=Vector3(x=camera.position[0], y=camera.position[1], z=camera.position[2]),
            target_m=Vector3(x=camera.target[0], y=camera.target[1], z=camera.target[2]),
            up=Vector3(x=camera.up[0], y=camera.up[1], z=camera.up[2]),
            vertical_fov_deg=camera.vfov,
            aspect_ratio=camera.aspect,
            image_width_px=camera.raster_width,
            image_height_px=camera.raster_height,
            near_plane_m=camera.near,
            far_plane_m=camera.far,
        ),
        appearance=AppearanceIntent(id="appearance:wave5"),
        physics=PhysicsPolicy(intents=(PhysicsIntent(
            id=f"physics:{object_id}",
            subject_id=object_id,
            body_mode=BodyMode[classification.body_mode],
            mass_kg=classification.mass_kg,
            collision_shape="box",
        ),)),
    )


class _BoundedTransformSettler:
    def __init__(self, *, position=None, rotation_y: float | None = None) -> None:
        self.position = position
        self.rotation_y = rotation_y
        self.configs = []

    def settle(self, world_contract: WorldContract, config=None) -> PhysicsSettleResult:
        self.configs.append(config)
        payload = world_contract.model_dump()
        transform = payload["instances"][0]["transform"]
        if self.position is not None:
            x, y, z = self.position
            transform["position_m"] = {"x": x, "y": y, "z": z}
        if self.rotation_y is not None:
            transform["rotation_deg"] = {"x": 0.0, "y": self.rotation_y, "z": 0.0}
        changed = WorldContract.model_validate(payload)
        return PhysicsSettleResult(
            settled_world_contract=changed,
            object_info=[], total_unsettled=0, total_dynamic=1,
            iterations_run=MAX_SETTLE_ITERATIONS,
            wall_time_s=MAX_SETTLE_SECONDS,
            warning_issued=False,
        )

def test_wave5_adapters_share_authoritative_revision_camera_and_identity(tmp_path: Path) -> None:
    plan, camera = _plan(), _camera()
    revision = plan.revisions[-1]
    door_id = str(plan.openings[0]["id"])
    object_id = str(plan.object_placements[0]["id"])

    room = build_authoritative_parametric_room(
        plan, camera, _approval(plan, camera), depth_mesh=_depth_mesh(tmp_path, camera)
    )
    finish = FinishPass().run(plan, _art_bible(), approved_plan_revision=revision.revision)
    doors = configure_door_physics(plan, approved_plan_revision=revision.revision)
    physics_input = PlanPhysicsInput.from_plan_placement(
        plan_revision=revision.revision, placement=plan.object_placements[0]
    )
    classification = UnifiedPhysicsClassifier().classify(
        physics_input, {"primary_material": "fabric", "object_id": str(uuid4())}
    )
    contract = _world_contract(plan, camera, classification)
    settled = UnifiedPhysicsSettle().settle(
        plan, contract, approved_plan_revision=revision.revision
    )

    assert room.plan_revision == finish.plan_revision == doors.plan_revision == classification.plan_revision == settled.plan_revision
    assert room.plan_hash == finish.plan_hash == doors.plan_hash == revision.plan_hash
    assert room.camera_hash == camera.compute_hash() == contract.source.camera_contract_hash
    assert {item.stable_id for item in room.openings} == {str(item["id"]) for item in plan.openings}
    assert {item.geometry_id for item in room.collision} == {
        item.stable_id for item in room.elements if item.static_collision
    }
    assert door_id in {item.parent_opening_id for item in finish.primitives}
    assert doors.doors[0].opening_id == door_id
    assert physics_input.category == classification.category == "props"
    assert contract.instances[0].category == "decor"
    assert classification.object_id == object_id
    assert settled.settled_world_contract.instances[0].id == object_id
    assert settled.settled_world_contract.openings == contract.openings
    assert settled.settled_world_contract.camera == contract.camera
    assert room.depth_reference is not None
    assert room.depth_reference.collision_enabled is False
    assert room.depth_reference.spatial_authority is False
    assert settled.circulation_preserved is True
    with pytest.raises(FrozenInstanceError):
        camera.vfov = 75.0  # type: ignore[misc]


@pytest.mark.parametrize("scope", ["architecture", "openings", "collision", "camera"])
def test_dual_spatial_authority_is_rejected(scope: str) -> None:
    plan, camera = _plan(), _camera()
    with pytest.raises(AuthorityConflictError, match="more than one source"):
        build_authoritative_parametric_room(
            plan, camera, _approval(plan, camera),
            authority_claims=(AuthorityClaim("depth", (scope,)),),
        )


def test_depth_cannot_be_promoted_to_collision_or_architecture(tmp_path: Path) -> None:
    camera = _camera()
    valid = _depth_mesh(tmp_path, camera)
    with pytest.raises(DepthReferenceError, match="optional, non-colliding"):
        replace(valid, collision_enabled=True)
    with pytest.raises(DepthReferenceError, match="optional, non-colliding"):
        replace(valid, spatial_authority=True)


@pytest.mark.parametrize(
    ("era", "expected_style"),
    [("1950s diner", "period_duplex"), ("1980s kitchen", "duplex"),
     ("contemporary kitchen", "decorator_receptacle")],
)
def test_finish_generation_is_era_appropriate_and_exclusions_omit(
    era: str, expected_style: str
) -> None:
    plan = _plan()
    generated = FinishPass().run(plan, _art_bible(era=era), approved_plan_revision=7)
    outlet = next(item for item in generated.primitives if item.source_detail_id == "outlet-n")
    assert outlet.style == expected_style
    assert outlet.geometry == "quad_decal"
    assert generated.uses_csg is False

    excluded = FinishPass().run(
        plan, _art_bible("no electrical outlets visible", era=era),
        approved_plan_revision=7,
    )
    assert not any(item.source_detail_id == "outlet-n" for item in excluded.primitives)
    assert any("outlet-n omitted: excluded by ArtBible" in item for item in excluded.omitted_details)


def test_door_hinge_and_settle_use_exact_bounded_configuration() -> None:
    plan, camera = _plan(), _camera()
    door = configure_door_physics(plan, approved_plan_revision=7).doors[0]
    assert door.hinge.joint_type == "hinge"
    assert door.hinge.axis == (0.0, 1.0, 0.0)
    assert (door.hinge.lower_limit_deg, door.hinge.upper_limit_deg) == (0.0, 90.0)
    assert door.hinge.interaction_mass_kg > 0.0
    assert door.body_mode == "STATIC"

    classified = UnifiedPhysicsClassifier().classify(
        PlanPhysicsInput.from_plan_placement(plan_revision=7, placement=plan.object_placements[0]),
        {"primary_material": "fabric"},
    )
    delegate = _BoundedTransformSettler(position=(1.0, 2.0, 1.0))
    result = UnifiedPhysicsSettle(delegate).settle(
        plan, _world_contract(plan, camera, classified), approved_plan_revision=7
    )
    config = delegate.configs[0]
    assert config.physics_settle_iterations == 500
    assert config.physics_settle_timeout_s == 5.0
    assert result.legacy_result.iterations_run == 500
    assert result.legacy_result.wall_time_s == 5.0
    assert result.settled_world_contract.instances[0].transform.position_m.y == pytest.approx(0.1)


# Property 7: Stable identity.
# **Validates: Requirements 16.1, 18.6, 31.3, 34.1**
@given(
    door_uuid=st.uuids(),
    object_uuid=st.uuids(),
    revision=st.integers(min_value=1, max_value=1000),
    width=st.floats(min_value=4.0, max_value=6.0, allow_nan=False, allow_infinity=False),
    depth=st.floats(min_value=4.0, max_value=6.0, allow_nan=False, allow_infinity=False),
    door_parameter=st.floats(min_value=0.3, max_value=0.7, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=12, deadline=None)
def test_property_7_stable_uuid_revision_and_binding_across_wave5_adapters(
    door_uuid: UUID,
    object_uuid: UUID,
    revision: int,
    width: float,
    depth: float,
    door_parameter: float,
) -> None:
    plan = _plan(
        width=width, depth=depth, revision=revision,
        door_id=str(door_uuid), object_id=str(object_uuid),
        door_parameter=door_parameter,
    )
    camera = _camera()
    room = build_authoritative_parametric_room(plan, camera, _approval(plan, camera))
    finish = FinishPass().run(plan, _art_bible(), approved_plan_revision=revision)
    door = configure_door_physics(plan, approved_plan_revision=revision).doors[0]
    classified = UnifiedPhysicsClassifier().classify(
        PlanPhysicsInput.from_plan_placement(
            plan_revision=revision, placement=plan.object_placements[0]
        ),
        {"primary_material": "fabric", "uuid": str(uuid4()), "dimensions": (9, 9, 9)},
    )

    assert room.plan_revision == finish.plan_revision == door.plan_revision == revision
    assert room.camera_hash == camera.compute_hash()
    assert str(door_uuid) in {item.stable_id for item in room.openings}
    assert str(door_uuid) in {item.parent_opening_id for item in finish.primitives}
    assert door.opening_id == str(door_uuid)
    assert classified.object_id == str(object_uuid)
    assert classified.dimensions_m == (0.2, 0.2, 0.2)
    assert all(item.binding.plan_revision == revision for item in room.elements)
    assert all(item.binding.camera_hash == camera.compute_hash() for item in room.collision)


# Property 4: Three-view identity (rotation-aware spatial truth).
# **Validates: Requirements 18.7, 18.8, 31.1-31.4, 33.1, 35.2**
@given(
    object_uuid=st.uuids(),
    width=st.floats(min_value=0.1, max_value=0.4, allow_nan=False, allow_infinity=False),
    height=st.floats(min_value=0.1, max_value=0.4, allow_nan=False, allow_infinity=False),
    depth=st.floats(min_value=0.1, max_value=0.4, allow_nan=False, allow_infinity=False),
    rotation_y=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False),
    delegated_x=st.floats(min_value=-3.0, max_value=7.0, allow_nan=False, allow_infinity=False),
    delegated_z=st.floats(min_value=-3.0, max_value=7.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30, deadline=None)
def test_property_4_settle_preserves_rotation_aware_containment_overlap_and_circulation(
    object_uuid: UUID,
    width: float,
    height: float,
    depth: float,
    rotation_y: float,
    delegated_x: float,
    delegated_z: float,
) -> None:
    base = _plan(object_id=str(object_uuid))
    placement = dict(base.object_placements[0])
    placement.update({"width": width, "height": height, "depth": depth})
    unrevised = replace(base, object_placements=(placement,), revisions=())
    plan = replace(unrevised, revisions=(PlanRevision(
        revision=7, changed="generated dimensions", reason="property",
        plan_hash=_compute_plan_hash(unrevised),
    ),))
    camera = _camera()
    classified = UnifiedPhysicsClassifier().classify(
        PlanPhysicsInput.from_plan_placement(plan_revision=7, placement=placement),
        {"primary_material": "fabric"},
    )
    delegate = _BoundedTransformSettler(
        position=(delegated_x, 2.0, delegated_z), rotation_y=rotation_y
    )
    result = UnifiedPhysicsSettle(delegate).settle(
        plan, _world_contract(plan, camera, classified), approved_plan_revision=7
    )
    item = result.settled_world_contract.instances[0]
    position = item.transform.position_m
    half = _rotated_half_extents(
        (width, height, depth), (0.0, item.transform.rotation_deg.y, 0.0)
    )

    assert position.x - half[0] >= PLAN_BOUNDS_MARGIN_M - 1e-6
    assert position.x + half[0] <= 4.0 - PLAN_BOUNDS_MARGIN_M + 1e-6
    assert position.z - half[2] >= PLAN_BOUNDS_MARGIN_M - 1e-6
    assert position.z + half[2] <= 4.0 - PLAN_BOUNDS_MARGIN_M + 1e-6
    assert position.y - half[1] >= -1e-6
    assert position.y + half[1] <= 3.0 - PLAN_BOUNDS_MARGIN_M + 1e-6
    assert _circulation_conflicts(
        plan, (position.x, position.z), (half[0], half[2])
    ) == set()
    assert result.circulation_preserved is True
    assert result.settled_world_contract.instances[0].id == str(object_uuid)
