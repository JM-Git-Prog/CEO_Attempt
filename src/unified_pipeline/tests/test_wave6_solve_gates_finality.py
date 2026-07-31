"""Integrated Wave 6 tests across solve, gates, and event finality.

The assembly/event path uses ``src.unified_pipeline.world_contract`` while the
structural gates consume the established Pydantic ``src.world_contract``.  The
fixtures below preserve and assert their shared authority values explicitly;
the distinct schemas are not treated as hash-equivalent.

**Validates: Requirements 19.2, 19.3, 20.1-20.10**
"""
from __future__ import annotations

import hashlib
import math
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from src.unified_pipeline.assembler import (
    ConsumerDefaultError,
    DuplicateAuthorityError,
    RevisionMismatchError,
    WorldContractAssembler,
)
from src.unified_pipeline.event_system import (
    EventDisposition,
    EventFinality,
    EventSystem,
)
from src.unified_pipeline.tests import test_assembler as assembly_fixtures
from src.unified_pipeline.validation_gates import (
    AssetEvidence,
    CollisionEvidence,
    MaterialEvidence,
    ProvenanceNode,
    SemanticEvidence,
    SettleEvidence,
    StructuralGateContext,
    validate_before_compilation,
)
from src.unified_pipeline.world_contract import (
    LightingConfig,
    Relationship,
    bind_plan_revision,
    finalize,
    verify_hash,
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
    WorldContract as GateWorldContract,
    WorldInstance,
    WorldOpening,
)


def _assembled(tmp_path: Path):
    object_id = str(uuid.uuid4())
    camera = assembly_fixtures._camera()
    placement = assembly_fixtures._placement(object_id, 1.0)
    placement["elevation"] = 0.4
    plan = assembly_fixtures._plan(placement)
    room = assembly_fixtures._room(plan, camera)
    asset = assembly_fixtures._asset(tmp_path)
    intent = assembly_fixtures._intent(object_id, asset)
    relationships = (
        Relationship(object_id, "entry", "adjacency"),
        Relationship(object_id, "room", "containment"),
    )
    result = WorldContractAssembler().assemble(
        plan,
        camera,
        room,
        (intent,),
        approved_plan_revision=3,
        relationships=relationships,
        lighting=LightingConfig(ambient_color="#221811", ambient_intensity=0.4),
    )
    return object_id, camera, plan, room, asset, intent, result


def _gate_plan_hash(plan) -> str:
    """Expand the unified Plan fingerprint into the gate schema's SHA-256 field."""
    return hashlib.sha256(plan.revisions[-1].plan_hash.encode("utf-8")).hexdigest()


