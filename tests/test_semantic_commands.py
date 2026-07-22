from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from src.camera_contract import camera_contract_for_plan
from src.floor_plan.models import FloorPlan
from src.models import SceneGraph
from src.orchestrator.prompts import (
    SEMANTIC_COMMAND_PLANNER_SYSTEM,
    semantic_command_planning_prompt,
)
from src.semantic_commands import (
    CameraRequestCommand,
    CommandAuthorization,
    CommandLimits,
    CommandOp,
    CommandProvenance,
    RejectionCode,
    apply_semantic_command_batch,
    parse_semantic_command,
    semantic_command_json_schema,
)
from src.world_contract import ExportPolicy, WorldContract, build_world_contract

FIXTURE = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"
MODEL_ID = "qwen2.5:7b"
PROMPT_HASH = hashlib.sha256(b"test prompt").hexdigest()


def build_contract() -> WorldContract:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    plan = FloorPlan.model_validate(payload["plan"])
    scene = SceneGraph.model_validate(payload["scene_graph"])
    return build_world_contract(
        plan,
        scene,
        camera_contract_for_plan(plan),
        session_id="command-test",
        interface_version=11,
        profile_id="upbge-contract-r1",
        plan_revision=3,
        appearance_intent={"mood": "warm"},
        export_policy=ExportPolicy(targets=("glb",)),
    )


def provenance() -> CommandProvenance:
    return CommandProvenance(model_id=MODEL_ID, source_prompt_hash=PROMPT_HASH)


def authorization(contract: WorldContract, *ops: CommandOp) -> CommandAuthorization:
    return CommandAuthorization(
        principal_id="command-validator",
        authorized_model_ids=frozenset({MODEL_ID}),
        allowed_ops=frozenset(ops),
        mutable_instance_ids=frozenset(item.id for item in contract.instances),
        mutable_material_ids=frozenset(item.id for item in contract.materials),
        mutable_light_ids=frozenset(item.id for item in contract.lights),
        mutable_interaction_ids=frozenset(item.id for item in contract.interactions),
    )


def new_instance_payload(identity: str = "chair_new") -> dict:
    return {
        "id": identity,
        "name": "Walnut chair",
        "category": "furniture",
        "mount": "floor",
        "transform": {"position_m": {"x": 0.0, "y": 0.0, "z": 0.0}},
        "dimensions": {"width_m": 0.5, "height_m": 0.9, "depth_m": 0.5},
        "material_id": f"material:instance:{identity}",
        "physics_intent_id": f"physics:instance:{identity}",
        "geometry_strategy": "primitive",
        "primitive_shape": "box",
    }


def create_payload(identity: str = "chair_new") -> dict:
    instance = new_instance_payload(identity)
    return {
        "version": "semantic-command/v1",
        "op": "create_instance",
        "command_id": f"create-{identity}",
        "instance": instance,
        "material": {
            "id": instance["material_id"],
            "base_color": "#805030",
            "roughness": 0.7,
        },
        "physics": {
            "id": instance["physics_intent_id"],
            "subject_id": identity,
            "body_mode": "dynamic",
            "mass_kg": 8.0,
        },
    }


def all_operation_payloads(contract: WorldContract) -> list[dict]:
    table = next(item for item in contract.instances if item.id == "table_1")
    material = next(item for item in contract.materials if item.id == table.material_id)
    physics = next(item for item in contract.physics.intents if item.id == table.physics_intent_id)
    return [
        create_payload(),
        {"version": "semantic-command/v1", "op": "remove_instance", "command_id": "remove", "subject_id": "table_1"},
        {
            "version": "semantic-command/v1", "op": "replace_instance", "command_id": "replace",
            "subject_id": "table_1", "instance": table.model_dump(mode="json"),
            "material": material.model_dump(mode="json"), "physics": physics.model_dump(mode="json"),
        },
        {
            "version": "semantic-command/v1", "op": "set_relation", "command_id": "relate",
            "subject_id": "table_1", "relation": {"kind": "south_of", "target_id": "pendant_1"},
        },
        {
            "version": "semantic-command/v1", "op": "set_style", "command_id": "style",
            "material_id": table.material_id, "style": {"roughness": 0.25},
        },
        {
            "version": "semantic-command/v1", "op": "set_light_intent", "command_id": "light",
            "light": contract.lights[0].model_dump(mode="json"),
        },
        {
            "version": "semantic-command/v1", "op": "camera_request", "command_id": "camera",
            "vertical_fov_deg": 55.0, "rationale": "Show more of the room",
        },
        {
            "version": "semantic-command/v1", "op": "set_physics_intent", "command_id": "physics",
            "intent": physics.model_dump(mode="json"),
        },
        {
            "version": "semantic-command/v1", "op": "set_interaction_intent", "command_id": "interaction",
            "intent": {"id": "grab-table", "kind": "grab", "subject_id": "table_1"},
        },
    ]


