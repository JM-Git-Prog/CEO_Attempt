"""Integrated Task 7.5 tests for concrete compilers and parity.

**Validates: Requirements 21.4, 20.8**
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.compilers.browser import BrowserCompiler
from src.unified_pipeline.compilers.godot import GodotCompiler
from src.unified_pipeline.compilers.parity import (
    CompilerAuthority,
    CompilerTarget,
    InvalidCompilerPayload,
    RoomDimensions,
    adapt_compiler_manifest,
    build_parity_payload,
    run_parity_gate,
)
from src.unified_pipeline.compilers.upbge import UPBGECompiler
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _contract(tmp_path: Path) -> tuple[WorldContract, CameraContract, Path]:
    mesh = tmp_path / "approved-table.glb"
    mesh.write_bytes(b"contract-bound-shared-compiler-mesh")
    room = tmp_path / "approved-room.glb"
    room.write_bytes(b"contract-bound-shared-room-shell")
    camera = CameraContract(
        position=(1.25, 1.6, -2.5), target=(0.0, 1.0, 0.0),
        vfov=57.0, aspect=1.5, near=0.05, far=60.0,
        raster_width=1200, raster_height=800,
    )
    instance = ObjectInstance(
        object_id="table-uuid",
        name="Round table",
        position=Vec3(0.625, 0.4, -0.75),
        rotation=Quaternion(0.0, 0.382683432365, 0.0, 0.923879532511),
        scale=Vec3(1.1, 0.8, 1.1),
        asset_binding=AssetBinding(
            asset_id=_sha256(mesh), mesh_path=str(mesh),
            triangle_count=1200, vertex_count=700, generator="hunyuan3d",
        ),
        physics_intent="static",
        material_intent=MaterialIntent(
            base_color="#7a4b2a", metallic=0.0, roughness=0.72, pass_level=2,
        ),
        semantic_label="furniture/table",
    )
    spawn = json.dumps({
        "player_spawn": {
            "position": [0.0, 0.05, -1.5],
            "rotation": [0.0, 0.0, 0.0, 1.0],
        }
    })
    contract = finalize(WorldContract(
        plan_revision="rev-7",
        camera_hash=camera.compute_hash(),
        camera=camera,
        room_shell_ref=str(room),
        instances=(instance,),
        relationships=(Relationship("table-uuid", "room", "containment", spawn),),
        lighting=LightingConfig(
            ambient_color="#201810", ambient_intensity=0.35,
            lights=(LightSource(
                light_id="warm-key", light_type="point",
                position=Vec3(0.0, 2.4, 0.0), color="#ffd8a0",
                intensity=2.75, temperature=3200.0, cast_shadows=True,
            ),),
        ),
        contract_id="shared-wave7-contract",
        created_at="2026-08-01T00:00:00Z",
    ))
    return contract, camera, room


def _authority(tmp_path: Path) -> CompilerAuthority:
    contract, camera, _ = _contract(tmp_path)
    return CompilerAuthority(
        contract, camera, RoomDimensions(4.0, 3.0, 2.7),
        {"table-uuid": 1},
    )


def _assert_manifest_artifacts(root: Path, manifest: dict) -> None:
    for artifact in manifest["artifacts"]:
        path = root / artifact["path"]
        assert path.is_file(), artifact["path"]
        assert _sha256(path) == artifact["sha256"]


def test_each_concrete_compiler_emits_valid_honestly_labeled_output(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    contract = authority.contract
    room = Path(contract.room_shell_ref)

    browser = BrowserCompiler().compile(contract, tmp_path / "browser")
    godot = GodotCompiler().compile(contract, tmp_path / "godot")
    upbge = UPBGECompiler(
        executable=tmp_path / "missing-upbge.exe",
        room_shells={contract.room_shell_ref: room},
    ).compile(contract, tmp_path / "upbge")

    browser_manifest = json.loads(browser.compiler_manifest_file.read_text("utf-8"))
    godot_manifest = json.loads(godot.manifest_file.read_text("utf-8"))
    for result, manifest, root in (
        (browser, browser_manifest, browser.output_dir),
        (godot, godot_manifest, godot.project_dir),
    ):
        assert result.contract_hash == contract.contract_hash
        assert result.contract_file.read_text("utf-8") == serialize(contract)
        assert manifest["contract_hash"] == contract.contract_hash
        assert manifest["plan_revision"] == contract.plan_revision
        assert manifest["instances"] == [item.to_dict() for item in contract.instances]
        assert manifest["authority"]["source"] == "one_canonical_world_contract"
        assert manifest["authority"]["transform_policy"] == (
            "exact_no_clamp_rescale_offset_or_normalization"
        )
        _assert_manifest_artifacts(root, manifest)

    upbge_manifest = json.loads(upbge.manifest_path.read_text("utf-8"))
    assert upbge.status == "fallback"
    assert upbge.artifact_kind == "deterministic_upbge_build_bundle"
    assert upbge.is_real_blend is False and upbge.is_upbge_ready is False
    assert upbge.blend_path is None and not (tmp_path / "upbge" / "scene.blend").exists()
    assert upbge.fallback_reason == "blender_or_upbge_unavailable"
    assert upbge_manifest["claim"] == "build_inputs_only_not_a_blend"
    assert upbge_manifest["world_contract_hash"] == contract.contract_hash
    for relative, digest in upbge_manifest["files"].items():
        assert _sha256(tmp_path / "upbge" / relative) == digest


def test_real_browser_and_godot_manifests_pass_post_compile_parity(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    browser = BrowserCompiler().compile(authority.contract, tmp_path / "browser-parity")
    godot = GodotCompiler().compile(authority.contract, tmp_path / "godot-parity")
    payloads = (
        adapt_compiler_manifest(
            authority, CompilerTarget.BROWSER,
            json.loads(browser.compiler_manifest_file.read_text("utf-8")),
        ),
        adapt_compiler_manifest(
            authority, CompilerTarget.GODOT,
            json.loads(godot.manifest_file.read_text("utf-8")),
        ),
    )

    report = run_parity_gate(authority, payloads)

    assert report.passed
    assert report.issues == ()
    assert report.contract_hash == authority.contract.contract_hash
    assert report.targets == ("browser", "godot")


def _set_path(data: dict, path: tuple[object, ...], value: object) -> None:
    current = data
    for key in path[:-1]:
        current = current[key]  # type: ignore[index,assignment]
    current[path[-1]] = value  # type: ignore[index]


_AUTHORITY_MISMATCHES = (
    (("contract_hash",), "f" * 64, "hash_mismatch"),
    (("plan_revision",), "rev-8", "revision_mismatch"),
    (("camera", "camera_hash"), "0" * 64, "camera_drift"),
    (("camera", "position", 0), 9.0, "camera_drift"),
    (("room_dimensions", "width_m"), 3.9, "room_dimension_drift"),
    (("instances", 0, "transform", "position", "x"), 0.7, "solved_transform_drift"),
    (("instances", 0, "transform", "rotation", "w"), 1.0, "solved_transform_drift"),
    (("instances", 0, "transform", "scale", "x"), 1.0, "solved_transform_drift"),
    (("instances", 0, "asset_binding", "asset_id"), "e" * 64, "asset_binding_drift"),
    (("instances", 0, "material_binding", "roughness"), 0.5, "material_binding_drift"),
    (("instances", 0, "physics_intent"), "dynamic", "physics_intent_drift"),
    (("instances", 0, "semantic_uuid"), "other-uuid", "semantic_uuid_drift"),
    (("instances", 0, "semantic_label"), "props/desk", "semantic_label_drift"),
    (("derivation", "source"), "consumer_estimate", "authority_source"),
    (("derivation", "consumer_defaults"), ["roughness=0.5"], "consumer_default"),
    (("derivation", "clamps"), ["position.x"], "clamp"),
    (("derivation", "rescalings"), ["fit_bounds"], "rescaling"),
    (("derivation", "rotation_substitutions"), ["euler"], "rotation_substitution"),
    (("derivation", "offset_substitutions"), ["center_origin"], "offset_substitution"),
    (("derivation", "camera_inferred"), True, "camera_inference"),
    (("derivation", "asset_normalization_counts", "table-uuid"), 2, "asset_normalization"),
)


@pytest.mark.parametrize(("path", "value", "expected_code"), _AUTHORITY_MISMATCHES)
def test_parity_gate_catches_canonical_hash_and_every_authority_mismatch(
    tmp_path: Path,
    path: tuple[object, ...],
    value: object,
    expected_code: str,
) -> None:
    authority = _authority(tmp_path)
    browser = build_parity_payload(authority, CompilerTarget.BROWSER)
    engine = copy.deepcopy(
        build_parity_payload(authority, CompilerTarget.GODOT).to_dict()
    )
    _set_path(engine, path, value)

    report = run_parity_gate(authority, (browser, engine))

    assert not report.passed
    assert expected_code in {issue.code for issue in report.issues}


def test_parity_gate_catches_instance_authority_membership_mismatch(
    tmp_path: Path,
) -> None:
    authority = _authority(tmp_path)
    browser = build_parity_payload(authority, CompilerTarget.BROWSER)
    engine = build_parity_payload(authority, CompilerTarget.GODOT).to_dict()
    engine["instances"] = []

    report = run_parity_gate(authority, (browser, engine))

    assert not report.passed
    assert {issue.code for issue in report.issues} == {"instance_membership"}
