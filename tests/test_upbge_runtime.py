from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings, strategies as st

import src.assembler.upbge_compile as engine_compiler

from src.upbge_capabilities import UPBGECapabilityReport
from src.upbge_runtime import (
    DYNAMIC_STATE_SCHEMA_VERSION,
    PLAYER_TEMPLATE,
    BoundedUPBGERuntimeSmokeRunner,
    RuntimeSmokeHarnessConfig,
    DynamicObjectState,
    RuntimeDynamicState,
    ValidationEvidence,
    build_runtime_plan,
    evaluate_runtime_package_gate,
    load_runtime_state,
    persist_runtime_state,
    publish_runtime_candidate,
)
from tests.upbge_test_support import build_test_contract


def _evidence(schema: str, passed: bool = True) -> ValidationEvidence:
    return ValidationEvidence(
        schema_version=schema, passed=passed,
        evidence_hash="a" * 64 if passed else None,
        failed_checks=() if passed else ("load",),
    )


def _verified_capability() -> UPBGECapabilityReport:
    return UPBGECapabilityReport(
        available=True, verified=True, compatible=True, executable_path="C:/UPBGE/upbge.exe",
        product="UPBGE", product_version="0.36", blender_api_version="3.6",
        python_version="3.10", supports_game_runtime=True, supports_eevee=True,
        supports_gltf=True, reason_code="verified",
    )


def test_runtime_plan_uses_immutable_first_party_sources_and_allowlisted_parameters():
    contract = build_test_contract(interactions=(
        {"id": "door-action", "kind": "door", "subject_id": "door_south",
         "parameters": {"open_angle_deg": 80.0}},
        {"id": "grab-action", "kind": "grab", "subject_id": "door_south",
         "parameters": {"max_mass_kg": 30.0}},
    ))
    source_before = PLAYER_TEMPLATE.source

    plan = build_runtime_plan(contract)

    assert PLAYER_TEMPLATE.source == source_before
    assert {item.kind for item in plan.interactions} == {"door", "grab"}
    assert all(source for _template, _entrypoint, source in plan.template_sources)
    assert {name for name, _hash in plan.template_hashes} == {
        "player.first_person", "interaction.door", "interaction.grab"
    }
    with pytest.raises(FrozenInstanceError):
        plan.schema_version = "changed"  # type: ignore[misc]


def test_runtime_rejects_unknown_or_out_of_bounds_interaction_parameters():
    unknown = build_test_contract(interactions=(
        {"id": "door-action", "kind": "door", "subject_id": "door_south",
         "parameters": {"python": "print('unsafe')"}},
    ))
    with pytest.raises(ValueError, match="unsupported door parameters: python"):
        build_runtime_plan(unknown)

    invalid = build_test_contract(interactions=(
        {"id": "grab-action", "kind": "grab", "subject_id": "door_south",
         "parameters": {"max_distance_m": 1.0, "hold_distance_m": 2.0}},
    ))
    with pytest.raises(ValueError, match="hold_distance_m"):
        build_runtime_plan(invalid)


def test_dynamic_state_is_separate_canonical_data_not_contract_mutation():
    contract = build_test_contract()
    state = RuntimeDynamicState(
        schema_version="upbge-runtime-state/v1",
        world_contract_hash=contract.content_hash(), sequence=2,
            objects=(DynamicObjectState(
                next(
                    item.subject_id for item in contract.physics.intents
                    if item.body_mode.value == "dynamic"
                ),
                (1.0, 2.0, 3.0), (0.0, 0.0, 20.0),
            ),),
    )

    encoded = state.canonical_bytes()

    assert b'"world_contract_hash"' in encoded
    assert b'"room"' not in encoded
    assert contract.content_hash() == state.world_contract_hash


