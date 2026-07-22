from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from src.camera_contract import camera_contract_for_plan
from src.constraint_solver import solve_relationships
from src.floor_plan.models import FloorPlan, FloorPlanV11
from src.floor_plan.solver import solve_explicit_plan
from src.models import RoomShell, SceneGraph
from src.orchestrator.mock_llm import _mock_floor_plan_v11
from src.world_contract import (
    BodyMode,
    Dimensions,
    ExportPolicy,
    MaterialIntent,
    RelationIntent,
    Vector3,
    WorldContract,
    WorldContractError,
    build_world_contract,
    canonical_world_contract,
    world_contract_from_json,
    world_contract_hash,
)

FIXTURE = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"


def approved_inputs() -> tuple[FloorPlan, SceneGraph]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return (
        FloorPlan.model_validate(payload["plan"]),
        SceneGraph.model_validate(payload["scene_graph"]),
    )


def build_contract(
    plan: FloorPlan | None = None, scene: SceneGraph | None = None, **updates,
) -> WorldContract:
    approved_plan, approved_scene = approved_inputs()
    return build_world_contract(
        plan or approved_plan,
        scene or approved_scene,
        camera_contract_for_plan(plan or approved_plan),
        session_id="contract-test",
        interface_version=11,
        profile_id="upbge-contract-r1",
        plan_revision=3,
        appearance_intent={
            "era": "mid-century", "mood": "warm", "palette": "walnut and cream",
            "architecture_notes": "clean diner shell", "lighting_notes": "warm pendant",
            "key_objects": ["pendant", "table"],
        },
        export_policy=ExportPolicy(targets=("godot", "glb")),
        **updates,
    )


def test_approved_authorities_convert_to_complete_engine_neutral_contract():
    contract = build_contract()

    assert contract.schema_version == "world-contract/v1"
    assert contract.coordinate_system == "right-handed-x-right-y-up-z-depth"
    assert contract.length_unit == "meter"
    assert contract.angle_unit == "degree"
    assert contract.room.dimensions == Dimensions(width_m=6.0, height_m=3.0, depth_m=4.0)
    assert [item.id for item in contract.openings] == ["door_south", "window_east"]
    assert [item.id for item in contract.instances] == ["pendant_1", "table_1"]
    assert contract.instances[1].transform.position_m == Vector3(x=0.5, y=0.0, z=-0.25)
    assert contract.instances[1].transform.rotation_deg.y == 30.0
    assert contract.instances[1].dimensions.width_m == 2.0
    assert contract.instances[1].mount.value == "floor"
    assert contract.instances[1].fixed is True
    table_physics = next(
        item for item in contract.physics.intents if item.subject_id == "table_1"
    )
    assert table_physics.body_mode == BodyMode.STATIC
    assert contract.lights[0].id == "pendant_1"
    assert contract.lights[0].fixture_instance_id == "pendant_1"
    assert contract.camera.id == camera_contract_for_plan(approved_inputs()[0]).contract_id
    assert contract.appearance.palette == "walnut and cream"
    assert tuple(target.value for target in contract.exports.targets) == ("glb", "godot")
    assert len(contract.source.plan_hash) == len(contract.source.scene_graph_hash) == 64


def test_v11_plan_relations_convert_automatically_and_world_solve_is_idempotent():
    plan = solve_explicit_plan(FloorPlanV11.model_validate(_mock_floor_plan_v11()))
    scene = SceneGraph(
        name="Typed V11 authority",
        description="Plan-owned geometry with no competing SceneGraph transforms",
        room=RoomShell(
            width=plan.room.width,
            depth=plan.room.depth,
            height=plan.room.height,
        ),
    )
    contract = build_contract(plan, scene)

    assert all(len(item.relations) == 1 for item in contract.instances)
    before = {item.id: item.transform for item in contract.instances}
    solved = solve_relationships(contract)
    assert solved.report.success, solved.report.model_dump()
    assert solved.contract is not None
    assert {item.id: item.transform for item in solved.contract.instances} == before


def test_canonical_round_trip_is_byte_stable_and_hashes_utf8_json():
    contract = build_contract()
    canonical = canonical_world_contract(contract)
    restored = world_contract_from_json(canonical)

    assert canonical == restored.canonical_bytes()
    assert restored == contract
    assert world_contract_hash(canonical) == contract.content_hash()
    assert b'": ' not in canonical and b", " not in canonical
    assert b"NaN" not in canonical and b"Infinity" not in canonical


def test_semantically_identical_authority_order_produces_equivalent_hash():
    plan, scene = approved_inputs()
    reordered_plan = plan.model_copy(update={
        "items": list(reversed(plan.items)),
        "openings": list(reversed(plan.openings)),
    })
    reordered_scene = scene.model_copy(update={
        "objects": list(reversed(scene.objects)),
        "lights": list(reversed(scene.lights)),
        "doors": list(reversed(scene.doors)),
        "windows": list(reversed(scene.windows)),
    })

    first = build_contract(plan, scene)
    second = build_contract(reordered_plan, reordered_scene)

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.content_hash() == second.content_hash()


