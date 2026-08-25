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
    AssemblyError,
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
    DoorInteractionMetadata,
    DynamicInteractionMetadata,
    InteractionBinding,
    InteractionCollider,
    LightingConfig,
    LightSource,
    MaterialIntent,
    Quaternion,
    Relationship,
    Vec3,
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
    navigation = result.contract.navigation
    assert navigation is not None
    assert navigation.bounds_minimum.to_dict() == {
        "x": room.navigable_bounds.minimum_m[0],
        "y": room.navigable_bounds.minimum_m[1],
        "z": room.navigable_bounds.minimum_m[2],
    }
    assert navigation.bounds_maximum.to_dict() == {
        "x": room.navigable_bounds.maximum_m[0],
        "y": room.navigable_bounds.maximum_m[1],
        "z": room.navigable_bounds.maximum_m[2],
    }
    assert [body.to_dict() for body in navigation.static_bodies] == [
        {
            "body_id": collision.stable_id,
            "source_id": collision.geometry_id,
            "center": {
                "x": collision.position_upbge[0],
                "y": collision.position_upbge[2],
                "z": collision.position_upbge[1],
            },
            "dimensions": {
                "x": collision.dimensions_upbge[0],
                "y": collision.dimensions_upbge[2],
                "z": collision.dimensions_upbge[1],
            },
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            "shape": collision.shape,
            "body_mode": collision.body_mode,
            "source_kind": "architecture",
        }
        for collision in sorted(room.collision, key=lambda item: item.stable_id)
    ]
    assert navigation.spawn_candidates[0].to_dict() == dict(
        zip(("x", "y", "z"), camera.position)
    )
    assert navigation.boundary_tolerance_m == pytest.approx(1e-9)
    architecture = {
        body.source_id: body for body in navigation.static_bodies
        if body.source_kind == "architecture"
    }
    floor = architecture["room:floor"]
    ceiling = architecture["room:ceiling"]
    assert floor.dimensions.y == pytest.approx(0.1)
    assert floor.center.y == pytest.approx(-0.05)
    assert ceiling.dimensions.y == pytest.approx(0.1)
    assert ceiling.center.y == pytest.approx(3.05)
    assert all(
        not (body.dimensions.y > 1.0 and abs(body.center.z) < body.dimensions.z / 2.0)
        for body in architecture.values()
        if body.source_id in {"room:floor", "room:ceiling"}
    )
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


def test_y_up_navigation_path_has_no_phantom_floor_and_keeps_real_obstacles(tmp_path: Path) -> None:
    """Probe the exact Browser player box against assembled Y-up collision bodies."""
    camera = _camera()
    plan = _plan(_placement("counter", 1.0))
    room = _room(plan, camera)
    counter = replace(
        _intent("counter", _asset(tmp_path)),
        physics_intent="static",
    )
    navigation = WorldContractAssembler().assemble(
        plan,
        camera,
        room,
        (counter,),
        approved_plan_revision=3,
        lighting=LightingConfig(),
    ).contract.navigation
    assert navigation is not None

    def player_intersects(position: Vec3, body) -> bool:
        player_center = Vec3(
            position.x,
            position.y - navigation.eye_height + navigation.player_height / 2.0,
            position.z,
        )
        player_half = Vec3(
            navigation.player_radius,
            navigation.player_height / 2.0,
            navigation.player_radius,
        )
        body_half = Vec3(
            body.dimensions.x / 2.0,
            body.dimensions.y / 2.0,
            body.dimensions.z / 2.0,
        )
        return all(
            abs(getattr(player_center, axis) - getattr(body.center, axis))
            < getattr(player_half, axis) + getattr(body_half, axis) - 1e-9
            for axis in ("x", "y", "z")
        )

    # The old Z-up tuple copy made the floor a vertical slab through z=0. A
    # centerline walk now remains clear across that exact former phantom plane.
    center_route = tuple(
        Vec3(0.0, navigation.eye_height, z / 10.0)
        for z in range(-12, 13, 2)
    )
    assert all(
        not any(player_intersects(point, body) for body in navigation.static_bodies)
        for point in center_route
    )

    counter_body = next(
        body for body in navigation.static_bodies if body.source_id == "counter"
    )
    assert player_intersects(
        Vec3(counter_body.center.x, navigation.eye_height, counter_body.center.z),
        counter_body,
    )

    wall_bodies = [
        body for body in navigation.static_bodies
        if body.source_kind == "architecture" and "wall" in body.source_id
    ]
    assert wall_bodies
    wall = max(wall_bodies, key=lambda body: body.dimensions.y)
    assert player_intersects(
        Vec3(wall.center.x, navigation.eye_height, wall.center.z), wall
    )

    opening = room.openings[0]
    opening_center = Vec3(
        opening.position_upbge[0],
        navigation.eye_height,
        opening.position_upbge[1],
    )
    assert not any(player_intersects(opening_center, body) for body in wall_bodies)


