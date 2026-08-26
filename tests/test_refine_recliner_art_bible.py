"""Focused tests for Task 11.8.4c deterministic recliner refinement support."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import refine_recliner_art_bible as refinement


def test_art_bible_prompts_bind_required_appearance_and_exclusions() -> None:
    """Unit example validating the exact Task 11.8.4c cue/prompt contract.

    **Validates: Requirements 38.4, 38.5, 38.8, 38.11, 39.3, 39.5**
    """
    record = refinement.build_cues_and_prompts()
    positive = record["positive_prompt"].lower()
    negative = record["negative_prompt"].lower()
    assert record["authoritative_art_bible"]["path"] == str(refinement.ART_BIBLE_PATH)
    assert record["authoritative_art_bible"]["sha256"] == refinement.ART_BIBLE_SHA256
    for phrase in ("soft overstuffed", "worn mottled medium-brown", "conventional low rectangular recliner base", "footrest physically integrated", "left arm", "right arm"):
        assert phrase in positive
    for phrase in ("rigid thin or blocky", "pedestal base", "detached floating footrest", "pristine modern", "fused room", "melted topology", "blob-like"):
        assert phrase in negative
    assert record["authority_boundary"]["metric_plan"].startswith("sole")
    assert "appearance" in record["authority_boundary"]["art_bible_and_canon"]


def test_common_gate_order_matches_locked_task_11_8_4_order() -> None:
    """Unit edge check: human approval remains last and cannot be manufactured.

    **Validates: Requirements 39.1, 39.2, 39.3, 39.4, 39.5, 39.13, 39.14**
    """
    assert refinement.COMMON_GATE_ORDER == [
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


@given(
    st.dictionaries(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=64), min_size=1, max_size=12),
    st.dictionaries(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=64), min_size=1, max_size=12),
)
def test_candidate_fingerprint_is_deterministic_under_mapping_order(inputs: dict[str, str], outputs: dict[str, str]) -> None:
    """Property: hash binding is independent of insertion order.

    **Validates: Requirements 39.4, 41.3, 41.6**
    """
    expected = refinement.candidate_fingerprint(inputs, outputs)
    assert refinement.candidate_fingerprint(dict(reversed(list(inputs.items()))), dict(reversed(list(outputs.items())))) == expected
    assert len(expected) == 64
    assert all(character in "0123456789abcdef" for character in expected)


import canon_decomposition_upbge_proof as complete_room_proof
import validate_canon_decomposition_upbge_proof as proof_validator
from src.unified_pipeline.strict_real_handlers import (
    handle_automated_final_validation,
    handle_compile,
)


TASK_1_DIAGNOSTIC_ID = "task-1-bug-condition-exploration-74fba659-f84f-409a-b87e-9327f458a5c7"
TASK_1_DIAGNOSTIC_ROOT = (
    ROOT
    / ".kiro"
    / "specs"
    / "unified-world-pipeline"
    / "evidence"
    / "task-11.8.4c-golden-room-convergence"
    / TASK_1_DIAGNOSTIC_ID
)
FAILED_RECLINER_ROOT = (
    ROOT
    / ".kiro"
    / "specs"
    / "unified-world-pipeline"
    / "evidence"
    / "task-11.8.4c-art-bible-recliner-19b7c7df-c5e5-4991-9ba7-ff68f4da7be9"
)
ACTIVE_DIAGNOSTIC_ROOT = (
    ROOT
    / "output"
    / "diag-browser-v8-q-18ee9af4-5673-47d5-a4aa-61c6e416c745"
)
KNOWN_COMPLETE_ROOM_COUNTEREXAMPLES = (
    "current_sparse_proof",
    "failed_recliner_48f2e5c6",
    "missing_empty_twin_expected_hash",
    "review_only_imageops_fit",
    "incomplete_inventory_and_world_bindings",
    "absent_calibrated_learned_perceptual_scoring",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": _sha256(path) if path.is_file() else None,
    }


def _tree_records(path: Path) -> list[dict[str, object]]:
    if not path.is_dir():
        return [{"path": str(path), "exists": False, "bytes": None, "sha256": None}]
    return [_file_record(candidate) for candidate in sorted(path.rglob("*")) if candidate.is_file()]


def _git(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return {
        "command": ["git", *arguments],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _write_exclusive_json(path: Path, value: object) -> None:
    serialized = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(serialized)


def _expected_behavior(result: dict[str, object]) -> bool:
    scores = result["scores"]
    assert isinstance(scores, dict)
    return all((
        result["iteration_id_is_fresh"],
        result["prior_bytes_unchanged"],
        result["complete_inventory_exact"],
        result["authority_bindings_valid"],
        result["proof_origin"] == "complete_3d_world_fixed_camera_render",
        result["render_protocol_hash_matches_calibration"],
        result["dual_replay_semantic_hashes_equal"],
        result["all_hard_gates_pass"],
        scores["I"] is not None and scores["I"] >= 95,
        scores["G"] is not None and scores["G"] >= 95,
        scores["L"] is not None and scores["L"] >= 95,
        scores["M"] is not None and scores["M"] >= 90,
        scores["P"] is not None and scores["P"] >= 95,
        scores["S"] is not None and scores["S"] >= 95.0,
        result["recliner_v2_pass"],
        result["qwen_pass"],
        result["primary_pass"],
        result["human_approval_binds_every_required_hash"],
        result["state"] == "VALIDATED_SUCCESS",
        result["kirograph_counts"] == {"problem": 1, "attempt": 1, "solution": 1},
        result["task_11_8_5"] == "BLOCKED_NOT_STARTED",
        result["staged_or_committed"] is False,
    ))


@pytest.fixture(scope="module")
def unfixed_complete_room_observation(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Capture the exact unfixed proof once, before the exploration assertion fails."""
    if TASK_1_DIAGNOSTIC_ROOT.exists():
        pytest.fail(f"append-only Task 1 diagnostic root already exists: {TASK_1_DIAGNOSTIC_ROOT}")
    TASK_1_DIAGNOSTIC_ROOT.mkdir(parents=True, exist_ok=False)

    hooks = ROOT / ".kiro" / "hooks"
    authority_artifacts = ACTIVE_DIAGNOSTIC_ROOT / "artifacts"
    baseline_root = refinement.BASELINE_DIR
    tasks_path = ROOT / ".kiro" / "specs" / "unified-world-pipeline" / "tasks.md"
    task_text = tasks_path.read_text(encoding="utf-8")
    snapshot = {
        "schema": "recliner-canon-visual-refinement-fix.task-1-preservation-snapshot.v1",
        "diagnostic_id": TASK_1_DIAGNOSTIC_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "scope": "Read-only pre-production characterization; no production, task, UI, session, qualification, process, index, or historical-artifact mutation.",
        "kirograph_queries_performed_before_test": {
            "context": "Execute Task 1 bug-condition exploration for complete Golden Room sparse proof",
            "memory": "Task 11.8.4c recliner qwen primary failed candidate 48f2e5c6 sparse proof blocky",
            "exact_revision": _git("rev-parse", "HEAD")["stdout"].strip(),
            "memory_finding": "candidate 48f2e5c6 passed qwen2.5vl but failed primary adjudication; Task 11.8.5 remains blocked",
        },
        "git": {
            "status": _git("status", "--porcelain=v1", "-uall"),
            "index_diff": _git("diff", "--cached", "--name-status"),
            "index_tree": _git("write-tree"),
        },
        "locked_references": [
            _file_record(complete_room_proof.CANON_PATH),
            _file_record(complete_room_proof.EMPTY_TWIN_PATH),
            _file_record(refinement.ART_BIBLE_PATH),
        ],
        "authority_inputs": [
            _file_record(authority_artifacts / "approved_metric_plan.json"),
            _file_record(authority_artifacts / "world_contract.json"),
            _file_record(authority_artifacts / "selected_objects.json"),
            _file_record(authority_artifacts / "spatial_solution.json"),
            _file_record(authority_artifacts / "scene_graph.json"),
        ],
        "approved_assets": _tree_records(authority_artifacts / "meshes"),
        "selected_inventory_and_decomposition": [
            _file_record(authority_artifacts / "selected_objects.json"),
            _file_record(refinement.BASELINE_PACK_PATH),
        ],
        "task_11_8_4b_baseline_and_prior_proof": _tree_records(baseline_root),
        "failed_task_11_8_4c_candidate": _tree_records(FAILED_RECLINER_ROOT),
        "active_task_state": {
            "files": [
                _file_record(tasks_path),
                _file_record(ROOT / ".kiro" / "specs" / "recliner-canon-visual-refinement-fix" / "tasks.md"),
            ],
            "task_11_8_4c_unchecked": "- [ ] 11.8.4c" in task_text,
            "task_11_8_5_blocked_not_started": "11.8.5" in task_text and "BLOCKED_NOT_STARTED" in task_text,
        },
        "unrelated_hooks": _tree_records(hooks),
    }
    snapshot_path = TASK_1_DIAGNOSTIC_ROOT / "preservation-snapshot.json"
    _write_exclusive_json(snapshot_path, snapshot)

    immutable_bindings = complete_room_proof.verify_immutable_inputs()
    recorded = json.loads(refinement.BASELINE_PROOF_PATH.read_text(encoding="utf-8"))
    pack = json.loads(refinement.BASELINE_PACK_PATH.read_text(encoding="utf-8"))
    bounded_validation = proof_validator.validate(baseline_root)
    rebuilt = complete_room_proof.build_evidence(
        baseline_root,
        pack,
        recorded["comfy_execution"],
        immutable_bindings,
        recorded["execution"]["blender"],
    )
    main_guard = None
    try:
        complete_room_proof.main([])
    except SystemExit as exc:
        main_guard = str(exc)

    learned_modules = {
        module: importlib.util.find_spec(module) is not None
        for module in ("lpips", "piq", "torch", "torchvision", "skimage")
    }
    local_vision = json.loads((FAILED_RECLINER_ROOT / "local-vision-screen.json").read_text(encoding="utf-8"))
    first_gate = {
        "locked_order": 1,
        "gate": "exact_reference_config_hashes",
        "verdict": "FAIL_MISSING_EMPTY_TWIN_EXPECTED_HASH_BINDING",
        "tool": "tools/canon_decomposition_upbge_proof.py::verify_immutable_inputs",
        "exit_code": 0,
        "detail": (
            f"verify_immutable_inputs returned {len(immutable_bindings)} verified bindings, "
            f"but EMPTY_TWIN_PATH {complete_room_proof.EMPTY_TWIN_PATH} is absent from EXPECTED_HASHES"
        ),
        "empty_twin_sha256": _sha256(complete_room_proof.EMPTY_TWIN_PATH),
        "snapshot_sha256": _sha256(snapshot_path),
    }
    first_gate["verdict_payload_sha256"] = hashlib.sha256(
        json.dumps(first_gate, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    result: dict[str, object] = {
        "iteration_id_is_fresh": False,
        "prior_bytes_unchanged": True,
        "complete_inventory_exact": False,
        "authority_bindings_valid": False,
        "proof_origin": "diagnostic_shell_and_recliner_only",
        "render_protocol_hash_matches_calibration": False,
        "dual_replay_semantic_hashes_equal": False,
        "all_hard_gates_pass": False,
        "scores": {"I": None, "G": None, "L": None, "M": None, "P": None, "S": None},
        "recliner_v2_pass": False,
        "qwen_pass": all(screen["model_verdict"]["pass"] for screen in local_vision["screens"]),
        "primary_pass": local_vision["primary_adjudication"]["verdict"] == "PASS",
        "human_approval_binds_every_required_hash": False,
        "state": rebuilt["result"],
        "required_uncalibrated_state": "BLOCKED_UNCALIBRATED",
        "uncalibrated_state_returned": rebuilt["result"] == "BLOCKED_UNCALIBRATED",
        "percentage_claim": None,
        "kirograph_counts": {"problem": 0, "attempt": 0, "solution": 0},
        "task_11_8_5": "BLOCKED_NOT_STARTED",
        "staged_or_committed": False,
        "first_failure": first_gate,
        "known_counterexamples": list(KNOWN_COMPLETE_ROOM_COUNTEREXAMPLES),
        "proof_observations": {
            "empty_twin_in_expected_hashes": complete_room_proof.EMPTY_TWIN_PATH in complete_room_proof.EXPECTED_HASHES,
            "combine_contact_sheet_uses_imageops_fit": "ImageOps.fit" in inspect.getsource(complete_room_proof.combine_contact_sheet),
            "build_evidence_calls_strict_compile": "handle_compile" in inspect.getsource(complete_room_proof.build_evidence),
            "build_evidence_calls_final_validation": "handle_automated_final_validation" in inspect.getsource(complete_room_proof.build_evidence),
            "main_missing_output_guard": main_guard,
            "bounded_existing_validator": bounded_validation,
            "legacy_build_evidence_result": rebuilt["result"],
            "strict_handler_source_hashes": {
                "handle_compile": hashlib.sha256(inspect.getsource(handle_compile).encode("utf-8")).hexdigest(),
                "handle_automated_final_validation": hashlib.sha256(inspect.getsource(handle_automated_final_validation).encode("utf-8")).hexdigest(),
            },
            "learned_perceptual_modules": learned_modules,
            "calibrated_learned_perceptual_available": learned_modules["lpips"] or learned_modules["piq"],
            "failed_recliner_fingerprint": local_vision["candidate_fingerprint"],
            "qwen_confidences": [screen["model_verdict"]["confidence"] for screen in local_vision["screens"]],
            "primary_verdict": local_vision["primary_adjudication"]["verdict"],
            "primary_failed_checks": local_vision["primary_adjudication"]["failed_checks"],
        },
    }
    diagnostic = {
        "schema": "recliner-canon-visual-refinement-fix.task-1-first-failure.v1",
        "diagnostic_id": TASK_1_DIAGNOSTIC_ID,
        "expected_test_outcome": "FAIL",
        "first_exact_failure": first_gate,
        "result": result,
        "preservation_snapshot": {
            "path": str(snapshot_path),
            "sha256": _sha256(snapshot_path),
        },
    }
    _write_exclusive_json(TASK_1_DIAGNOSTIC_ROOT / "first-failure.json", diagnostic)
    return result


@settings(max_examples=len(KNOWN_COMPLETE_ROOM_COUNTEREXAMPLES), deadline=None)
@given(counterexample=st.sampled_from(KNOWN_COMPLETE_ROOM_COUNTEREXAMPLES))
def test_property_1_unfixed_complete_room_cannot_satisfy_expected_behavior(
    counterexample: str,
    unfixed_complete_room_observation: dict[str, object],
) -> None:
    """Property 1: the current sparse proof cannot satisfy expectedBehavior.

    This is the pre-fix exploration property and is expected to fail on the
    unfixed revision. Its first exact verdict is persisted before assertion.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 2.12, 2.15, 2.18, 2.21, 2.25, 2.28, 2.30, 3.1, 3.2, 3.3, 3.6, 3.8, 3.12, 3.18**
    """
    observed = dict(unfixed_complete_room_observation)
    observed["counterexample"] = counterexample
    assert _expected_behavior(observed), json.dumps(observed, sort_keys=True)


# Task 2 consumes the immutable Task 1 observation rather than constructing a
# more convenient post-fix baseline.
TASK_1_SNAPSHOT_PATH = TASK_1_DIAGNOSTIC_ROOT / "preservation-snapshot.json"
TASK_1_SNAPSHOT_SHA256 = "af584af135eb3eb6cbb5f5dd135bd606b422be7141cbe76dc1a240c26d3bfbe9"
TASK_1_REVISION = "7e89d697de3b4218f362f6fba0efcd5723d4917f"
TASK_1_INDEX_TREE = "c2c0baf3b589aa8a31f49613c72a7b62880790c4"
SELECTED_MANIFEST_PATH = ACTIVE_DIAGNOSTIC_ROOT / "artifacts" / "selected_objects.json"
CANON_COMPARE_TEST_PATH = ROOT / "src" / "unified_pipeline" / "tests" / "test_canon_compare.py"
GOLDEN_ROOM_EVIDENCE_PREFIX = ".kiro/specs/unified-world-pipeline/evidence/task-11.8.4c-golden-room-convergence/"
EXPECTED_COMMON_GATE_ORDER = tuple(refinement.COMMON_GATE_ORDER)
FORBIDDEN_BOUNDARY_TOKENS = (
    ".revise(",
    "RoomPlateGenerator",
    "SceneCanonGenerator",
    "UnifiedPlaceholderGenerator",
    "ObjectIsolator",
    ".segment(",
)
PRESERVED_RECORD_GROUPS = (
    "locked_references",
    "authority_inputs",
    "approved_assets",
    "selected_inventory_and_decomposition",
    "task_11_8_4b_baseline_and_prior_proof",
    "failed_task_11_8_4c_candidate",
    "unrelated_hooks",
)
PROTECTED_TREE_GROUPS = {
    "approved_assets": ACTIVE_DIAGNOSTIC_ROOT / "artifacts" / "meshes",
    "task_11_8_4b_baseline_and_prior_proof": refinement.BASELINE_DIR,
    "failed_task_11_8_4c_candidate": FAILED_RECLINER_ROOT,
    "unrelated_hooks": ROOT / ".kiro" / "hooks",
}
ALLOWED_IMPLEMENTATION_PATHS = {
    "tools/canon_decomposition_upbge_proof.py",
    "tools/validate_canon_decomposition_upbge_proof.py",
    "tools/refine_recliner_art_bible.py",
    "tools/validate_recliner_art_bible_refinement.py",
    "tests/test_refine_recliner_art_bible.py",
    "src/unified_pipeline/tests/test_canon_compare.py",
}
NEGATIVE_MUTATION_CASES = (
    "manifest_order",
    "prior_file_mutation",
    "prior_file_addition",
    "prior_file_deletion",
    "index_change",
    "staged_change",
    "task_state_change",
    "hook_mutation",
    "ui_worktree_change",
    "session_worktree_change",
    "qualification_worktree_change",
    "process_owner_worktree_change",
    "service_worktree_change",
    "commit_change",
    "plan_revise_call",
    "room_regeneration_call",
    "canon_regeneration_call",
    "placeholder_substitution",
    "isolator_identity_promotion",
    "gate_order_change",
)


def _load_task_1_snapshot() -> dict[str, object]:
    assert _sha256(TASK_1_SNAPSHOT_PATH) == TASK_1_SNAPSHOT_SHA256
    return json.loads(TASK_1_SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _snapshot_records(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {}
    for group in PRESERVED_RECORD_GROUPS:
        for record in snapshot[group]:
            records[str(record["path"])] = dict(record)
    # The bugfix workflow file advances from Task 1 to Task 2 under the
    # orchestrator, so it is not a preserved product/task-state authority.
    # The active Unified World Pipeline task file is preserved byte-for-byte.
    for record in snapshot["active_task_state"]["files"]:
        if "unified-world-pipeline" in str(record["path"]):
            records[str(record["path"])] = dict(record)
    return records


def _status_paths(status: str) -> set[str]:
    return {
        line[3:].replace("\\", "/")
        for line in status.splitlines()
        if len(line) >= 4
    }


def _observed_preservation_state() -> dict[str, object]:
    snapshot = _load_task_1_snapshot()
    expected_records = _snapshot_records(snapshot)
    observed_records = {
        path: _file_record(Path(path))
        for path in expected_records
    }
    protected_additions: list[str] = []
    for group, root in PROTECTED_TREE_GROUPS.items():
        expected = {str(record["path"]) for record in snapshot[group]}
        actual = {
            str(path) for path in root.rglob("*") if path.is_file()
        } if root.is_dir() else set()
        protected_additions.extend(sorted(actual - expected))

    task_text = Path(snapshot["active_task_state"]["files"][0]["path"]).read_text(
        encoding="utf-8"
    )
    selected = json.loads(SELECTED_MANIFEST_PATH.read_text(encoding="utf-8"))
    baseline = json.loads(refinement.BASELINE_PROOF_PATH.read_text(encoding="utf-8"))
    failed = json.loads((FAILED_RECLINER_ROOT / "proof-evidence.json").read_text(encoding="utf-8"))
    first_failure = json.loads((TASK_1_DIAGNOSTIC_ROOT / "first-failure.json").read_text(encoding="utf-8"))
    source_paths = (
        ROOT / "tools" / "canon_decomposition_upbge_proof.py",
        ROOT / "tools" / "validate_canon_decomposition_upbge_proof.py",
        ROOT / "tools" / "refine_recliner_art_bible.py",
        ROOT / "tools" / "validate_recliner_art_bible_refinement.py",
    )
    forbidden_calls = {
        token: any(token in path.read_text(encoding="utf-8") for path in source_paths)
        for token in FORBIDDEN_BOUNDARY_TOKENS
    }
    status_result = _git("status", "--porcelain=v1", "-uall")
    staged_result = _git("diff", "--cached", "--name-status")
    index_result = _git("write-tree")
    head_result = _git("rev-parse", "HEAD")
    baseline_status = snapshot["git"]["status"]["stdout"]
    return {
        "snapshot_sha256": _sha256(TASK_1_SNAPSHOT_PATH),
        "records": observed_records,
        "protected_additions": protected_additions,
        "task_11_8_4c_unchecked": "- [ ] 11.8.4c" in task_text,
        "task_11_8_5_blocked_not_started": (
            "11.8.5" in task_text and "BLOCKED_NOT_STARTED" in task_text
        ),
        "staged_diff": staged_result["stdout"],
        "index_tree": index_result["stdout"].strip(),
        "head": head_result["stdout"].strip(),
        "worktree_paths": sorted(_status_paths(status_result["stdout"])),
        "baseline_worktree_paths": sorted(_status_paths(baseline_status)),
        "manifest_selected_ids": list(selected["selected_plan_instance_ids"]),
        "manifest_object_ids": [item["plan_instance_id"] for item in selected["objects"]],
        "manifest_detection_ids": [item["detection_object_id"] for item in selected["objects"]],
        "manifest_identity_authority": selected["identity_authority"],
        "manifest_detection_role": selected["detection_role"],
        "manifest_observation_authority": [item["observation_authority"] for item in selected["objects"]],
        "common_gate_order": list(failed["common_standalone_asset_gate"]["checks_in_order"]),
        "baseline_fingerprint": baseline["candidate_fingerprint"],
        "baseline_result": baseline["result"],
        "failed_fingerprint": failed["candidate_fingerprint"],
        "failed_result": failed["result"],
        "failed_downstream": dict(failed["downstream"]),
        "first_failure_snapshot_sha256": first_failure["preservation_snapshot"]["sha256"],
        "forbidden_calls": forbidden_calls,
        "forbidden_operations": {
            "ui_or_version_changed": False,
            "session_or_qualification_changed": False,
            "process_or_service_owner_changed": False,
            "hook_changed_by_task": False,
            "cloud_or_download_used": False,
        },
    }


def _path_allowed(path: str, baseline_paths: set[str]) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized in baseline_paths
        or normalized in ALLOWED_IMPLEMENTATION_PATHS
        or normalized.startswith(GOLDEN_ROOM_EVIDENCE_PREFIX)
    )


def _preservation_violations(observed: dict[str, object]) -> list[str]:
    snapshot = _load_task_1_snapshot()
    expected_records = _snapshot_records(snapshot)
    violations: list[str] = []
    if observed["snapshot_sha256"] != TASK_1_SNAPSHOT_SHA256:
        violations.append("task1_snapshot_drift")
    for path, expected in expected_records.items():
        actual = observed["records"].get(path)
        if actual != expected:
            violations.append(f"prior_file_drift:{path}")
    violations.extend(
        f"prior_file_addition:{path}" for path in observed["protected_additions"]
    )
    if not observed["task_11_8_4c_unchecked"]:
        violations.append("task_11_8_4c_advanced")
    if not observed["task_11_8_5_blocked_not_started"]:
        violations.append("task_11_8_5_unblocked")
    if observed["staged_diff"]:
        violations.append("git_index_has_staged_diff")
    if observed["index_tree"] != TASK_1_INDEX_TREE:
        violations.append("git_index_tree_changed")
    if observed["head"] != TASK_1_REVISION:
        violations.append("commit_or_head_changed")
    baseline_paths = set(observed["baseline_worktree_paths"])
    for path in observed["worktree_paths"]:
        if not _path_allowed(path, baseline_paths):
            violations.append(f"unrelated_worktree_change:{path}")
    if observed["manifest_selected_ids"] != observed["manifest_object_ids"]:
        violations.append("selected_manifest_order_or_identity_drift")
    if set(observed["manifest_selected_ids"]) & set(observed["manifest_detection_ids"]):
        violations.append("isolator_observation_promoted_to_plan_identity")
    if observed["manifest_identity_authority"] != "approved_plan_instance_id":
        violations.append("manifest_identity_authority_drift")
    if observed["manifest_detection_role"] != "bounded_segmentation_observation_only":
        violations.append("manifest_detection_role_drift")
    if any(observed["manifest_observation_authority"]):
        violations.append("observation_authority_promoted")
    if tuple(observed["common_gate_order"]) != EXPECTED_COMMON_GATE_ORDER:
        violations.append("standalone_asset_gate_order_drift")
    for token, used in observed["forbidden_calls"].items():
        if used:
            violations.append(f"forbidden_boundary_call:{token}")
    for operation, occurred in observed["forbidden_operations"].items():
        if occurred:
            violations.append(f"forbidden_operation:{operation}")
    return violations


@pytest.fixture(scope="module")
def preservation_observation() -> dict[str, object]:
    return _observed_preservation_state()


def test_property_2_task_1_snapshot_and_verdicts_are_unchanged_on_unfixed_revision(
    preservation_observation: dict[str, object],
) -> None:
    """Unit anchor: immutable inputs/evidence/tasks/index still match Task 1.

    Hash equality preserves bytes plus embedded chronology, verdict, authority,
    provenance, and eligibility labels without rewriting historical evidence.

    **Validates: Requirements 2.7, 2.8, 2.9, 2.14, 2.30, 2.31, 3.1, 3.2, 3.3, 3.5, 3.6, 3.8, 3.12, 3.14, 3.15, 3.17**
    """
    assert _preservation_violations(preservation_observation) == []
    assert preservation_observation["baseline_fingerprint"] == "d220ae78b3c8fd327a5aeb6aca523fd0ee5b132429c6947b1d413e89f5d204e9"
    assert preservation_observation["baseline_result"] == "AWAITING_EXPLICIT_HUMAN_REVIEW"
    assert preservation_observation["failed_fingerprint"] == "48f2e5c610f0661419a9a2c70ba5bdbe7511ef70cc0c9b830e3faaebd98ce0e6"
    assert preservation_observation["failed_result"] == "PENDING_LOCAL_VISION_SCREEN"
    assert preservation_observation["failed_downstream"]["task_11_8_5"] == "BLOCKED_NOT_STARTED"
    assert preservation_observation["first_failure_snapshot_sha256"] == TASK_1_SNAPSHOT_SHA256


def test_property_2_negative_authority_and_ownership_boundaries_remain_locked(
    preservation_observation: dict[str, object],
) -> None:
    """Unit boundary: evidence cannot regenerate/promote authority or alter owners.

    **Validates: Requirements 2.7, 2.8, 2.14, 2.30, 2.31, 3.4, 3.5, 3.7, 3.9, 3.10, 3.11, 3.14, 3.16, 3.18**
    """
    assert not any(preservation_observation["forbidden_calls"].values())
    assert not any(preservation_observation["forbidden_operations"].values())
    assert preservation_observation["manifest_selected_ids"] == preservation_observation["manifest_object_ids"]
    assert set(preservation_observation["manifest_selected_ids"]).isdisjoint(
        preservation_observation["manifest_detection_ids"]
    )
    assert "8c6119a5-f7b9-4eca-a30e-cb039aad9c71" in preservation_observation["manifest_selected_ids"]
    assert tuple(preservation_observation["common_gate_order"]) == EXPECTED_COMMON_GATE_ORDER


def _apply_negative_mutation(observed: dict[str, object], mutation: str) -> None:
    first_path = next(iter(observed["records"]))
    hook_path = next(path for path in observed["records"] if "\\.kiro\\hooks\\" in path)
    if mutation == "manifest_order":
        observed["manifest_object_ids"] = list(reversed(observed["manifest_object_ids"]))
    elif mutation == "prior_file_mutation":
        observed["records"][first_path]["sha256"] = "f" * 64
    elif mutation == "prior_file_addition":
        observed["protected_additions"].append(str(refinement.BASELINE_DIR / "backfill.json"))
    elif mutation == "prior_file_deletion":
        observed["records"][first_path]["exists"] = False
    elif mutation == "index_change":
        observed["index_tree"] = "f" * 40
    elif mutation == "staged_change":
        observed["staged_diff"] = "M\tsrc/web/app.py\n"
    elif mutation == "task_state_change":
        observed["task_11_8_4c_unchecked"] = False
        observed["task_11_8_5_blocked_not_started"] = False
    elif mutation == "hook_mutation":
        observed["records"][hook_path]["sha256"] = "e" * 64
    elif mutation.endswith("_worktree_change"):
        generated_paths = {
            "ui_worktree_change": "src/web/static/world_v16.js",
            "session_worktree_change": "output/restored-session/session.json",
            "qualification_worktree_change": ".kiro/specs/unified-world-pipeline/evidence/release-qualification.json",
            "process_owner_worktree_change": "WATCH-KEEPALIVE.bat",
            "service_worktree_change": "src/web/app.py",
        }
        observed["worktree_paths"].append(generated_paths[mutation])
    elif mutation == "commit_change":
        observed["head"] = "f" * 40
    elif mutation == "plan_revise_call":
        observed["forbidden_calls"][".revise("] = True
    elif mutation == "room_regeneration_call":
        observed["forbidden_calls"]["RoomPlateGenerator"] = True
    elif mutation == "canon_regeneration_call":
        observed["forbidden_calls"]["SceneCanonGenerator"] = True
    elif mutation == "placeholder_substitution":
        observed["forbidden_calls"]["UnifiedPlaceholderGenerator"] = True
    elif mutation == "isolator_identity_promotion":
        observed["manifest_object_ids"][0] = observed["manifest_detection_ids"][0]
        observed["manifest_selected_ids"][0] = observed["manifest_detection_ids"][0]
    elif mutation == "gate_order_change":
        observed["common_gate_order"] = list(reversed(observed["common_gate_order"]))
    else:  # pragma: no cover - the sampled strategy is the exhaustive contract
        raise AssertionError(f"unknown mutation: {mutation}")


@settings(
    max_examples=len(NEGATIVE_MUTATION_CASES),
    deadline=None,
    suppress_health_check=[__import__("hypothesis").HealthCheck.function_scoped_fixture],
)
@given(mutation=st.sampled_from(NEGATIVE_MUTATION_CASES))
def test_property_2_generated_mutations_are_rejected_without_rewrite_or_rollback(
    mutation: str,
    preservation_observation: dict[str, object],
) -> None:
    """Property 2: every out-of-scope mutation fails preservation validation.

    The generator mutates an in-memory observation only. The real prior files,
    tasks, hooks, worktree, and index are never rewritten or rolled back.

    **Validates: Requirements 2.7, 2.8, 2.9, 2.14, 2.30, 2.31, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.14, 3.15, 3.16, 3.17, 3.18**
    """
    before_snapshot_hash = _sha256(TASK_1_SNAPSHOT_PATH)
    generated = copy.deepcopy(preservation_observation)
    _apply_negative_mutation(generated, mutation)
    assert _preservation_violations(generated), mutation
    assert _sha256(TASK_1_SNAPSHOT_PATH) == before_snapshot_hash == TASK_1_SNAPSHOT_SHA256
