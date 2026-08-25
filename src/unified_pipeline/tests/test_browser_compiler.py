"""Focused tests for browser compilation, walkability, interactions, and lighting.

Validates Requirements 21.1, 21.4, 22.2, 22.3, 22.4, and 22.5.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings, strategies as st
import pytest

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.compilers.browser import (
    BrowserCompiler,
    BrowserCompilerError,
    _select_safe_spawn,
)
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
    compute_hash,
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
            legacy_ambient_color="#19120d",
            legacy_ambient_intensity=0.28125,
            lights=(
                LightSource(
                    light_id="key-light",
                    light_type="point",
                    position=Vec3(0.25, 2.375, -0.5),
                    color="#ffd4a3",
                    intensity=3.125,
                    temperature=3250.0,
                    cast_shadows=True,
                    white_balance_color="#ffd4a3",
                    legacy_color="#ffd4a3",
                    legacy_intensity=3.125,
                ),
                LightSource(
                    light_id="fill-light",
                    light_type="point",
                    position=Vec3(-1.125, 1.875, 0.75),
                    color="#a8c8ff",
                    intensity=0.4375,
                    temperature=6750.0,
                    cast_shadows=False,
                    white_balance_color="#a8c8ff",
                    legacy_color="#a8c8ff",
                    legacy_intensity=0.4375,
                ),
            ),
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
    assert scene["lighting"] == contract.lighting.to_dict()
    assert scene["interactions"][1]["object_id"] == _DOOR_UUID
    assert scene["interactions"][1]["door"]["upper_limit_deg"] == 95.0
    assert scene["selected_spawn"] == {"x": 1.25, "y": 1.62, "z": 1.25}
    assert scene["safe_spawn_policy"] == "first_safe_contract_candidate_in_declared_order"
    assert compiled["position"] == source.position.to_dict()
    assert compiled["rotation"] == source.rotation.to_dict()
    assert compiled["scale"] == source.scale.to_dict()
    assert compiled["asset_binding"] == source.asset_binding.to_dict()
    assert compiled["material_intent"] == source.material_intent.to_dict()
    compiler_only_fields = {"asset_uri", "material_asset_uris"}
    assert {
        key: value for key, value in compiled.items()
        if key not in compiler_only_fields
    } == source.to_dict()
    assert compiled["material_asset_uris"] == {}
    copied = result.output_dir / compiled["asset_uri"]
    assert copied.read_bytes() == Path(source.asset_binding.mesh_path).read_bytes()
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == source.asset_binding.asset_id

    script = result.viewer_script.read_text(encoding="utf-8")
    assert "GLTFLoader" in script
    assert "MeshStandardMaterial" in script
    assert "OrbitControls" in script
    assert "PointerLockControls" in script
    assert 'document.querySelector("#first-person").onclick = enterFirstPerson;' in script
    assert "firstPerson.lock();" in script
    assert "isLocked =" not in script
    assert "new EventSource" in script
    assert "canOccupy" in script
    assert "playerIntersectsBody" in script
    assert "navigation.gravity" in script
    assert "navigation.movement_speed" in script
    assert "compiled safe spawn" in script.lower()
    assert "registerInteraction" in script
    assert "interactionRaycaster.intersectObjects(interactionProxies" in script
    assert "fixedPhysicsStep = 1 / 60" in script
    assert "createGrabConstraint(metadata, contract.contract_hash)" in script
    assert "releasedGrabState()" in script
    assert "constraint.contractHash !== contract.contract_hash" in script
    assert "function applyImpulse(body, impulse, worldPoint)" in script
    assert "impulseVelocityDelta" in script
    assert "localBoxAngularVelocityDelta" in script
    assert "body.angularVelocity.add" in script
    assert "function interactionObstacle(body)" in script
    assert "...doorBodies.values(), ...dynamicBodies.values()" in script
    assert "pivot.quaternion.setFromAxisAngle" in script
    assert "binding.object_id" in script
    assert "Lighting metadata drift detected" in script
    assert "light.color.set(retained ? value.legacy_color : value.color)" in script
    assert "light.intensity = retained ? value.legacy_intensity : value.intensity" in script
    assert "light.position.set(value.position.x, value.position.y, value.position.z)" in script
    assert "temperature_kelvin: value.temperature" in script
    assert "light.castShadow = value.cast_shadows" in script
    assert "light.shadow.autoUpdate = value.cast_shadows" in script
    assert "node.castShadow = true" in script
    assert "node.receiveShadow = true" in script
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
    assert "?v=4" in html
    assert "?v=5" in html
    assert "?v=6" in html
    assert "?v=7" in html
    assert "?v=8" in html
    assert "Browser v8" in html
    assert '<base href="./world/">' in html
    assert scene["progressive"]["endpoint"] == "../events"
    assert 'id="mode-real"' in html
    assert 'id="mode-game"' in html
    assert "viewer.js" in html

    compiler_manifest = json.loads(
        result.compiler_manifest_file.read_text(encoding="utf-8")
    )
    assert compiler_manifest["interface_version"] == 8
    assert compiler_manifest["lighting"] == contract.lighting.to_dict()
    assert compiler_manifest["authority"]["missing_authority_policy"] == "fail_closed"
    assert 'get("v") || "8"' in script
    assert 'supportsModeOverlay = new Set(["6", "7", "8"]).has(interfaceVersion)' in script
    assert 'flatShading: new Set(["7", "8"]).has(interfaceVersion) && intent.shading_model === "flat"' in script
    assert "computeVertexNormals" not in script
    assert "targetRenderer.toneMappingExposure = lighting.exposure" in script
    assert "value.intensity_unit !== \"candela\"" in script
    assert "kiro:room-mode:${contract.contract_hash}:${contract.room_shell_ref}" in script
    assert "behavior overlay only · visuals unchanged" in script
    assert 'localStorage.setItem(modeStorageKey, nextMode)' in script
    assert 'document.body.dataset.behaviorMode = nextMode' in script


def test_progressive_loader_falls_back_when_stream_is_open_but_silent(
    tmp_path: Path,
) -> None:
    """Validates Requirement 22.3: a silent SSE stream cannot stall a complete world."""
    contract = _contract(tmp_path / "silent-progress-stream")
    result = BrowserCompiler().compile(
        contract,
        tmp_path / "silent-progress-stream-output",
    )

    script = result.viewer_script.read_text(encoding="utf-8")
    assert "function startProgressiveFallback()" in script
    assert "function armProgressiveFallback()" in script
    assert "fallbackTimer = setTimeout(startProgressiveFallback, 2000);" in script
    assert "eventSource.onerror = startProgressiveFallback;" in script
    assert script.count("armProgressiveFallback();") >= 2
    assert "if (loaded.has(objectId)) return;" in script


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

    incomplete_payload = valid.to_dict()
    incomplete_payload["interactions"][0]["dynamic"]["can_topple"] = False
    incomplete_payload["contract_hash"] = ""
    incomplete = finalize(WorldContract.from_dict(incomplete_payload))
    with pytest.raises(BrowserCompilerError, match="outside safe bounds"):
        BrowserCompiler().compile(incomplete, tmp_path / "missing-topple")


def test_hinged_door_cannot_keep_a_stale_static_collider(tmp_path: Path) -> None:
    valid = _contract(tmp_path / "valid-door-collision")
    payload = valid.to_dict()
    payload["navigation"]["static_bodies"].append({
        "body_id": "stale-door-static-collider",
        "source_id": _DOOR_UUID,
        "center": {"x": -1.0, "y": 1.0, "z": 1.4},
        "dimensions": {"x": 0.8, "y": 2.0, "z": 0.05},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        "shape": "box",
        "body_mode": "STATIC",
        "source_kind": "instance",
    })
    payload["contract_hash"] = ""
    stale = finalize(WorldContract.from_dict(payload))

    with pytest.raises(BrowserCompilerError, match="cannot remain in static"):
        BrowserCompiler().compile(stale, tmp_path / "stale-door-collision")


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


def test_generated_interaction_runtime_syntax_and_behavior_smoke(tmp_path: Path) -> None:
    """Execute the same pure hinge/constraint/impulse module imported by viewer.js."""
    contract = _contract(tmp_path / "runtime-smoke")
    result = BrowserCompiler().compile(contract, tmp_path / "runtime-smoke-output")
    node = shutil.which("node")
    assert node is not None, "Node.js is required to validate generated browser modules"

    runtime = result.output_dir / "interaction_runtime.mjs"
    assert runtime.is_file()
    viewer_module = result.output_dir / "viewer.mjs"
    viewer_module.write_text(result.viewer_script.read_text(encoding="utf-8"), encoding="utf-8")

    for module in (runtime, viewer_module):
        completed = subprocess.run(
            [node, "--check", str(module)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr

    smoke = result.output_dir / "interaction_smoke.mjs"
    smoke.write_text(
        f'''import assert from "node:assert/strict";
import {{
  advanceDoorAngle, createGrabConstraint, impulseVelocityDelta,
  localBoxAngularVelocityDelta, releasedGrabState, toggleDoorTarget,
}} from {json.dumps(runtime.as_uri())};

assert.equal(toggleDoorTarget(0, 0, 95), 95);
let angle = 0;
for (let step = 0; step < 120; step += 1) {{
  angle = advanceDoorAngle(angle, 95, 120, 1 / 60, 0, 95);
  assert.ok(angle >= 0 && angle <= 95);
}}
assert.equal(angle, 95);
angle = advanceDoorAngle(angle, toggleDoorTarget(angle, 0, 95), 120, 10, 0, 95);
assert.equal(angle, 0);

const held = createGrabConstraint(
  {{hold_distance_m: 1.5, hold_stiffness: 14}}, {json.dumps(contract.contract_hash)}
);
assert.equal(held.contractHash, {json.dumps(contract.contract_hash)});
assert.equal(held.holdDistanceM, 1.5);
assert.ok(Object.isFrozen(held));
assert.deepEqual(releasedGrabState(), {{held: false, grabConstraint: null}});

assert.deepEqual(impulseVelocityDelta({{x: 8.5, y: 0, z: -17}}, 8.5), {{x: 1, y: 0, z: -2}});
const topple = localBoxAngularVelocityDelta(
  {{x: 0, y: 0, z: 10}}, {{x: 0.55, y: 0.9, z: 0.625}}, 8.5
);
assert.equal(topple.x, 0);
assert.equal(topple.y, 0);
assert.ok(topple.z > 0);
assert.deepEqual(
  localBoxAngularVelocityDelta(
    {{x: 0, y: 0, z: 0}}, {{x: 0.55, y: 0.9, z: 0.625}}, 8.5
  ),
  {{x: 0, y: 0, z: 0}}
);
console.log("interaction-runtime-smoke:ok");
''',
        encoding="utf-8",
    )
    completed = subprocess.run(
        [node, str(smoke)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "interaction-runtime-smoke:ok"


def test_door_interaction_metadata_fails_closed_for_invalid_limits(tmp_path: Path) -> None:
    valid = _contract(tmp_path / "invalid-door-limits")
    invalid_cases = (
        ({"lower_limit_deg": 95.0}, "outside safe explicit bounds"),
        ({"initial_angle_deg": 96.0}, "outside safe explicit bounds"),
        ({"axis": {"x": 1.0, "y": 0.0, "z": 0.0}}, "outside safe explicit bounds"),
        ({"angular_speed_deg_s": 0.0}, "outside safe explicit bounds"),
    )
    for index, (changes, message) in enumerate(invalid_cases):
        payload = valid.to_dict()
        payload["interactions"][1]["door"].update(changes)
        payload["contract_hash"] = ""
        candidate = finalize(WorldContract.from_dict(payload))
        with pytest.raises(BrowserCompilerError, match=message):
            BrowserCompiler().compile(candidate, tmp_path / f"invalid-door-{index}")


def test_lighting_is_exact_hash_bound_and_v4_remains_available(tmp_path: Path) -> None:
    """Validates Requirement 22.5 without changing retained browser versions."""
    contract = _contract(tmp_path / "exact-lighting")
    result = BrowserCompiler().compile(contract, tmp_path / "exact-lighting-output")

    scene = json.loads(result.scene_manifest_file.read_text(encoding="utf-8"))
    compiler_manifest = json.loads(
        result.compiler_manifest_file.read_text(encoding="utf-8")
    )
    assert scene["lighting"] == contract.lighting.to_dict()
    assert compiler_manifest["lighting"] == contract.lighting.to_dict()
    assert scene["lighting"]["ambient_color"] == "#19120d"
    assert scene["lighting"]["ambient_intensity"] == 0.28125
    assert [item["light_id"] for item in scene["lighting"]["lights"]] == [
        "key-light", "fill-light"
    ]
    assert scene["lighting"]["lights"][0]["intensity"] == 3.125
    assert scene["lighting"]["lights"][0]["legacy_intensity"] == 3.125
    assert scene["lighting"]["lights"][0]["legacy_color"] == "#ffd4a3"
    assert scene["lighting"]["lights"][0]["white_balance_color"] == "#ffd4a3"

    script = result.viewer_script.read_text(encoding="utf-8")
    assert 'function applyContractLighting(targetScene, targetRenderer, lighting, version)' in script
    assert 'const retained = !new Set(["7", "8"]).has(version)' in script
    assert "Retained Browser v1-v4/v6 lighting behavior" in script
    assert "targetRenderer.shadowMap.enabled = lighting.lights.some" in script
    assert 'if (new Set(["5", "6", "7", "8"]).has(interfaceVersion)) {\n          node.castShadow = true;' in script
    assert "light.userData.temperature = value.temperature" in script
    assert 'temperature_semantics: "explicit_contract_white_balance_already_applied_to_render_color"' in script


def test_shadow_computation_from_each_contract_light_source(tmp_path: Path) -> None:
    """Validates Requirement 22.5: Compute shadows from each light source.

    Verifies:
    - shadowMap.enabled is activated when any light casts shadows
    - PCFSoftShadowMap type is set for quality shadow rendering
    - Each light with cast_shadows=True gets shadow map size and bias
    - Meshes (instances and room shell) cast and receive shadows
    - No independent inference of shadow parameters outside contract values
    """
    contract = _contract(tmp_path / "shadow-compute")
    result = BrowserCompiler().compile(contract, tmp_path / "shadow-compute-output")

    script = result.viewer_script.read_text(encoding="utf-8")

    # Shadow map enabled based on contract light cast_shadows flags
    assert "targetRenderer.shadowMap.enabled = lighting.lights.some(light => light.cast_shadows)" in script
    # PCFSoftShadowMap for quality shadow computation
    assert "targetRenderer.shadowMap.type = THREE.PCFSoftShadowMap" in script
    # Shadow map size and bias configured for shadow-casting lights
    assert "light.shadow.mapSize.set(1024, 1024)" in script
    assert "light.shadow.bias = -0.001" in script
    # Each light's shadow flag comes directly from contract
    assert "light.castShadow = value.cast_shadows" in script
    assert "light.shadow.autoUpdate = value.cast_shadows" in script
    # Instance meshes cast and receive shadows in v5
    assert "node.castShadow = true" in script
    assert "node.receiveShadow = true" in script
    # Room shell also participates in shadow computation
    assert "gltf.scene.traverse(node =>" in script

    # Verify the contract has shadow-casting lights
    assert any(light.cast_shadows for light in contract.lighting.lights)
    assert any(not light.cast_shadows for light in contract.lighting.lights)

    # Verify lighting policy prohibits inference
    compiler_manifest = json.loads(
        result.compiler_manifest_file.read_text(encoding="utf-8")
    )
    assert compiler_manifest["authority"]["lighting_policy"] == (
        "exact_contract_physical_units_exposure_and_legacy_profiles_no_inference"
    )
    assert compiler_manifest["authority"]["temperature_policy"] == (
        "explicit_kelvin_and_white_balance_color_already_applied_upstream"
    )
    assert compiler_manifest["authority"]["shading_policy"] == (
        "explicit_contract_asset_smooth_or_derivative_flat_no_runtime_normal_generation"
    )


def test_lighting_fails_closed_for_inexact_or_missing_contract_values(
    tmp_path: Path,
) -> None:
    """Validates Requirement 22.5 fail-closed browser representation."""
    valid = _contract(tmp_path / "valid-lighting")
    source = valid.lighting.lights[0]
    invalid_lighting = (
        (replace(valid.lighting, ambient_color="warm"), "ambient light color"),
        (replace(valid.lighting, ambient_intensity=-0.1), "ambient light intensity"),
        (replace(valid.lighting, lights=(source, source)), "unique and nonempty"),
        (replace(valid.lighting, lights=(replace(source, light_id=""),)), "unique and nonempty"),
        (replace(valid.lighting, lights=(replace(source, light_type="directional"),)), "lacks enough contract data"),
        (replace(valid.lighting, lights=(replace(source, position=Vec3(float("nan"), 2.0, 0.0)),)), "position.x"),
        (replace(valid.lighting, lights=(replace(source, color="orange"),)), "exact #RRGGBB"),
        (replace(valid.lighting, lights=(replace(source, intensity=-1.0),)), "intensity cannot be negative"),
        (replace(valid.lighting, lights=(replace(source, temperature=0.0),)), "within 1000K"),
        (replace(valid.lighting, lights=(replace(source, cast_shadows=1),)), "explicit boolean"),
    )

    for index, (lighting, message) in enumerate(invalid_lighting):
        unhashed = replace(valid, lighting=lighting, contract_hash="")
        candidate = replace(unhashed, contract_hash=compute_hash(unhashed))
        with pytest.raises(BrowserCompilerError, match=message):
            BrowserCompiler().compile(candidate, tmp_path / f"invalid-lighting-{index}")


def test_v8_boundary_tolerance_accepts_decimal_grid_roundoff_only(tmp_path: Path) -> None:
    """A mathematically boundary-safe aperture point survives binary float drift."""
    navigation = _contract(tmp_path / "boundary").navigation
    assert navigation is not None
    rounded_grid_point = Vec3(-1.4500000000000002, 1.62, 1.25)
    tolerant = replace(
        navigation,
        bounds_minimum=Vec3(-1.7, 0.0, -2.0),
        bounds_maximum=Vec3(1.7, 2.7, 2.0),
        spawn_candidates=(rounded_grid_point,),
        boundary_tolerance_m=1e-9,
    )

    assert _select_safe_spawn(tolerant) == rounded_grid_point.to_dict()
    with pytest.raises(BrowserCompilerError, match="no deterministic safe spawn"):
        _select_safe_spawn(replace(tolerant, boundary_tolerance_m=0.0))


@settings(max_examples=20, deadline=None)
@given(drift=st.floats(
    min_value=0.0,
    max_value=9e-10,
    allow_nan=False,
    allow_infinity=False,
))
def test_property_v8_hash_bound_tolerance_contains_subnanometre_grid_drift(
    drift: float,
) -> None:
    """**Validates: Requirements 22.4**"""
    with TemporaryDirectory() as directory:
        navigation = _contract(Path(directory) / "boundary-property").navigation
    assert navigation is not None
    candidate = Vec3(-1.45 - drift, 1.62, 1.25)
    tolerant = replace(
        navigation,
        bounds_minimum=Vec3(-1.7, 0.0, -2.0),
        bounds_maximum=Vec3(1.7, 2.7, 2.0),
        spawn_candidates=(candidate,),
        boundary_tolerance_m=1e-9,
    )

    assert _select_safe_spawn(tolerant) == candidate.to_dict()


def test_environment_free_pbr_profile_is_contract_bound_and_fails_closed(
    tmp_path: Path,
) -> None:
    valid = _contract(tmp_path / "environment-free")
    instance = valid.instances[0]
    bounded_material = replace(
        instance.material_intent,
        metallic=0.35,
        roughness=0.32,
        render_profile="environment-free-bounded-metallic/v1",
    )
    bounded = finalize(replace(
        valid,
        instances=(replace(instance, material_intent=bounded_material), *valid.instances[1:]),
        contract_hash="",
    ))
    result = BrowserCompiler().compile(bounded, tmp_path / "environment-free-output")
    scene = json.loads(result.scene_manifest_file.read_text(encoding="utf-8"))
    assert scene["instances"][0]["material_intent"]["render_profile"] == (
        "environment-free-bounded-metallic/v1"
    )

    unrenderable = finalize(replace(
        bounded,
        instances=(replace(
            bounded.instances[0],
            material_intent=replace(bounded_material, metallic=0.9, roughness=0.24),
        ), *bounded.instances[1:]),
        contract_hash="",
    ))
    with pytest.raises(BrowserCompilerError, match="not renderable without an environment map"):
        BrowserCompiler().compile(unrenderable, tmp_path / "unrenderable-output")


def test_slice_n_safe_spawn_skips_blocked_camera_origin_for_clear_plan_candidate(
    tmp_path: Path,
) -> None:
    navigation = _contract(tmp_path / "slice-n-safe-spawn").navigation
    assert navigation is not None
    unsafe = Vec3(0.0, navigation.eye_height, 0.0)
    safe = Vec3(1.25, navigation.eye_height, 1.25)
    blocker = StaticCollisionBody(
        body_id="collision:instance:counter",
        source_id="counter",
        center=Vec3(0.0, navigation.player_height / 2.0, 0.0),
        dimensions=Vec3(1.6, navigation.player_height, 0.6),
        rotation=Quaternion(),
        shape="box",
        body_mode="STATIC",
        source_kind="instance",
    )
    candidate = replace(
        navigation,
        static_bodies=(blocker,),
        spawn_candidates=(unsafe, safe),
        boundary_tolerance_m=1e-9,
    )

    assert _select_safe_spawn(candidate) == safe.to_dict()
