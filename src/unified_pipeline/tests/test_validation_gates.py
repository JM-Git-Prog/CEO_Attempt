"""Focused Task 6.2 tests for structural publication gates.

**Validates: Requirements 20.1-20.10**
"""
from __future__ import annotations

import hashlib
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from src.unified_pipeline.models import MetricPlan, PlanRevision
from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
from src.unified_pipeline.validation_gates import (
    AssetEvidence,
    CollisionEvidence,
    MaterialEvidence,
    ProvenanceNode,
    PublicationGateError,
    SemanticEvidence,
    SettleEvidence,
    StructuralGateContext,
    _rotation_aware_half_extents,
    authorize_compilation,
    validate_before_compilation,
)
from src.world_contract import (
    AppearanceIntent, BodyMode, CameraBinding, Dimensions, MaterialIntent,
    Mount, PhysicsIntent, PhysicsPolicy, RoomShell, SourceBinding, Transform,
    Vector3, WorldContract, WorldInstance, WorldOpening,
)

_HASH = "a" * 64


def _plan(object_id: str, *, paths: tuple[dict, ...] | None = None) -> MetricPlan:
    return MetricPlan(
        room_dimensions=(4.0, 4.0, 3.0),
        walls=_build_walls_from_dimensions(4.0, 4.0, 3.0),
        openings=({
            "id": "entry", "type": "door", "wall": "north",
            "parameter": 0.5, "width": 0.9, "height": 2.1,
        },),
        object_placements=({
            "id": object_id, "name": "table", "x": 1.0, "y": 2.0,
            "width": 0.6, "height": 0.8, "depth": 0.4,
            "rotation_deg": 0.0,
        },),
        circulation_paths=paths if paths is not None else ({
            "id": "main-path", "start": (3.5, 0.4), "end": (3.5, 3.6),
            "min_width": 0.6,
        },),
        revisions=(PlanRevision(
            revision=4, changed="approved", reason="test", plan_hash=_HASH,
        ),),
        template_id="gate-test",
    )