def _gate_contract(object_id, camera, plan, result) -> GateWorldContract:
    modern = result.contract.instances[0]
    width, depth, height = plan.room_dimensions
    material_id = f"material:{object_id}"
    physics_id = f"physics:{object_id}"
    yaw = math.degrees(2.0 * math.atan2(modern.rotation.y, modern.rotation.w))
    opening = plan.openings[0]
    wall_length = width if opening["wall"] in {"north", "south"} else depth
    offset = (float(opening["parameter"]) - 0.5) * wall_length
    return GateWorldContract(
        source=SourceBinding(
            session_id="wave6-integration",
            interface_version=16,
            profile_id="unified-v16",
            plan_revision=3,
            plan_hash=_gate_plan_hash(plan),
            scene_graph_hash=result.scene_graph.room_authority_hash,
            camera_contract_id="camera-1",
            camera_contract_hash=result.contract.camera_hash,
            appearance_intent_hash="d" * 64,
            canon_hash="e" * 64,
        ),
        room=RoomShell(
            dimensions=Dimensions(width_m=width, height_m=height, depth_m=depth),
            floor_material_id="material:floor",
            wall_material_id="material:wall",
            ceiling_material_id="material:ceiling",
        ),
        openings=(WorldOpening(
            id=str(opening["id"]),
            kind=str(opening["type"]),
            wall=str(opening["wall"]),
            offset_m=offset,
            width_m=float(opening["width"]),
            height_m=float(opening["height"]),
        ),),
        instances=(WorldInstance(
            id=object_id,
            name=modern.name,
            category="furniture",
            mount=Mount.FLOOR,
            transform=Transform(
                position_m=Vector3(**modern.position.to_dict()),
                rotation_deg=Vector3(x=0.0, y=yaw, z=0.0),
            ),
            dimensions=Dimensions(
                width_m=modern.scale.x,
                height_m=modern.scale.y,
                depth_m=modern.scale.z,
            ),
            material_id=material_id,
            physics_intent_id=physics_id,
            geometry_strategy="generated",
            primitive_shape="box",
        ),),
        materials=(
            MaterialIntent(id="material:floor"),
            MaterialIntent(id="material:wall"),
            MaterialIntent(id="material:ceiling"),
            MaterialIntent(
                id=material_id,
                base_color=modern.material_intent.base_color,
                metallic=modern.material_intent.metallic,
                roughness=modern.material_intent.roughness,
            ),
        ),
        camera=CameraBinding(
            id="camera-1",
            source_schema_version="camera-contract/v1",
            position_m=Vector3(
                x=camera.position[0], y=camera.position[1], z=camera.position[2]
            ),
            target_m=Vector3(
                x=camera.target[0], y=camera.target[1], z=camera.target[2]
            ),
            up=Vector3(x=camera.up[0], y=camera.up[1], z=camera.up[2]),
            vertical_fov_deg=camera.vfov,
            aspect_ratio=camera.aspect,
            image_width_px=camera.raster_width,
            image_height_px=camera.raster_height,
            near_plane_m=camera.near,
            far_plane_m=camera.far,
        ),
        appearance=AppearanceIntent(id="appearance"),
        physics=PhysicsPolicy(intents=(PhysicsIntent(
            id=physics_id,
            subject_id=object_id,
            body_mode=BodyMode.STATIC,
            collision_shape="box",
            mass_kg=0.0,
        ),)),
    )


def _gate_context(object_id, plan, room, result) -> StructuralGateContext:
    contract = _gate_contract(object_id, assembly_fixtures._camera(), plan, result)
    canonical_hash = contract.content_hash()
    modern = result.contract.instances[0]
    normalized = result.normalized_assets[0]
    yaw = math.degrees(2.0 * math.atan2(modern.rotation.y, modern.rotation.w))
    return StructuralGateContext(
        contract=contract,
        plan=plan,
        room=room,
        provenance=(
            ProvenanceNode("raw-evidence", "evidence", "1" * 64),
            ProvenanceNode("accepted-intent", "intent", "2" * 64, "raw-evidence"),
            ProvenanceNode(
                "approved-plan", "approved_plan", _gate_plan_hash(plan),
                "accepted-intent", 3,
            ),
            ProvenanceNode("contract", "world_contract", canonical_hash, "approved-plan", 3),
        ),
        assets=(AssetEvidence(
            "asset-binding", object_id, normalized.path, normalized.sha256,
            normalized.triangle_count, normalized.normalization_count,
        ),),
        materials=(MaterialEvidence(
            "material-binding", object_id, f"material:{object_id}", True,
        ),),
        semantics=(SemanticEvidence(
            "semantic-binding", object_id, object_id, modern.semantic_label, "props",
        ),),
        collisions=(CollisionEvidence(
            "collision-binding",
            object_id,
            object_id,
            (modern.position.x, modern.position.y, modern.position.z),
            (modern.scale.x, modern.scale.y, modern.scale.z),
            (0.0, yaw, 0.0),
        ),),
        settle=SettleEvidence(canonical_hash, 3, True),
    )


def _rebind(context: StructuralGateContext, contract: GateWorldContract, **changes):
    canonical_hash = contract.content_hash()
    provenance = tuple(
        replace(node, sha256=canonical_hash) if node.kind == "world_contract" else node
        for node in context.provenance
    )
    return replace(
        context,
        contract=contract,
        provenance=provenance,
        settle=replace(context.settle, contract_hash=canonical_hash),
        **changes,
    )


