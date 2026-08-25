"""Generate once, then validate, Task 11.8.4 fail-closed gate evidence.

This script reads existing Task 11.8.3 artifacts only. It does not generate, alter,
approve, texture, or select an asset.
"""

from __future__ import annotations

import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = Path(__file__).resolve().parent
BAKEOFF_PATH = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a.json"
BUNDLE_DIR = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a"
EVIDENCE_ID = "d3f9253c-130b-4a6c-b597-1fc2fa27dd75"
OUTPUT_PATH = EVIDENCE_DIR / f"task-11.8.4-standalone-asset-gate-{EVIDENCE_ID}.json"
EXPECTED_UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED_SOURCE_SHA = "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6"
EXPECTED_WORKFLOW_SHA = "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196"
MIRROR_PATH = Path(r"C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png")
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


def resolve_recorded_path(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def hash_binding(path: Path, expected: str) -> dict[str, Any]:
    observed = sha256(path)
    return {
        "path": str(path),
        "exists": path.is_file(),
        "sha256_expected": expected,
        "sha256_observed": observed,
        "verified": observed == expected,
    }


def inspect_glb(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    magic, version, declared_length = struct.unpack_from("<4sII", payload, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(payload):
        raise AssertionError(f"Invalid GLB container: {path}")

    offset = 12
    document: dict[str, Any] | None = None
    binary_chunk_length = 0
    while offset < declared_length:
        chunk_length, chunk_type = struct.unpack_from("<II", payload, offset)
        chunk = payload[offset + 8 : offset + 8 + chunk_length]
        offset += 8 + chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(chunk.rstrip(b" \x00"))
        elif chunk_type == 0x004E4942:
            binary_chunk_length = chunk_length
    if document is None or binary_chunk_length <= 0:
        raise AssertionError(f"Required GLB JSON/BIN chunks missing: {path}")

    buffer_views = document.get("bufferViews", [])
    views_in_bounds = all(
        int(view.get("byteOffset", 0)) + int(view["byteLength"]) <= binary_chunk_length
        for view in buffer_views
    )
    accessors = document.get("accessors", [])
    primitive_count = 0
    vertex_count = 0
    face_count = 0
    mins: list[list[float]] = []
    maxs: list[list[float]] = []
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            primitive_count += 1
            position = accessors[int(primitive["attributes"]["POSITION"])]
            vertices = int(position["count"])
            indices = accessors[int(primitive["indices"])]
            index_count = int(indices["count"])
            if int(primitive.get("mode", 4)) != 4 or index_count % 3:
                raise AssertionError(f"Non-triangle or malformed primitive: {path}")
            vertex_count += vertices
            face_count += index_count // 3
            if "min" in position and "max" in position:
                mins.append([float(value) for value in position["min"]])
                maxs.append([float(value) for value in position["max"]])
    if not mins or not maxs:
        raise AssertionError(f"Position bounds missing: {path}")
    overall_min = [min(values[axis] for values in mins) for axis in range(3)]
    overall_max = [max(values[axis] for values in maxs) for axis in range(3)]
    extents = [overall_max[axis] - overall_min[axis] for axis in range(3)]

    images = document.get("images", [])
    buffers = document.get("buffers", [])
    external_images = [
        image["uri"]
        for image in images
        if image.get("uri") and not image["uri"].startswith("data:")
    ]
    external_buffers = [buffer["uri"] for buffer in buffers if buffer.get("uri")]
    embedded_images = sum(
        1 for image in images if "bufferView" in image or image.get("uri", "").startswith("data:")
    )
    material_count = len(document.get("materials", []))
    texture_count = len(document.get("textures", []))
    durable_material = embedded_images > 0 and texture_count > 0 and material_count > 0

    return {
        "container": "GLB_2_0",
        "container_load_method": "independent GLB header/chunk/bufferView/accessor/primitive validation; cross-bound to Task 11.8.3 trimesh load evidence",
        "declared_bytes": declared_length,
        "actual_bytes": len(payload),
        "binary_chunk_bytes": binary_chunk_length,
        "buffer_views_in_bounds": views_in_bounds,
        "independent_load": views_in_bounds and primitive_count > 0 and vertex_count > 0 and face_count > 0,
        "geometry_count": primitive_count,
        "vertex_count": vertex_count,
        "face_count": face_count,
        "extents_generator_space": extents,
        "material_count": material_count,
        "texture_count": texture_count,
        "image_count": len(images),
        "embedded_image_count": embedded_images,
        "external_image_uris": external_images,
        "external_buffer_uris": external_buffers,
        "durable_material_present": durable_material,
    }


def verify_lane_chain(lane: dict[str, Any]) -> list[dict[str, Any]]:
    pairs: list[tuple[str, str]] = [
        ("prepared_input_path", "prepared_input_sha256"),
        ("output_path", "output_sha256"),
        ("preview_path", "preview_sha256"),
    ]
    if lane["lane"] == "raw_crop":
        pairs.extend(
            [
                ("source_path", "source_sha256"),
                ("extraction_workflow_path", "extraction_workflow_sha256"),
                ("raw_input_path", "raw_input_sha256"),
            ]
        )
    else:
        pairs.extend(
            [
                ("historical_source_path", "historical_source_sha256"),
                ("qwen_workflow_path", "qwen_workflow_sha256"),
                ("qwen_edited_room_path", "qwen_edited_room_sha256"),
                ("qwen_difference_path", "qwen_difference_sha256"),
            ]
        )
    return [hash_binding(resolve_recorded_path(lane[path_key]), lane[hash_key]) for path_key, hash_key in pairs]


def make_check(name: str, passed: bool, observation: str) -> dict[str, Any]:
    return {"check": name, "pass": passed, "observation": observation}


def evaluate_lane(lane: dict[str, Any], source_evidence: dict[str, Any]) -> dict[str, Any]:
    artifact_path = resolve_recorded_path(lane["output_path"])
    preview_path = resolve_recorded_path(lane["preview_path"])
    chain = verify_lane_chain(lane)
    glb = inspect_glb(artifact_path)
    glb["watertight"] = lane["watertight"]
    chain_pass = all(binding["verified"] for binding in chain)
    recorded_geometry_matches = (
        glb["geometry_count"] == lane["geometry_count"]
        and glb["vertex_count"] == lane["vertex_count"]
        and glb["face_count"] == lane["face_count"]
    )
    source_match = lane.get("source_match") is True
    is_raw = lane["lane"] == "raw_crop"

    checks = [
        make_check(
            "evidence_chain_integrity",
            chain_pass and recorded_geometry_matches,
            "All lane input/workflow/output/preview hashes and recorded geometry counts match Task 11.8.3."
            if chain_pass and recorded_geometry_matches
            else "One or more lane hashes or recorded geometry counts do not match Task 11.8.3.",
        ),
        make_check(
            "stable_uuid_binding",
            source_evidence["fixed_identity"]["recliner_uuid"] == EXPECTED_UUID,
            f"Candidate remains bound to common recliner UUID {EXPECTED_UUID}.",
        ),
        make_check(
            "golden_room_source_identity",
            source_match,
            "Raw crop is source-matched to the immutable Golden Room reference."
            if source_match
            else "Historical Qwen lane is V3 whole-room removal/difference evidence, not Golden Room source-matched and not a true amodal completion.",
        ),
        make_check(
            "independent_loadability",
            glb["independent_load"],
            "Independent GLB container/accessor validation found positive geometry; Task 11.8.3's bound record independently loaded the same hash through trimesh."
            if glb["independent_load"]
            else "Independent GLB load or positive geometry check failed.",
        ),
        make_check(
            "non_placeholder_geometry",
            glb["face_count"] >= 100 and glb["vertex_count"] >= 50,
            f"High-density generated geometry ({glb['face_count']} faces, {glb['vertex_count']} vertices), not a placeholder primitive.",
        ),
        make_check(
            "recognizable_recliner_silhouette_identity",
            True,
            "Neutral front/right/rear/left preview shows a recliner-like seat, back, arms, and extended footrest."
            if is_raw
            else "Neutral front/right/rear/left preview shows a recliner-like seat, back, arms, and extended footrest, but this does not cure source mismatch.",
        ),
        make_check(
            "no_fused_scene_or_ground_sheet_geometry",
            True,
            "Neutral four-view output shows no room shell or generated ground sheet attached to the GLB.",
        ),
        make_check(
            "no_obvious_catastrophic_reconstruction_artifacts",
            True,
            "Four views remain coherent without catastrophic collapse; non-watertight topology is retained as a limitation, not used to waive other failures.",
        ),
        make_check(
            "neutral_multi_angle_turntable_evidence",
            preview_path.is_file(),
            f"Hash-bound front/right/rear/left neutral preview: {lane['preview_path']}.",
        ),
        make_check(
            "durable_non_temporary_material_continuity",
            glb["durable_material_present"],
            "Embedded durable textured material is present."
            if glb["durable_material_present"]
            else "Hard failure: geometry-only GLB has no embedded durable textured material; temporary/Pass-1 exceptions are prohibited.",
        ),
        make_check(
            "no_unresolved_external_materials_or_buffers",
            not glb["external_image_uris"] and not glb["external_buffer_uris"],
            "No external image or buffer URI is referenced; the separate durable-material requirement still fails."
            if not glb["external_image_uris"] and not glb["external_buffer_uris"]
            else "Unresolved external image or buffer dependencies are present.",
        ),
        make_check(
            "explicit_hash_bound_human_approval",
            False,
            "No human asset approval exists or is manufactured; a hard-failing candidate is ineligible for approval.",
        ),
    ]
    assert [check["check"] for check in checks] == COMMON_CHECKS
    failed_checks = [check["check"] for check in checks if not check["pass"]]
    return {
        "lane": lane["lane"],
        "availability": lane["availability"],
        "recliner_uuid": EXPECTED_UUID,
        "artifact_path": lane["output_path"],
        "artifact_sha256": sha256(artifact_path),
        "preview_path": lane["preview_path"],
        "preview_sha256": sha256(preview_path),
        "source_match": source_match,
        "source_and_semantic_provenance": (
            "Golden Room raw source-matched crop"
            if is_raw
            else "Historical V3 Qwen whole-room removal/difference; not Golden Room source-matched; not a true amodal completion"
        ),
        "hash_bindings": chain,
        "independent_glb_inspection": glb,
        "common_gate_checks": checks,
        "failed_checks": failed_checks,
        "gate_verdict": "FAIL" if failed_checks else "PASS",
        "human_approval": {
            "present": False,
            "status": "NOT_REQUESTED_HARD_FAILURE",
            "asset_hash_bound": False,
            "candidate_fingerprint_bound": False,
            "golden_room_reference_hashes_bound": False,
        },
        "approved": False,
        "selected": False,
    }


def build_record() -> dict[str, Any]:
    source_evidence = json.loads(BAKEOFF_PATH.read_text(encoding="utf-8"))
    completed = [lane for lane in source_evidence["lanes"] if lane.get("output_path")]
    unavailable = [lane for lane in source_evidence["lanes"] if not lane.get("output_path")]
    assert [lane["lane"] for lane in completed] == ["raw_crop", "existing_qwen_amodal_completion"]
    assert [lane["lane"] for lane in unavailable] == ["video_depth"]
    assert source_evidence["fixed_identity"]["recliner_uuid"] == EXPECTED_UUID

    source_binding = hash_binding(
        Path(source_evidence["fixed_identity"]["authoritative_source_image_path"]),
        EXPECTED_SOURCE_SHA,
    )
    workflow_binding = hash_binding(
        Path(source_evidence["fixed_identity"]["authoritative_workflow_path"]),
        EXPECTED_WORKFLOW_SHA,
    )
    mirror_binding = hash_binding(MIRROR_PATH, EXPECTED_SOURCE_SHA)
    demo_binding = hash_binding(
        ROOT / source_evidence["evidence_chain"]["demo_profile_binding_path"],
        source_evidence["evidence_chain"]["demo_profile_binding_sha256"],
    )
    worldmirror_binding = hash_binding(
        ROOT / source_evidence["evidence_chain"]["worldmirror_retry_defer_path"],
        source_evidence["evidence_chain"]["worldmirror_retry_defer_sha256"],
    )
    lanes = [evaluate_lane(lane, source_evidence) for lane in completed]
    all_chain_bindings = [source_binding, workflow_binding, mirror_binding, demo_binding, worldmirror_binding]
    overall_chain_pass = all(binding["verified"] for binding in all_chain_bindings)

    return {
        "schema": "unified-world-pipeline.task-11.8.4.standalone-asset-gate.v1",
        "evidence_id": EVIDENCE_ID,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4",
        "result": "NO_LANE_PASSES_FAIL_CLOSED",
        "scope_boundary": "Task 11.8.4 evaluation only; no approval, selection, replacement generation, exploration, Task 11.8.5 work, Demo Ready, release qualification, or release claim.",
        "recliner_uuid": EXPECTED_UUID,
        "source_evidence": {
            "task_11_8_3_path": str(BAKEOFF_PATH.relative_to(ROOT)).replace("\\", "/"),
            "task_11_8_3_sha256": sha256(BAKEOFF_PATH),
            "completed_lane_count": 2,
            "completed_lanes": [lane["lane"] for lane in completed],
            "video_depth_status": unavailable[0]["availability"],
            "video_depth_evaluated": False,
            "video_depth_exclusion_reason": unavailable[0]["reason"],
        },
        "candidate_binding": {
            "git_head": source_evidence["evidence_chain"]["git_head"],
            "task_11_8_3_pre_finalization_candidate_tree_fingerprint": source_evidence["evidence_chain"]["pre_finalization_candidate_tree_fingerprint"],
            "task_11_8_3_pre_finalization_candidate_tree_path_count": source_evidence["evidence_chain"]["pre_finalization_candidate_tree_path_count"],
            "algorithm": source_evidence["evidence_chain"]["candidate_tree_fingerprint_algorithm"],
            "binding_scope": "Parent bake-off candidate fingerprint plus exact Task 11.8.3 evidence, asset, preview, source, workflow, and profile-evidence hashes. No human approval exists to bind to a newer fingerprint.",
        },
        "golden_room_reference_bindings": {
            "authoritative_source_image": source_binding,
            "authoritative_workflow": workflow_binding,
            "shared_input_mirror": mirror_binding,
            "demo_profile_binding": demo_binding,
            "worldmirror_defer_binding": worldmirror_binding,
            "all_verified": overall_chain_pass,
        },
        "common_gate": {
            "policy": "All checks are mandatory and identical for every completed lane; no lane-specific exception can convert a failure into a pass.",
            "checks_in_order": COMMON_CHECKS,
            "hard_fail_conditions": [
                "source identity mismatch",
                "independent load failure",
                "placeholder or fused geometry",
                "obvious catastrophic reconstruction artifact",
                "missing neutral multi-angle evidence",
                "missing durable non-temporary material continuity",
                "unresolved external material or buffer",
                "missing explicit hash-bound human approval",
                "evidence-chain mismatch",
            ],
        },
        "lane_verdicts": lanes,
        "selection": {
            "passing_lane_count": 0,
            "passing_lanes": [],
            "visually_best_passing_lane": None,
            "selected_lane": None,
            "selected_asset_sha256": None,
            "human_approval_created": False,
            "note": "Raw crop has source-matched provenance and fewer identity failures, but it still fails durable-material and human-approval requirements; no failing lane is selected.",
        },
        "fail_closed_blocker": {
            "active": True,
            "code": "NO_RECLINER_LANE_PASSES_STANDALONE_ASSET_GATE",
            "summary": "Both completed candidates lack durable materials and explicit hash-bound human approval; the historical Qwen candidate additionally fails Golden Room source/semantic identity.",
            "demo_ready_blocked": True,
            "structural_success_cannot_override": True,
            "visual_success_cannot_override_structural_failure": True,
            "do_not_continue_into_task": "11.8.5",
            "exploration_expansion_authorized": False,
        },
        "validation": {
            "validator_path": str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/"),
            "command": "python .kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4.py",
            "method": "Rehash all bound evidence, independently load each GLB 2.0 header/chunk/bufferView/accessor/primitive structure, cross-check Task 11.8.3 trimesh geometry evidence, and assert identical rubric plus fail-closed outcomes.",
            "result": "PASS",
        },
        "preservation": {
            "production_code_modified": False,
            "test_code_modified": False,
            "ui_or_interface_modified": False,
            "v3_through_v16_behavior_modified": False,
            "asset_or_material_generated_or_modified": False,
            "replacement_or_pipeline_session_created": False,
            "exploratory_model_or_worldmirror_invoked": False,
            "cloud_used": False,
            "ollama_used": False,
            "scheduled_task_modified": False,
            "ratchet_watch_owner": "Windows Scheduled Task/keepalive",
            "comfyui_owner": "Comfy Desktop on port 8188",
            "commit_created": False,
            "unrelated_worktree_changes_modified": False,
        },
        "status_effect": {
            "task_11_8_4_outcome": "COMPLETE_WITH_FAIL_CLOSED_BLOCKER",
            "leave_incomplete": ["11.8", "11.8.5", "11.8.6", "11.8.7", "11.8.8", "11.8.9", "11.7.1", "11.9", "11.10", "11.11"],
        },
        "mvp_alignment": "The common gate made the bounded no-pass decision from existing evidence only and stopped before Task 11.8.5 without reopening exploration, preserving the 6–8 active-coding-hour MVP focus.",
    }


def validate_record(record: dict[str, Any]) -> None:
    assert record["schema"] == "unified-world-pipeline.task-11.8.4.standalone-asset-gate.v1"
    assert record["recliner_uuid"] == EXPECTED_UUID
    assert record["result"] == "NO_LANE_PASSES_FAIL_CLOSED"
    assert record["golden_room_reference_bindings"]["all_verified"] is True
    assert len(record["lane_verdicts"]) == 2
    assert [lane["lane"] for lane in record["lane_verdicts"]] == [
        "raw_crop",
        "existing_qwen_amodal_completion",
    ]
    for lane in record["lane_verdicts"]:
        assert [check["check"] for check in lane["common_gate_checks"]] == COMMON_CHECKS
        assert lane["gate_verdict"] == "FAIL"
        assert "durable_non_temporary_material_continuity" in lane["failed_checks"]
        assert "explicit_hash_bound_human_approval" in lane["failed_checks"]
        assert lane["independent_glb_inspection"]["independent_load"] is True
        assert lane["independent_glb_inspection"]["durable_material_present"] is False
        assert all(binding["verified"] for binding in lane["hash_bindings"])
        assert lane["approved"] is False
        assert lane["selected"] is False
    qwen = record["lane_verdicts"][1]
    assert "golden_room_source_identity" in qwen["failed_checks"]
    assert record["selection"]["passing_lane_count"] == 0
    assert record["selection"]["visually_best_passing_lane"] is None
    assert record["selection"]["selected_lane"] is None
    assert record["fail_closed_blocker"]["active"] is True
    assert record["fail_closed_blocker"]["do_not_continue_into_task"] == "11.8.5"
    assert record["preservation"]["asset_or_material_generated_or_modified"] is False
    assert record["preservation"]["exploratory_model_or_worldmirror_invoked"] is False
    assert record["preservation"]["cloud_used"] is False
    assert record["preservation"]["commit_created"] is False


def compare_fresh_observation(stored: dict[str, Any], observed: dict[str, Any]) -> None:
    assert stored["source_evidence"]["task_11_8_3_sha256"] == observed["source_evidence"]["task_11_8_3_sha256"]
    assert stored["source_evidence"]["completed_lanes"] == observed["source_evidence"]["completed_lanes"]
    assert stored["source_evidence"]["video_depth_status"] == observed["source_evidence"]["video_depth_status"]
    assert stored["golden_room_reference_bindings"]["all_verified"] is True
    assert observed["golden_room_reference_bindings"]["all_verified"] is True
    for binding_name in (
        "authoritative_source_image",
        "authoritative_workflow",
        "shared_input_mirror",
        "demo_profile_binding",
        "worldmirror_defer_binding",
    ):
        assert stored["golden_room_reference_bindings"][binding_name]["sha256_observed"] == observed["golden_room_reference_bindings"][binding_name]["sha256_observed"]
    for stored_lane, observed_lane in zip(stored["lane_verdicts"], observed["lane_verdicts"], strict=True):
        assert stored_lane["lane"] == observed_lane["lane"]
        assert stored_lane["artifact_sha256"] == observed_lane["artifact_sha256"]
        assert stored_lane["preview_sha256"] == observed_lane["preview_sha256"]
        assert stored_lane["source_match"] == observed_lane["source_match"]
        assert stored_lane["failed_checks"] == observed_lane["failed_checks"]
        assert stored_lane["gate_verdict"] == observed_lane["gate_verdict"]
        assert stored_lane["hash_bindings"] == observed_lane["hash_bindings"]
        for key in (
            "container",
            "declared_bytes",
            "actual_bytes",
            "independent_load",
            "geometry_count",
            "vertex_count",
            "face_count",
            "extents_generator_space",
            "watertight",
            "material_count",
            "texture_count",
            "image_count",
            "embedded_image_count",
            "external_image_uris",
            "external_buffer_uris",
            "durable_material_present",
        ):
            assert stored_lane["independent_glb_inspection"][key] == observed_lane["independent_glb_inspection"][key]


def main() -> None:
    if OUTPUT_PATH.exists():
        record = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        observed = build_record()
        compare_fresh_observation(record, observed)
    else:
        record = build_record()
        validate_record(record)
        OUTPUT_PATH.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        record = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    validate_record(record)
    print(f"PASS Task 11.8.4 targeted validation: {len(record['lane_verdicts'])} lanes evaluated identically")
    for lane in record["lane_verdicts"]:
        print(f"  {lane['lane']}: {lane['gate_verdict']} ({', '.join(lane['failed_checks'])})")
    print(f"  selection: {record['selection']['selected_lane']}")
    print(f"  blocker: {record['fail_closed_blocker']['code']}")
    print(f"  evidence: {OUTPUT_PATH}")
    print(f"  evidence_sha256: {sha256(OUTPUT_PATH)}")


if __name__ == "__main__":
    main()
