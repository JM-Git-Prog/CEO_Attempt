"""Focused tests for Task 7.1 BrowserCompiler.

Validates Requirements 21.1 and 21.4.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.compilers.browser import BrowserCompiler, BrowserCompilerError
from src.unified_pipeline.world_contract import (
    AssetBinding,
    DoorInteractionMetadata,
    DynamicInteractionMetadata,
    FirstPersonNavigation,
    InteractionBinding,
    InteractionCollider,
    LightSource,
    LightingConfig,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    StaticCollisionBody,
    Vec3,
    WorldContract,
    finalize,
    serialize,
)


_OBJECT_UUID = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
_INTERACTION_UUID = "36ad6eb4-2330-59d9-83ac-11455dc88435"
_DOOR_UUID = "3d793b48-2950-5509-938b-37e7a902e55e"
_DOOR_INTERACTION_UUID = "64876636-3e6f-58cb-8832-24ff838b3968"


def _contract(tmp_path: Path, *, include_camera: bool = True) -> WorldContract:
    tmp_path.mkdir(parents=True, exist_ok=True)
    mesh = tmp_path / "approved.glb"
    mesh.write_bytes(b"exact-approved-browser-glb")
    digest = hashlib.sha256(mesh.read_bytes()).hexdigest()
    camera = CameraContract(
        position=(-1.25, 1.625, -2.75),
        target=(0.125, 0.875, 1.5),
        up=(0.0, 1.0, 0.0),
        vfov=53.75,
        aspect=1.5,
        near=0.03125,
        far=87.5,
        raster_width=1200,
        raster_height=800,
    )
    instance = ObjectInstance(
        object_id=_OBJECT_UUID,
        name="Chair",
        position=Vec3(-0.625, 0.45, 1.875),
        rotation=Quaternion(0.0, -0.3826834323650898, 0.0, 0.9238795325112867),
        scale=Vec3(0.55, 0.9, 0.625),
        asset_binding=AssetBinding(
            asset_id=digest,
            mesh_path=str(mesh),
            triangle_count=2048,
            vertex_count=1100,
            generator="hunyuan3d",
        ),
        physics_intent="dynamic",
        material_intent=MaterialIntent(
            base_color="#8a5b39", metallic=0.125, roughness=0.71875, pass_level=2
        ),
        semantic_label="furniture/chair",
    )
    door_mesh = tmp_path / "approved-door.glb"
    door_mesh.write_bytes(b"exact-approved-browser-door-glb")
    door_digest = hashlib.sha256(door_mesh.read_bytes()).hexdigest()
    door = ObjectInstance(
        object_id=_DOOR_UUID,
        name="Door",
        position=Vec3(-1.0, 0.0, 1.4),
        rotation=Quaternion(),
        scale=Vec3(0.8, 2.0, 0.05),
        asset_binding=AssetBinding(
            asset_id=door_digest,
            mesh_path=str(door_mesh),
            triangle_count=512,
            vertex_count=300,
            generator="hunyuan3d",
        ),
        physics_intent="static",
        material_intent=MaterialIntent(
            base_color="#704020", metallic=0.0, roughness=0.8, pass_level=2
        ),
        semantic_label="architecture/door",
        is_architectural=True,
    )
    return finalize(WorldContract(
        plan_revision="rev-11",
        camera_hash=camera.compute_hash(),
        camera=camera if include_camera else None,
        room_shell_ref="parametric-room:sha256:" + "a" * 64,
        navigation=FirstPersonNavigation(
            bounds_minimum=Vec3(-2.0, 0.0, -2.0),
            bounds_maximum=Vec3(2.0, 2.7, 2.0),
            static_bodies=(
                StaticCollisionBody(
                    body_id="room-floor",
                    source_id="room:floor",
                    center=Vec3(0.0, -0.05, 0.0),
                    dimensions=Vec3(4.0, 0.1, 4.0),
                    source_kind="architecture",
                ),
                StaticCollisionBody(
                    body_id="blocked-center",
                    source_id="counter",
                    center=Vec3(0.0, 0.5, 0.0),
                    dimensions=Vec3(1.0, 1.0, 1.0),
                ),
            ),
            spawn_candidates=(Vec3(0.0, 1.62, 0.0), Vec3(1.25, 1.62, 1.25)),
            player_radius=0.25,
            player_height=1.75,
            eye_height=1.62,
            movement_speed=2.0,
            gravity=9.81,
        ),
        instances=(instance, door),
        interactions=(
            InteractionBinding(
                interaction_id=_INTERACTION_UUID,
                object_id=_OBJECT_UUID,
                kind="dynamic",
                collider=InteractionCollider(
                    center_offset=Vec3(0.0, 0.45, 0.0),
                    dimensions=Vec3(0.55, 0.9, 0.625),
                ),
                dynamic=DynamicInteractionMetadata(
                    mass_kg=8.5,
                    friction=0.5,
                    restitution=0.2,
                    can_grab=True,
                    can_push=True,
                    can_topple=True,
                    grab_distance_m=3.0,
                    hold_distance_m=1.5,
                    hold_stiffness=14.0,
                    push_impulse_ns=10.0,
                    linear_damping=1.25,
                    angular_damping=1.75,
                ),
            ),
            InteractionBinding(
                interaction_id=_DOOR_INTERACTION_UUID,
                object_id=_DOOR_UUID,
                kind="door_hinge",
                collider=InteractionCollider(
                    center_offset=Vec3(0.0, 1.0, 0.0),
                    dimensions=Vec3(0.8, 2.0, 0.05),
                ),
                door=DoorInteractionMetadata(
                    pivot=Vec3(-1.4, 0.0, 1.4),
                    axis=Vec3(0.0, 1.0, 0.0),
                    lower_limit_deg=0.0,
                    upper_limit_deg=95.0,
                    initial_angle_deg=0.0,
                    angular_speed_deg_s=120.0,
                    interaction_distance_m=3.0,
                    interaction_mass_kg=18.5,
                ),
            ),
        ),
        lighting=LightingConfig(
            ambient_color="#19120d",
            ambient_intensity=0.28125,
            lights=(LightSource(
                light_id="key-light",
                light_type="point",
                position=Vec3(0.25, 2.375, -0.5),
                color="#ffd4a3",
                intensity=3.125,
                temperature=3250.0,
                cast_shadows=True,
            ),),
        ),
        contract_id="browser-contract-test",
        created_at="2026-08-01T00:00:00Z",
    ))


def test_compiles_exact_contract_to_three_scene(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    result = BrowserCompiler().compile(contract, tmp_path / "browser")

    assert all(path.is_file() for path in result.artifact_paths)
    assert result.contract_hash == contract.contract_hash
    assert result.plan_revision == contract.plan_revision
    assert result.contract_file.read_text(encoding="utf-8") == serialize(contract)

    scene = json.loads(result.scene_manifest_file.read_text(encoding="utf-8"))
    compiled = scene["instances"][0]
    source = contract.instances[0]
    assert scene["contract_hash"] == contract.contract_hash
    assert scene["plan_revision"] == contract.plan_revision
    assert scene["camera_hash"] == contract.camera_hash
    assert scene["camera"] == contract.camera.to_dict()
    assert scene["navigation"] == contract.navigation.to_dict()
    assert scene["interactions"] == [item.to_dict() for item in contract.interactions]
    assert scene["interactions"][1]["object_id"] == _DOOR_UUID
    assert scene["interactions"][1]["door"]["upper_limit_deg"] == 95.0
    assert scene["selected_spawn"] == {"x": 1.25, "y": 1.62, "z": 1.25}
    assert scene["safe_spawn_policy"] == "first_safe_contract_candidate_in_declared_order"
    assert compiled["position"] == source.position.to_dict()
    assert compiled["rotation"] == source.rotation.to_dict()
    assert compiled["scale"] == source.scale.to_dict()
    assert compiled["asset_binding"] == source.asset_binding.to_dict()
    assert compiled["material_intent"] == source.material_intent.to_dict()
    copied = result.output_dir / compiled["asset_uri"]
    assert copied.read_bytes() == Path(source.asset_binding.mesh_path).read_bytes()
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == source.asset_binding.asset_id

    script = result.viewer_script.read_text(encoding="utf-8")
    assert "GLTFLoader" in script
    assert "MeshStandardMaterial" in script
    assert "OrbitControls" in script
    assert "PointerLockControls" in script
    assert "new EventSource" in script
    assert "canOccupy" in script
    assert "playerIntersectsBody" in script
    assert "navigation.gravity" in script
    assert "navigation.movement_speed" in script
    assert "compiled safe spawn" in script.lower()
    assert "registerInteraction" in script
    assert "interactionRaycaster.intersectObjects(interactionProxies" in script
    assert "fixedPhysicsStep = 1 / 60" in script
    assert "metadata.push_impulse_ns / metadata.mass_kg" in script
    assert "pivot.quaternion.setFromAxisAngle" in script
    assert "binding.object_id" in script
    assert "root.position.set(instance.position.x" in script
    assert "root.quaternion.set" in script
    assert "root.scale.set(instance.scale.x" in script
    assert "Box3" not in script
    assert "getSize" not in script
    assert "normalize()" not in script

    html = result.index_file.read_text(encoding="utf-8")
    assert "?v=1" in html
    assert "?v=2" in html
    assert "?v=3" in html
    assert "Browser v3" in html
    assert "viewer.js" in html


def test_fails_closed_for_missing_camera_and_hash_drift(tmp_path: Path) -> None:
    without_camera = _contract(tmp_path, include_camera=False)
    with pytest.raises(BrowserCompilerError, match="will not infer"):
        BrowserCompiler().compile(without_camera, tmp_path / "missing-camera")

    valid = _contract(tmp_path / "valid")
    tampered = WorldContract.from_dict({**valid.to_dict(), "contract_hash": "0" * 64})
    with pytest.raises(BrowserCompilerError, match="hash"):
        BrowserCompiler().compile(tampered, tmp_path / "tampered")


def test_fails_closed_instead_of_normalizing_or_defaulting_assets(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    Path(contract.instances[0].asset_binding.mesh_path).write_bytes(b"mutated")
    with pytest.raises(BrowserCompilerError, match="hash mismatch"):
        BrowserCompiler().compile(contract, tmp_path / "mutated-asset")


def test_fails_closed_without_navigation_or_safe_spawn(tmp_path: Path) -> None:
    valid = _contract(tmp_path / "valid")
    missing_payload = valid.to_dict()
    missing_payload["navigation"] = None
    missing_payload["contract_hash"] = ""
    missing = finalize(WorldContract.from_dict(missing_payload))
    with pytest.raises(BrowserCompilerError, match="will not infer"):
        BrowserCompiler().compile(missing, tmp_path / "missing-navigation")

    blocked_payload = valid.to_dict()
    blocked_payload["navigation"]["spawn_candidates"] = [{"x": 0.0, "y": 1.62, "z": 0.0}]
    blocked_payload["contract_hash"] = ""
    blocked = finalize(WorldContract.from_dict(blocked_payload))
    with pytest.raises(BrowserCompilerError, match="no deterministic safe spawn"):
        BrowserCompiler().compile(blocked, tmp_path / "blocked-spawn")


def test_navigation_round_trip_is_hash_bound(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    restored = WorldContract.from_dict(contract.to_dict())

    assert restored.navigation == contract.navigation
    assert restored.contract_hash == contract.contract_hash
    assert serialize(restored) == serialize(contract)


def test_interactions_fail_closed_for_missing_or_unstable_uuid_metadata(
    tmp_path: Path,
) -> None:
    valid = _contract(tmp_path / "valid-interaction")

    missing_payload = valid.to_dict()
    missing_payload["interactions"] = []
    missing_payload["contract_hash"] = ""
    missing = finalize(WorldContract.from_dict(missing_payload))
    with pytest.raises(BrowserCompilerError, match="every dynamic instance"):
        BrowserCompiler().compile(missing, tmp_path / "missing-interaction")

    invalid_payload = valid.to_dict()
    invalid_payload["interactions"][0]["object_id"] = "chair-by-name"
    invalid_payload["contract_hash"] = ""
    invalid = finalize(WorldContract.from_dict(invalid_payload))
    with pytest.raises(BrowserCompilerError, match="canonical stable UUID"):
        BrowserCompiler().compile(invalid, tmp_path / "invalid-interaction")

    drift_payload = valid.to_dict()
    drift_payload["interactions"][0]["collider"]["dimensions"]["x"] = 99.0
    drift_payload["contract_hash"] = ""
    drift = finalize(WorldContract.from_dict(drift_payload))
    with pytest.raises(BrowserCompilerError, match="exactly match Plan-owned"):
        BrowserCompiler().compile(drift, tmp_path / "interaction-collider-drift")


def test_interaction_uuid_and_physics_metadata_are_round_trip_hash_bound(
    tmp_path: Path,
) -> None:
    contract = _contract(tmp_path / "round-trip-interaction")
    restored = WorldContract.from_dict(contract.to_dict())

    assert restored.interactions == contract.interactions
    assert restored.interactions[0].object_id == _OBJECT_UUID
    assert restored.interactions[0].interaction_id == _INTERACTION_UUID
    assert restored.contract_hash == contract.contract_hash

    changed_payload = contract.to_dict()
    changed_payload["interactions"][0]["dynamic"]["push_impulse_ns"] = 11.0
    changed_payload["contract_hash"] = ""
    changed = finalize(WorldContract.from_dict(changed_payload))
    assert changed.contract_hash != contract.contract_hash
