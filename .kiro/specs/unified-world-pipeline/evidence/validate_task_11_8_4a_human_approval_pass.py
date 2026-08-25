"""Validate the append-only Task 11.8.4a exact hash-bound human approval."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = Path(__file__).resolve().parent
EVIDENCE_ID = "ac67e3f0-9c19-44fa-9eed-e822f9e82515"
EVIDENCE = EVIDENCE_DIR / f"task-11.8.4a-human-approval-pass-{EVIDENCE_ID}.json"
CANDIDATE = EVIDENCE_DIR / "task-11.8.4a-approval-candidate-additional-03-7c9f6b25-130e-4f47-838c-4cecd86f6d34.json"
CANDIDATE_VALIDATOR = EVIDENCE_DIR / "validate_task_11_8_4a_additional_approval_candidate.py"
BASE_VALIDATOR = EVIDENCE_DIR / "validate_task_11_8_4a_semantic_surface_evidence.py"
TASKS = ROOT / ".kiro/specs/unified-world-pipeline/tasks.md"
ARTIFACT = EVIDENCE_DIR / "task-11.8.4a-continuity-corrected-raw-crop-recliner-3876cc8a-81a2-4bba-9da0-185ba59db002/recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
PREVIEW = EVIDENCE_DIR / "task-11.8.4a-additional-03-edge-preserving-denoise-c858e5e3-7968-40ee-b8e5-b54f1c073911/recliner-raw-crop_additional-03-edge-preserving-denoise-eight-panel.png"

EXPECTED = {
    "artifact_sha256": "4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf",
    "preview_sha256": "9865be16e82e383f12f5475574d48636d536a3b825de95c9d6ccbcd27a2000d7",
    "approved_candidate_fingerprint": "6b8a2b6b25e2cbc6e6b674ef037e95d3339584eefb83e6b3350b2f7da8d28baf",
    "candidate_evidence_sha256": "09b48cea36bce340667a3a185bf7727011f3f44793a5ddb3d21c0c5d96234b41",
    "golden_source_sha256": "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    "workflow_sha256": "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196",
    "extraction_workflow_sha256": "362dea52c21418717e919d9ea942f74a9016dd38088ec618660c21f74f2f37af",
    "raw_crop_sha256": "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a",
    "recliner_uuid": "3b2cae03-3556-5c1e-a19b-ea3c1e15694c",
    "source_lane": "raw_crop",
    "question_id": "call_d61e943d-5832-456b-b812-b095ab52eb82",
    "response": "Approve exact candidate",
}
EXCLUDED_FROM_RECORD_FINGERPRINT = {
    ".kiro/specs/unified-world-pipeline/tasks.md",
    f".kiro/specs/unified-world-pipeline/evidence/{EVIDENCE.name}",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record_creation_fingerprint() -> tuple[str, str, int]:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    listed = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    ).split(b"\0")
    paths = sorted(
        item.decode("utf-8")
        for item in listed
        if item and item.decode("utf-8") not in EXCLUDED_FROM_RECORD_FINGERPRINT
    )
    digest = hashlib.sha256()
    digest.update(head.encode("ascii") + b"\n")
    for path in paths:
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / path).read_bytes())
    return head, digest.hexdigest(), len(paths)


def non_self_record_hash(record: dict) -> str:
    payload = copy.deepcopy(record)
    del payload["integrity"]["resulting_evidence_sha256"]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    base = load(BASE_VALIDATOR, "task_11_8_4a_approval_base")

    assert record["schema"] == "unified-world-pipeline.task-11.8.4a.human-approval-pass.v1"
    assert record["evidence_id"] == EVIDENCE_ID
    assert record["task"] == "11.8.4a" and record["result"] == "PASS"
    assert sha256(CANDIDATE) == EXPECTED["candidate_evidence_sha256"]
    assert sha256(ARTIFACT) == EXPECTED["artifact_sha256"]
    assert sha256(PREVIEW) == EXPECTED["preview_sha256"]

    bindings = record["exact_approval_bindings"]
    for key, value in EXPECTED.items():
        assert bindings[key] == value, key
    assert candidate["candidate_binding"]["pre_record_candidate_tree_fingerprint"] == EXPECTED["approved_candidate_fingerprint"]
    assert candidate["artifact"]["sha256"] == EXPECTED["artifact_sha256"]
    assert candidate["selected_preview"]["sha256"] == EXPECTED["preview_sha256"]
    assert candidate["recliner_uuid"] == EXPECTED["recliner_uuid"] and candidate["source_lane"] == EXPECTED["source_lane"]
    assert candidate["golden_room_provenance"]["authoritative_canon"]["sha256"] == EXPECTED["golden_source_sha256"]
    assert candidate["golden_room_provenance"]["workflow"]["sha256"] == EXPECTED["workflow_sha256"]
    assert candidate["golden_room_provenance"]["extraction_workflow"]["sha256"] == EXPECTED["extraction_workflow_sha256"]
    assert candidate["golden_room_provenance"]["raw_crop"]["sha256"] == EXPECTED["raw_crop_sha256"]

    checks = record["common_gate"]["checks"]
    assert record["common_gate"]["checks_in_order"] == base.COMMON_CHECKS
    assert [item["check"] for item in checks] == base.COMMON_CHECKS
    assert len(checks) == 12 and all(item["pass"] is True for item in checks)
    assert record["common_gate"]["passed_checks"] == 12
    assert record["common_gate"]["failed_checks"] == []
    assert record["common_gate"]["verdict"] == "PASS"
    assert all(item["pass"] is True for item in candidate["common_gate"]["checks"][:11])

    approval = record["human_approval"]
    assert approval["present"] is True and approval["approved"] is True
    assert approval["question_id"] == EXPECTED["question_id"]
    assert approval["response"] == EXPECTED["response"]
    assert all(approval[name] is True for name in (
        "asset_hash_bound", "preview_hash_bound", "candidate_fingerprint_bound",
        "gate_evidence_hash_bound", "golden_room_reference_hashes_bound",
        "uuid_bound", "source_lane_bound",
    ))

    for item in record["hash_bindings"]:
        path = Path(item["path"]) if Path(item["path"]).is_absolute() else ROOT / item["path"]
        assert path.is_file() and sha256(path) == item["sha256"], item["path"]

    head, fingerprint, count = record_creation_fingerprint()
    creation = record["record_creation_binding"]
    assert creation["git_head"] == head
    assert creation["fingerprint"] == fingerprint
    assert creation["path_count"] == count
    assert creation["excluded_paths"] == sorted(EXCLUDED_FROM_RECORD_FINGERPRINT)
    assert record["approved_candidate_binding"]["fingerprint"] == EXPECTED["approved_candidate_fingerprint"]
    assert record["approved_candidate_binding"]["meaning_unchanged"] is True
    assert record["integrity"]["resulting_evidence_sha256"]["value"] == non_self_record_hash(record)

    artifact = base.inspect_artifact()
    assert artifact["durable_material_present"] is True
    assert artifact["external_image_uris"] == [] and artifact["external_buffer_uris"] == []
    assert record["authority"]["metric_plan_remains_sole_spatial_authority"] is True
    assert record["authority"]["immutable_plan_derived_camera_contract_remains_camera_authority"] is True
    assert record["authority"]["world_contract_remains_final_binding_authority"] is True
    assert all(record["preservation"].values())
    assert record["status_effect"]["task_11_8_4a_complete"] is True
    assert record["status_effect"]["task_11_8_5"] == "ELIGIBLE_NOT_STARTED"
    assert "- [ ] 11.8.5 Produce and approve" in TASKS.read_text(encoding="utf-8")

    print("PASS Task 11.8.4a exact hash-bound human approval validation")
    print("  common_gate: 12/12 PASS")
    print("  user_input:", approval["question_id"], repr(approval["response"]))
    print("  approved_candidate_fingerprint:", EXPECTED["approved_candidate_fingerprint"])
    print("  record_creation_fingerprint:", fingerprint)
    print("  approval_evidence_sha256:", sha256(EVIDENCE))
    print("  non_self_record_hash:", record["integrity"]["resulting_evidence_sha256"]["value"])
    print("  Task 11.8.5: ELIGIBLE_NOT_STARTED")


if __name__ == "__main__":
    main()