def test_assembler_hash_binds_explicit_uuid_interactions(tmp_path: Path) -> None:
    object_id = "db2790ad-331f-5411-9347-1815acb004bd"
    interaction = InteractionBinding(
        interaction_id="3a07e72b-8b91-56e9-b902-34cdba2f85cf",
        object_id=object_id,
        kind="dynamic",
        collider=InteractionCollider(
            center_offset=Vec3(0.0, 0.4, 0.0),
            dimensions=Vec3(0.4, 0.8, 0.4),
        ),
        dynamic=DynamicInteractionMetadata(
            mass_kg=6.0,
            friction=0.5,
            restitution=0.2,
            can_grab=True,
            can_push=True,
            can_topple=True,
            grab_distance_m=3.0,
            hold_distance_m=1.5,
            hold_stiffness=12.0,
            push_impulse_ns=9.0,
            linear_damping=1.0,
            angular_damping=1.5,
        ),
    )
    camera = _camera()
    plan = _plan(_placement(object_id, 1.0))
    result = WorldContractAssembler().assemble(
        plan,
        camera,
        _room(plan, camera),
        (_intent(object_id, _asset(tmp_path)),),
        approved_plan_revision=3,
        interactions=(interaction,),
        lighting=LightingConfig(),
    )

    assert result.contract.interactions == (interaction,)
    assert result.contract.to_dict()["interactions"] == [interaction.to_dict()]
    assert verify_hash(result.contract)


def test_dynamic_instance_uses_explicit_settled_transform(tmp_path: Path) -> None:
    object_id = "db2790ad-331f-5411-9347-1815acb004bd"
    camera = _camera()
    plan = _plan(_placement(object_id, 1.0))
    asset = _asset(tmp_path)
    intent = replace(
        _intent(object_id, asset),
        settled_position=(-0.8, 0.25, 0.1),
        settled_rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
    )

    result = WorldContractAssembler().assemble(
        plan, camera, _room(plan, camera), (intent,),
        approved_plan_revision=3, lighting=LightingConfig(),
    )

    instance = result.contract.instances[0]
    assert instance.position.to_dict() == {"x": -0.8, "y": 0.25, "z": 0.1}
    assert instance.rotation == intent.settled_rotation
    assert verify_hash(result.contract)


def test_static_instance_rejects_settled_transform_override(tmp_path: Path) -> None:
    camera = _camera()
    plan = _plan(_placement("table", 1.0))
    intent = replace(
        _intent("table", _asset(tmp_path)),
        physics_intent="static",
        settled_position=(0.0, 0.0, 0.0),
        settled_rotation=Quaternion(),
    )
    with pytest.raises(ConsumerDefaultError, match="dynamic physics"):
        WorldContractAssembler().assemble(
            plan, camera, _room(plan, camera), (intent,),
            approved_plan_revision=3, lighting=LightingConfig(),
        )


def test_assembler_keeps_hinged_door_out_of_static_navigation(tmp_path: Path) -> None:
    object_id = "39ea4512-28ff-5936-8358-45833a64168d"
    interaction = InteractionBinding(
        interaction_id="0e158c43-3c65-5903-a58d-acceeea1496e",
        object_id=object_id,
        kind="door_hinge",
        collider=InteractionCollider(
            center_offset=Vec3(0.0, 0.4, 0.0),
            dimensions=Vec3(0.4, 0.8, 0.4),
        ),
        door=DoorInteractionMetadata(
            pivot=Vec3(-1.2, 0.0, 0.0),
            axis=Vec3(0.0, 1.0, 0.0),
            lower_limit_deg=0.0,
            upper_limit_deg=90.0,
            initial_angle_deg=0.0,
            angular_speed_deg_s=100.0,
            interaction_distance_m=2.5,
            interaction_mass_kg=15.0,
        ),
    )
    camera = _camera()
    plan = _plan(_placement(object_id, 1.0))
    asset = _asset(tmp_path)
    door_intent = InstanceAssemblyInput(
        object_id=object_id,
        name="Door",
        approved_asset=asset,
        physics_intent="static",
        material_intent=MaterialIntent(
            base_color="#805533", metallic=0.0, roughness=0.7, pass_level=2
        ),
        semantic_label="architecture/door",
        is_architectural=True,
    )

    result = WorldContractAssembler().assemble(
        plan,
        camera,
        _room(plan, camera),
        (door_intent,),
        approved_plan_revision=3,
        interactions=(interaction,),
        lighting=LightingConfig(),
    )

    assert result.contract.interactions == (interaction,)
    assert all(
        body.source_id != object_id
        for body in result.contract.navigation.static_bodies
    )
    assert verify_hash(result.contract)


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


def test_rejects_unsupported_inexact_lighting_before_contract_hashing(
    tmp_path: Path,
) -> None:
    """Validates Requirement 22.5 at the final WorldContract binding boundary."""
    camera = _camera()
    plan = _plan(_placement("table", 1.0))
    unsupported = LightingConfig(
        ambient_color="#221811",
        ambient_intensity=0.4,
        lights=(LightSource(
            light_id="incomplete-spot",
            light_type="spot",
            position=Vec3(0.0, 2.5, 0.0),
            color="#ffd2a1",
            intensity=2.0,
            temperature=3200.0,
            cast_shadows=True,
        ),),
    )

    with pytest.raises(AssemblyError, match="lacks enough contract data"):
        WorldContractAssembler().assemble(
            plan,
            camera,
            _room(plan, camera),
            (_intent("table", _asset(tmp_path)),),
            approved_plan_revision=3,
            lighting=unsupported,
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
