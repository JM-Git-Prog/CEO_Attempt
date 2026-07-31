"""Focused Task 5.5 tests for Plan-authoritative physics settling.

**Validates: Requirements 18.7, 18.8, 31.1-31.4, 33.1-33.4**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

import src.photo_pipeline.stages.physics_settle as legacy_settle
from src.photo_pipeline.stages.physics_settle import PhysicsSettle, PhysicsSettleResult
from src.unified_pipeline.models import MetricPlan, PlanRevision
from src.unified_pipeline.physics_settle import (
    MAX_SETTLE_ITERATIONS,
    MAX_SETTLE_SECONDS,
    PLAN_BOUNDS_MARGIN_M,
    PhysicsSettleAuthorityError,
    UnifiedPhysicsSettle,
    _circulation_conflicts,
)
from src.world_contract import (
    AppearanceIntent,
    BodyMode,
    CameraBinding,
    Dimensions,
    MaterialIntent,
    Mount,
    PhysicsIntent,
    PhysicsPolicy,
    RoomShell,
    SourceBinding,
    Transform,
    Vector3,
    WorldContract,
    WorldInstance,
    WorldOpening,
)

_HASH = "0" * 64


def _plan(*placements: dict, circulation_paths: tuple[dict, ...] = ()) -> MetricPlan:
    return MetricPlan(
        room_dimensions=(4.0, 4.0, 3.0),
        walls=(
            {"id": "north", "start": (0.0, 0.0, 0.0), "end": (4.0, 0.0, 0.0), "height": 3.0},
            {"id": "east", "start": (4.0, 0.0, 0.0), "end": (4.0, 4.0, 0.0), "height": 3.0},
            {"id": "south", "start": (4.0, 4.0, 0.0), "end": (0.0, 4.0, 0.0), "height": 3.0},
            {"id": "west", "start": (0.0, 4.0, 0.0), "end": (0.0, 0.0, 0.0), "height": 3.0},
        ),
        openings=(
            {"id": "door-n", "type": "door", "wall": "north", "parameter": 0.5, "width": 0.9, "height": 2.1},
        ),
        object_placements=tuple(placements),
        circulation_paths=circulation_paths,
        revisions=(PlanRevision(revision=4, changed="approved", reason="test", plan_hash="plan-4"),),
        template_id="test-room",
    )


def _placement(
    object_id: str = "cup", *, x: float = 1.0, y: float = 1.0,
    width: float = 0.4, height: float = 0.4, depth: float = 0.4,
) -> dict:
    return {
        "id": object_id, "name": object_id, "x": x, "y": y,
        "width": width, "height": height, "depth": depth, "rotation_deg": 0.0,
    }


def _instance(
    placement: dict,
    *,
    position: tuple[float, float, float] | None = None,
    body_mode: BodyMode = BodyMode.DYNAMIC,
) -> tuple[WorldInstance, PhysicsIntent]:
    object_id = placement["id"]
    position = position or (placement["x"], 1.5, placement["y"])
    instance = WorldInstance(
        id=object_id,
        name=placement["name"],
        category="decor",
        mount=Mount.FLOOR,
        transform=Transform(position_m=Vector3(x=position[0], y=position[1], z=position[2])),
        dimensions=Dimensions(
            width_m=placement["width"],
            height_m=placement["height"],
            depth_m=placement["depth"],
        ),
        fixed=body_mode == BodyMode.STATIC,
        material_id=f"material:{object_id}",
        physics_intent_id=f"physics:{object_id}",
        geometry_strategy="primitive",
        primitive_shape="box",
    )
    physics = PhysicsIntent(
        id=f"physics:{object_id}",
        subject_id=object_id,
        body_mode=body_mode,
        mass_kg=1.0 if body_mode == BodyMode.DYNAMIC else 0.0,
        collision_shape="box",
    )
    return instance, physics


def _contract(*entries: tuple[WorldInstance, PhysicsIntent]) -> WorldContract:
    instances = tuple(entry[0] for entry in entries)
    intents = tuple(entry[1] for entry in entries)
    materials = [
        MaterialIntent(id="material:floor"),
        MaterialIntent(id="material:wall"),
        MaterialIntent(id="material:ceiling"),
    ]
    materials.extend(MaterialIntent(id=item.material_id) for item in instances)

    return WorldContract(
        source=SourceBinding(
            session_id="settle-test",
            interface_version=16,
            profile_id="unified-v16",
            plan_revision=4,
            plan_hash=_HASH,
            scene_graph_hash=_HASH,
            camera_contract_id="camera-1",
            camera_contract_hash=_HASH,
            appearance_intent_hash=_HASH,
        ),
        room=RoomShell(
            dimensions=Dimensions(width_m=4.0, height_m=3.0, depth_m=4.0),
            floor_material_id="material:floor",
            wall_material_id="material:wall",
            ceiling_material_id="material:ceiling",
        ),
        openings=(WorldOpening(
            id="door-n", kind="door", wall="north", offset_m=0.0,
            width_m=0.9, height_m=2.1,
        ),),
        instances=instances,
        materials=tuple(materials),
        camera=CameraBinding(
            id="camera-1",
            source_schema_version="camera-contract/v1",
            position_m=Vector3(x=2.0, y=1.6, z=3.5),
            target_m=Vector3(x=2.0, y=1.0, z=2.0),
            up=Vector3(x=0.0, y=1.0, z=0.0),
            vertical_fov_deg=60.0,
            aspect_ratio=4 / 3,
            image_width_px=1024,
            image_height_px=768,
            near_plane_m=0.1,
            far_plane_m=100.0,
        ),
        appearance=AppearanceIntent(id="appearance"),
        physics=PhysicsPolicy(intents=intents),
    )


class _RewritingSettler(PhysicsSettle):
    def __init__(
        self,
        *,
        positions: dict[str, tuple[float, float, float]] | None = None,
        rotations: dict[str, tuple[float, float, float]] | None = None,
        rewrite_camera: bool = False,
    ) -> None:
        self.positions = positions or {}
        self.rotations = rotations or {}
        self.rewrite_camera = rewrite_camera

    def settle(self, world_contract, config=None):
        base = super().settle(world_contract, config)
        payload = base.settled_world_contract.model_dump()
        for item in payload["instances"]:
            if item["id"] in self.positions:
                x, y, z = self.positions[item["id"]]
                item["transform"]["position_m"] = {"x": x, "y": y, "z": z}
            if item["id"] in self.rotations:
                x, y, z = self.rotations[item["id"]]
                item["transform"]["rotation_deg"] = {"x": x, "y": y, "z": z}
        if self.rewrite_camera:
            payload["camera"]["vertical_fov_deg"] = 75.0
        changed = WorldContract.model_validate(payload)
        return PhysicsSettleResult(
            settled_world_contract=changed,
            object_info=base.object_info,
            total_unsettled=base.total_unsettled,
            total_dynamic=base.total_dynamic,
            iterations_run=base.iterations_run,
            wall_time_s=base.wall_time_s,
            warning_issued=base.warning_issued,
        )


def test_real_legacy_fallback_resolves_floater_and_clamps_plan_bounds(monkeypatch):
    monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
    placement = _placement(x=0.1, y=3.9)
    plan = _plan(placement)
    contract = _contract(_instance(placement, position=(0.1, 2.0, 3.9)))

    result = UnifiedPhysicsSettle().settle(plan, contract, approved_plan_revision=4)
    item = result.settled_world_contract.instances[0]

    assert item.transform.position_m.x == pytest.approx(0.25)
    assert item.transform.position_m.y == pytest.approx(0.2)
    assert item.transform.position_m.z == pytest.approx(3.75)
    assert result.legacy_result.iterations_run <= MAX_SETTLE_ITERATIONS
    assert result.legacy_result.wall_time_s <= MAX_SETTLE_SECONDS
    assert result.circulation_preserved is True
    assert {reason for correction in result.corrections for reason in correction.reasons} >= {
        "clamped_to_plan_bounds", "resolved_floater_or_floor_penetration"
    }


def test_architecture_openings_camera_and_non_transform_data_are_preserved(monkeypatch):
    monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
    placement = _placement()
    plan = _plan(placement)
    contract = _contract(_instance(placement))

    settled = UnifiedPhysicsSettle().settle(
        plan, contract, approved_plan_revision=4
    ).settled_world_contract

    assert settled.room == contract.room
    assert settled.openings == contract.openings
    assert settled.camera == contract.camera
    assert settled.source == contract.source
    assert settled.instances[0].model_copy(update={"transform": contract.instances[0].transform}) == contract.instances[0]


def test_new_circulation_conflict_restores_plan_transform(monkeypatch):
    monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
    placement = _placement(x=1.0, y=2.0)
    path = ({"start": (2.0, 0.0), "end": (2.0, 4.0), "min_width": 0.6},)
    plan = _plan(placement, circulation_paths=path)
    contract = _contract(_instance(placement, position=(1.0, 1.0, 2.0)))
    settler = _RewritingSettler(positions={"cup": (1.6, 0.2, 2.0)})

    result = UnifiedPhysicsSettle(settler).settle(plan, contract, approved_plan_revision=4)
    item = result.settled_world_contract.instances[0]

    assert item.transform.position_m.x == pytest.approx(1.0)
    assert _circulation_conflicts(plan, (1.0, 2.0), (0.2, 0.2)) == set()
    assert "restored_plan_transform_for_circulation" in result.corrections[0].reasons


def test_rotation_aware_extents_are_clamped_with_margin(monkeypatch):
    monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
    placement = _placement(x=0.1, y=2.0)
    plan = _plan(placement)
    contract = _contract(_instance(placement, position=(0.1, 1.0, 2.0)))
    settler = _RewritingSettler(rotations={"cup": (0.0, 45.0, 0.0)})

    item = UnifiedPhysicsSettle(settler).settle(
        plan, contract, approved_plan_revision=4
    ).settled_world_contract.instances[0]

    expected_half_extent = (0.4 / 2) * (2 ** 0.5)
    assert item.transform.position_m.x == pytest.approx(expected_half_extent + PLAN_BOUNDS_MARGIN_M)


def test_post_guard_resolves_delegated_interpenetration(monkeypatch):
    monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
    first = _placement("cup-a", x=1.0, y=2.0)
    second = _placement("cup-b", x=3.0, y=2.0)
    plan = _plan(first, second)
    contract = _contract(
        _instance(first, position=(1.0, 1.0, 2.0)),
        _instance(second, position=(3.0, 1.0, 2.0)),
    )
    settler = _RewritingSettler(positions={"cup-b": (1.0, 0.2, 2.0)})

    result = UnifiedPhysicsSettle(settler).settle(plan, contract, approved_plan_revision=4)
    positions = [item.transform.position_m for item in result.settled_world_contract.instances]

    assert (
        abs(positions[0].x - positions[1].x) >= 0.4 - 1e-8
        or abs(positions[0].y - positions[1].y) >= 0.4 - 1e-8
        or abs(positions[0].z - positions[1].z) >= 0.4 - 1e-8
    )
    assert any("resolved_interpenetration" in correction.reasons for correction in result.corrections)


def test_authority_rewrites_and_revision_mismatch_fail_closed(monkeypatch):
    monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
    placement = _placement()
    plan = _plan(placement)
    contract = _contract(_instance(placement))

    with pytest.raises(PhysicsSettleAuthorityError, match="rewrite architecture, openings, camera"):
        UnifiedPhysicsSettle(_RewritingSettler(rewrite_camera=True)).settle(
            plan, contract, approved_plan_revision=4
        )
    with pytest.raises(PhysicsSettleAuthorityError, match="latest nonzero revision"):
        UnifiedPhysicsSettle().settle(plan, contract, approved_plan_revision=3)


# Property: every delegated horizontal position remains inside rotation-aware Plan bounds.
# **Validates: Requirements 18.7, 18.8, 31.1-31.4**
@given(
    x=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
    z=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=40, deadline=None)
def test_property_settle_is_contained_by_authoritative_plan(x: float, z: float):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(legacy_settle, "PYBULLET_AVAILABLE", False)
        placement = _placement(x=x, y=z)
        plan = _plan(placement)
        contract = _contract(_instance(placement, position=(x, 2.0, z)))

        item = UnifiedPhysicsSettle().settle(
            plan, contract, approved_plan_revision=4
        ).settled_world_contract.instances[0]

    assert item.transform.position_m.x - 0.2 >= PLAN_BOUNDS_MARGIN_M - 1e-8
    assert item.transform.position_m.x + 0.2 <= 4.0 - PLAN_BOUNDS_MARGIN_M + 1e-8
    assert item.transform.position_m.z - 0.2 >= PLAN_BOUNDS_MARGIN_M - 1e-8
    assert item.transform.position_m.z + 0.2 <= 4.0 - PLAN_BOUNDS_MARGIN_M + 1e-8