def test_runtime_package_gate_requires_capability_parity_and_smoke_evidence():
    accepted = evaluate_runtime_package_gate(
        _verified_capability(), _evidence("structural-parity/v1"),
        _evidence("runtime-smoke/v1"),
    )
    rejected = evaluate_runtime_package_gate(
        UPBGECapabilityReport(), _evidence("structural-parity/v1"),
        _evidence("runtime-smoke/v1", passed=False),
    )

    assert accepted.allowed and accepted.failed_gates == ()
    assert not rejected.allowed
    assert rejected.failed_gates == ("capability", "runtime_smoke")
    assert rejected.capability_path is None


def test_bounded_first_party_runner_requires_exact_machine_evidence(tmp_path):
    executable = Path(sys.executable)
    package = tmp_path / "runtime.blend"
    package.write_bytes(b"runtime")

    def command_factory(engine, _package, request, report):
        source = (
            "import json,sys;"
            "request=json.load(open(sys.argv[1],encoding='utf-8'));"
            "json.dump({'schema_version':'upbge-runtime-smoke-evidence/v1',"
            "'checks':{name:True for name in request['checks']}},"
            "open(sys.argv[2],'w',encoding='utf-8'))"
        )
        return (str(engine), "-c", source, str(request), str(report))

    runner = BoundedUPBGERuntimeSmokeRunner(
        RuntimeSmokeHarnessConfig(timeout_seconds=5.0), command_factory=command_factory,
    )
    evidence = runner(executable, package, ("door-action", "grab-action"))

    assert evidence == {
        "load": True, "player_spawn": True, "movement": True, "collision": True,
        "opening_traversal": True, "interaction:door-action": True,
        "interaction:grab-action": True,
    }


def test_bounded_runner_does_not_treat_zero_exit_as_runtime_success(tmp_path):
    executable = Path(sys.executable)
    package = tmp_path / "runtime.blend"
    package.write_bytes(b"runtime")
    runner = BoundedUPBGERuntimeSmokeRunner(
        RuntimeSmokeHarnessConfig(timeout_seconds=5.0),
        command_factory=lambda engine, _package, _request, _report: (
            str(engine), "-c", "pass",
        ),
    )

    evidence = runner(executable, package, ())

    assert set(evidence) == {
        "load", "player_spawn", "movement", "collision", "opening_traversal",
    }
    assert all(value is not True for value in evidence.values())


