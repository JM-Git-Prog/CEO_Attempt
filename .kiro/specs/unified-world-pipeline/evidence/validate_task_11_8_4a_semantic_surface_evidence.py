"""Validate Task 11.8.4a semantic continuous-surface approval evidence.

The exact Task 11.8.4 common gate order is preserved. Strengthened checks fail
closed on semantic yaw/label permutation and point-splat/stipple evidence. Human
approval remains false and Task 11.8.5 remains blocked.
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

import cv2
import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = Path(__file__).resolve().parent
EVIDENCE_ID = "cf5fd0f5-0ec5-4985-aa11-bc72dbd48637"
BUNDLE = EVIDENCE_DIR / f"task-11.8.4a-semantic-surface-recliner-{EVIDENCE_ID}"
RENDERER = BUNDLE / "render_semantic_surface_evidence.py"
RENDER_RECORD = BUNDLE / "render-record.json"
PREVIEW = BUNDLE / "recliner-raw-crop_semantic-surface-neutral-eight-panel.png"
OUTPUT = EVIDENCE_DIR / f"task-11.8.4a-semantic-surface-recliner-{EVIDENCE_ID}.json"
HOLD = EVIDENCE_DIR / "task-11.8.4a-visual-gate-hold-f3bdd7ac-c938-4a56-abad-79e850bd243b.json"

PRIOR_ID = "3876cc8a-81a2-4bba-9da0-185ba59db002"
PRIOR_BUNDLE = EVIDENCE_DIR / f"task-11.8.4a-continuity-corrected-raw-crop-recliner-{PRIOR_ID}"
PRIOR_EVIDENCE = EVIDENCE_DIR / f"task-11.8.4a-continuity-corrected-raw-crop-recliner-{PRIOR_ID}.json"
ARTIFACT = PRIOR_BUNDLE / "recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
PRIOR_PREVIEW = PRIOR_BUNDLE / "recliner-raw-crop_continuity-corrected-neutral-eight-panel.png"
PRIOR_GATE = EVIDENCE_DIR / "task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json"
SOURCE_IMAGE = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png")
MIRROR_IMAGE = Path(r"C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png")
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
WORKFLOW_UI = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json")
WORKFLOW_API = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.api.json")
PROCESSOR = ROOT / "src" / "photo_pipeline" / "stages" / "material_processor.py"

UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED = {
    PRIOR_EVIDENCE: "1525378dc6a7f82c1c420b760949158ddaf36db6d6638649850e7509e09bdaf1",
    ARTIFACT: "4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf",
    PRIOR_PREVIEW: "c6b41469032748ef02bf70136ec965eb9cb09d872a9013ca033609ed0d4a39cc",
    PRIOR_GATE: "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
    SOURCE_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    MIRROR_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    SOURCE_CROP: "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a",
    WORKFLOW_UI: "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196",
    WORKFLOW_API: "362dea52c21418717e919d9ea942f74a9016dd38088ec618660c21f74f2f37af",
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
SEMANTIC_ORDER = ("front", "right", "rear", "left")
EXPECTED_SEMANTIC_YAWS = {"front": 270, "right": 0, "rear": 90, "left": 180}
MAX_STIPPLE_SCORE = 0.08
MIN_PANEL_IOU = 0.82
MIN_ASSIGNMENT_MARGIN = 0.02


def load_renderer():
    spec = importlib.util.spec_from_file_location("task_11_8_4a_semantic_renderer", RENDERER)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load semantic surface renderer")
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
    return {
        "path": relative(path),
        "exists": path.is_file(),
        "sha256_expected": expected,
        "sha256_observed": observed,
        "verified": observed is not None and (expected is None or observed == expected),
    }


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
        "note": "Computed after the hold, renderer, preview, render record, and validator existed, immediately before writing this non-self-referential gate evidence record.",
    }


def parse_glb(path: Path) -> tuple[dict[str, Any], int]:
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
    document, binary_length = parse_glb(ARTIFACT)
    external_images = [item["uri"] for item in document.get("images", []) if item.get("uri") and not item["uri"].startswith("data:")]
    external_buffers = [item["uri"] for item in document.get("buffers", []) if item.get("uri")]
    embedded_images = [item for item in document.get("images", []) if "bufferView" in item or item.get("uri", "").startswith("data:")]
    views_in_bounds = all(int(view.get("byteOffset", 0)) + int(view["byteLength"]) <= binary_length for view in document.get("bufferViews", []))
    referenced = {"baseColorTexture": False, "metallicRoughnessTexture": False, "normalTexture": False}
    for material in document.get("materials", []):
        pbr = material.get("pbrMetallicRoughness", {})
        referenced["baseColorTexture"] |= "baseColorTexture" in pbr
        referenced["metallicRoughnessTexture"] |= "metallicRoughnessTexture" in pbr
        referenced["normalTexture"] |= "normalTexture" in material
    scene = trimesh.load(str(ARTIFACT), force="scene", process=False)
    geometries = list(scene.geometry.values())
    if len(geometries) != 1:
        raise AssertionError("Corrected artifact is not independently one-geometry loadable")
    geometry = geometries[0]
    material = getattr(geometry.visual, "material", None)
    in_memory = {name: isinstance(getattr(material, name, None), Image.Image) for name in referenced}
    return {
        "independent_loadability": True,
        "buffer_views_in_bounds": views_in_bounds,
        "geometry_count": len(geometries),
        "vertex_count": int(len(geometry.vertices)),
        "face_count": int(len(geometry.faces)),
        "extents": [float(value) for value in geometry.extents],
        "material_count": len(document.get("materials", [])),
        "texture_count": len(document.get("textures", [])),
        "embedded_image_count": len(embedded_images),
        "material_texture_references": referenced,
        "trimesh_in_memory_textures": in_memory,
        "external_image_uris": external_images,
        "external_buffer_uris": external_buffers,
        "durable_material_present": len(embedded_images) >= 3 and all(referenced.values()) and all(in_memory.values()),
    }


def panel_mask(panel: np.ndarray) -> np.ndarray:
    corners = np.concatenate((panel[:8, :8], panel[:8, -8:], panel[-8:, :8], panel[-8:, -8:]), axis=0)
    background = np.median(corners.reshape(-1, 3), axis=0)
    mask = np.max(np.abs(panel.astype(np.float32) - background), axis=2) > 8.0
    mask[:36] = False
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if count <= 1:
        return np.zeros_like(mask)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == largest


def crop_panel_masks(path: Path) -> list[np.ndarray]:
    image = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    if image.shape[:2] != (912, 1680):
        raise AssertionError(f"Unexpected preview dimensions: {image.shape}")
    return [panel_mask(image[72:492, column * 420 : (column + 1) * 420]) for column in range(4)]


def stipple_score_from_panel(panel: np.ndarray, mask: np.ndarray) -> float:
    gray = cv2.cvtColor(panel, cv2.COLOR_RGB2GRAY).astype(np.float32)
    interior = cv2.erode(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    smooth = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.15, sigmaY=1.15)
    residual = np.abs(gray - smooth)
    return float(np.mean(residual[interior] > 4.0))


def assess_preview(path: Path, renderer: Any, vertices: np.ndarray, semantic_yaws: dict[str, int]) -> dict[str, Any]:
    image = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    observed = crop_panel_masks(path)
    expected = []
    for label in SEMANTIC_ORDER:
        mask = renderer.surface_mask(vertices, semantic_yaws[label]).copy()
        mask[:36] = False
        expected.append(mask)
    matrix = np.array([[renderer.mask_iou(actual, target) for target in expected] for actual in observed], dtype=np.float64)
    inferred = [SEMANTIC_ORDER[int(np.argmax(row))] for row in matrix]
    expected_iou = [float(matrix[index, index]) for index in range(4)]
    margins = []
    for index, row in enumerate(matrix):
        alternatives = np.delete(row, index)
        margins.append(float(row[index] - np.max(alternatives)))
    stipple = []
    for column, mask in enumerate(observed):
        panel = image[72:492, column * 420 : (column + 1) * 420]
        stipple.append(stipple_score_from_panel(panel, mask))
    return {
        "inferred_semantic_label_by_panel": {SEMANTIC_ORDER[index]: inferred[index] for index in range(4)},
        "silhouette_iou_matrix_rows_observed_columns_expected": matrix.tolist(),
        "expected_label_iou": {SEMANTIC_ORDER[index]: expected_iou[index] for index in range(4)},
        "assignment_margin": {SEMANTIC_ORDER[index]: margins[index] for index in range(4)},
        "semantic_label_contract_pass": inferred == list(SEMANTIC_ORDER) and min(expected_iou) >= MIN_PANEL_IOU and min(margins) >= MIN_ASSIGNMENT_MARGIN,
        "geometry_stipple_score_by_panel": {SEMANTIC_ORDER[index]: stipple[index] for index in range(4)},
        "continuous_surface_pass": max(stipple) <= MAX_STIPPLE_SCORE,
        "thresholds": {"minimum_expected_panel_iou": MIN_PANEL_IOU, "minimum_assignment_margin": MIN_ASSIGNMENT_MARGIN, "maximum_stipple_score": MAX_STIPPLE_SCORE},
    }


def make_check(name: str, passed: bool, observation: str) -> dict[str, Any]:
    return {"check": name, "pass": bool(passed), "observation": observation}


def build_record(candidate_binding: dict[str, Any]) -> dict[str, Any]:
    renderer = load_renderer()
    render = json.loads(RENDER_RECORD.read_text(encoding="utf-8"))
    hold = json.loads(HOLD.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_EVIDENCE.read_text(encoding="utf-8"))
    prior_gate = json.loads(PRIOR_GATE.read_text(encoding="utf-8"))
    inherited = {item["check"]: item["pass"] for item in prior_gate["lane_verdicts"][0]["common_gate_checks"]}
    artifact = inspect_artifact()
    geometry = renderer.one_geometry(ARTIFACT)
    vertices = np.asarray(geometry.vertices, dtype=np.float64)
    vertices = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    if len(vertices) > renderer.MAX_RENDER_VERTICES:
        indices = np.linspace(0, len(vertices) - 1, renderer.MAX_RENDER_VERTICES, dtype=np.int64)
        vertices = vertices[indices]
    derived = renderer.derive_view_contract(vertices)
    semantic_yaws = {key: int(value) for key, value in derived["semantic_yaws_degrees"].items()}
    current_assessment = assess_preview(PREVIEW, renderer, vertices, semantic_yaws)
    previous_assessment = assess_preview(PRIOR_PREVIEW, renderer, vertices, semantic_yaws)

    fixed_bindings = [binding(path, expected) for path, expected in EXPECTED.items()]
    dynamic_bindings = [binding(HOLD), binding(RENDERER), binding(RENDER_RECORD), binding(PREVIEW), binding(Path(__file__))]
    all_bindings = fixed_bindings + dynamic_bindings
    chain_pass = all(item["verified"] for item in all_bindings)
    contract_pass = semantic_yaws == EXPECTED_SEMANTIC_YAWS and derived == render["view_contract"]
    metadata = Image.open(PREVIEW).info
    metadata_pass = metadata.get("renderer") == "continuous-normal-field-surface-v1" and json.loads(metadata.get("semantic_yaws_degrees", "{}")) == EXPECTED_SEMANTIC_YAWS
    previous_fails = not previous_assessment["semantic_label_contract_pass"] and not previous_assessment["continuous_surface_pass"]
    current_pass = current_assessment["semantic_label_contract_pass"] and current_assessment["continuous_surface_pass"] and contract_pass and metadata_pass
    source_identity = EXPECTED[SOURCE_IMAGE] == EXPECTED[MIRROR_IMAGE] and render["source_lane"] == "raw_crop" and render["recliner_uuid"] == UUID
    non_placeholder = artifact["vertex_count"] == 675366 and artifact["face_count"] == 1358256
    no_external = not artifact["external_image_uris"] and not artifact["external_buffer_uris"]

    checks = [
        make_check("evidence_chain_integrity", chain_pass and hold["explicit_user_artifact_rejection_claimed"] is False, "Prior gate, corrected candidate, held preview, artifact, source/workflows, hold, renderer, render record, replacement preview, and validator hashes verify; the hold does not claim explicit artifact rejection."),
        make_check("stable_uuid_binding", render["recliner_uuid"] == UUID, f"The unchanged artifact and replacement evidence remain bound to recliner UUID {UUID}."),
        make_check("golden_room_source_identity", source_identity, "Only the Golden Room source-matched raw_crop lane is used; image, identical mirror, crop, and workflow hashes verify."),
        make_check("independent_loadability", artifact["independent_loadability"] and artifact["buffer_views_in_bounds"], "The unchanged GLB independently loads as one geometry and all GLB buffer views are in bounds."),
        make_check("non_placeholder_geometry", non_placeholder, "The unchanged generated geometry remains 675366 vertices / 1358256 faces; no placeholder or geometry substitution occurred."),
        make_check("recognizable_recliner_silhouette_identity", inherited["recognizable_recliner_silhouette_identity"] and current_assessment["semantic_label_contract_pass"], "Recognizable recliner silhouettes are now truthfully bound to source/geometry-derived front, right, rear, and left views."),
        make_check("no_fused_scene_or_ground_sheet_geometry", inherited["no_fused_scene_or_ground_sheet_geometry"], "The immutable common gate's no-fused-room/no-ground-sheet result remains bound to the byte-identical artifact."),
        make_check("no_obvious_catastrophic_reconstruction_artifacts", inherited["no_obvious_catastrophic_reconstruction_artifacts"] and current_assessment["continuous_surface_pass"], "Continuous neutral topology lighting now exposes the unchanged geometry without point-splat stipple; prior inherited artifact verdict remains unchanged."),
        make_check("neutral_multi_angle_turntable_evidence", current_pass and previous_fails, f"Replacement hash-bound eight-panel evidence uses semantic yaws {semantic_yaws}, continuous surfaces, neutral contrast lighting, truthful labels, and fail-closed regressions proving the held preview fails orientation and stipple checks: {relative(PREVIEW)}."),
        make_check("durable_non_temporary_material_continuity", artifact["durable_material_present"] and current_assessment["continuous_surface_pass"], "The unchanged embedded Pass-2 base color, metallic/roughness, and normal textures are shown as continuous surfaces under the same neutral key/fill/rim lighting as the geometry row."),
        make_check("no_unresolved_external_materials_or_buffers", no_external, "The unchanged GLB has no unresolved external image or buffer URI."),
        make_check("explicit_hash_bound_human_approval", False, "PENDING: human approval remains false. Any later decision must bind the unchanged artifact hash, new candidate fingerprint, Golden Room reference hashes, new preview hash, hold hash, and this gate evidence hash."),
    ]
    assert [item["check"] for item in checks] == COMMON_CHECKS
    non_human_pass = all(item["pass"] for item in checks[:11])
    return {
        "schema": "unified-world-pipeline.task-11.8.4a.semantic-surface-gate.v1",
        "evidence_id": EVIDENCE_ID,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "result": "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL" if non_human_pass else "FAIL_CLOSED_NON_HUMAN_BLOCKER",
        "scope_boundary": "Task 11.8.4a evidence renderer/view-contract correction only. The corrected GLB/material and all prior candidates/evidence remain immutable; Task 11.8.5 remains blocked; no UI, production/test code, service, ownership, session, model, cloud, download, commit, Demo Ready, or release action occurred.",
        "recliner_uuid": UUID,
        "source_lane": "raw_crop",
        "candidate_binding": candidate_binding,
        "visual_gate_hold": {"record": binding(HOLD), "explicit_user_artifact_rejection_claimed": False, "prior_preview_valid_approval_evidence": False, "findings": hold["findings"]},
        "immutable_corrected_candidate": {"evidence": binding(PRIOR_EVIDENCE, EXPECTED[PRIOR_EVIDENCE]), "artifact": binding(ARTIFACT, EXPECTED[ARTIFACT]), "prior_preview": binding(PRIOR_PREVIEW, EXPECTED[PRIOR_PREVIEW]), "prior_candidate_fingerprint": prior["candidate_binding"]["pre_record_candidate_tree_fingerprint"], "modified": False},
        "golden_room_provenance": {"authoritative_source_image": binding(SOURCE_IMAGE, EXPECTED[SOURCE_IMAGE]), "identical_shared_input_mirror": binding(MIRROR_IMAGE, EXPECTED[MIRROR_IMAGE]), "raw_source_crop": binding(SOURCE_CROP, EXPECTED[SOURCE_CROP]), "authoritative_workflow": binding(WORKFLOW_UI, EXPECTED[WORKFLOW_UI]), "raw_crop_extraction_workflow": binding(WORKFLOW_API, EXPECTED[WORKFLOW_API])},
        "artifact": {"path": relative(ARTIFACT), "sha256": sha256(ARTIFACT), "reused_without_modification": True, "inspection": artifact},
        "semantic_view_contract": derived,
        "neutral_multi_angle_evidence": {"path": relative(PREVIEW), "sha256": sha256(PREVIEW), "dimensions": list(Image.open(PREVIEW).size), "renderer": render["renderer"], "metadata_verified": metadata_pass, "assessment": current_assessment},
        "strengthened_evidence_regression": {"held_preview_path": relative(PRIOR_PREVIEW), "held_preview_sha256": sha256(PRIOR_PREVIEW), "held_preview_assessment": previous_assessment, "held_preview_fails_yaw_label_permutation": not previous_assessment["semantic_label_contract_pass"], "held_preview_fails_stipple_non_surface_check": not previous_assessment["continuous_surface_pass"], "replacement_passes_both_checks": current_assessment["semantic_label_contract_pass"] and current_assessment["continuous_surface_pass"], "pass": previous_fails and current_pass},
        "common_gate": {"policy": "Exact Task 11.8.4 12-check order; no lane-specific exception or weakened criterion. Semantic orientation and continuous-surface evidence checks strengthen the existing silhouette/artifact/neutral/material checks and fail closed.", "checks_in_order": COMMON_CHECKS, "checks": checks, "non_human_checks_pass": non_human_pass, "failed_checks": [item["check"] for item in checks if not item["pass"]], "verdict": "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL" if non_human_pass else "FAIL_CLOSED_NON_HUMAN_BLOCKER"},
        "human_approval": {"present": False, "status": "AWAITING_USER_DECISION" if non_human_pass else "NOT_REQUESTED_NON_HUMAN_FAILURE", "asset_hash_bound": False, "candidate_fingerprint_bound": False, "golden_room_reference_hashes_bound": False, "preview_hash_bound": False, "hold_hash_bound": False, "gate_evidence_hash_bound": False, "approved": False},
        "authority": {"metric_plan_remains_sole_authority_for": ["dimensions", "transforms", "placement", "architecture", "openings", "collision", "navigation"], "immutable_plan_derived_camera_contract_remains_camera_authority": True, "world_contract_remains_final_binding_authority": True, "asset_and_evidence_views_are_not_spatial_authority": True},
        "validation": {"validator_path": relative(Path(__file__)), "command": "python .kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a_semantic_surface_evidence.py", "exact_common_gate_order_rerun": True, "strengthened_checks": ["source/geometry-derived semantic yaw contract", "truthful front/right/rear/left label-to-silhouette assignment", "continuous-surface anti-stipple evidence", "neutral key/fill/rim contrast", "held prior preview must fail yaw permutation and stipple checks"], "result": "PASS" if non_human_pass else "FAIL"},
        "preservation": {"task_11_8_4_evidence_modified": False, "prior_task_11_8_4a_candidate_evidence_or_hashes_modified": False, "corrected_glb_or_material_modified": False, "production_code_modified": False, "test_code_modified": False, "ui_or_interface_modified": False, "production_service_or_ownership_modified": False, "replacement_or_qualification_session_created": False, "new_model_download_integration_preflight_or_inference": False, "cloud_used": False, "commit_created": False, "unrelated_worktree_content_modified": False},
        "status_effect": {"task_11_8_4a": "AWAITING_EXPLICIT_USER_APPROVAL" if non_human_pass else "BLOCKED_NON_HUMAN_FAILURE", "task_11_8_4a_complete": False, "task_11_8_5": "BLOCKED", "approval_or_completion_claimed": False},
        "mvp_alignment": "Advances the 6-8 active-coding-hour MVP target: this is the smallest evidence-only renderer/view-contract correction, reuses the unchanged approved candidate, adds no model/tooling/service exploration, and leaves downstream work frozen.",
        "all_hash_bindings": all_bindings,
    }


def validate(record: dict[str, Any]) -> None:
    assert record["schema"] == "unified-world-pipeline.task-11.8.4a.semantic-surface-gate.v1"
    assert record["recliner_uuid"] == UUID and record["source_lane"] == "raw_crop"
    assert record["artifact"]["sha256"] == EXPECTED[ARTIFACT]
    assert record["artifact"]["reused_without_modification"] is True
    assert record["semantic_view_contract"]["semantic_yaws_degrees"] == EXPECTED_SEMANTIC_YAWS
    assert record["semantic_view_contract"]["generator_axes_assumed_semantic"] is False
    assert record["strengthened_evidence_regression"]["held_preview_fails_yaw_label_permutation"] is True
    assert record["strengthened_evidence_regression"]["held_preview_fails_stipple_non_surface_check"] is True
    assert record["strengthened_evidence_regression"]["replacement_passes_both_checks"] is True
    assert record["strengthened_evidence_regression"]["pass"] is True
    assert record["common_gate"]["checks_in_order"] == COMMON_CHECKS
    assert [item["check"] for item in record["common_gate"]["checks"]] == COMMON_CHECKS
    assert all(item["pass"] for item in record["common_gate"]["checks"][:11])
    assert record["common_gate"]["checks"][11]["pass"] is False
    assert record["common_gate"]["failed_checks"] == ["explicit_hash_bound_human_approval"]
    assert record["common_gate"]["verdict"] == "AWAITING_EXPLICIT_HASH_BOUND_HUMAN_APPROVAL"
    assert record["human_approval"]["present"] is False and record["human_approval"]["approved"] is False
    assert record["status_effect"]["task_11_8_4a_complete"] is False
    assert record["status_effect"]["task_11_8_5"] == "BLOCKED"
    assert record["visual_gate_hold"]["explicit_user_artifact_rejection_claimed"] is False
    assert record["artifact"]["inspection"]["durable_material_present"] is True
    assert record["artifact"]["inspection"]["external_image_uris"] == []
    assert record["artifact"]["inspection"]["external_buffer_uris"] == []
    assert all(item["verified"] for item in record["all_hash_bindings"])
    for path, expected in EXPECTED.items():
        assert sha256(path) == expected


def compare(stored: dict[str, Any], observed: dict[str, Any]) -> None:
    for field in ("candidate_binding", "visual_gate_hold", "immutable_corrected_candidate", "golden_room_provenance", "artifact", "semantic_view_contract", "neutral_multi_angle_evidence", "strengthened_evidence_regression", "common_gate", "all_hash_bindings"):
        assert stored[field] == observed[field], field


def main() -> None:
    if not PREVIEW.is_file() or not RENDER_RECORD.is_file():
        raise AssertionError("Run the bounded evidence renderer before validation")
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
    print("PASS Task 11.8.4a semantic continuous-surface targeted validation")
    print(f"  artifact_sha256: {record['artifact']['sha256']}")
    print(f"  preview_sha256: {record['neutral_multi_angle_evidence']['sha256']}")
    print(f"  candidate_fingerprint: {record['candidate_binding']['pre_record_candidate_tree_fingerprint']}")
    print(f"  semantic_yaws: {record['semantic_view_contract']['semantic_yaws_degrees']}")
    print(f"  held_preview_orientation_pass: {record['strengthened_evidence_regression']['held_preview_assessment']['semantic_label_contract_pass']} (required false)")
    print(f"  held_preview_surface_pass: {record['strengthened_evidence_regression']['held_preview_assessment']['continuous_surface_pass']} (required false)")
    print("  non_human_checks: 11/11 PASS")
    print(f"  human_approval: {record['human_approval']['status']}")
    print(f"  evidence: {OUTPUT}")
    print(f"  evidence_sha256: {sha256(OUTPUT)}")


if __name__ == "__main__":
    main()