def _contract(object_id: str) -> WorldContract:
    material_id = f"material:{object_id}"
    physics_id = f"physics:{object_id}"
    return WorldContract(
        source=SourceBinding(
            session_id="structural-gate-test", interface_version=16,
            profile_id="unified-v16", plan_revision=4, plan_hash=_HASH,
            scene_graph_hash="b" * 64, camera_contract_id="camera-1",
            camera_contract_hash="c" * 64,
            appearance_intent_hash="d" * 64, canon_hash="e" * 64,
        ),
        room=RoomShell(
            dimensions=Dimensions(width_m=4.0, height_m=3.0, depth_m=4.0),
            floor_material_id="material:floor", wall_material_id="material:wall",
            ceiling_material_id="material:ceiling",
        ),
        openings=(WorldOpening(
            id="entry", kind="door", wall="north", offset_m=0.0,
            width_m=0.9, height_m=2.1,
        ),),
        instances=(WorldInstance(
            id=object_id, name="table", category="furniture", mount=Mount.FLOOR,
            transform=Transform(position_m=Vector3(x=1.0, y=0.4, z=2.0)),
            dimensions=Dimensions(width_m=0.6, height_m=0.8, depth_m=0.4),
            material_id=material_id, physics_intent_id=physics_id,
            geometry_strategy="generated", primitive_shape="box",
        ),),
        materials=(
            MaterialIntent(id="material:floor"), MaterialIntent(id="material:wall"),
            MaterialIntent(id="material:ceiling"), MaterialIntent(id=material_id),
        ),
        camera=CameraBinding(
            id="camera-1", source_schema_version="camera-contract/v1",
            position_m=Vector3(x=2.0, y=1.6, z=3.4),
            target_m=Vector3(x=2.0, y=1.0, z=2.0),
            up=Vector3(x=0.0, y=1.0, z=0.0), vertical_fov_deg=60.0,
            aspect_ratio=4 / 3, image_width_px=1024, image_height_px=768,
            near_plane_m=0.1, far_plane_m=100.0,
        ),
        appearance=AppearanceIntent(id="appearance"),
        physics=PhysicsPolicy(intents=(PhysicsIntent(
            id=physics_id, subject_id=object_id, body_mode=BodyMode.STATIC,
            collision_shape="box", mass_kg=0.0,
        ),)),
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(tmp_path: Path) -> StructuralGateContext:
    object_id = str(uuid.uuid4())
    contract = _contract(object_id)
    mesh = tmp_path / "table.glb"
    mesh.write_bytes(b"self-contained-test-glb")
    canonical_hash = contract.content_hash()
    return StructuralGateContext(
        contract=contract,
        plan=_plan(object_id),
        provenance=(
            ProvenanceNode("raw-evidence", "evidence", "1" * 64),
            ProvenanceNode("accepted-intent", "intent", "2" * 64, "raw-evidence"),
            ProvenanceNode("approved-plan", "approved_plan", _HASH, "accepted-intent", 4),
            ProvenanceNode("contract", "world_contract", canonical_hash, "approved-plan", 4),
        ),
        assets=(AssetEvidence(
            "asset-binding", object_id, str(mesh), _sha(mesh), 1200, 1,
        ),),
        materials=(MaterialEvidence(
            "material-binding", object_id, f"material:{object_id}", True,
        ),),
        semantics=(SemanticEvidence(
            "semantic-binding", object_id, object_id, "furniture/table", "props",
        ),),
        collisions=(CollisionEvidence(
            "collision-binding", object_id, object_id, (1.0, 0.4, 2.0),
            (0.6, 0.8, 0.4),
        ),),
        settle=SettleEvidence(canonical_hash, 4, True),
    )


def _rebind_contract(
    context: StructuralGateContext, contract: WorldContract,
    *, collision: CollisionEvidence | None = None,
) -> StructuralGateContext:
    canonical_hash = contract.content_hash()
    provenance = tuple(
        replace(item, sha256=canonical_hash)
        if item.kind == "world_contract" else item
        for item in context.provenance
    )
    return replace(
        context,
        contract=contract,
        provenance=provenance,
        collisions=(collision,) if collision is not None else context.collisions,
        settle=replace(context.settle, contract_hash=canonical_hash),
    )


def _result(report, name: str):
    return next(item for item in report.results if item.gate == name)


def test_all_structural_gates_pass_and_authorize_compilation(tmp_path: Path) -> None:
    context = _context(tmp_path)

    report = validate_before_compilation(context)
    token = authorize_compilation(context)

    assert report.passed is True
    assert [item.gate for item in report.results] == [
        "provenance", "containment", "overlap_opening_circulation", "camera",
        "asset", "material", "geometry", "physics", "semantic",
    ]
    assert all(item.plan_revision == 4 for item in report.results)
    assert all(item.canonical_hash == context.contract.content_hash() for item in report.results)
    assert report.parity_deferred is True
    assert token.canonical_hash == context.contract.content_hash()
    assert len(token.report_hash) == 64


def test_gate_report_records_focused_provenance_failure(tmp_path: Path) -> None:
    context = _context(tmp_path)
    broken = replace(
        context,
        provenance=tuple(
            replace(item, parent_id="missing-node") if item.kind == "intent" else item
            for item in context.provenance
        ),
    )

    result = _result(validate_before_compilation(broken), "provenance")

    assert result.passed is False
    assert any(item.code == "provenance.missing_parent" for item in result.diagnostics)
    assert any(item.offending_node == "accepted-intent" for item in result.diagnostics)


def test_rotation_aware_extent_and_camera_collision_fail_closed(tmp_path: Path) -> None:
    context = _context(tmp_path)
    instance = context.contract.instances[0]
    changed_instance = instance.model_copy(update={
        "transform": Transform(
            position_m=Vector3(x=0.4, y=0.4, z=2.0),
            rotation_deg=Vector3(x=0.0, y=45.0, z=0.0),
        ),
        "dimensions": Dimensions(width_m=0.2, height_m=0.8, depth_m=1.0),
    })
    payload = context.contract.model_dump()
    payload["instances"] = [changed_instance.model_dump()]
    changed = WorldContract.model_validate(payload)
    collision = CollisionEvidence(
        "collision-binding", instance.id, instance.id, (2.0, 1.6, 3.4),
        (0.2, 0.8, 1.0), (0.0, 45.0, 0.0),
    )
    changed_context = _rebind_contract(context, changed, collision=collision)

    report = validate_before_compilation(changed_context)

    assert any(
        item.code == "containment.object_extent"
        for item in _result(report, "containment").diagnostics
    )
    assert any(
        item.code == "camera.inside_collision"
        for item in _result(report, "camera").diagnostics
    )


def test_opening_circulation_and_overlap_gate_reports_bindings(tmp_path: Path) -> None:
    context = _context(tmp_path)
    bad_plan = replace(context.plan, circulation_paths=({
        "id": "too-narrow", "start": (3.5, 0.4), "end": (3.5, 3.6),
        "min_width": 0.59,
    },))

    result = _result(
        validate_before_compilation(replace(context, plan=bad_plan)),
        "overlap_opening_circulation",
    )

    assert result.passed is False
    diagnostic = next(
        item for item in result.diagnostics
        if item.code == "circulation.minimum_clearance"
    )
    assert diagnostic.offending_binding == "too-narrow"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda item: replace(item, normalization_count=2), "asset.normalization_count"),
        (lambda item: replace(item, triangle_count=0), "asset.triangle_count"),
        (lambda item: replace(item, sha256="0" * 64), "asset.sha256_mismatch"),
    ],
)
def test_asset_gate_verifies_digest_triangles_and_exactly_once_normalization(
    tmp_path: Path, change, code: str,
) -> None:
    context = _context(tmp_path)
    report = validate_before_compilation(
        replace(context, assets=(change(context.assets[0]),))
    )
    assert any(item.code == code for item in _result(report, "asset").diagnostics)


