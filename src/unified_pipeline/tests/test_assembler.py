"""Focused tests for Task 6.1 mandatory WorldContract assembly.

**Validates: Requirements 19.1, 19.2, 19.3, 19.4**
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings, strategies as st

from src.unified_pipeline.approval_gates import ApprovalGate
from src.unified_pipeline.assembler import (
    MANDATORY_CHAIN,
    ApprovedAssetRecord,
    AssetNormalizer,
    ConsumerDefaultError,
    DuplicateAuthorityError,
    InstanceAssemblyInput,
    PostHashMutationError,
    RevisionMismatchError,
    WorldContractAssembler,
)
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.models import MetricPlan, PlanRevision
from src.unified_pipeline.parametric_room import build_authoritative_parametric_room
from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
from src.unified_pipeline.plan_validator import _compute_plan_hash
from src.unified_pipeline.world_contract import (
    LightingConfig,
    MaterialIntent,
    Relationship,
    verify_hash,
)


def _camera() -> CameraContract:
    return CameraContract(position=(0.0, 1.6, -1.2), target=(0.0, 1.1, 0.0))


def _plan(*placements: dict) -> MetricPlan:
    base = MetricPlan(
        room_dimensions=(4.0, 4.0, 3.0),
        walls=_build_walls_from_dimensions(4.0, 4.0, 3.0),
        openings=({
            "id": "entry", "type": "door", "wall": "north",
            "parameter": 0.2, "width": 0.9, "height": 2.1,
        },),
        object_placements=tuple(placements),
        template_id="test-room",
    )
    return replace(base, revisions=(PlanRevision(
        revision=3,
        changed="approved normalized room",
        reason="test",
        plan_hash=_compute_plan_hash(base),
    ),))


def _placement(object_id: str, x: float) -> dict:
    return {
        "id": object_id,
        "name": object_id,
        "x": x,
        "y": 2.0,
        "width": 0.4,
        "height": 0.8,
        "depth": 0.4,
        "rotation_deg": 0.0,
    }


def _room(plan: MetricPlan, camera: CameraContract):
    gate = ApprovalGate("blockout", "plan_blockout")
    gate.present({
        "plan_revision": plan.revisions[-1].revision,
        "camera_hash": camera.compute_hash(),
    })
    gate.approve()
    return build_authoritative_parametric_room(plan, camera, gate)


def _asset(tmp_path: Path) -> ApprovedAssetRecord:
    path = tmp_path / "approved.glb"
    path.write_bytes(b"approved normalized glb")
    return ApprovedAssetRecord(
        path=str(path),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        triangle_count=1200,
        vertex_count=700,
        generator="hunyuan3d",
    )


def _intent(object_id: str, asset: ApprovedAssetRecord) -> InstanceAssemblyInput:
    return InstanceAssemblyInput(
        object_id=object_id,
        name=object_id,
        approved_asset=asset,
        physics_intent="dynamic",
        material_intent=MaterialIntent(
            base_color="#805533", metallic=0.0, roughness=0.7, pass_level=2
        ),
        semantic_label=f"furniture/{object_id}",
    )


def test_assembles_full_chain_and_binds_authoritative_values(tmp_path: Path) -> None:
    camera = _camera()
    plan = _plan(_placement("table", 1.0))
    room = _room(plan, camera)
    asset = _asset(tmp_path)

    result = WorldContractAssembler().assemble(
        plan,
        camera,
        room,
        (_intent("table", asset),),
        approved_plan_revision=3,
        relationships=(Relationship("table", "room", "containment"),),
        lighting=LightingConfig(ambient_color="#221811", ambient_intensity=0.4),
    )

    assert result.stage_trace == MANDATORY_CHAIN
    assert result.contract.plan_revision == "rev-3"
    assert result.contract.camera_hash == camera.compute_hash()
    assert result.contract.room_shell_ref.startswith("parametric-room:sha256:")
    assert verify_hash(result.contract)
    assert result.contract_hash == result.contract.contract_hash
    instance = result.contract.instances[0]
    assert instance.position.x == pytest.approx(-1.0)
    assert instance.position.z == pytest.approx(0.0)
    assert instance.scale.to_dict() == {"x": 0.4, "y": 0.8, "z": 0.4}
    assert instance.asset_binding.to_dict() == {
        "asset_id": asset.sha256,
        "mesh_path": str(Path(asset.path).resolve()),
        "triangle_count": 1200,
        "vertex_count": 700,
        "generator": "hunyuan3d",
    }


def test_normalizes_shared_approved_asset_exactly_once(tmp_path: Path) -> None:
    camera = _camera()
    plan = _plan(_placement("chair-a", 1.0), _placement("chair-b", 3.0))
    room = _room(plan, camera)
    asset = _asset(tmp_path)
    normalizer = AssetNormalizer()
    assembler = WorldContractAssembler(asset_normalizer=normalizer)

    result = assembler.assemble(
        plan,
        camera,
        room,
        (_intent("chair-b", asset), _intent("chair-a", asset)),
        approved_plan_revision=3,
        lighting=LightingConfig(),
    )
    assembler.assemble(
        plan,
        camera,
        room,
        (_intent("chair-a", asset), _intent("chair-b", asset)),
        approved_plan_revision=3,
        lighting=LightingConfig(),
    )

    assert len(result.normalized_assets) == 1
    assert result.normalized_assets[0].normalization_count == 1
    assert normalizer.normalization_count(asset) == 1


def test_rejects_revision_authority_and_consumer_default_drift(tmp_path: Path) -> None:
    camera = _camera()
    plan = _plan(_placement("table", 1.0))
    room = _room(plan, camera)
    intent = _intent("table", _asset(tmp_path))
    assembler = WorldContractAssembler()

    with pytest.raises(RevisionMismatchError, match="latest nonzero"):
        assembler.assemble(
            plan, camera, room, (intent,), approved_plan_revision=2,
            lighting=LightingConfig(),
        )
    with pytest.raises(DuplicateAuthorityError, match="more than one source"):
        assembler.assemble(
            plan, camera, room, (intent,), approved_plan_revision=3,
            lighting=LightingConfig(), authority_claims=("depth_mesh",),
        )
    with pytest.raises(ConsumerDefaultError, match="consumer defaults"):
        assembler.assemble(
            plan, camera, room, (intent,), approved_plan_revision=3,
            lighting=LightingConfig(), consumer_defaults={"scale": (1, 1, 1)},
        )


def test_detects_post_hash_mutation(tmp_path: Path) -> None:
    camera = _camera()
    plan = _plan(_placement("table", 1.0))
    result = WorldContractAssembler().assemble(
        plan,
        camera,
        _room(plan, camera),
        (_intent("table", _asset(tmp_path)),),
        approved_plan_revision=3,
        lighting=LightingConfig(),
    )

    object.__setattr__(result.contract, "camera_hash", "0" * 64)
    with pytest.raises(PostHashMutationError, match="changed after canonical hashing"):
        result.assert_unchanged()


# Property: canonical output is independent of caller collection ordering.
# **Validates: Requirements 19.2, 19.3**
@given(reverse_instances=st.booleans(), reverse_relationships=st.booleans())
@settings(max_examples=4, deadline=None)
def test_property_canonical_hash_ignores_input_order(
    reverse_instances: bool, reverse_relationships: bool
) -> None:
    camera = _camera()
    plan = _plan(_placement("chair-a", 1.0), _placement("chair-b", 3.0))
    room = _room(plan, camera)
    with TemporaryDirectory() as directory:
        asset = _asset(Path(directory))
        instances = [_intent("chair-a", asset), _intent("chair-b", asset)]
        relationships = [
            Relationship("chair-a", "room", "containment"),
            Relationship("chair-b", "room", "containment"),
        ]
        expected = WorldContractAssembler().assemble(
            plan, camera, room, instances, approved_plan_revision=3,
            relationships=relationships, lighting=LightingConfig(),
        )

        if reverse_instances:
            instances.reverse()
        if reverse_relationships:
            relationships.reverse()
        actual = WorldContractAssembler().assemble(
            plan, camera, room, instances, approved_plan_revision=3,
            relationships=relationships, lighting=LightingConfig(),
        )

    assert actual.contract_hash == expected.contract_hash
    assert actual.canonical_json == expected.canonical_json
