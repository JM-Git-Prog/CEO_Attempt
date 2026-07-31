from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.unified_pipeline.compilers.upbge import (
    SCENE_COLLECTIONS,
    UPBGECompileError,
    UPBGECompiler,
    build_upbge_plan,
)
from src.unified_pipeline.world_contract import (
    AssetBinding,
    LightSource,
    LightingConfig,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Vec3,
    WorldContract,
    finalize,
)


def _contract(tmp_path: Path) -> tuple[WorldContract, Path]:
    asset = tmp_path / "source.glb"
    asset.write_bytes(b"contract-bound-test-glb")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    room = tmp_path / "room.glb"
    room.write_bytes(b"contract-bound-room-glb")
    instance = ObjectInstance(
        object_id="spawn-1",
        name="Safe spawn",
        position=Vec3(1.25, 1.0, -2.5),
        rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
        scale=Vec3(0.2, 0.2, 0.2),
        asset_binding=AssetBinding(
            asset_id=digest,
            mesh_path=str(asset),
            triangle_count=12,
            vertex_count=8,
            generator="placeholder",
        ),
        physics_intent="trigger",
        material_intent=MaterialIntent(
            base_color="#804020", metallic=0.1, roughness=0.7, pass_level=1,
        ),
        semantic_label="player_spawn",
    )
    contract = finalize(WorldContract(
        plan_revision="rev-3",
        camera_hash="c" * 64,
        room_shell_ref="room-shell:test",
        instances=(instance,),
        lighting=LightingConfig(
            ambient_color="#101820",
            ambient_intensity=0.25,
            lights=(LightSource(
                light_id="key", light_type="area",
                position=Vec3(2.0, 2.5, -1.0), color="#ffe0c0",
                intensity=750.0, temperature=3200.0,
            ),),
        ),
        contract_id="world-test",
        created_at="2026-08-01T00:00:00Z",
    ))
    return contract, room


def test_plan_is_deterministic_and_preserves_authoritative_values(tmp_path: Path):
    contract, _room = _contract(tmp_path)

    first = build_upbge_plan(contract)
    second = build_upbge_plan(contract)
    instance = first["instances"][0]

    assert first == second
    assert first["world_contract_hash"] == contract.contract_hash
    assert first["plan_revision"] == "rev-3"
    assert first["camera_hash"] == "c" * 64
    assert first["scene"]["collections"] == list(SCENE_COLLECTIONS)
    assert instance["transform_domain"]["position"] == [1.25, 1.0, -2.5]
    assert instance["transform_upbge"]["position"] == [1.25, -2.5, 1.0]
    assert instance["physics"]["intent"] == "trigger"
    assert instance["material"]["roughness"] == 0.7
    assert first["player"]["spawn"] == {
        "strategy": "contract_spawn_marker",
        "source_object_id": "spawn-1",
        "position_upbge": [1.25, -2.5, 1.0],
        "rotation_upbge_xyzw": [-0.0, -0.0, -0.0, 1.0],
    }
    assert first["player"]["logic_bricks"][0]["controller"]["module"] == (
        "upbge_player_controller.main"
    )


def test_unavailable_engine_emits_honestly_labeled_bundle_not_blend(tmp_path: Path):
    contract, room = _contract(tmp_path)
    output = tmp_path / "fallback"
    compiler = UPBGECompiler(
        executable=tmp_path / "definitely-missing-upbge.exe",
        room_shells={contract.room_shell_ref: room},
    )

    result = compiler.compile(contract, output)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    plan = json.loads(result.plan_path.read_text(encoding="utf-8"))

    assert result.status == "fallback"
    assert result.artifact_kind == "deterministic_upbge_build_bundle"
    assert result.is_real_blend is False
    assert result.is_upbge_ready is False
    assert result.blend_path is None
    assert result.fallback_reason == "blender_or_upbge_unavailable"
    assert not (output / "scene.blend").exists()
    assert manifest["claim"] == "build_inputs_only_not_a_blend"
    assert plan["world_contract_hash"] == contract.contract_hash
    assert (output / "build_upbge.py").is_file()
    assert (output / "upbge_player_controller.py").is_file()


def test_unresolved_room_reference_blocks_real_compile(tmp_path: Path):
    contract, _room = _contract(tmp_path)
    compiler = UPBGECompiler(executable=sys.executable)

    result = compiler.compile(contract, tmp_path / "unresolved")

    assert result.status == "fallback"
    assert result.fallback_reason == "unresolved_contract_dependencies"
    assert result.blend_path is None
    assert any("room_shell" in message for message in result.diagnostics)


def test_invalid_contract_hash_fails_closed(tmp_path: Path):
    contract, _room = _contract(tmp_path)
    payload = contract.to_dict()
    payload["contract_hash"] = "0" * 64
    changed = WorldContract.from_dict(payload)

    with pytest.raises(UPBGECompileError, match="valid canonical hash"):
        build_upbge_plan(changed)


def test_validated_builder_output_is_the_only_real_upbge_blend_claim(tmp_path: Path):
    contract, room = _contract(tmp_path)

    def runner(command, **_kwargs):
        output = Path(command[command.index("--output") + 1])
        report = Path(command[command.index("--report") + 1])
        output.write_bytes(b"BLENDER-v300")
        report.write_text(json.dumps({
            "blend_saved": True,
            "character_physics_configured": True,
            "logic_bricks_attached": True,
            "instance_physics_configured": True,
            "scene_collections": list(SCENE_COLLECTIONS),
            "world_contract_hash": contract.contract_hash,
            "player_spawn_upbge": [1.25, -2.5, 1.0],
        }), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    compiler = UPBGECompiler(
        executable=sys.executable,
        room_shells={contract.room_shell_ref: room},
        runner=runner,
    )
    result = compiler.compile(contract, tmp_path / "compiled")

    assert result.status == "compiled"
    assert result.artifact_kind == "upbge_blend"
    assert result.is_real_blend is True
    assert result.is_upbge_ready is True
    assert result.blend_path is not None
    assert result.blend_path.read_bytes().startswith(b"BLENDER")
