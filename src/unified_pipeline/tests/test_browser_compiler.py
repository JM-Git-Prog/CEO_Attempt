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
    LightSource,
    LightingConfig,
    MaterialIntent,
    ObjectInstance,
    Quaternion,
    Vec3,
    WorldContract,
    finalize,
    serialize,
)


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
        object_id="stable-chair-uuid",
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
    return finalize(WorldContract(
        plan_revision="rev-11",
        camera_hash=camera.compute_hash(),
        camera=camera if include_camera else None,
        room_shell_ref="parametric-room:sha256:" + "a" * 64,
        instances=(instance,),
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
    assert "root.position.set(instance.position.x" in script
    assert "root.quaternion.set" in script
    assert "root.scale.set(instance.scale.x" in script
    assert "Box3" not in script
    assert "getSize" not in script
    assert "normalize()" not in script

    html = result.index_file.read_text(encoding="utf-8")
    assert "?v=1" in html
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
