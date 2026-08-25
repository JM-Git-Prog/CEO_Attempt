"""Validate the append-only Task 11.8.4a informed human rejection.

This validator intentionally does not rerun earlier candidate/render validators. It
verifies the exact rejected candidate, immutable historical chain, superseded
approval authority, fail-closed common-gate result, and blocked task state.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE_DIR = Path(__file__).resolve().parent
EVIDENCE_ID = "13500f5f-04dc-4085-a6c4-6407f69bf3b1"
EVIDENCE = EVIDENCE_DIR / f"task-11.8.4a-human-rejection-revocation-blocker-{EVIDENCE_ID}.json"
PRIOR_APPROVAL = EVIDENCE_DIR / "task-11.8.4a-human-approval-pass-ac67e3f0-9c19-44fa-9eed-e822f9e82515.json"
CANDIDATE = EVIDENCE_DIR / "task-11.8.4a-approval-candidate-additional-03-7c9f6b25-130e-4f47-838c-4cecd86f6d34.json"
ARTIFACT = EVIDENCE_DIR / "task-11.8.4a-continuity-corrected-raw-crop-recliner-3876cc8a-81a2-4bba-9da0-185ba59db002/recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
PREVIEW = EVIDENCE_DIR / "task-11.8.4a-additional-03-edge-preserving-denoise-c858e5e3-7968-40ee-b8e5-b54f1c073911/recliner-raw-crop_additional-03-edge-preserving-denoise-eight-panel.png"
TASKS = ROOT / ".kiro/specs/unified-world-pipeline/tasks.md"

USER_REJECTION = "i dont approve that, it looks like a blob"
ARTIFACT_SHA256 = "4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf"
PREVIEW_SHA256 = "9865be16e82e383f12f5475574d48636d536a3b825de95c9d6ccbcd27a2000d7"
CANDIDATE_FINGERPRINT = "6b8a2b6b25e2cbc6e6b674ef037e95d3339584eefb83e6b3350b2f7da8d28baf"
CANDIDATE_EVIDENCE_SHA256 = "09b48cea36bce340667a3a185bf7727011f3f44793a5ddb3d21c0c5d96234b41"
PRIOR_APPROVAL_SHA256 = "57946e10d2e58df0c87be5931f528c867f9fa31704b4743a410f990c63ee1773"
EVIDENCE_FULL_FILE_SHA256 = "34f39460cadf4a8c74c1b6f57d8f80b54ea0adced12a2ea2e20d8afc129e56e2"
EVIDENCE_CANONICAL_NON_SELF_SHA256 = "dfe199e2d9496edeadd01f374dbe4b730a806a25b339aef29b316c7d0f7e3f00"
RECLINER_UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"

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

EXPECTED_HISTORICAL = {
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json": "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-approval-candidate-additional-03-7c9f6b25-130e-4f47-838c-4cecd86f6d34.json": CANDIDATE_EVIDENCE_SHA256,
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-continuity-corrected-raw-crop-recliner-3876cc8a-81a2-4bba-9da0-185ba59db002.json": "1525378dc6a7f82c1c420b760949158ddaf36db6d6638649850e7509e09bdaf1",
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-human-approval-pass-ac67e3f0-9c19-44fa-9eed-e822f9e82515.json": PRIOR_APPROVAL_SHA256,
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-remediated-raw-crop-recliner-aa1347b1-9a3e-45f6-af16-571c7e03dde8.json": "b0fc2b37f5b2c97b815552ee004f13228507ec272559ef04e45d67175859c3fa",
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-semantic-surface-fail-closed-d3730c08-0447-4640-ae0c-55183e0e0a45.json": "7fd1f453cd9e8f6aa54305b2926b829222f72534c95b4014ffccda0f591e532c",
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-visual-gate-hold-f3bdd7ac-c938-4a56-abad-79e850bd243b.json": "6c0af3b5a1486f7504085b54d84eece6bc866b274801ea839e3dc995305e648c",
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-visual-rejection-b1cbf2d1-1a25-478c-8ddf-3a4f5bfd4780.json": "ba20df1f1664daebb7ead03b395c8d916ed3633198430ed0c82eb29da9f22253",
    ".kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4.py": "17021de5e29c8a6d985a490da9759b1cf3a741e6eedbd35ab4d8bede95352729",
    ".kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a.py": "77402c75b9d8c15abb68c6a082eea02768b32c2be79323fcb3b898ee518fe608",
    ".kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a_additional_approval_candidate.py": "0c6e503b3d591ac60e58f77d8f032f4cf61c4d63cc91501399154de100e17c7c",
    ".kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a_human_approval_pass.py": "6e6f6efd012b4c21ff8d338e25098fd1183b10b22178aae4c885f79c034c5d42",
    ".kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a_semantic_surface_evidence.py": "5c9c93b3763145e18d2d808d365d98897f84f0dbbcbb8ebf7fd6b556803152da",
    ".kiro/specs/unified-world-pipeline/evidence/validate_task_11_8_4a_visual_correction.py": "857a3a24cc097af07e0f3c80f6d8845fb2410841978965ff8eb4256705f6587c",
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-continuity-corrected-raw-crop-recliner-3876cc8a-81a2-4bba-9da0-185ba59db002/recliner-raw-crop_continuity-corrected-fabric-pbr.glb": ARTIFACT_SHA256,
    ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4a-additional-03-edge-preserving-denoise-c858e5e3-7968-40ee-b8e5-b54f1c073911/recliner-raw-crop_additional-03-edge-preserving-denoise-eight-panel.png": PREVIEW_SHA256,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_non_self_sha256(record: dict) -> str:
    payload = copy.deepcopy(record)
    del payload["integrity"]
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def main() -> None:
    record = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_APPROVAL.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))

    assert record["schema"] == "unified-world-pipeline.task-11.8.4a.human-rejection-revocation-blocker.v1"
    assert record["evidence_id"] == EVIDENCE_ID
    assert record["task"] == "11.8.4a"
    assert record["result"] == "FAIL_CLOSED_EXPLICIT_HUMAN_REJECTION"

    binding = record["exact_candidate_binding"]
    assert binding["artifact_sha256"] == ARTIFACT_SHA256
    assert binding["preview_sha256"] == PREVIEW_SHA256
    assert binding["candidate_fingerprint"] == CANDIDATE_FINGERPRINT
    assert binding["candidate_evidence_sha256"] == CANDIDATE_EVIDENCE_SHA256
    assert binding["recliner_uuid"] == RECLINER_UUID
    assert binding["source_lane"] == "raw_crop"
    assert sha256(ARTIFACT) == ARTIFACT_SHA256
    assert sha256(PREVIEW) == PREVIEW_SHA256
    assert sha256(CANDIDATE) == CANDIDATE_EVIDENCE_SHA256

    assert candidate["artifact"]["sha256"] == ARTIFACT_SHA256
    assert candidate["selected_preview"]["sha256"] == PREVIEW_SHA256
    assert candidate["candidate_binding"]["pre_record_candidate_tree_fingerprint"] == CANDIDATE_FINGERPRINT
    assert candidate["recliner_uuid"] == RECLINER_UUID
    assert candidate["source_lane"] == "raw_crop"

    superseded = record["superseded_release_authority"]
    assert sha256(PRIOR_APPROVAL) == PRIOR_APPROVAL_SHA256
    assert superseded["prior_approval_evidence_full_file_sha256"] == PRIOR_APPROVAL_SHA256
    assert superseded["prior_record_preserved_as_historical_evidence"] is True
    assert superseded["prior_record_result_relabelled_or_edited"] is False
    assert superseded["historical_interaction_erased"] is False
    assert "Current StandaloneAssetGate pass authority" in superseded["superseded_scope"]
    assert prior["result"] == "PASS"
    assert prior["exact_approval_bindings"]["artifact_sha256"] == ARTIFACT_SHA256
    assert prior["exact_approval_bindings"]["preview_sha256"] == PREVIEW_SHA256
    assert prior["exact_approval_bindings"]["approved_candidate_fingerprint"] == CANDIDATE_FINGERPRINT

    chronology = record["informed_review_chronology"]
    assert chronology["initial_limitation"] == "The initially blocked file:// preview prevented informed visual review of the exact PNG."
    assert PREVIEW_SHA256 in chronology["later_review"]
    assert chronology["latest_user_judgement_verbatim"] == USER_REJECTION
    assert chronology["latest_judgement_is_authoritative_for_current_human_gate"] is True
    assert "opened and viewed locally" in chronology["later_review"]

    defect = record["human_visual_defect"]
    assert defect["observed_by"] == "user"
    assert defect["observation"] == "blob-like geometry"
    assert "no stronger topology, reconstruction, fused-geometry, material, or quantitative finding" in defect["interpretation_limit"]

    common_gate = record["common_gate"]
    checks = common_gate["checks"]
    assert common_gate["checks_in_order"] == COMMON_CHECKS
    assert [item["check"] for item in checks] == COMMON_CHECKS
    assert len(checks) == 12
    failed = [item["check"] for item in checks if item["pass"] is False]
    assert failed == ["recognizable_recliner_silhouette_identity", "explicit_hash_bound_human_approval"]
    assert common_gate["failed_checks"] == failed
    assert common_gate["passed_checks"] == 10
    assert common_gate["verdict"] == "FAIL_CLOSED_EXPLICIT_HUMAN_REJECTION"
    assert checks[5]["basis"] == "The informed user visual verdict on the exact preview was that it looks like a blob; no stronger geometry finding is asserted."
    assert checks[11]["status"] == "REVOKED_BY_LATER_INFORMED_EXPLICIT_REJECTION"
    assert USER_REJECTION in checks[11]["basis"]

    approval = record["current_human_approval"]
    assert approval["present"] is True
    assert approval["approved"] is False
    assert approval["status"] == "REVOKED_AND_EXPLICITLY_REJECTED"
    assert approval["latest_user_judgement_verbatim"] == USER_REJECTION
    assert all(approval[name] is True for name in (
        "asset_hash_bound",
        "preview_hash_bound",
        "candidate_fingerprint_bound",
        "prior_approval_evidence_hash_bound",
    ))

    manifest = {item["path"]: item["sha256"] for item in record["immutable_historical_manifest"]}
    assert manifest == EXPECTED_HISTORICAL
    assert len(record["immutable_historical_manifest"]) == len(EXPECTED_HISTORICAL)
    for relative_path, expected in EXPECTED_HISTORICAL.items():
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        assert sha256(path) == expected, relative_path

    effect = record["execution_effect"]
    assert effect["task_11_8_4a"] == "FAIL_CLOSED_INCOMPLETE"
    assert effect["task_11_8_5"] == "BLOCKED_NOT_STARTED"
    assert effect["all_downstream_task_11_8_leaves"] == "BLOCKED_NOT_STARTED"
    assert effect["task_11_7_1_and_tasks_11_9_through_11_11"] == "BLOCKED_NOT_STARTED"
    assert effect["further_evidence_renderer_attempts"] == "PROHIBITED_FOR_THIS_REJECTED_CANDIDATE"
    assert effect["renderer_attempt_reason"] == "Evidence-renderer-only changes cannot repair the user's rejected underlying blob-like geometry."
    assert effect["demo_ready_claimed"] is False
    assert effect["release_ready_claimed"] is False
    assert effect["platform_complete_claimed"] is False

    preservation = record["preservation"]
    assert preservation["prior_candidate_blocker_validator_and_approval_files_modified"] is False
    assert preservation["glb_preview_geometry_materials_or_sources_modified"] is False
    assert preservation["ui_or_interface_version_modified"] is False
    assert preservation["production_or_test_code_modified"] is False
    assert preservation["session_or_qualification_started"] is False
    assert preservation["model_download_integration_inference_or_cloud_used"] is False
    assert preservation["unrelated_worktree_content_modified"] is False
    assert preservation["commit_created"] is False
    assert preservation["record_is_append_only"] is True

    tasks = TASKS.read_text(encoding="utf-8")
    assert "  - [ ] 11.8.4a Remediate and approve the Golden Room source-matched raw-crop recliner" in tasks
    assert "  - [x] 11.8.4a Remediate and approve the Golden Room source-matched raw-crop recliner" not in tasks
    assert "  - [ ] 11.8.5 Produce and approve the five standalone Golden Room hero assets only after Task 11.8.4a passes" in tasks

    assert sha256(EVIDENCE) == EVIDENCE_FULL_FILE_SHA256
    assert canonical_non_self_sha256(record) == EVIDENCE_CANONICAL_NON_SELF_SHA256
    assert "removing the complete integrity object" in record["integrity"]["canonical_non_self_hash_policy"]
    assert "cannot be truthfully self-embedded" in record["integrity"]["full_file_hash_policy"]

    print("PASS Task 11.8.4a informed human-rejection revocation validation")
    print("  result: FAIL_CLOSED_EXPLICIT_HUMAN_REJECTION")
    print("  user_rejection:", repr(USER_REJECTION))
    print("  artifact_sha256:", ARTIFACT_SHA256)
    print("  preview_sha256:", PREVIEW_SHA256)
    print("  candidate_fingerprint:", CANDIDATE_FINGERPRINT)
    print("  prior_approval_sha256:", PRIOR_APPROVAL_SHA256)
    print("  task_11_8_4a: FAIL_CLOSED_INCOMPLETE")
    print("  task_11_8_5: BLOCKED_NOT_STARTED")
    print("  downstream: BLOCKED_NOT_STARTED")
    print("  blocker_evidence:", EVIDENCE.relative_to(ROOT).as_posix())
    print("  blocker_evidence_sha256:", EVIDENCE_FULL_FILE_SHA256)
    print("  canonical_non_self_sha256:", EVIDENCE_CANONICAL_NON_SELF_SHA256)


if __name__ == "__main__":
    main()
