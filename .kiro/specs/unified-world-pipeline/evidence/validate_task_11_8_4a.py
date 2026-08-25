"""Create once, then validate, Task 11.8.4a remediation evidence.

The final common-gate verdict intentionally remains awaiting explicit human
approval. This validator never manufactures or records approval.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = Path(__file__).resolve().parent
EVIDENCE_ID = "aa1347b1-9a3e-45f6-af16-571c7e03dde8"
BUNDLE = EVIDENCE_DIR / f"task-11.8.4a-remediated-raw-crop-recliner-{EVIDENCE_ID}"
OUTPUT = EVIDENCE_DIR / f"task-11.8.4a-remediated-raw-crop-recliner-{EVIDENCE_ID}.json"
PRIOR_VALIDATOR = EVIDENCE_DIR / "validate_task_11_8_4.py"
PRIOR_GATE = EVIDENCE_DIR / "task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json"
BAKEOFF = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a.json"
SOURCE_BUNDLE = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a"
SOURCE_GLB = SOURCE_BUNDLE / "objects" / "recliner-raw-crop_hunyuan3d.glb"
SOURCE_NEUTRAL = SOURCE_BUNDLE / "lane-raw-crop-neutral.png"
SOURCE_IMAGE = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png")
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
WORKFLOW_UI = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json")
WORKFLOW_API = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.api.json")
MIRROR_IMAGE = Path(r"C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png")
ARTIFACT = BUNDLE / "recliner-raw-crop_durable-fabric-pbr.glb"
PREVIEW = BUNDLE / "recliner-raw-crop_durable-fabric-pbr-neutral-eight-panel.png"
DERIVED_TEXTURE = BUNDLE / "recliner-raw-crop_source-derived-fabric-base.png"
BUILD_RECORD = BUNDLE / "build-record.json"
BUILD_SCRIPT = BUNDLE / "build_final_remediated_recliner.py"
PROCESSOR = ROOT / "src" / "photo_pipeline" / "stages" / "material_processor.py"
ATTEMPT1_REVIEW = EVIDENCE_DIR / "task-11.8.4a-remediated-raw-crop-recliner-0f7d85b5-f7b0-4e18-8e92-6fb2ab65e3c1" / "attempt1-review.json"

UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED = {
    PRIOR_GATE: "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
    BAKEOFF: "1b72f3d0bff59c7ba494f0b782b449de6f1edbd5121fb7a268b5d37a4f1fe218",
    SOURCE_GLB: "970d3b92c8d25f27b088de9696c5762255b72a7e7b7af1180ef8f946fa70ad06",
    SOURCE_NEUTRAL: "8f52b50c172cefbeaa6ec19f59495ca27eb88c8a4bf0986c513e6bd62c2444b3",
    SOURCE_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    MIRROR_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    WORKFLOW_UI: "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196",
    WORKFLOW_API: "362dea52c21418717e919d9ea942f74a9016dd38088ec618660c21f74f2f37af",
    SOURCE_CROP: "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a",
    DERIVED_TEXTURE: "fb6395a06abf9387df711c2b310f0e928a2558a7eeb9e51b0b3f41b2e940cb52",
    ARTIFACT: "181ad41bfde7b1a807cb8c2c89c5a3ce977618b8b3092252d3abe5c05b07e7b2",
    PREVIEW: "37776fac4fa6634ee31f39d195b87d571de94ffe7e1be7d00f5dd758d97794a6",
}
COMMON_CHECKS = [
    "evidence_chain_integrity",
    "stable_uuid_binding",
    "golden_room_source_identity",
    "independent_loadability",
    "non_placeholder_geometry",
    "recognizable_recliner_silhouette_identity",
    "no_fused_scene_or_ground_sheet_geometry",
    "no_obvious_catastrophic_reconstruction_artifacts",
    "neutral_multi_angle_turntable_evidence",
    "durable_non_temporary_material_continuity",
    "no_unresolved_external_materials_or_buffers",
    "explicit_hash_bound_human_approval",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def binding(path: Path, expected: str | None = None) -> dict[str, Any]:
    observed = sha256(path) if path.is_file() else None
    return {
        "path": relative(path),
        "exists": path.is_file(),
        "sha256_expected": expected,
        "sha256_observed": observed,
        "verified": observed is not None and (expected is None or observed == expected),
    }


def candidate_tree_fingerprint() -> dict[str, Any]:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    ).split(b"\0")
    paths = sorted(item.decode("utf-8") for item in listed if item)
    digest = hashlib.sha256()
    digest.update(head.encode("ascii") + b"\n")
    for path in paths:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / path).read_bytes())
    return {
        "git_head": head,
        "pre_record_candidate_tree_fingerprint": digest.hexdigest(),
        "pre_record_candidate_tree_path_count": len(paths),
        "algorithm": "candidate-tree-v1: SHA-256 initialized with raw ASCII HEAD plus LF; for each lexicographically sorted tracked or untracked nonignored path from git ls-files -z --cached --others --exclude-standard, append UTF-8 path, NUL, then raw file bytes with no post-content delimiter",
        "note": "Computed after all Task 11.8.4a scripts/artifacts and before writing this non-self-referential evidence record.",
    }


def parse_document(path: Path) -> tuple[dict[str, Any], int]:
    payload = path.read_bytes()
    magic, version, declared = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared != len(payload):
        raise AssertionError("Invalid GLB 2.0 container")
    offset = 12
    document = None
    binary_length = 0
    while offset < declared:
        length, kind = struct.unpack_from("<II", payload, offset)
        chunk = payload[offset + 8 : offset + 8 + length]
        offset += 8 + length
        if kind == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \x00"))
        elif kind == 0x004E4942:
            binary_length = length
    if document is None or binary_length <= 0:
        raise AssertionError("GLB JSON/BIN chunks missing")
    return document, binary_length


def inspect_artifact() -> dict[str, Any]:
    document, binary_length = parse_document(ARTIFACT)
    images = document.get("images", [])
    textures = document.get("textures", [])
    materials = document.get("materials", [])
    external_images = [image["uri"] for image in images if image.get("uri") and not image["uri"].startswith("data:")]
    external_buffers = [buffer["uri"] for buffer in document.get("buffers", []) if buffer.get("uri")]
    embedded_images = [index for index, image in enumerate(images) if "bufferView" in image or image.get("uri", "").startswith("data:")]
    views_in_bounds = all(
        int(view.get("byteOffset", 0)) + int(view["byteLength"]) <= binary_length
        for view in document.get("bufferViews", [])
    )
    referenced = {"baseColorTexture": False, "metallicRoughnessTexture": False, "normalTexture": False}
    for material in materials:
        pbr = material.get("pbrMetallicRoughness", {})
        referenced["baseColorTexture"] |= "baseColorTexture" in pbr
        referenced["metallicRoughnessTexture"] |= "metallicRoughnessTexture" in pbr
        referenced["normalTexture"] |= "normalTexture" in material

    source_scene = trimesh.load(str(SOURCE_GLB), force="scene", process=False)
    final_scene = trimesh.load(str(ARTIFACT), force="scene", process=False)
    source_geometries = list(source_scene.geometry.values())
    final_geometries = list(final_scene.geometry.values())
    if len(source_geometries) != 1 or len(final_geometries) != 1:
        raise AssertionError("Expected one source and one remediated geometry")
    source = source_geometries[0]
    final = final_geometries[0]
    max_position_delta = float(np.max(np.abs(np.asarray(source.vertices) - np.asarray(final.vertices))))
    max_extent_delta = float(np.max(np.abs(np.asarray(source.extents) - np.asarray(final.extents))))
    material = getattr(final.visual, "material", None)
    in_memory = {
        name: isinstance(getattr(material, name, None), Image.Image)
        for name in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture")
    }
    uv = getattr(final.visual, "uv", None)
    return {
        "container": "GLB_2_0",
        "declared_bytes": ARTIFACT.stat().st_size,
        "actual_bytes": ARTIFACT.stat().st_size,
        "binary_chunk_bytes": binary_length,
        "buffer_views_in_bounds": views_in_bounds,
        "independent_trimesh_load": True,
        "geometry_count": len(final_geometries),
        "vertex_count": int(len(final.vertices)),
        "face_count": int(len(final.faces)),
        "extents_generator_space": [float(value) for value in final.extents],
        "source_geometry_sha256": sha256(SOURCE_GLB),
        "geometry_preserved": max_position_delta < 1e-5 and max_extent_delta < 1e-5,
        "max_position_delta": max_position_delta,
        "max_extent_delta": max_extent_delta,
        "material_count": len(materials),
        "texture_count": len(textures),
        "image_count": len(images),
        "embedded_image_count": len(embedded_images),
        "external_image_uris": external_images,
        "external_buffer_uris": external_buffers,
        "material_texture_references": referenced,
        "trimesh_in_memory_textures": in_memory,
        "uv_count": 0 if uv is None else int(len(uv)),
        "durable_material_present": (
            len(materials) > 0
            and len(textures) >= 3
            and len(embedded_images) >= 3
            and all(referenced.values())
            and all(in_memory.values())
        ),
    }


def make_check(name: str, passed: bool, observation: str) -> dict[str, Any]:
    return {"check": name, "pass": passed, "observation": observation}


def build_record(candidate_binding: dict[str, Any]) -> dict[str, Any]:
    fixed_bindings = [binding(path, expected) for path, expected in EXPECTED.items()]
    dynamic_bindings = [binding(BUILD_RECORD), binding(BUILD_SCRIPT), binding(PROCESSOR), binding(ATTEMPT1_REVIEW)]
    all_bindings = fixed_bindings + dynamic_bindings
    chain_pass = all(item["verified"] for item in all_bindings)
    prior = json.loads(PRIOR_GATE.read_text(encoding="utf-8"))
    prior_raw = prior["lane_verdicts"][0]
    inherited_checks = {item["check"]: item["pass"] for item in prior_raw["common_gate_checks"]}
    artifact = inspect_artifact()
    preview_image = Image.open(PREVIEW)
    preview_valid = preview_image.size == (1680, 912) and preview_image.mode == "RGB"
    build = json.loads(BUILD_RECORD.read_text(encoding="utf-8"))
    source_identity = (
        EXPECTED[SOURCE_IMAGE] == EXPECTED[MIRROR_IMAGE]
        and build["recliner_uuid"] == UUID
        and build["source_lane"] == "raw_crop"
    )
    non_placeholder = (
        artifact["geometry_preserved"]
        and artifact["vertex_count"] == 675366
        and artifact["face_count"] == 1358256
    )
    no_external = not artifact["external_image_uris"] and not artifact["external_buffer_uris"]
    checks = [
        make_check("evidence_chain_integrity", chain_pass and artifact["geometry_preserved"], "All source, workflow, prior-gate, build, material-pipeline, artifact, and preview hashes verify; copied generated geometry matches the raw-crop source within 1e-5."),
        make_check("stable_uuid_binding", build["recliner_uuid"] == UUID, f"Remediated artifact remains bound to recliner UUID {UUID}."),
        make_check("golden_room_source_identity", source_identity, "Only the Golden Room source-matched raw_crop lane was used; authoritative image, identical mirror, UI workflow, extraction workflow, crop, and prepared-input hashes verify."),
        make_check("independent_loadability", artifact["independent_trimesh_load"] and artifact["buffer_views_in_bounds"], "GLB 2.0 chunks, buffer views, accessors, and one positive trimesh geometry load independently."),
        make_check("non_placeholder_geometry", non_placeholder, "The original high-density generated geometry is preserved exactly (675366 vertices, 1358256 faces); no placeholder primitive was substituted."),
        make_check("recognizable_recliner_silhouette_identity", inherited_checks["recognizable_recliner_silhouette_identity"] and artifact["geometry_preserved"], "The immutable Task 11.8.4 review passed recliner silhouette/identity; zero geometry delta carries that exact shape into the new hash-bound neutral review."),
        make_check("no_fused_scene_or_ground_sheet_geometry", inherited_checks["no_fused_scene_or_ground_sheet_geometry"] and artifact["geometry_preserved"], "The immutable Task 11.8.4 review found no room shell or ground sheet; zero geometry delta preserves that result."),
        make_check("no_obvious_catastrophic_reconstruction_artifacts", inherited_checks["no_obvious_catastrophic_reconstruction_artifacts"] and artifact["geometry_preserved"], "The immutable Task 11.8.4 review found no catastrophic reconstruction collapse; the new geometry/topology row exposes the unchanged four-view result."),
        make_check("neutral_multi_angle_turntable_evidence", preview_valid, f"Hash-bound 1680x912 front/right/rear/left evidence includes separate geometry/topology and embedded-material rows: {relative(PREVIEW)}."),
        make_check("durable_non_temporary_material_continuity", artifact["durable_material_present"], "Final GLB embeds source-derived base color plus Pass-2 fabric metallic-roughness and normal maps; all three load in-memory and the neutral material row shows bounded brown fabric coverage on every view."),
        make_check("no_unresolved_external_materials_or_buffers", no_external, "GLB contains no external image URI or buffer URI; all material images are embedded buffer views."),
        make_check("explicit_hash_bound_human_approval", False, "PENDING: no approval is manufactured. User decision must explicitly bind artifact hash, pre-record candidate fingerprint, Golden Room source/workflow hashes, preview hash, and this gate evidence hash."),
    ]
    assert [item["check"] for item in checks] == COMMON_CHECKS
    non_human_pass = all(item["pass"] for item in checks[:11])
    return {
        "schema": "unified-world-pipeline.task-11.8.4a.remediated-raw-crop-gate.v1",
        "evidence_id": EVIDENCE_ID,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "result": "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL" if non_human_pass else "FAIL_CLOSED_NON_HUMAN_BLOCKER",
        "scope_boundary": "Task 11.8.4a remediation and exact common-gate re-evaluation only; no approval is manufactured, Task 11.8.5 remains blocked, and no Demo Ready, release, session, service, UI, or commit claim is made.",
        "recliner_uuid": UUID,
        "source_lane": "raw_crop",
        "candidate_binding": candidate_binding,
        "golden_room_provenance": {
            "authoritative_source_image": binding(SOURCE_IMAGE, EXPECTED[SOURCE_IMAGE]),
            "identical_shared_input_mirror": binding(MIRROR_IMAGE, EXPECTED[MIRROR_IMAGE]),
            "authoritative_workflow": binding(WORKFLOW_UI, EXPECTED[WORKFLOW_UI]),
            "raw_crop_extraction_workflow": binding(WORKFLOW_API, EXPECTED[WORKFLOW_API]),
            "raw_source_crop": binding(SOURCE_CROP, EXPECTED[SOURCE_CROP]),
            "prepared_raw_crop": binding(SOURCE_NEUTRAL, EXPECTED[SOURCE_NEUTRAL]),
            "immutable_task_11_8_4_evidence": binding(PRIOR_GATE, EXPECTED[PRIOR_GATE]),
        },
        "remediation": {
            "attempt_1": {"review": binding(ATTEMPT1_REVIEW), "verdict": "FAIL_NON_HUMAN_MATERIAL_CONTINUITY", "approval_requested": False},
            "attempt_2": {"build_record": binding(BUILD_RECORD), "build_script": binding(BUILD_SCRIPT), "material_processor": binding(PROCESSOR), "method": "source-derived alpha-aware fabric fill followed by unchanged existing MaterialProcessor Pass 1 and Pass 2 fabric PBR paths", "model_or_service_used": False},
        },
        "artifact": {
            "path": relative(ARTIFACT),
            "sha256": sha256(ARTIFACT),
            "bytes": ARTIFACT.stat().st_size,
            "inspection": artifact,
        },
        "neutral_multi_angle_evidence": {
            "path": relative(PREVIEW),
            "sha256": sha256(PREVIEW),
            "dimensions": list(preview_image.size),
            "layout": "front/right/rear/left; geometry/topology row and embedded-material row",
            "reviewed_non_human_observations": ["recognizable recliner seat/back/arms/extended footrest", "unchanged coherent topology", "no fused room or ground sheet", "no catastrophic collapse", "source-derived brown fabric coverage continues across all four material views"],
        },
        "common_gate": {
            "policy": "Exact Task 11.8.4 12-check order; no lane-specific exception or weakened criterion.",
            "checks_in_order": COMMON_CHECKS,
            "checks": checks,
            "non_human_checks_pass": non_human_pass,
            "failed_checks": [item["check"] for item in checks if not item["pass"]],
            "verdict": "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL" if non_human_pass else "FAIL",
        },
        "human_approval": {
            "present": False,
            "status": "AWAITING_USER_DECISION" if non_human_pass else "NOT_REQUESTED_NON_HUMAN_FAILURE",
            "asset_hash_bound": False,
            "candidate_fingerprint_bound": False,
            "golden_room_reference_hashes_bound": False,
            "preview_hash_bound": False,
            "gate_evidence_hash_bound": False,
            "approved": False,
        },
        "authority": {
            "metric_plan_remains_sole_authority_for": ["dimensions", "transforms", "placement", "architecture", "openings", "collision", "navigation"],
            "immutable_plan_derived_camera_contract_remains_camera_authority": True,
            "world_contract_remains_final_binding_authority": True,
            "asset_is_not_spatial_authority": True,
        },
        "validation": {
            "validator_path": relative(Path(__file__)),
            "command": "python .kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a.py",
            "targeted_assertions": ["immutable prior evidence hash", "source/workflow/crop provenance", "UUID binding", "GLB 2.0 and trimesh load", "geometry identity", "embedded base-color/metallic-roughness/normal textures", "no external image/buffer URIs", "neutral evidence hash/dimensions", "exact 12-check order", "human approval remains absent"],
            "result": "PASS" if non_human_pass else "FAIL",
        },
        "preservation": {
            "task_11_8_4_evidence_modified": False,
            "source_raw_crop_candidate_modified": False,
            "production_code_modified": False,
            "test_code_modified": False,
            "ui_or_interface_modified": False,
            "production_service_or_ownership_modified": False,
            "replacement_or_qualification_session_created": False,
            "new_model_download_integration_preflight_or_inference": False,
            "cloud_used": False,
            "commit_created": False,
            "unrelated_worktree_content_modified": False,
        },
        "status_effect": {
            "task_11_8_4a": "AWAITING_EXPLICIT_USER_APPROVAL" if non_human_pass else "BLOCKED_NON_HUMAN_FAILURE",
            "task_11_8_5": "BLOCKED",
            "approval_or_completion_claimed": False,
        },
        "mvp_alignment": "Bounded material-only remediation used source pixels and the existing local material path, deferred non-blocking polish/model work, and keeps the 6-8 active-coding-hour Demo Ready critical path focused.",
        "all_hash_bindings": all_bindings,
    }


def validate(record: dict[str, Any]) -> None:
    assert record["schema"] == "unified-world-pipeline.task-11.8.4a.remediated-raw-crop-gate.v1"
    assert record["recliner_uuid"] == UUID
    assert record["source_lane"] == "raw_crop"
    assert record["artifact"]["sha256"] == EXPECTED[ARTIFACT]
    assert record["neutral_multi_angle_evidence"]["sha256"] == EXPECTED[PREVIEW]
    assert record["common_gate"]["checks_in_order"] == COMMON_CHECKS
    assert [item["check"] for item in record["common_gate"]["checks"]] == COMMON_CHECKS
    assert all(item["pass"] for item in record["common_gate"]["checks"][:11])
    assert record["common_gate"]["checks"][11]["pass"] is False
    assert record["common_gate"]["failed_checks"] == ["explicit_hash_bound_human_approval"]
    assert record["common_gate"]["verdict"] == "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL"
    assert record["human_approval"]["present"] is False
    assert record["human_approval"]["approved"] is False
    assert record["status_effect"]["task_11_8_5"] == "BLOCKED"
    assert record["artifact"]["inspection"]["durable_material_present"] is True
    assert record["artifact"]["inspection"]["external_image_uris"] == []
    assert record["artifact"]["inspection"]["external_buffer_uris"] == []
    assert record["artifact"]["inspection"]["geometry_preserved"] is True
    assert all(item["verified"] for item in record["all_hash_bindings"])
    assert sha256(PRIOR_GATE) == EXPECTED[PRIOR_GATE]


def compare(stored: dict[str, Any], observed: dict[str, Any]) -> None:
    assert stored["candidate_binding"] == observed["candidate_binding"]
    assert stored["artifact"] == observed["artifact"]
    assert stored["neutral_multi_angle_evidence"] == observed["neutral_multi_angle_evidence"]
    assert stored["common_gate"] == observed["common_gate"]
    assert stored["golden_room_provenance"] == observed["golden_room_provenance"]
    assert stored["all_hash_bindings"] == observed["all_hash_bindings"]


def main() -> None:
    if OUTPUT.exists():
        stored = json.loads(OUTPUT.read_text(encoding="utf-8"))
        observed = build_record(stored["candidate_binding"])
        compare(stored, observed)
        record = stored
    else:
        record = build_record(candidate_tree_fingerprint())
        validate(record)
        OUTPUT.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        record = json.loads(OUTPUT.read_text(encoding="utf-8"))
    validate(record)
    print("PASS Task 11.8.4a targeted validation")
    print(f"  artifact_sha256: {record['artifact']['sha256']}")
    print(f"  preview_sha256: {record['neutral_multi_angle_evidence']['sha256']}")
    print(f"  candidate_fingerprint: {record['candidate_binding']['pre_record_candidate_tree_fingerprint']}")
    print(f"  non_human_checks: {sum(item['pass'] for item in record['common_gate']['checks'][:11])}/11 PASS")
    print(f"  human_approval: {record['human_approval']['status']}")
    print(f"  evidence: {OUTPUT}")
    print(f"  evidence_sha256: {sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