def test_duplicate_ids_are_rejected_before_conversion():
    plan, scene = approved_inputs()
    duplicate = plan.model_copy(update={"items": [plan.items[0], plan.items[0]]})

    with pytest.raises(WorldContractError, match="duplicate Plan IDs: table_1"):
        build_contract(duplicate, scene)


def test_dangling_references_and_invalid_dimensions_are_rejected():
    payload = build_contract().model_dump(mode="json")
    payload["instances"][0]["material_id"] = "material:missing"
    with pytest.raises(ValidationError, match="dangling material reference"):
        WorldContract.model_validate(payload)

    with pytest.raises(ValidationError, match="greater than 0"):
        Dimensions(width_m=0.0, height_m=1.0, depth_m=1.0)


def test_unsupported_relations_and_dangling_relation_targets_are_rejected():
    with pytest.raises(ValidationError, match="Input should be"):
        RelationIntent.model_validate({"kind": "inside_of", "target_id": "table_1"})

    with pytest.raises(ValidationError, match="dangling target missing"):
        build_contract(relations={
            "table_1": [{"kind": "adjacent_to", "target_id": "missing"}]
        })


def test_non_finite_numbers_are_rejected_in_models_and_canonical_input():
    with pytest.raises(ValidationError, match="finite number"):
        Vector3(x=float("nan"), y=0.0, z=0.0)

    payload = build_contract().model_dump(mode="json")
    payload["lights"][0]["intensity"] = float("inf")
    with pytest.raises(ValidationError, match="finite number"):
        canonical_world_contract(payload)


def test_conflicting_plan_scene_graph_authorities_fail_closed():
    plan, scene = approved_inputs()
    conflicting_room = scene.model_copy(
        update={"room": scene.room.model_copy(update={"width": 7.0})}
    )
    with pytest.raises(WorldContractError, match="conflicting authorities for room.width"):
        build_contract(plan, conflicting_room)

    table = scene.objects[0].model_copy(
        update={"position": scene.objects[0].position.model_copy(update={"x": 1.25})}
    )
    conflicting_object = scene.model_copy(update={"objects": [table]})
    with pytest.raises(WorldContractError, match="instance table_1 x"):
        build_contract(plan, conflicting_object)


def test_appearance_intent_cannot_claim_geometry_or_camera_authority():
    plan, scene = approved_inputs()
    with pytest.raises(WorldContractError, match="cannot claim geometry/camera authority"):
        build_world_contract(
            plan,
            scene,
            camera_contract_for_plan(plan),
            session_id="contract-test",
            interface_version=11,
            profile_id="upbge-contract-r1",
            plan_revision=3,
            appearance_intent={"mood": "warm", "camera": {"fov": 90}},
        )


# Property 1: Canonicalization Idempotence
# **Validates: Requirements 1.5**
@given(
    reverse_instances=st.booleans(),
    reverse_materials=st.booleans(),
    roughness=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_canonicalization_idempotence(
    reverse_instances: bool, reverse_materials: bool, roughness: float,
):
    payload = build_contract().model_dump(mode="json")
    payload["materials"][0]["roughness"] = roughness
    if reverse_instances:
        payload["instances"].reverse()
    if reverse_materials:
        payload["materials"].reverse()

    canonical = canonical_world_contract(payload)
    restored = world_contract_from_json(canonical)
    reordered = restored.model_dump(mode="json")
    reordered["instances"].reverse()
    reordered["materials"].reverse()

    assert canonical_world_contract(canonical) == canonical
    assert canonical_world_contract(reordered) == canonical
    assert world_contract_hash(canonical) == world_contract_hash(reordered)


def test_geometry_strategies_require_explicit_safe_bindings():
    payload = build_contract().model_dump(mode="json")
    instance = payload["instances"][0]
    instance["geometry_strategy"] = "asset"
    instance["primitive_shape"] = None
    with pytest.raises(ValidationError, match="requires asset_registry_id"):
        WorldContract.model_validate(payload)

    instance["asset_registry_id"] = "asset:fixture:v1"
    contract = WorldContract.model_validate(payload)
    assert contract.instances[0].asset_registry_id == "asset:fixture:v1"

    primitive_payload = contract.model_dump(mode="json")
    primitive = primitive_payload["instances"][0]
    primitive["geometry_strategy"] = "generated"
    primitive["asset_registry_id"] = None
    primitive["primitive_shape"] = None
    with pytest.raises(ValidationError, match="requires primitive_shape"):
        WorldContract.model_validate(primitive_payload)
