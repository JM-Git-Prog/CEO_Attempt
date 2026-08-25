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
