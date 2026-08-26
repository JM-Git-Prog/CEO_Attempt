"""Replay validation for a Task 11.8.4b Canon-decomposition proof directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from PIL import Image

import canon_decomposition_upbge_proof as proof


def compare_glb(recorded: dict[str, Any], observed: dict[str, Any], label: str) -> None:
    keys = (
        "container",
        "declared_bytes",
        "actual_bytes",
        "binary_chunk_bytes",
        "buffer_views_in_bounds",
        "node_names",
        "mesh_names",
        "node_count",
        "mesh_count",
        "primitive_count",
        "material_count",
        "texture_count",
        "image_count",
        "embedded_image_count",
        "external_buffer_uris",
        "external_image_uris",
        "trimesh_geometry_count",
        "independently_loaded",
    )
    mismatches = {key: {"recorded": recorded.get(key), "observed": observed.get(key)} for key in keys if recorded.get(key) != observed.get(key)}
    if mismatches:
        raise AssertionError(f"{label} GLB inspection drift: {mismatches}")


def _iter_file_bindings(value: Any, label: str = "root") -> list[tuple[str, dict[str, Any]]]:
    bindings: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        if "path" in value and ("sha256_observed" in value or "sha256" in value):
            bindings.append((label, value))
        for key, child in value.items():
            bindings.extend(_iter_file_bindings(child, f"{label}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            bindings.extend(_iter_file_bindings(child, f"{label}[{index}]"))
    return bindings


def validate_reference_lock(reference_path: Path) -> dict[str, Any]:
    """Independently reopen and rehash one successful Task 3.1 references.json."""
    if reference_path.is_symlink() or not reference_path.is_file():
        raise AssertionError(f"references.json is not a regular non-symlink file: {reference_path}")
    lock = json.loads(reference_path.read_text(encoding="utf-8"))
    if lock.get("schema") != "recliner-canon-visual-refinement-fix.references/v1":
        raise AssertionError("Unexpected references.json schema")
    if lock.get("state") != "INITIALIZE_REFERENCES":
        raise AssertionError("references.json state mismatch")
    recorded_lock_hash = str(lock.get("lock_sha256", ""))
    unsigned = dict(lock)
    unsigned.pop("lock_sha256", None)
    if recorded_lock_hash != proof._canonical_hash(unsigned):
        raise AssertionError("references.json canonical lock hash mismatch")

    observed_references = proof.verify_reference_specs()
    if lock.get("references") != observed_references:
        raise AssertionError("Locked Canon/empty-twin reference records drifted")

    rehashed = 0
    for label, binding in _iter_file_bindings(lock):
        raw_path = Path(str(binding["path"]))
        path = raw_path if raw_path.is_absolute() else proof.ROOT / raw_path
        if path.is_symlink() or not path.is_file():
            raise AssertionError(f"Locked file is missing, non-regular, or symlinked: {label} -> {path}")
        observed_hash = proof.sha256_file(path)
        expected_hash = binding.get("sha256_observed", binding.get("sha256"))
        if observed_hash != expected_hash:
            raise AssertionError(f"Locked file hash drift: {label} -> {path}")
        if binding.get("bytes") is not None and path.stat().st_size != binding["bytes"]:
            raise AssertionError(f"Locked file byte-count drift: {label} -> {path}")
        rehashed += 1

    inventory = lock.get("inventory", {})
    selected = proof.load_selected_manifest(proof.SELECTED_MANIFEST_PATH)
    if selected["manifest_sha256"] != inventory.get("manifest_sha256"):
        raise AssertionError("Selected manifest hash does not match references.json")
    selected_ids = list(selected["selected_plan_instance_ids"])
    if selected_ids != inventory.get("selected_plan_instance_ids"):
        raise AssertionError("Selected Plan UUID order/set drifted")
    if inventory.get("stable_uuid_counts") != dict(sorted(__import__("collections").Counter(selected_ids).items())):
        raise AssertionError("Selected Plan UUID counts drifted")
    if any(item.get("observation_authority") is not False for item in selected["objects"]):
        raise AssertionError("Segmentation observation was promoted to identity authority")

    decomposition = json.loads(proof.DECOMPOSITION_PACK_PATH.read_text(encoding="utf-8"))
    observed_decomposition = proof.validate_decomposition_authority(decomposition)
    if inventory.get("decomposition", {}).get("authority_validation") != observed_decomposition:
        raise AssertionError("Decomposition/isolation authority validation drifted")

    world_payload = json.loads(proof.WORLD_CONTRACT_PATH.read_text(encoding="utf-8"))
    world = proof.WorldContract.from_dict(world_payload)
    if not proof.verify_hash(world):
        raise AssertionError("WorldContract hash is invalid during independent replay")
    camera = proof.CameraContract.from_dict(world_payload["camera"])
    recorded_camera = lock.get("authorities", {}).get("camera_contract", {})
    if recorded_camera.get("fields") != camera.to_dict() or recorded_camera.get("sha256") != camera.compute_hash():
        raise AssertionError("CameraContract fields/hash drifted")

    assets = lock.get("assets")
    if not isinstance(assets, list) or {item.get("object_id") for item in assets} != set(selected_ids):
        raise AssertionError("Approved asset UUID set drifted")
    if any(not item.get("generator") or "placeholder" in str(item["generator"]).casefold() for item in assets):
        raise AssertionError("Placeholder or missing asset provenance detected")
    if lock.get("source", {}).get("repository") != proof.repository_fingerprint():
        raise AssertionError("Source/working-tree fingerprint drifted")
    browser = lock.get("toolchain", {}).get("browser", {})
    if browser.get("version") != "strict-canonical-worldcontract-to-threejs/v1":
        raise AssertionError("Browser compiler version binding is absent or drifted")

    return {
        "result": "PASS",
        "state": "INITIALIZE_REFERENCES",
        "references_path": str(reference_path),
        "references_sha256": proof.sha256_file(reference_path),
        "lock_sha256": recorded_lock_hash,
        "rehashed_file_bindings": rehashed,
        "object_count": len(selected_ids),
    }


def validate_reference_initialization(directory: Path) -> dict[str, Any]:
    """Validate either a successful lock or an exact fail-closed 3.1 checkpoint."""
    directory = directory.resolve()
    reference_path = directory / "references.json"
    if reference_path.exists():
        return validate_reference_lock(reference_path)
    checkpoint_path = directory / "checkpoint.json"
    if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
        raise AssertionError("Neither references.json nor a regular failure checkpoint exists")
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    recorded_hash = str(checkpoint.get("checkpoint_sha256", ""))
    unsigned = dict(checkpoint)
    unsigned.pop("checkpoint_sha256", None)
    if recorded_hash != proof._canonical_hash(unsigned):
        raise AssertionError("INITIALIZE_REFERENCES checkpoint hash mismatch")
    if (
        checkpoint.get("state") != "INITIALIZE_REFERENCES"
        or checkpoint.get("result") != "FAILED"
        or checkpoint.get("references_json_written") is not False
        or any(checkpoint.get(key) is not False for key in ("calibration_written", "candidate_written", "score_written"))
    ):
        raise AssertionError("Failure checkpoint permits output or later-stage progression")
    recorded_detail = checkpoint.get("first_failure", {}).get("detail")
    try:
        proof.build_reference_lock()
    except proof.ReferenceLockError as error:
        if str(error) != recorded_detail:
            raise AssertionError(
                f"INITIALIZE_REFERENCES blocker drift: recorded={recorded_detail!r}, observed={str(error)!r}"
            ) from error
    else:
        raise AssertionError("Recorded INITIALIZE_REFERENCES blocker no longer reproduces")
    forbidden_names = {"calibration-manifest.json", "candidate.png", "score.json"}
    unexpected = sorted(path.name for path in directory.rglob("*") if path.is_file() and path.name in forbidden_names)
    if unexpected:
        raise AssertionError(f"Blocked initialization wrote later-stage output: {unexpected}")
    return {
        "result": "BLOCKED",
        "state": "INITIALIZE_REFERENCES",
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": proof.sha256_file(checkpoint_path),
        "first_failure": recorded_detail,
        "references_json_written": False,
        "later_subtasks_eligible": False,
    }


def validate(directory: Path) -> dict[str, Any]:
    directory = directory.resolve()
    evidence_path = directory / "proof-evidence.json"
    pack_path = directory / "canon-decomposition-pack.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    if evidence.get("schema") != "unified-world-pipeline.task-11.8.4b.canon-decomposition-deterministic-proof.v1":
        raise AssertionError("Unexpected evidence schema")
    if evidence.get("task") != "11.8.4b":
        raise AssertionError("Evidence task mismatch")
    if evidence.get("result") != "AWAITING_EXPLICIT_HUMAN_REVIEW":
        raise AssertionError(f"Proof is not eligible for human review: {evidence.get('result')}")
    if evidence.get("failed_non_human_checks"):
        raise AssertionError(f"Recorded non-human failures: {evidence['failed_non_human_checks']}")
    if evidence.get("human_review", {}).get("approved") is not False:
        raise AssertionError("Human approval must remain false until explicit later review")

    for binding in evidence["immutable_input_bindings"]:
        path = Path(binding["path"])
        expected = binding["sha256_expected"]
        if not path.is_file() or proof.sha256_file(path) != expected:
            raise AssertionError(f"Immutable input drift: {path}")

    for name, binding in evidence["output_bindings"].items():
        path = Path(binding["path"])
        if not path.is_file() or proof.sha256_file(path) != binding["sha256"] or path.stat().st_size != binding["bytes"]:
            raise AssertionError(f"Output binding drift: {name} -> {path}")

    pack_checks = proof.validate_pack(pack)
    failed_pack = [check["check"] for check in pack_checks if not check["pass"]]
    if failed_pack:
        raise AssertionError(f"Pack validation failed: {failed_pack}")

    recliner_path = directory / "deterministic-recliner.glb"
    shell_path = directory / "deterministic-empty-room-shell.glb"
    observed_recliner = proof.inspect_glb(recliner_path)
    observed_shell = proof.inspect_glb(shell_path)
    compare_glb(evidence["glb_inspection"]["recliner"], observed_recliner, "recliner")
    compare_glb(evidence["glb_inspection"]["empty_room_shell"], observed_shell, "shell")

    names = set(observed_recliner["node_names"]) | set(observed_recliner["mesh_names"])
    missing_components = sorted(name for name in proof.REQUIRED_COMPONENTS - {"recliner_root"} if not any(name in candidate for candidate in names))
    if missing_components:
        raise AssertionError(f"Missing separate recliner components: {missing_components}")
    if observed_recliner["mesh_count"] < 10 or observed_recliner["trimesh_geometry_count"] < 10:
        raise AssertionError("Recliner is not represented by enough independently loadable component meshes")
    if observed_recliner["embedded_image_count"] < 3 or observed_recliner["external_image_uris"] or observed_recliner["external_buffer_uris"]:
        raise AssertionError("Recliner material/image/buffer embedding is not durable and self-contained")
    if proof.sha256_file(recliner_path) == proof.REJECTED_GLB_SHA256:
        raise AssertionError("New recliner unexpectedly matches rejected candidate")
    if proof.sha256_file(proof.REJECTED_GLB_PATH) != proof.REJECTED_GLB_SHA256:
        raise AssertionError("Rejected candidate bytes changed")

    pngs = (
        directory / "canon-camera-comparison-contact-sheet.png",
        directory / "recliner-neutral-multi-angle-sheet.png",
    )
    dimensions = {}
    for path in pngs:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            dimensions[path.name] = list(image.size)
            if image.width < 1000 or image.height < 450:
                raise AssertionError(f"Review sheet too small: {path} {image.size}")

    return {
        "result": "PASS",
        "evidence_path": str(evidence_path),
        "evidence_sha256": proof.sha256_file(evidence_path),
        "candidate_fingerprint": evidence["candidate_fingerprint"],
        "pack_checks": pack_checks,
        "recliner_sha256": proof.sha256_file(recliner_path),
        "shell_sha256": proof.sha256_file(shell_path),
        "review_png_dimensions": dimensions,
        "human_gate": "AWAITING_EXPLICIT_HUMAN_REVIEW",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proof_directory", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(validate(args.proof_directory), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
