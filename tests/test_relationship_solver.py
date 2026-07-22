from __future__ import annotations

import math

import pytest
from hypothesis import given, settings, strategies as st

from src.floor_plan.geometry import footprints_intersect, inside_room
from src.relationship_solver import ConstraintStatus, solve_relationships
from src.world_contract import (
    Dimensions,
    Mount,
    RelationIntent,
    Transform,
    Vector3,
    Wall,
    WorldContract,
)
from tests.test_world_contract import build_contract


def _instance(
    contract: WorldContract,
    identity: str,
    *,
    x: float = -2.0,
    y: float = 0.0,
    z: float = -2.0,
    width: float = 0.5,
    height: float = 0.6,
    depth: float = 0.5,
    rotation: float = 0.0,
    mount: Mount = Mount.FLOOR,
    fixed: bool = False,
    clearance: float = 0.0,
    relations: tuple[RelationIntent, ...] = (),
):
    template = next(item for item in contract.instances if item.id == "table_1")
    return template.model_copy(update={
        "id": identity,
        "name": identity,
        "mount": mount,
        "fixed": fixed,
        "clearance_m": clearance,
        "physics_intent_id": f"physics:{identity}",
        "dimensions": Dimensions(width_m=width, height_m=height, depth_m=depth),
        "transform": Transform(
            position_m=Vector3(x=x, y=y, z=z),
            rotation_deg=Vector3(y=rotation),
        ),
        "relations": relations,
    })


def _contract_with(*instances, room_width: float = 8.0, room_depth: float = 8.0) -> WorldContract:
    contract = build_contract()
    physics_template = next(
        item for item in contract.physics.intents if item.subject_id == "table_1"
    )
    physics = tuple(
        physics_template.model_copy(update={
            "id": instance.physics_intent_id,
            "subject_id": instance.id,
        })
        for instance in instances
    )
    payload = contract.model_copy(update={
        "room": contract.room.model_copy(update={
            "dimensions": Dimensions(
                width_m=room_width,
                height_m=3.0,
                depth_m=room_depth,
            )
        }),
        "openings": (),
        "instances": tuple(instances),
        "lights": (),
        "physics": contract.physics.model_copy(update={"intents": physics}),
        "camera": contract.camera.model_copy(update={
            "position_m": Vector3(x=room_width / 2 + 2.0, y=1.7, z=-room_depth / 2 - 2.0),
            "target_m": Vector3(),
        }),
    })
    return WorldContract.model_validate(payload.model_dump(mode="json"))


def _status(result) -> ConstraintStatus:
    assert len(result.report.relations) == 1
    return result.report.relations[0].status


@pytest.mark.parametrize(
    "relation,subject_kwargs",
    [
        (RelationIntent(kind="centered"), {}),
        (RelationIntent(kind="against_wall", wall="north"), {}),
        (RelationIntent(kind="near_corner", wall="west"), {}),
    ],
)
def test_room_and_wall_relationships_are_resolved(relation, subject_kwargs):
    contract = build_contract()
    subject = _instance(contract, "subject", relations=(relation,), **subject_kwargs)
    result = solve_relationships(_contract_with(subject))

    assert result.report.success
    assert result.contract is not None
    assert _status(result) == ConstraintStatus.SATISFIED


@pytest.mark.parametrize(
    "kind,mount",
    [
        ("adjacent_to", Mount.FLOOR),
        ("north_of", Mount.FLOOR),
        ("south_of", Mount.FLOOR),
        ("east_of", Mount.FLOOR),
        ("west_of", Mount.FLOOR),
        ("around", Mount.FLOOR),
        ("above", Mount.WALL),
        ("facing", Mount.FLOOR),
    ],
)
def test_target_relationships_are_resolved(kind: str, mount: Mount):
    base = build_contract()
    anchor = _instance(base, "anchor", x=0.0, z=0.0, width=1.0, depth=1.0, fixed=True)
    relation = RelationIntent(kind=kind, target_id="anchor")
    subject = _instance(base, "subject", x=-2.0, z=-2.0, mount=mount, relations=(relation,))
    result = solve_relationships(_contract_with(anchor, subject))

    assert result.report.success
    assert result.contract is not None
    assert _status(result) == ConstraintStatus.SATISFIED
    if kind == "facing":
        solved = next(item for item in result.contract.instances if item.id == "subject")
        expected = math.degrees(math.atan2(2.0, -2.0)) % 360.0
        assert solved.transform.rotation_deg.y == pytest.approx(expected)


def test_weighted_relaxation_preserves_higher_weight_hard_intent():
    base = build_contract()
    anchor = _instance(base, "anchor", x=0.0, z=0.0, width=1.0, depth=1.0, fixed=True)
    subject = _instance(base, "subject", relations=(
        RelationIntent(kind="east_of", target_id="anchor", weight=10.0),
        RelationIntent(kind="centered", weight=0.25, relaxable=True),
    ))
    result = solve_relationships(_contract_with(anchor, subject))

    assert result.report.success
    assert [item.status for item in result.report.relations] == [
        ConstraintStatus.RELAXED,
        ConstraintStatus.SATISFIED,
    ]
    assert len(result.report.unsatisfied_constraints) == 1