def _gate_result(report, gate: str):
    return next(result for result in report.results if result.gate == gate)


def _break_gate(context: StructuralGateContext, gate: str) -> StructuralGateContext:
    if gate == "provenance":
        return replace(context, provenance=tuple(
            replace(node, sha256="0" * 64) if node.kind == "world_contract" else node
            for node in context.provenance
        ))
    if gate == "containment":
        instance = context.contract.instances[0]
        moved = instance.model_copy(update={
            "transform": instance.transform.model_copy(update={
                "position_m": Vector3(x=10.0, y=instance.transform.position_m.y, z=0.0)
            })
        })
        payload = context.contract.model_dump()
        payload["instances"] = [moved.model_dump()]
        contract = GateWorldContract.model_validate(payload)
        collision = replace(context.collisions[0], center_m=(10.0, 0.4, 0.0))
        return _rebind(context, contract, collisions=(collision,))
    if gate == "overlap_opening_circulation":
        bad_plan = replace(context.plan, circulation_paths=({
            "id": "too-narrow", "start": (1.8, -1.5), "end": (1.8, 1.5),
            "min_width": 0.59,
        },))
        return replace(context, plan=bad_plan)
    if gate == "camera":
        payload = context.contract.model_dump()
        payload["camera"]["target_m"] = {"x": 20.0, "y": 1.0, "z": 20.0}
        return _rebind(context, GateWorldContract.model_validate(payload))
    if gate == "asset":
        return replace(
            context,
            assets=(replace(context.assets[0], normalization_count=2),),
        )
    if gate == "material":
        return replace(
            context,
            materials=(replace(context.materials[0], verified=False, degraded=False),),
        )
    if gate == "geometry":
        return replace(context, plan=replace(context.plan, walls=context.plan.walls[:-1]))
    if gate == "physics":
        return replace(context, settle=replace(context.settle, completed=False))
    if gate == "semantic":
        return replace(
            context,
            semantics=(replace(context.semantics[0], category="architecture"),),
        )
    raise AssertionError(f"unknown gate {gate}")


def test_solve_chain_is_deterministic_after_relationship_solving_and_fail_closed(
    tmp_path: Path,
) -> None:
    object_id, camera, plan, room, asset, intent, first = _assembled(tmp_path)
    second = WorldContractAssembler().assemble(
        plan,
        camera,
        room,
        (intent,),
        approved_plan_revision=3,
        relationships=tuple(reversed(first.scene_graph.relationships)),
        lighting=LightingConfig(ambient_color="#221811", ambient_intensity=0.4),
    )

    assert first.contract.relationships == second.contract.relationships
    assert first.canonical_json == second.canonical_json
    assert first.contract_hash == second.contract_hash
    assert verify_hash(first.contract)
    assert first.normalized_assets[0].normalization_count == 1
    assert first.contract.instances[0].asset_binding.mesh_path == str(Path(asset.path).resolve())

    assembler = WorldContractAssembler()
    with pytest.raises(RevisionMismatchError):
        assembler.assemble(
            plan, camera, room, (intent,), approved_plan_revision=2,
            lighting=LightingConfig(),
        )
    with pytest.raises(DuplicateAuthorityError):
        assembler.assemble(
            plan, camera, room, (intent,), approved_plan_revision=3,
            authority_claims=("depth-room",), lighting=LightingConfig(),
        )
    with pytest.raises(ConsumerDefaultError):
        assembler.assemble(
            plan, camera, room, (intent,), approved_plan_revision=3,
            consumer_defaults={"browser.scale": (1.0, 1.0, 1.0)},
            lighting=LightingConfig(),
        )
    assert first.contract.instances[0].object_id == object_id