def test_all_nine_operations_are_typed_allowlisted_models():
    contract = build_contract()
    commands = [parse_semantic_command(payload) for payload in all_operation_payloads(contract)]

    assert {command.op for command in commands} == {op.value for op in CommandOp}
    schema = semantic_command_json_schema()
    assert schema["discriminator"]["propertyName"] == "op"
    with pytest.raises(ValidationError):
        parse_semantic_command({
            "version": "semantic-command/v1", "op": "run_python", "command_id": "unsafe"
        })
    with pytest.raises(ValidationError):
        parse_semantic_command({**create_payload(), "unexpected": "field"})


def test_planner_prompt_requires_explicit_relations_and_exposes_no_engine_details():
    prompt = semantic_command_planning_prompt(build_contract(), "place a chair near the table")

    assert "set_relation" in prompt
    assert "south_of" in SEMANTIC_COMMAND_PLANNER_SYSTEM
    assert "Never infer placement from names" in SEMANTIC_COMMAND_PLANNER_SYSTEM
    assert "table_1" in prompt
    assert "bpy" not in prompt and "UPBGE" not in prompt and "filesystem" not in prompt


def test_create_and_forward_relation_apply_transactionally_with_provenance_hashes():
    contract = build_contract()
    commands = [
        {
            "version": "semantic-command/v1", "op": "set_relation", "command_id": "relate-new",
            "subject_id": "chair_new", "relation": {"kind": "adjacent_to", "target_id": "table_1"},
        },
        create_payload(),
    ]

    result = apply_semantic_command_batch(
        contract,
        commands,
        authorization=authorization(
            contract, CommandOp.CREATE_INSTANCE, CommandOp.SET_RELATION
        ),
        provenance=provenance(),
    )

    assert result.accepted is True
    assert result.contract is not contract
    assert result.before_hash == contract.content_hash()
    assert result.after_hash == result.contract.content_hash()
    assert result.after_hash != result.before_hash
    assert result.record is not None
    assert result.record.model_id == MODEL_ID
    assert result.record.source_prompt_hash == PROMPT_HASH
    assert hashlib.sha256(
        result.record.canonical_commands_json.encode("utf-8")
    ).hexdigest() == result.record.command_log_hash
    chair = next(item for item in result.contract.instances if item.id == "chair_new")
    assert chair.relations[0].target_id == "table_1"


def test_camera_changes_remain_requests_and_do_not_mutate_camera_authority():
    contract = build_contract()
    command = {
        "version": "semantic-command/v1", "op": "camera_request", "command_id": "wider-view",
        "vertical_fov_deg": 60.0, "rationale": "Include both tables",
    }
    result = apply_semantic_command_batch(
        contract, [command],
        authorization=authorization(contract, CommandOp.CAMERA_REQUEST),
        provenance=provenance(),
    )

    assert result.accepted is True
    assert result.contract.camera == contract.camera
    assert result.before_hash == result.after_hash
    assert result.camera_requests == (CameraRequestCommand.model_validate(command),)