def test_material_degradation_must_be_honest(tmp_path: Path) -> None:
    context = _context(tmp_path)
    dishonest = replace(
        context.materials[0], verified=False, degraded=True, degradation_reason=""
    )

    result = _result(
        validate_before_compilation(replace(context, materials=(dishonest,))),
        "material",
    )

    assert any(
        item.code == "material.missing_degradation_reason"
        for item in result.diagnostics
    )


def test_geometry_physics_and_semantic_failures_block_compilation(tmp_path: Path) -> None:
    context = _context(tmp_path)
    open_plan = replace(context.plan, walls=context.plan.walls[:-1])
    bad_semantic = replace(
        context.semantics[0], stable_uuid=str(uuid.uuid4()), category="architecture"
    )
    bad_settle = replace(
        context.settle, total_unsettled=1,
        floating_instance_ids=(context.contract.instances[0].id,),
    )
    broken = replace(
        context, plan=open_plan, semantics=(bad_semantic,), settle=bad_settle,
    )

    report = validate_before_compilation(broken)

    assert any(item.code == "geometry.room_closure" for item in _result(report, "geometry").diagnostics)
    assert any(item.code == "physics.unsettled" for item in _result(report, "physics").diagnostics)
    assert {item.code for item in _result(report, "semantic").diagnostics} >= {
        "semantic.unstable_uuid", "semantic.invalid_category",
    }
    with pytest.raises(PublicationGateError, match="compilation blocked"):
        report.require_compilation_ready()


def test_degraded_material_with_reason_is_publishable(tmp_path: Path) -> None:
    context = _context(tmp_path)
    degraded = replace(
        context.materials[0], verified=False, degraded=True,
        degradation_reason="Pass 2 unavailable; verified Pass 1 base color retained",
    )

    report = validate_before_compilation(replace(context, materials=(degraded,)))

    assert _result(report, "material").passed is True
    assert report.passed is True


# Property: positions computed from rotation-aware extents remain contained.
# **Validates: Requirements 20.1, 20.4**
@given(yaw=st.floats(
    min_value=-720.0, max_value=720.0, allow_nan=False, allow_infinity=False
))
@settings(max_examples=40, deadline=None)
def test_property_rotation_aware_extent_drives_containment(yaw: float) -> None:
    with tempfile.TemporaryDirectory() as directory:
        context = _context(Path(directory))
        instance = context.contract.instances[0]
        dimensions = (0.2, 0.8, 1.0)
        half = _rotation_aware_half_extents(dimensions, (0.0, yaw, 0.0))
        center = (half[0] + 0.01, 0.4, 2.0)
        changed_instance = instance.model_copy(update={
            "transform": Transform(
                position_m=Vector3(x=center[0], y=center[1], z=center[2]),
                rotation_deg=Vector3(x=0.0, y=yaw, z=0.0),
            ),
            "dimensions": Dimensions(
                width_m=dimensions[0], height_m=dimensions[1], depth_m=dimensions[2]
            ),
        })
        payload = context.contract.model_dump()
        payload["instances"] = [changed_instance.model_dump()]
        contract = WorldContract.model_validate(payload)
        collision = CollisionEvidence(
            "collision-binding", instance.id, instance.id, center, dimensions,
            (0.0, yaw, 0.0),
        )
        rebound = _rebind_contract(context, contract, collision=collision)

        result = _result(validate_before_compilation(rebound), "containment")

        assert result.passed is True