def test_dynamic_state_persists_atomically_outside_world_contract(tmp_path):
    contract = build_test_contract()
    contract_before = contract.canonical_bytes()
    state = RuntimeDynamicState(
        schema_version=DYNAMIC_STATE_SCHEMA_VERSION,
        world_contract_hash=contract.content_hash(), sequence=1,
        objects=(DynamicObjectState("door_south", (1.0, 2.0, 3.0), (0.0, 0.0, 20.0)),),
    )

    state_path = persist_runtime_state(state, tmp_path / "state", contract)

    assert state_path.name == "runtime_state.json"
    assert load_runtime_state(state_path.parent, contract) == state
    assert b'"room"' not in state_path.read_bytes()
    assert contract.canonical_bytes() == contract_before
    with pytest.raises(ValueError, match="sequence must advance"):
        persist_runtime_state(state, state_path.parent, contract)
    with pytest.raises(ValueError, match="non-dynamic subjects"):
        persist_runtime_state(
            RuntimeDynamicState(
                schema_version=DYNAMIC_STATE_SCHEMA_VERSION,
                world_contract_hash=contract.content_hash(), sequence=2,
                objects=(DynamicObjectState("window_east", (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),),
            ),
            tmp_path / "other-state", contract,
        )


@pytest.mark.parametrize(
    ("body_mode", "engine_type", "ghost"),
    (("static", "STATIC", False), ("kinematic", "DYNAMIC", False),
     ("dynamic", "RIGID_BODY", False), ("trigger", "SENSOR", True)),
)
def test_engine_configures_each_body_mode_from_explicit_physics_intent(
    body_mode, engine_type, ghost,
):
    class FakeObject(dict):
        def __init__(self):
            super().__init__()
            self.game = SimpleNamespace(use_actor=False, use_ghost=False)
            self.active_material = SimpleNamespace(
                physics=SimpleNamespace(friction=0.0, elasticity=0.0)
            )

    obj = FakeObject()
    spec = {
        "stable_id": f"physics:{body_mode}", "body_mode": body_mode,
        "collision_shape": "capsule", "mass_kg": 8.0, "friction": 0.7,
        "restitution": 0.25, "can_topple": body_mode == "dynamic",
    }

    engine_compiler._configure_physics(obj, spec)

    assert obj.game.physics_type == engine_type
    assert obj.game.collision_bounds_type == "CAPSULE"
    assert obj.game.use_collision_bounds and obj.game.use_actor
    assert obj.game.use_ghost is ghost
    assert obj["kiro_body_mode"] == body_mode
    assert obj.active_material.physics.friction == 0.7
    assert obj.active_material.physics.elasticity == 0.25
    if body_mode == "dynamic":
        assert obj.game.mass == 8.0
    if body_mode == "kinematic":
        assert obj["kiro_kinematic"] is True


def test_playable_runtime_is_published_only_with_evidence_bound_to_world_and_candidate(tmp_path):
    contract = build_test_contract()
    candidate = tmp_path / "runtime_candidate.blend"
    candidate.write_bytes(b"compiled runtime candidate")
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    contract_hash = contract.content_hash()
    parity = ValidationEvidence(
        "structural-parity/v1", True, "a" * 64,
        world_contract_hash=contract_hash,
    )
    stale_smoke = ValidationEvidence(
        "runtime-smoke/v1", True, "b" * 64,
        world_contract_hash=contract_hash, artifact_hash="0" * 64,
    )

    rejected = publish_runtime_candidate(
        candidate, tmp_path / "rejected", contract, _verified_capability(),
        parity, stale_smoke,
    )

    assert not rejected.gate.allowed and rejected.artifact is None
    assert not (tmp_path / "rejected").exists()

    accepted = publish_runtime_candidate(
        candidate, tmp_path / "published", contract, _verified_capability(), parity,
        ValidationEvidence(
            "runtime-smoke/v1", True, "b" * 64,
            world_contract_hash=contract_hash, artifact_hash=candidate_hash,
        ),
    )
    assert accepted.gate.allowed
    assert accepted.artifact is not None
    assert accepted.artifact.role == "playable_runtime"
    assert accepted.artifact.sha256 == candidate_hash
    assert Path(accepted.artifact.path).read_bytes() == candidate.read_bytes()


# Property 10: Runtime Template Isolation
# **Validates: Requirements 2.3, 6.2, 8.1**
@settings(max_examples=25, deadline=None)
@given(
    angle=st.floats(min_value=-180.0, max_value=180.0, exclude_min=False,
                    exclude_max=False, allow_nan=False, allow_infinity=False)
    .filter(lambda value: abs(value) > 1e-6),
    speed=st.floats(min_value=0.01, max_value=720.0, allow_nan=False,
                    allow_infinity=False),
    mass=st.floats(min_value=0.1, max_value=1000.0, allow_nan=False,
                   allow_infinity=False),
)
def test_property_runtime_template_source_is_isolated_from_semantic_parameters(
    angle: float, speed: float, mass: float,
):
    sources_before = {
        template_id: (entrypoint, source)
        for template_id, entrypoint, source in build_runtime_plan(build_test_contract()).template_sources
    }
    contract = build_test_contract(interactions=(
        {"id": "door-action", "kind": "door", "subject_id": "door_south",
         "parameters": {"open_angle_deg": angle, "speed_deg_s": speed}},
        {"id": "grab-action", "kind": "grab", "subject_id": "door_south",
         "parameters": {"max_mass_kg": mass}},
    ))

    plan = build_runtime_plan(contract)

    assert {
        template_id: (entrypoint, source)
        for template_id, entrypoint, source in plan.template_sources
    } == sources_before
    assert dict(next(item for item in plan.interactions if item.kind == "door").parameters)[
        "open_angle_deg"
    ] == angle
