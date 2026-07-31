"""Integrated interaction and walkability tests for Task 8.5.

**Validates: Requirements 22.1, 22.2, 22.3, 22.4**
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pytest

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.compilers.browser import BrowserCompiler
from src.unified_pipeline.compilers.godot import GodotCompiler
from src.unified_pipeline.world_contract import (
    AssetBinding,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Relationship,
    Vec3,
    WorldContract,
    finalize,
)

_PLAYER_RADIUS_M = 0.3
_SPAWN = (0.0, 0.05, -1.5)


def _asset(path: Path, label: str) -> AssetBinding:
    content = f"approved-wave8-{label}".encode()
    path.write_bytes(content)
    return AssetBinding(
        asset_id=hashlib.sha256(content).hexdigest(),
        mesh_path=str(path), triangle_count=1200, vertex_count=700,
        generator="hunyuan3d",
    )


def _instance(
    object_id: str, position: tuple[float, float, float],
    scale: tuple[float, float, float], asset: AssetBinding,
    *, physics: str, label: str, architectural: bool = False,
) -> ObjectInstance:
    return ObjectInstance(
        object_id=object_id, name=object_id,
        position=Vec3(*position), rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
        scale=Vec3(*scale), asset_binding=asset, physics_intent=physics,
        material_intent=MaterialIntent("#765432", 0.0, 0.7),
        semantic_label=label, is_architectural=architectural,
    )

def _contract(tmp_path: Path) -> WorldContract:
    camera = CameraContract(
        position=(_SPAWN[0], 1.65, _SPAWN[2]),
        target=(0.0, 1.25, 0.0), vfov=58.0, aspect=1.5,
        near=0.05, far=60.0, raster_width=1200, raster_height=800,
    )
    instances = (
        _instance(
            "wall-north", (0.0, 1.5, 2.8), (4.0, 3.0, 0.1),
            _asset(tmp_path / "wall.glb", "wall"),
            physics="static", label="architecture/wall", architectural=True,
        ),
        _instance(
            "crate", (1.2, 0.5, -0.2), (0.5, 1.0, 0.5),
            _asset(tmp_path / "crate.glb", "crate"),
            physics="dynamic", label="props/crate",
        ),
        _instance(
            "door", (-1.0, 1.05, 2.8), (0.9, 2.1, 0.04),
            _asset(tmp_path / "door.glb", "door"),
            physics="static", label="architecture/door", architectural=True,
        ),
    )
    spawn = {"player_spawn": {
        "position": list(_SPAWN), "rotation": [0.0, 0.0, 0.0, 1.0],
    }}
    hinge = {"door_hinge": {
        "child_body_id": "door", "anchor_body_id": "room",
        "pivot_position": [-1.45, 0.0, 2.8], "axis": [0.0, 1.0, 0.0],
        "lower_limit_deg": -5.0, "upper_limit_deg": 95.0,
        "interaction_mass_kg": 18.5,
    }}
    return finalize(WorldContract(
        plan_revision="rev-wave8", camera_hash=camera.compute_hash(), camera=camera,
        room_shell_ref="parametric-room:sha256:" + "a" * 64,
        instances=instances,
        relationships=(
            Relationship("player", "room", "spawn", json.dumps(spawn)),
            Relationship("door", "room", "hinge", json.dumps(hinge)),
        ),
        contract_id="wave8-walkability",
    ))


def _compiled(tmp_path: Path):
    contract = _contract(tmp_path)
    browser = BrowserCompiler().compile(contract, tmp_path / "browser")
    godot = GodotCompiler().compile(contract, tmp_path / "godot")
    return contract, browser, godot


def test_contract_safe_spawn_drives_walkable_browser_and_godot_outputs(
    tmp_path: Path,
) -> None:
    contract, browser, godot = _compiled(tmp_path)
    godot_manifest = json.loads(godot.manifest_file.read_text("utf-8"))
    browser_scene = json.loads(browser.scene_manifest_file.read_text("utf-8"))

    assert godot_manifest["spawn"]["position"] == list(_SPAWN)
    assert godot_manifest["spawn"]["source"] == "relationship:player->room"
    assert browser_scene["camera"]["position"][::2] == [_SPAWN[0], _SPAWN[2]]
    scene = godot.main_scene.read_text("utf-8")
    player_section = scene.split('[node name="Player"', 1)[1]
    player_position = re.search(r"position = Vector3\(([^)]+)\)", player_section)
    assert player_position is not None
    assert tuple(float(value) for value in player_position.group(1).split(", ")) == pytest.approx(_SPAWN)

    for instance in contract.instances:
        clear_x = abs(_SPAWN[0] - instance.position.x) > _PLAYER_RADIUS_M + instance.scale.x / 2
        clear_z = abs(_SPAWN[2] - instance.position.z) > _PLAYER_RADIUS_M + instance.scale.z / 2
        assert clear_x or clear_z, f"spawn intersects {instance.object_id}"

    browser_script = browser.viewer_script.read_text("utf-8")
    assert "new PointerLockControls(camera, renderer.domElement)" in browser_script
    assert all(code in browser_script for code in ("KeyW", "KeyA", "KeyS", "KeyD"))
    assert "movementRateMetersPerSecond * delta" in browser_script


def test_player_collision_response_preserves_static_and_dynamic_physics(
    tmp_path: Path,
) -> None:
    _, _, godot = _compiled(tmp_path)
    scene = godot.main_scene.read_text("utf-8")
    player_scene = godot.player_scene.read_text("utf-8")
    player_script = godot.player_script.read_text("utf-8")
    body_script = (godot.project_dir / "contract_body.gd").read_text("utf-8")

    assert 'type="CharacterBody3D"' in player_scene
    assert 'type="CapsuleShape3D"' in player_scene
    assert f"radius = {_PLAYER_RADIUS_M}" in player_scene
    assert 'type="StaticBody3D"' in scene
    assert scene.count('type="RigidBody3D"') == 2  # crate plus hinged door
    assert "create_convex_shape" in body_script
    assert "velocity.y -= _gravity * delta" in player_script
    assert "move_and_slide()" in player_script
    assert "get_slide_collision_count()" in player_script
    assert "collider.apply_central_impulse(-collision.get_normal() * PUSH_IMPULSE)" in player_script


def test_door_interaction_emits_bounded_physical_hinge(tmp_path: Path) -> None:
    _, _, godot = _compiled(tmp_path)
    manifest = json.loads(godot.manifest_file.read_text("utf-8"))
    scene = godot.main_scene.read_text("utf-8")
    hinge = manifest["door_hinges"][0]

    assert hinge == {
        "child_id": "door", "anchor_id": "room",
        "pivot": [-1.45, 0.0, 2.8], "axis": [0.0, 1.0, 0.0],
        "lower_limit_deg": -5.0, "upper_limit_deg": 95.0,
        "mass_kg": 18.5,
        "source_relationship": ["door", "room", "hinge"],
    }
    assert 'type="HingeJoint3D"' in scene
    assert 'metadata/_kiro_door_hinge = true' in scene
    assert "mass = 18.5" in scene
    lower = float(re.search(r"angular_limit/lower = ([^\n]+)", scene).group(1))
    upper = float(re.search(r"angular_limit/upper = ([^\n]+)", scene).group(1))
    assert lower == pytest.approx(math.radians(-5.0))
    assert upper == pytest.approx(math.radians(95.0))


def test_grab_then_release_uses_raycast_constraint_without_identity_drift(
    tmp_path: Path,
) -> None:
    contract, _, godot = _compiled(tmp_path)
    project = godot.project_file.read_text("utf-8")
    player_scene = godot.player_scene.read_text("utf-8")
    player_script = godot.player_script.read_text("utf-8")

    assert 'interact={"deadzone":0.5' in project
    assert '"physical_keycode":69' in project
    assert 'type="RayCast3D"' in player_scene
    assert "target_position = Vector3(0, 0, -3)" in player_scene
    assert 'type="Marker3D"' in player_scene
    assert "position = Vector3(0, 0, -1.5)" in player_scene

    release_at = player_script.index("if is_instance_valid(_grabbed):\n        _grabbed = null")
    acquire_at = player_script.index("if collider is RigidBody3D:\n            _grabbed = collider")
    hold_at = player_script.index("_grabbed.linear_velocity = displacement * HOLD_STIFFNESS")
    assert release_at < acquire_at < hold_at
    assert "_grabbed.sleeping = false" in player_script

    manifest = json.loads(godot.manifest_file.read_text("utf-8"))
    assert [item["object_id"] for item in manifest["instances"]] == [
        item.object_id for item in contract.instances
    ]