def test_contract_families_preserve_identical_authority_and_all_gates_pass(
    tmp_path: Path,
) -> None:
    object_id, camera, plan, room, _, _, assembled = _assembled(tmp_path)
    context = _gate_context(object_id, plan, room, assembled)
    modern = assembled.contract.instances[0]
    gated = context.contract.instances[0]

    assert assembled.contract.plan_revision == f"rev-{context.contract.source.plan_revision}"
    assert assembled.contract.camera_hash == context.contract.source.camera_contract_hash
    assert modern.object_id == gated.id == object_id
    assert modern.position.to_dict() == gated.transform.position_m.model_dump()
    assert modern.scale.to_dict() == {
        "x": gated.dimensions.width_m,
        "y": gated.dimensions.height_m,
        "z": gated.dimensions.depth_m,
    }
    assert modern.asset_binding.mesh_path == context.assets[0].path
    assert modern.asset_binding.asset_id == context.assets[0].sha256
    assert verify_hash(assembled.contract)
    assert len(context.contract.content_hash()) == 64

    report = validate_before_compilation(context)
    assert report.passed
    assert all(result.passed for result in report.results)
    assert all(result.plan_revision == 3 for result in report.results)
    assert all(result.canonical_hash == context.contract.content_hash() for result in report.results)


@pytest.mark.parametrize(
    "gate",
    (
        "provenance",
        "containment",
        "overlap_opening_circulation",
        "camera",
        "asset",
        "material",
        "geometry",
        "physics",
        "semantic",
    ),
)
def test_each_structural_gate_has_a_fail_closed_path(tmp_path: Path, gate: str) -> None:
    object_id, _, plan, room, _, _, assembled = _assembled(tmp_path)
    context = _gate_context(object_id, plan, room, assembled)

    result = _gate_result(validate_before_compilation(_break_gate(context, gate)), gate)

    assert result.passed is False
    assert result.plan_revision == 3
    assert result.canonical_hash
    assert result.diagnostics
    expected_prefix = {
        "overlap_opening_circulation": "circulation",
    }.get(gate, gate)
    assert any(diagnostic.code.startswith(expected_prefix) for diagnostic in result.diagnostics)


def test_finality_orders_contract_before_final_and_survives_reconnect_then_cancels_stale(
    tmp_path: Path,
) -> None:
    _, _, _, _, _, _, assembled = _assembled(tmp_path)
    contract = assembled.contract
    journal = tmp_path / "wave6-events.jsonl"
    system = EventSystem("wave6-session", journal)

    registered = system.register_contract(contract)
    finalized = system.authorize_finality(
        plan_revision=contract.plan_revision,
        contract_hash=contract.contract_hash,
        structural_gates_passed=True,
        parity_gate_passed=True,
    )
    published = system.publish_object(contract.instances[0].object_id).event

    assert registered.finality is EventFinality.PROVISIONAL
    assert registered.sequence < finalized.sequence < published.sequence
    assert published.finality is EventFinality.FINAL
    assert published.contract_hash == contract.contract_hash
    assert published.payload["position"] == contract.instances[0].position.to_dict()

    reconnected = EventSystem("wave6-session", journal)
    assert [event.to_dict() for event in reconnected.replay(registered.event_id)] == [
        event.to_dict() for event in system.replay(registered.event_id)
    ]

    newer = finalize(bind_plan_revision(contract, "rev-4"))
    reconnected.register_contract(newer)
    stale = reconnected.ingest_compiler({
        "event_id": "late-rev-3-response",
        "event_type": "compiler.completed",
        "status": "final",
        "plan_revision": contract.plan_revision,
        "contract_hash": contract.contract_hash,
    })
    assert stale.disposition is EventDisposition.DOWNGRADED
    assert stale.event.finality is EventFinality.PROVISIONAL
    assert "stale plan revision" in stale.reason

    reconnected.authorize_finality(
        plan_revision=newer.plan_revision,
        contract_hash=newer.contract_hash,
        structural_gates_passed=True,
        parity_gate_passed=True,
    )
    mismatched = reconnected.ingest_compiler({
        "event_id": "wrong-hash-response",
        "event_type": "compiler.completed",
        "status": "final",
        "plan_revision": newer.plan_revision,
        "contract_hash": contract.contract_hash,
    })
    assert mismatched.disposition is EventDisposition.DOWNGRADED
    assert mismatched.event.finality is EventFinality.PROVISIONAL
    assert "canonical hash does not match" in mismatched.reason