def test_impossible_layout_returns_blockers_and_no_overlapping_contract():
    base = build_contract()
    anchor = _instance(
        base, "anchor", x=0.0, z=0.0, width=1.8, depth=1.8, fixed=True
    )
    subject = _instance(
        base, "subject", width=1.0, depth=1.0,
        relations=(RelationIntent(kind="centered"),),
    )
    result = solve_relationships(
        _contract_with(anchor, subject, room_width=2.0, room_depth=2.0)
    )

    assert not result.report.success
    assert result.contract is None
    assert _status(result) == ConstraintStatus.BLOCKED
    assert result.report.unsatisfied_constraints
    assert any("physical_overlap" in item.message for item in result.report.hard_constraints)


def test_opening_camera_clearance_and_rotation_aware_bounds_are_hard_constraints():
    base = build_contract()
    doorway_subject = _instance(
        base, "doorway_subject", x=-1.0, z=0.0,
        relations=(RelationIntent(kind="against_wall", wall="south"),),
    )
    doorway_contract = _contract_with(doorway_subject)
    doorway = base.openings[0].model_copy(update={"physics_intent_id": None})
    doorway_contract = WorldContract.model_validate(doorway_contract.model_copy(
        update={"openings": (doorway,)}
    ).model_dump(mode="json"))
    doorway = solve_relationships(doorway_contract)
    assert doorway.contract is None
    assert any(
        item.reason_code == "opening_keep_clear"
        for item in doorway.report.hard_constraints
    )

    centered = _instance(
        base, "centered", relations=(RelationIntent(kind="centered"),)
    )
    camera_contract = _contract_with(centered)
    camera_contract = WorldContract.model_validate(camera_contract.model_copy(update={
        "camera": camera_contract.camera.model_copy(update={
            "position_m": Vector3(x=0.0, y=1.6, z=0.0),
            "target_m": Vector3(x=1.0, y=1.0, z=0.0),
        })
    }).model_dump(mode="json"))
    camera = solve_relationships(camera_contract)
    assert camera.contract is None
    assert any(item.reason_code == "camera_occupancy" for item in camera.report.hard_constraints)

    rotated = _instance(
        base, "rotated", width=3.0, depth=0.4,
        relations=(RelationIntent(kind="against_wall", wall="east"),),
    )
    rotation_result = solve_relationships(_contract_with(rotated, room_width=4.0, room_depth=4.0))
    assert rotation_result.report.success
    solved = rotation_result.contract.instances[0]
    assert solved.transform.rotation_deg.y == pytest.approx(90.0)


def test_around_relation_distributes_exact_repeated_count_deterministically():
    base = build_contract()
    anchor = _instance(base, "anchor", x=0.0, z=0.0, width=1.0, depth=1.0, fixed=True)
    subjects = tuple(
        _instance(
            base, f"seat_{index}",
            relations=(RelationIntent(kind="around", target_id="anchor"),),
        )
        for index in range(4)
    )
    first = solve_relationships(_contract_with(anchor, *subjects))
    second = solve_relationships(_contract_with(anchor, *subjects))

    assert first.report.success
    assert first.contract == second.contract
    assert len(first.report.relations) == 4
    assert all(item.status == ConstraintStatus.SATISFIED for item in first.report.relations)
    positions = {
        (round(item.transform.position_m.x, 6), round(item.transform.position_m.z, 6))
        for item in first.contract.instances if item.id.startswith("seat_")
    }
    assert len(positions) == 4


# Property 6: Constraint Safety
# **Validates: Requirements 3.2, 3.3**
@given(
    room_width=st.floats(min_value=3.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    room_depth=st.floats(min_value=3.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    width=st.floats(min_value=0.2, max_value=1.0, allow_nan=False, allow_infinity=False),
    depth=st.floats(min_value=0.2, max_value=1.0, allow_nan=False, allow_infinity=False),
    rotation=st.floats(min_value=0.0, max_value=359.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=30, deadline=None)
def test_property_successful_solve_is_rotation_aware_and_safe(
    room_width: float,
    room_depth: float,
    width: float,
    depth: float,
    rotation: float,
):
    base = build_contract()
    subject = _instance(
        base,
        "subject",
        width=width,
        depth=depth,
        rotation=rotation,
        relations=(RelationIntent(kind="centered"),),
    )
    contract = _contract_with(
        subject, room_width=room_width, room_depth=room_depth
    )
    result = solve_relationships(contract)

    assert result.report.success
    assert result.contract is not None
    solved = result.contract.instances[0]
    volume = type("Volume", (), {
        "x": solved.transform.position_m.x,
        "z": solved.transform.position_m.z,
        "width": solved.dimensions.width_m,
        "depth": solved.dimensions.depth_m,
        "height": solved.dimensions.height_m,
        "elevation": solved.transform.position_m.y,
        "rotation_deg": solved.transform.rotation_deg.y,
    })()
    assert inside_room(volume, room_width, room_depth)
    assert result.report.unsatisfied_constraints == ()
