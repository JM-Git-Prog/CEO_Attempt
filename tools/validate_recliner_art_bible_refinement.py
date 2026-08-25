"""Replay validator for a Task 11.8.4c Art-Bible recliner evidence directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

import canon_decomposition_upbge_proof as baseline
import refine_recliner_art_bible as refinement


def compare_inspection(recorded: dict[str, Any], observed: dict[str, Any]) -> None:
    keys = (
        "container", "declared_bytes", "actual_bytes", "binary_chunk_bytes", "buffer_views_in_bounds",
        "node_names", "mesh_names", "node_count", "mesh_count", "primitive_count", "material_count",
        "texture_count", "image_count", "embedded_image_count", "external_buffer_uris", "external_image_uris",
        "trimesh_geometry_count", "independently_loaded",
    )
    drift = {key: {"recorded": recorded.get(key), "observed": observed.get(key)} for key in keys if recorded.get(key) != observed.get(key)}
    if drift:
        raise AssertionError(f"GLB inspection drift: {drift}")


def validate(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    evidence_path = directory / refinement.EVIDENCE_NAME
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    prompts_path = directory / refinement.PROMPTS_NAME
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    if evidence.get("schema") != "unified-world-pipeline.task-11.8.4c.art-bible-recliner-refinement.v1":
        raise AssertionError("Unexpected Task 11.8.4c evidence schema")
    if evidence.get("task") != "11.8.4c":
        raise AssertionError("Task mismatch")
    if evidence.get("result") not in {"PENDING_LOCAL_VISION_SCREEN", "AWAITING_EXPLICIT_HUMAN_REVIEW"}:
        raise AssertionError(f"Evidence is fail-closed or has unexpected state: {evidence.get('result')}")
    if evidence.get("prior_baseline", {}).get("candidate_fingerprint") != refinement.BASELINE_FINGERPRINT:
        raise AssertionError("Immutable baseline fingerprint mismatch")
    if evidence.get("prior_baseline", {}).get("modified_or_relabelled") is not False:
        raise AssertionError("Baseline may not be modified or relabelled")
    for item in evidence["immutable_input_bindings"]:
        path = Path(item["path"])
        expected = item.get("sha256_expected") or item.get("sha256_observed")
        if not path.is_file() or baseline.sha256_file(path) != expected:
            raise AssertionError(f"Immutable input drift: {path}")
    for name, item in evidence["output_bindings"].items():
        path = Path(item["path"])
        if not path.is_file() or baseline.sha256_file(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise AssertionError(f"Output binding drift: {name} -> {path}")
    if baseline.sha256_file(refinement.BASELINE_GLB_PATH) != refinement.BASELINE_GLB_SHA256:
        raise AssertionError("Task 11.8.4b baseline GLB changed")
    if baseline.sha256_file(refinement.BASELINE_PROOF_PATH) != refinement.BASELINE_PROOF_SHA256:
        raise AssertionError("Task 11.8.4b proof changed")
    if baseline.sha256_file(refinement.ART_BIBLE_PATH) != refinement.ART_BIBLE_SHA256:
        raise AssertionError("Art Bible hash mismatch")
    if baseline.sha256_file(refinement.CANON_PATH) != refinement.CANON_SHA256:
        raise AssertionError("Canon hash mismatch")
    observed = baseline.inspect_glb(directory / refinement.OUTPUT_GLB_NAME)
    compare_inspection(evidence["glb_inspection"], observed)
    names = set(observed["node_names"]) | set(observed["mesh_names"])
    missing = sorted(name for name in refinement.REQUIRED_COMPONENTS - {"recliner_root"} if not any(name in candidate for candidate in names))
    if missing:
        raise AssertionError(f"Missing separate components: {missing}")
    if observed["mesh_count"] < 16 or observed["trimesh_geometry_count"] < 16:
        raise AssertionError("Insufficient independently loadable component topology")
    if observed["material_count"] < 4 or observed["embedded_image_count"] < 4:
        raise AssertionError("Durable embedded materials/textures missing")
    if observed["external_image_uris"] or observed["external_buffer_uris"] or not observed["buffer_views_in_bounds"]:
        raise AssertionError("GLB has unresolved or invalid external/buffer references")
    if baseline.sha256_file(directory / refinement.OUTPUT_GLB_NAME) in {refinement.BASELINE_GLB_SHA256, baseline.REJECTED_GLB_SHA256}:
        raise AssertionError("Refined GLB is not new")
    replay_failures = [check["check"] for check in evidence["task_11_8_4b_replay_checks"] if not check["pass"]]
    if replay_failures:
        raise AssertionError(f"Task 11.8.4b replay failures: {replay_failures}")
    gate = evidence["common_standalone_asset_gate"]
    if gate["checks_in_order"] != refinement.COMMON_GATE_ORDER:
        raise AssertionError("Common StandaloneAssetGate order drift")
    non_human_failures = [check["check"] for check in gate["checks"][:-1] if not check["pass"]]
    if non_human_failures:
        raise AssertionError(f"Common non-human gate failures: {non_human_failures}")
    approval = gate["checks"][-1]
    if approval["check"] != "explicit_hash_bound_human_approval" or approval["pass"] is not False:
        raise AssertionError("Human approval must remain pending")
    for filename in ("canon-camera-comparison-contact-sheet.png", "recliner-neutral-multi-angle-sheet.png"):
        path = directory / filename
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width < 1200 or image.height < 490:
                raise AssertionError(f"Review sheet too small: {path} {image.size}")
    expected_fingerprint = refinement.candidate_fingerprint(
        {
            "art_bible": refinement.ART_BIBLE_SHA256,
            "canon": refinement.CANON_SHA256,
            "recliner_cutout": refinement.RECLINER_CUTOUT_SHA256,
            "baseline_fingerprint": refinement.BASELINE_FINGERPRINT,
            "baseline_glb": refinement.BASELINE_GLB_SHA256,
            "baseline_proof": refinement.BASELINE_PROOF_SHA256,
            "baseline_shell": baseline.sha256_file(refinement.BASELINE_SHELL_PATH),
            "baseline_pack": baseline.sha256_file(refinement.BASELINE_PACK_PATH),
            "rejection_record": refinement.REJECTION_SHA256,
            "generator": evidence["execution"]["generator_sha256"],
        },
        {name: item["sha256"] for name, item in evidence["output_bindings"].items()},
    )
    if expected_fingerprint != evidence["candidate_fingerprint"]:
        raise AssertionError("Candidate fingerprint replay mismatch")
    if refinement.prompt_fingerprint(prompts) != evidence["prompt_fingerprint"]:
        raise AssertionError("Prompt fingerprint replay mismatch")
    vision_path = directory / "local-vision-screen.json"
    vision_status = "NOT_PRESENT"
    if vision_path.is_file():
        vision = json.loads(vision_path.read_text(encoding="utf-8"))
        if vision.get("candidate_fingerprint") != evidence["candidate_fingerprint"]:
            raise AssertionError("Local vision screen candidate mismatch")
        for screen in vision.get("screens", []):
            path = Path(screen["path"])
            if not path.is_file() or baseline.sha256_file(path) != screen["sha256"]:
                raise AssertionError(f"Local vision screen image drift: {path}")
        vision_status = vision.get("overall", "UNKNOWN")
    return {
        "result": "PASS",
        "evidence_path": str(evidence_path),
        "evidence_sha256": baseline.sha256_file(evidence_path),
        "candidate_fingerprint": evidence["candidate_fingerprint"],
        "glb_sha256": baseline.sha256_file(directory / refinement.OUTPUT_GLB_NAME),
        "review_sheet_hashes": {
            filename: baseline.sha256_file(directory / filename)
            for filename in ("canon-camera-comparison-contact-sheet.png", "recliner-neutral-multi-angle-sheet.png")
        },
        "local_vision_status": vision_status,
        "human_gate": "AWAITING_EXPLICIT_HUMAN_REVIEW" if evidence["result"] == "AWAITING_EXPLICIT_HUMAN_REVIEW" else "PENDING_LOCAL_VISION_SCREEN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.evidence_directory), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