@pytest.mark.parametrize("unsafe", [
    "import os; os.system('whoami')",
    "powershell -Command Get-ChildItem",
    "C:\\temp\\payload.exe",
    "../../outside/world.blend",
    "bpy.ops.object.delete()",
    "shader_type spatial;",
    "run this every frame",
])
def test_every_free_text_field_rejects_code_paths_engine_operators_and_frame_control(unsafe: str):
    payload = {
        "version": "semantic-command/v1", "op": "camera_request", "command_id": "unsafe-request",
        "vertical_fov_deg": 60.0, "rationale": unsafe,
    }
    with pytest.raises(ValidationError, match="unsafe content"):
        parse_semantic_command(payload)


def test_authority_reference_limit_and_relation_cycle_failures_are_structured_and_atomic():
    contract = build_contract()
    immutable = CommandAuthorization(
        principal_id="validator", authorized_model_ids=frozenset({MODEL_ID}),
        allowed_ops=frozenset({CommandOp.REMOVE_INSTANCE}),
    )
    immutable_result = apply_semantic_command_batch(
        contract,
        [{"version": "semantic-command/v1", "op": "remove_instance", "command_id": "remove", "subject_id": "table_1"}],
        authorization=immutable,
        provenance=provenance(),
    )
    assert immutable_result.rejections[0].code == RejectionCode.IMMUTABLE_AUTHORITY
    assert immutable_result.contract is contract
    assert immutable_result.before_hash == immutable_result.after_hash

    dangling_result = apply_semantic_command_batch(
        contract,
        [{
            "version": "semantic-command/v1", "op": "set_relation", "command_id": "missing",
            "subject_id": "table_1", "relation": {"kind": "adjacent_to", "target_id": "missing"},
        }],
        authorization=authorization(contract, CommandOp.SET_RELATION),
        provenance=provenance(),
    )
    assert dangling_result.rejections[0].code == RejectionCode.DANGLING_REFERENCE

    limit_result = apply_semantic_command_batch(
        contract, [create_payload()],
        authorization=authorization(contract, CommandOp.CREATE_INSTANCE),
        provenance=provenance(), limits=CommandLimits(max_instances=len(contract.instances)),
    )
    assert limit_result.rejections[0].code == RejectionCode.LIMIT_EXCEEDED
    assert limit_result.after_hash == contract.content_hash()

    cycle_commands = [
        {
            "version": "semantic-command/v1", "op": "set_relation", "command_id": "a-to-b",
            "subject_id": "table_1", "relation": {"kind": "adjacent_to", "target_id": "pendant_1"},
        },
        {
            "version": "semantic-command/v1", "op": "set_relation", "command_id": "b-to-a",
            "subject_id": "pendant_1", "relation": {"kind": "facing", "target_id": "table_1"},
        },
    ]
    cycle_result = apply_semantic_command_batch(
        contract, cycle_commands,
        authorization=authorization(contract, CommandOp.SET_RELATION),
        provenance=provenance(),
    )
    assert cycle_result.rejections[0].code == RejectionCode.RELATION_CYCLE
    assert cycle_result.contract is contract


# Property 2: Command Atomicity
# **Validates: Requirements 2.5**
@given(
    missing_id=st.from_regex(r"missing_[a-z]{1,12}", fullmatch=True),
    roughness=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_any_invalid_command_leaves_world_contract_unchanged(
    missing_id: str, roughness: float,
):
    contract = build_contract()
    table = next(item for item in contract.instances if item.id == "table_1")
    commands = [
        {
            "version": "semantic-command/v1", "op": "set_style", "command_id": "valid-first",
            "material_id": table.material_id, "style": {"roughness": roughness},
        },
        {
            "version": "semantic-command/v1", "op": "set_relation", "command_id": "invalid-second",
            "subject_id": "table_1",
            "relation": {"kind": "adjacent_to", "target_id": missing_id},
        },
    ]

    result = apply_semantic_command_batch(
        contract, commands,
        authorization=authorization(
            contract, CommandOp.SET_STYLE, CommandOp.SET_RELATION
        ),
        provenance=provenance(),
    )

    assert result.accepted is False
    assert result.contract is contract
    assert result.contract.canonical_bytes() == contract.canonical_bytes()
    assert result.before_hash == result.after_hash == contract.content_hash()
