"""Create-once and validate Task 11.8.4a continuity-correction evidence.

The exact common StandaloneAssetGate order is preserved. Image-based material
criteria supplement (and do not replace or weaken) the common gate. Human
approval is never manufactured; Task 11.8.5 remains blocked.
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
EVIDENCE_ID = "3876cc8a-81a2-4bba-9da0-185ba59db002"
BUNDLE = EVIDENCE_DIR / f"task-11.8.4a-continuity-corrected-raw-crop-recliner-{EVIDENCE_ID}"
BUILDER_PATH = BUNDLE / "build_continuity_corrected_recliner.py"
BUILD_RECORD = BUNDLE / "build-record.json"
ARTIFACT = BUNDLE / "recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
PREVIEW = BUNDLE / "recliner-raw-crop_continuity-corrected-neutral-eight-panel.png"
DERIVED_TEXTURE = BUNDLE / "recliner-raw-crop_seamless-upholstery-source-map.png"
OUTPUT = EVIDENCE_DIR / f"task-11.8.4a-continuity-corrected-raw-crop-recliner-{EVIDENCE_ID}.json"

PRIOR_GATE = EVIDENCE_DIR / "task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json"
BAKEOFF = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a.json"
SOURCE_BUNDLE = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a"
SOURCE_GLB = SOURCE_BUNDLE / "objects" / "recliner-raw-crop_hunyuan3d.glb"
SOURCE_NEUTRAL = SOURCE_BUNDLE / "lane-raw-crop-neutral.png"
SOURCE_IMAGE = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png")
MIRROR_IMAGE = Path(r"C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png")
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
WORKFLOW_UI = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json")
WORKFLOW_API = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.api.json")
REJECTED_EVIDENCE = EVIDENCE_DIR / "task-11.8.4a-remediated-raw-crop-recliner-aa1347b1-9a3e-45f6-af16-571c7e03dde8.json"
REJECTED_BUNDLE = EVIDENCE_DIR / "task-11.8.4a-remediated-raw-crop-recliner-aa1347b1-9a3e-45f6-af16-571c7e03dde8"
REJECTED_ARTIFACT = REJECTED_BUNDLE / "recliner-raw-crop_durable-fabric-pbr.glb"
REJECTED_PREVIEW = REJECTED_BUNDLE / "recliner-raw-crop_durable-fabric-pbr-neutral-eight-panel.png"
VISUAL_REJECTION = EVIDENCE_DIR / "task-11.8.4a-visual-rejection-b1cbf2d1-1a25-478c-8ddf-3a4f5bfd4780.json"
PROCESSOR = ROOT / "src" / "photo_pipeline" / "stages" / "material_processor.py"

UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED = {
    PRIOR_GATE: "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
    BAKEOFF: "1b72f3d0bff59c7ba494f0b782b449de6f1edbd5121fb7a268b5d37a4f1fe218",
    SOURCE_GLB: "970d3b92c8d25f27b088de9696c5762255b72a7e7b7af1180ef8f946fa70ad06",
    SOURCE_NEUTRAL: "8f52b50c172cefbeaa6ec19f59495ca27eb88c8a4bf0986c513e6bd62c2444b3",
    SOURCE_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    MIRROR_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    SOURCE_CROP: "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a",
    WORKFLOW_UI: "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196",
    WORKFLOW_API: "362dea52c21418717e919d9ea942f74a9016dd38088ec618660c21f74f2f37af",
    REJECTED_EVIDENCE: "b0fc2b37f5b2c97b815552ee004f13228507ec272559ef04e45d67175859c3fa",
    REJECTED_ARTIFACT: "181ad41bfde7b1a807cb8c2c89c5a3ce977618b8b3092252d3abe5c05b07e7b2",
    REJECTED_PREVIEW: "37776fac4fa6634ee31f39d195b87d571de94ffe7e1be7d00f5dd758d97794a6",
    VISUAL_REJECTION: "ba20df1f1664daebb7ead03b395c8d916ed3633198430ed0c82eb29da9f22253",
    DERIVED_TEXTURE: "fe7b30e9714da36d91c2b2786a327d6329a660d37443fc86b3ed8de2071b4518",
    ARTIFACT: "4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf",
    PREVIEW: "c6b41469032748ef02bf70136ec965eb9cb09d872a9013ca033609ed0d4a39cc",
    PROCESSOR: "c3fa4d9b763b369b40020555d945de74c73be935eeb35409a190ae2a09a6984e",
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


def load_builder():
    spec = importlib.util.spec_from_file_location("task_11_8_4a_continuity_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load continuity builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
    return {"path": relative(path), "exists": path.is_file(), "sha256_expected": expected, "sha256_observed": observed, "verified": observed is not None and (expected is None or observed == expected)}


def candidate_tree_fingerprint() -> dict[str, Any]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    listed = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT).split(b"\0")
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
        "note": "Computed after rejection record, correction builder, artifact, preview, build record, and validator existed, immediately before writing this non-self-referential evidence record.",
    }


def parse_document(path: Path) -> tuple[dict[str, Any], int]:
    payload = path.read_bytes()
    magic, version, declared = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared != len(payload):
        raise AssertionError("Invalid GLB 2.0 container")
    document = None
    binary_length = 0
    offset = 12
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
    embedded_images = [image for image in images if "bufferView" in image or image.get("uri", "").startswith("data:")]
    views_in_bounds = all(int(view.get("byteOffset", 0)) + int(view["byteLength"]) <= binary_length for view in document.get("bufferViews", []))
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
        raise AssertionError("Expected one source and final geometry")
    source, final = source_geometries[0], final_geometries[0]
    max_position_delta = float(np.max(np.abs(np.asarray(source.vertices) - np.asarray(final.vertices))))
    max_extent_delta = float(np.max(np.abs(np.asarray(source.extents) - np.asarray(final.extents))))
    material = getattr(final.visual, "material", None)
    in_memory = {name: isinstance(getattr(material, name, None), Image.Image) for name in ("baseColorTexture", "metallicRoughnessTexture", "normalTexture")}
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
        "durable_material_present": len(materials) > 0 and len(textures) >= 3 and len(embedded_images) >= 3 and all(referenced.values()) and all(in_memory.values()),
    }


def make_check(name: str, passed: bool, observation: str) -> dict[str, Any]:
    return {"check": name, "pass": passed, "observation": observation}


def build_record(candidate_binding: dict[str, Any]) -> dict[str, Any]:
    builder = load_builder()
    build = json.loads(BUILD_RECORD.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_GATE.read_text(encoding="utf-8"))
    inherited = {item["check"]: item["pass"] for item in prior["lane_verdicts"][0]["common_gate_checks"]}
    visual = builder.assess_artifact_visual(ARTIFACT)
    rejected_visual = builder.assess_artifact_visual(REJECTED_ARTIFACT)
    rejected_holes = builder.rejected_preview_hole_ratio(REJECTED_PREVIEW)
    artifact = inspect_artifact()
    preview_image = Image.open(PREVIEW)

    fixed_bindings = [binding(path, expected) for path, expected in EXPECTED.items()]
    dynamic_bindings = [binding(BUILD_RECORD), binding(BUILDER_PATH), binding(Path(__file__))]
    all_bindings = fixed_bindings + dynamic_bindings
    chain_pass = all(item["verified"] for item in all_bindings)
    visual_regression_pass = (
        not rejected_visual["checks"]["projected_subject_leakage"]
        and rejected_holes > builder.VISUAL_THRESHOLDS["internal_hole_ratio_max"]
        and visual["pass"]
        and visual == build["image_based_visual_validation"]
    )
    source_identity = build["recliner_uuid"] == UUID and build["source_lane"] == "raw_crop" and EXPECTED[SOURCE_IMAGE] == EXPECTED[MIRROR_IMAGE]
    non_placeholder = artifact["geometry_preserved"] and artifact["vertex_count"] == 675366 and artifact["face_count"] == 1358256
    no_external = not artifact["external_image_uris"] and not artifact["external_buffer_uris"]
    preview_valid = preview_image.size == (1680, 912) and preview_image.mode == "RGB" and sha256(PREVIEW) == EXPECTED[PREVIEW]
    material_pass = artifact["durable_material_present"] and visual_regression_pass

    checks = [
        make_check("evidence_chain_integrity", chain_pass and artifact["geometry_preserved"], "All prior no-pass/rejection, source/workflow, build, approved material-pipeline, corrected artifact, and preview hashes verify; source geometry is unchanged."),
        make_check("stable_uuid_binding", build["recliner_uuid"] == UUID, f"Corrected artifact remains bound to recliner UUID {UUID}."),
        make_check("golden_room_source_identity", source_identity, "Only the Golden Room source-matched raw_crop lane was used; authoritative image, identical mirror, workflow, crop, and prepared-input hashes verify."),
        make_check("independent_loadability", artifact["independent_trimesh_load"] and artifact["buffer_views_in_bounds"], "GLB 2.0 chunks and buffer views are valid and one positive trimesh geometry loads independently."),
        make_check("non_placeholder_geometry", non_placeholder, "The original generated raw-crop geometry remains exact at 675366 vertices and 1358256 faces; no placeholder was substituted."),
        make_check("recognizable_recliner_silhouette_identity", inherited["recognizable_recliner_silhouette_identity"] and artifact["geometry_preserved"], "The immutable common gate passed recliner silhouette/identity; zero geometry delta and corrected continuous four-view evidence preserve it."),
        make_check("no_fused_scene_or_ground_sheet_geometry", inherited["no_fused_scene_or_ground_sheet_geometry"] and artifact["geometry_preserved"], "The immutable common gate found no fused room or ground sheet; geometry remains byte-source-identical within 1e-5."),
        make_check("no_obvious_catastrophic_reconstruction_artifacts", inherited["no_obvious_catastrophic_reconstruction_artifacts"] and artifact["geometry_preserved"], "The unchanged geometry retains the prior non-catastrophic verdict and is exposed in four continuous neutral views."),
        make_check("neutral_multi_angle_turntable_evidence", preview_valid and visual["pass"], f"Hash-bound 1680x912 front/right/rear/left geometry and material evidence passes coverage-aware image checks: {relative(PREVIEW)}."),
        make_check("durable_non_temporary_material_continuity", material_pass, "Pass-2 base-color, metallic-roughness, and normal maps are embedded, and image checks reject projected-subject leakage, holes/speckle, false-surface edges, palette outliers, and cross-view discontinuity. The known rejected artifact fails the strengthened regression."),
        make_check("no_unresolved_external_materials_or_buffers", no_external, "All three material images are embedded buffer views; no external image or buffer URI exists."),
        make_check("explicit_hash_bound_human_approval", False, "PENDING: no approval is manufactured. User decision must bind artifact hash, pre-record candidate fingerprint, Golden Room image/workflow hashes, preview hash, rejection evidence hash, and this gate evidence hash."),
    ]
    assert [item["check"] for item in checks] == COMMON_CHECKS
    non_human_pass = all(item["pass"] for item in checks[:11])
    return {
        "schema": "unified-world-pipeline.task-11.8.4a.continuity-corrected-gate.v1",
        "evidence_id": EVIDENCE_ID,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "result": "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL" if non_human_pass else "FAIL_CLOSED_NON_HUMAN_BLOCKER",
        "scope_boundary": "Continuation of active Task 11.8.4a only; immutable rejected candidates remain preserved, Task 11.8.5 remains blocked, and no Demo Ready, release, session, service, UI, ownership, or commit claim is made.",
        "recliner_uuid": UUID,
        "source_lane": "raw_crop",
        "candidate_binding": candidate_binding,
        "visual_rejection": {"record": binding(VISUAL_REJECTION, EXPECTED[VISUAL_REJECTION]), "rejected_evidence": binding(REJECTED_EVIDENCE, EXPECTED[REJECTED_EVIDENCE]), "rejected_artifact": binding(REJECTED_ARTIFACT, EXPECTED[REJECTED_ARTIFACT]), "rejected_preview": binding(REJECTED_PREVIEW, EXPECTED[REJECTED_PREVIEW]), "findings": ["projection smearing", "speckled/holed coverage", "false surfaces", "broken material continuity"], "immutable": True},
        "golden_room_provenance": {"authoritative_source_image": binding(SOURCE_IMAGE, EXPECTED[SOURCE_IMAGE]), "identical_shared_input_mirror": binding(MIRROR_IMAGE, EXPECTED[MIRROR_IMAGE]), "authoritative_workflow": binding(WORKFLOW_UI, EXPECTED[WORKFLOW_UI]), "raw_crop_extraction_workflow": binding(WORKFLOW_API, EXPECTED[WORKFLOW_API]), "raw_source_crop": binding(SOURCE_CROP, EXPECTED[SOURCE_CROP]), "prepared_raw_crop": binding(SOURCE_NEUTRAL, EXPECTED[SOURCE_NEUTRAL]), "immutable_task_11_8_4_evidence": binding(PRIOR_GATE, EXPECTED[PRIOR_GATE])},
        "correction": {"method": build["correction_scope"], "derived_source_map": binding(DERIVED_TEXTURE, EXPECTED[DERIVED_TEXTURE]), "derivation": build["material_input_derivation"], "material_pipeline": build["material_pipeline"], "model_or_service_used": False},
        "artifact": {"path": relative(ARTIFACT), "sha256": sha256(ARTIFACT), "bytes": ARTIFACT.stat().st_size, "inspection": artifact},
        "neutral_multi_angle_evidence": {"path": relative(PREVIEW), "sha256": sha256(PREVIEW), "dimensions": list(preview_image.size), "layout": "front/right/rear/left; continuous geometry row and embedded-material row", "image_based_validation": visual},
        "strengthened_visual_regression": {"known_rejected_artifact_hash": EXPECTED[REJECTED_ARTIFACT], "known_rejected_projected_subject_leakage_correlation": rejected_visual["projected_subject_leakage_correlation"], "known_rejected_artifact_fails_projected_subject_leakage": not rejected_visual["checks"]["projected_subject_leakage"], "known_rejected_preview_max_internal_hole_ratio": rejected_holes, "known_rejected_preview_fails_hole_threshold": rejected_holes > builder.VISUAL_THRESHOLDS["internal_hole_ratio_max"], "corrected_artifact_passes_all_image_criteria": visual["pass"], "pass": visual_regression_pass},
        "common_gate": {"policy": "Exact Task 11.8.4 12-check order; no lane-specific exception or weakened criterion. Strengthened image criteria are additional fail-closed evidence inside the existing material/neutral checks.", "checks_in_order": COMMON_CHECKS, "checks": checks, "non_human_checks_pass": non_human_pass, "failed_checks": [item["check"] for item in checks if not item["pass"]], "verdict": "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL" if non_human_pass else "FAIL"},
        "human_approval": {"present": False, "status": "AWAITING_USER_DECISION" if non_human_pass else "NOT_REQUESTED_NON_HUMAN_FAILURE", "asset_hash_bound": False, "candidate_fingerprint_bound": False, "golden_room_reference_hashes_bound": False, "preview_hash_bound": False, "rejection_evidence_hash_bound": False, "gate_evidence_hash_bound": False, "approved": False},
        "authority": {"metric_plan_remains_sole_authority_for": ["dimensions", "transforms", "placement", "architecture", "openings", "collision", "navigation"], "immutable_plan_derived_camera_contract_remains_camera_authority": True, "world_contract_remains_final_binding_authority": True, "asset_is_not_spatial_authority": True},
        "validation": {"validator_path": relative(Path(__file__)), "command": "python .kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a_visual_correction.py", "targeted_assertions": ["immutability of prior no-pass and visually rejected candidates", "source/workflow/crop provenance", "UUID binding", "GLB 2.0 and independent trimesh load", "source geometry identity", "embedded base-color/metallic-roughness/normal textures", "no external image/buffer URIs", "projected-subject leakage regression", "rendered coverage and holes/speckle", "false-surface edge and palette continuity", "cross-view continuity", "exact 12-check order", "human approval remains absent"], "result": "PASS" if non_human_pass else "FAIL"},
        "preservation": {"task_11_8_4_evidence_modified": False, "rejected_task_11_8_4a_evidence_or_artifacts_modified": False, "source_raw_crop_candidate_modified": False, "production_code_modified": False, "test_code_modified": False, "ui_or_interface_modified": False, "production_service_or_ownership_modified": False, "replacement_or_qualification_session_created": False, "new_model_download_integration_preflight_or_inference": False, "cloud_used": False, "commit_created": False, "unrelated_worktree_content_modified": False},
        "status_effect": {"task_11_8_4a": "AWAITING_EXPLICIT_USER_APPROVAL" if non_human_pass else "BLOCKED_NON_HUMAN_FAILURE", "task_11_8_5": "BLOCKED", "approval_or_completion_claimed": False},
        "mvp_alignment": "Compatible with the 6-8 active-coding-hour MVP target: the correction is source-only, material-only, model-free, and reuses the approved local pipeline; no exploratory geometry, tooling expansion, or downstream work was opened.",
        "all_hash_bindings": all_bindings,
    }


def validate(record: dict[str, Any]) -> None:
    assert record["schema"] == "unified-world-pipeline.task-11.8.4a.continuity-corrected-gate.v1"
    assert record["recliner_uuid"] == UUID and record["source_lane"] == "raw_crop"
    assert record["artifact"]["sha256"] == EXPECTED[ARTIFACT]
    assert record["neutral_multi_angle_evidence"]["sha256"] == EXPECTED[PREVIEW]
    assert record["common_gate"]["checks_in_order"] == COMMON_CHECKS
    assert [item["check"] for item in record["common_gate"]["checks"]] == COMMON_CHECKS
    assert all(item["pass"] for item in record["common_gate"]["checks"][:11])
    assert record["common_gate"]["checks"][11]["pass"] is False
    assert record["common_gate"]["failed_checks"] == ["explicit_hash_bound_human_approval"]
    assert record["common_gate"]["verdict"] == "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL"
    assert record["strengthened_visual_regression"]["pass"] is True
    assert record["neutral_multi_angle_evidence"]["image_based_validation"]["pass"] is True
    assert record["human_approval"]["present"] is False and record["human_approval"]["approved"] is False
    assert record["status_effect"]["task_11_8_5"] == "BLOCKED"
    assert record["artifact"]["inspection"]["durable_material_present"] is True
    assert record["artifact"]["inspection"]["external_image_uris"] == []
    assert record["artifact"]["inspection"]["external_buffer_uris"] == []
    assert record["artifact"]["inspection"]["geometry_preserved"] is True
    assert all(item["verified"] for item in record["all_hash_bindings"])
    for path, expected in EXPECTED.items():
        assert sha256(path) == expected


def compare(stored: dict[str, Any], observed: dict[str, Any]) -> None:
    for field in ("candidate_binding", "visual_rejection", "golden_room_provenance", "correction", "artifact", "neutral_multi_angle_evidence", "strengthened_visual_regression", "common_gate", "all_hash_bindings"):
        assert stored[field] == observed[field], field


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
    print("PASS Task 11.8.4a strengthened targeted validation")
    print(f"  artifact_sha256: {record['artifact']['sha256']}")
    print(f"  preview_sha256: {record['neutral_multi_angle_evidence']['sha256']}")
    print(f"  candidate_fingerprint: {record['candidate_binding']['pre_record_candidate_tree_fingerprint']}")
    print(f"  known_rejected_leakage: {record['strengthened_visual_regression']['known_rejected_projected_subject_leakage_correlation']:.9f} (rejected)")
    print(f"  corrected_leakage: {record['neutral_multi_angle_evidence']['image_based_validation']['projected_subject_leakage_correlation']:.9f} (pass)")
    print("  non_human_checks: 11/11 PASS")
    print(f"  human_approval: {record['human_approval']['status']}")
    print(f"  evidence: {OUTPUT}")
    print(f"  evidence_sha256: {sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
