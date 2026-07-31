"""Focused tests for Task 7.2 GodotCompiler.

Validates Requirements 21.2, 21.4, and 21.6.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.unified_pipeline.compilers.godot import (
    GodotCompiler,
    GodotCompilerError,
)
from src.unified_pipeline.world_contract import (
    AssetBinding,
    LightSource,
    LightingConfig,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Relationship,
    Vec3,
    WorldContract,
    finalize,
    serialize,
)


def _asset(path: Path, content: bytes) -> AssetBinding:
    path.write_bytes(content)
    return AssetBinding(
        asset_id=hashlib.sha256(content).hexdigest(),
        mesh_path=str(path),
        triangle_count=12,
        vertex_count=8,
        generator="placeholder",
    )


def _contract(tmp_path: Path) -> WorldContract:
    static_asset = _asset(tmp_path / "wall.glb", b"static-approved-glb")
    dynamic_asset = _asset(tmp_path / "crate.glb", b"dynamic-approved-glb")
    door_asset = _asset(tmp_path / "door.glb", b"door-approved-glb")
    instances = (
        ObjectInstance(
            object_id="wall-1",
            name="Wall",
            position=Vec3(0.0, 1.5, 2.0),
            rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
            scale=Vec3(4.0, 3.0, 0.1),
            asset_binding=static_asset,
            physics_intent="static",
            material_intent=MaterialIntent("#806040", 0.0, 0.8, pass_level=2),
            semantic_label="architecture/wall",
            is_architectural=True,
        ),
        ObjectInstance(
            object_id="crate-1",
            name="Crate",
            position=Vec3(1.25, 0.5, -0.75),
            rotation=Quaternion(0.0, 0.25, 0.0, 0.9682458365518543),
            scale=Vec3(0.5, 1.0, 0.75),
            asset_binding=dynamic_asset,
            physics_intent="dynamic",
            material_intent=MaterialIntent("#704020", 0.1, 0.7),
            semantic_label="props/crate",
        ),
        ObjectInstance(
            object_id="door-1",
            name="Door",
            position=Vec3(-1.0, 1.05, 2.0),
            rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
            scale=Vec3(0.9, 2.1, 0.04),
            asset_binding=door_asset,
            physics_intent="static",
            material_intent=MaterialIntent("#503018", 0.0, 0.65),
            semantic_label="architecture/door",
            is_architectural=True,
        ),
    )
    spawn = {
        "player_spawn": {
            "position": {"x": 0.25, "y": 0.05, "z": -1.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
        }
    }
    hinge = {
        "door_hinge": {
            "child_body_id": "door-1",
            "anchor_body_id": "room",
            "pivot_position": [-1.45, 0.0, 2.0],
            "axis": [0.0, 1.0, 0.0],
            "lower_limit_deg": -5.0,
            "upper_limit_deg": 95.0,
            "interaction_mass_kg": 18.5,
        }
    }
    contract = WorldContract(
        plan_revision="rev-7",
        camera_hash="c" * 64,
        room_shell_ref="parametric-room:sha256:" + "a" * 64,
        instances=instances,
        relationships=(
            Relationship("crate-1", "room", "containment", json.dumps(spawn)),
            Relationship("door-1", "room", "parent_child", json.dumps(hinge)),
        ),
        lighting=LightingConfig(
            ambient_color="#201810",
            ambient_intensity=0.35,
            lights=(LightSource(
                light_id="warm-light",
                light_type="point",
                position=Vec3(0.0, 2.4, 0.0),
                color="#ffd8a0",
                intensity=2.75,
                temperature=3200.0,
                cast_shadows=True,
            ),),
        ),
        contract_id="world-godot-test",
        created_at="2026-08-01T00:00:00Z",
    )
    return finalize(contract)


def test_emits_complete_contract_driven_godot_project(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    output = tmp_path / "godot"

    result = GodotCompiler().compile(contract, output)

    assert all(path.is_file() for path in result.artifact_paths)
    assert result.contract_hash == contract.contract_hash
    assert result.contract_file.read_text(encoding="utf-8") == serialize(contract)

    scene = result.main_scene.read_text(encoding="utf-8")
    assert 'type="StaticBody3D"' in scene
    assert 'type="RigidBody3D"' in scene
    assert 'type="HingeJoint3D"' in scene
    assert 'type="OmniLight3D"' in scene
    assert 'position = Vector3(1.25, 0.5, -0.75)' in scene
    assert 'scale = Vector3(0.5, 1, 0.75)' in scene
    assert 'mass = 18.5' in scene
    assert f'metadata/_kiro_world_contract_hash = "{contract.contract_hash}"' in scene
    assert 'position = Vector3(0.25, 0.050000000000000003, -1.5)' in scene

    assert "extends CharacterBody3D" in result.player_script.read_text(encoding="utf-8")
    assert "_toggle_grab" in result.player_script.read_text(encoding="utf-8")
    assert "create_convex_shape" in (output / "contract_body.gd").read_text(encoding="utf-8")

    manifest = json.loads(result.manifest_file.read_text(encoding="utf-8"))
    assert manifest["contract_hash"] == contract.contract_hash
    assert manifest["camera_hash"] == contract.camera_hash
    assert manifest["spawn"]["position"] == [0.25, 0.05, -1.5]
    assert manifest["door_hinges"][0]["axis"] == [0.0, 1.0, 0.0]
    copied_assets = list((output / "assets" / "meshes").glob("*.glb"))
    assert {_path.read_bytes() for _path in copied_assets} == {
        b"static-approved-glb", b"dynamic-approved-glb", b"door-approved-glb"
    }


def test_rejects_hash_asset_and_spawn_authority_drift(tmp_path: Path) -> None:
    contract = _contract(tmp_path)
    invalid_hash = WorldContract.from_dict({**contract.to_dict(), "contract_hash": "0" * 64})
    with pytest.raises(GodotCompilerError, match="hash"):
        GodotCompiler().compile(invalid_hash, tmp_path / "bad-hash")

    Path(contract.instances[0].asset_binding.mesh_path).write_bytes(b"mutated")
    with pytest.raises(GodotCompilerError, match="hash mismatch"):
        GodotCompiler().compile(contract, tmp_path / "bad-asset")

    no_spawn = finalize(WorldContract(
        plan_revision="rev-1",
        camera_hash="d" * 64,
        room_shell_ref="parametric-room:sha256:" + "e" * 64,
        instances=contract.instances,
        relationships=(),
        lighting=LightingConfig(),
        contract_id="world-no-spawn",
    ))
    with pytest.raises(GodotCompilerError, match="explicit player_spawn"):
        GodotCompiler().compile(no_spawn, tmp_path / "no-spawn")
