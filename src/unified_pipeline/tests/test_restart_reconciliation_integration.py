"""Offline integration coverage for Task 11.4.4 restart reconciliation.

The tests reconstruct evidence and orchestrator instances from durable files. They
never create qualification sessions or contact local services.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.2, 3.3, 3.6**
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import fields
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.unified_pipeline.orchestrator import (
    CheckpointState,
    ExternalJobResult,
    ExternalJobState,
    LeaseConflictError,
    StageResult,
    StageSpec,
    UnifiedOrchestrator,
)
from src.unified_pipeline.qualification import CANONICAL_PROMPT
from src.unified_pipeline.restart_recovery import (
    COMPLETED_LLM_TASKS,
    DOWNSTREAM_LLM_TASKS,
    REQUIRED_INSPECTION_STAGES,
    CriticalPathState,
    EvidenceRecord,
    EvidenceScope,
    reconcile_restart_state,
)


BASELINE_FINGERPRINT = "a" * 64
CANDIDATE_FINGERPRINT = "b" * 64
CHANGED_TREE_FINGERPRINT = "c" * 64
BASELINE_COUNTS = (
    ("unified_strict_real", 922),
    ("routes", 36),
    ("mesh", 53),
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _persist_and_reload(
    path: Path,
    records: tuple[EvidenceRecord, ...],
    *,
    reverse: bool = False,
) -> tuple[SimpleNamespace, ...]:
    """Cross a JSON process boundary and return fresh attribute records."""
    payload = [
        {item.name: _jsonable(getattr(record, item.name)) for item in fields(record)}
        for record in records
    ]
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if reverse:
        decoded.reverse()
    return tuple(SimpleNamespace(**item) for item in decoded)


def _task_record() -> EvidenceRecord:
    return EvidenceRecord(
        source="tasks",
        scope=EvidenceScope.TASK,
        observed_at=600,
        active_spec="unified-world-pipeline",
        active_interface="V16",
        completed_llm_tasks=COMPLETED_LLM_TASKS,
        active_llm_tasks=frozenset(),
    )


def _historical_continuation() -> EvidenceRecord:
    return EvidenceRecord(
        source="continuation",
        scope=EvidenceScope.CONTINUATION,
        observed_at=100,
        active_spec="llm-driven-upbge-runtime",
        active_interface="V11",
        active_llm_tasks=frozenset({10, 13, 14}),
    )


def _validation(fingerprint: str, observed_at: int) -> EvidenceRecord:
    return EvidenceRecord(
        source=f"validation:{fingerprint[:8]}",
        scope=EvidenceScope.VALIDATION,
        observed_at=observed_at,
        validated_fingerprint=fingerprint,
        candidate_status="VALIDATED",
        validation_green=True,
        validation_counts=BASELINE_COUNTS,
        supporting_checks_green=True,
    )


def _tree(fingerprint: str, observed_at: int) -> EvidenceRecord:
    return EvidenceRecord(
        source=f"tree:{fingerprint[:8]}",
        scope=EvidenceScope.TREE,
        observed_at=observed_at,
        current_tree_fingerprint=fingerprint,
    )


def _services(observed_at: int = 900) -> EvidenceRecord:
    return EvidenceRecord(
        source="services",
        scope=EvidenceScope.SERVICE,
        observed_at=observed_at,
        services_live=True,
    )


def _eligible_session(
    session_id: str,
    fingerprint: str,
    observed_at: int,
    **changes: Any,
) -> EvidenceRecord:
    values: dict[str, Any] = {
        "source": f"session:{session_id}",
        "scope": EvidenceScope.SESSION,
        "observed_at": observed_at,
        "release_session_id": session_id,
        "release_session_eligible": True,
        "release_status": "COMPLETE",
        "active_interface": "V16",
        "candidate_fingerprint": fingerprint,
        "services_live": True,
        "clean_live_pass": True,
        "session_brand_new": True,
        "session_empty_at_start": True,
        "session_restored": False,
        "session_reused": False,
        "canonical_prompt": CANONICAL_PROMPT,
        "mocked": False,
        "inspected_stages": REQUIRED_INSPECTION_STAGES,
        "defect": False,
    }
    values.update(changes)
    return EvidenceRecord(**values)


def _known_conflicting_checkpoint() -> tuple[EvidenceRecord, ...]:
    return (
        _task_record(),
        _historical_continuation(),
        _validation(BASELINE_FINGERPRINT, 400),
        _tree(CANDIDATE_FINGERPRINT, 700),
        _eligible_session(
            "c4195e57",
            BASELINE_FINGERPRINT,
            500,
            services_live=None,
            clean_live_pass=False,
            session_brand_new=False,
            session_empty_at_start=False,
            session_restored=True,
            session_reused=True,
            canonical_prompt="non-canonical diagnostic prompt",
            mocked=True,
            inspected_stages=frozenset({"brief", "plan"}),
            defect=True,
        ),
    )


def test_process_and_agent_restart_progress_monotonically_without_erasing_baseline(
    tmp_path: Path,
) -> None:
    """Reload the known conflict, then cross each critical-path restart gate."""
    checkpoint_path = tmp_path / "restart-evidence.json"
    records = _known_conflicting_checkpoint()
    baseline_digest = records[2].source_digest

    process_restart = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records)
    )
    agent_restart = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records, reverse=True)
    )

    assert process_restart == agent_restart
    assert process_restart.critical_path_state is (
        CriticalPathState.RECOVERED_UNVALIDATED_CANDIDATE
    )
    assert process_restart.next_action == "VALIDATE_CURRENT_V16_CANDIDATE"
    assert process_restart.completed_llm_tasks == COMPLETED_LLM_TASKS
    assert process_restart.inactive_downstream_tasks == DOWNSTREAM_LLM_TASKS
    assert process_restart.rejected_release_evidence == frozenset({"c4195e57"})

    records += (_validation(CANDIDATE_FINGERPRINT, 800),)
    validated = reconcile_restart_state(_persist_and_reload(checkpoint_path, records))
    records += (_services(),)
    services_verified = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records, reverse=True)
    )
    records += (_eligible_session("qual-fresh-v16", CANDIDATE_FINGERPRINT, 1000),)
    zero_state_passed = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records)
    )
    records += (
        EvidenceRecord(
            source="qualification:headless",
            scope=EvidenceScope.QUALIFICATION,
            observed_at=1100,
            fresh_headless_rounds=5,
            fresh_human_like_rounds=0,
        ),
    )
    fresh_rounds = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records, reverse=True)
    )
    records += (
        EvidenceRecord(
            source="qualification:complete",
            scope=EvidenceScope.QUALIFICATION,
            observed_at=1200,
            fresh_headless_rounds=5,
            fresh_human_like_rounds=5,
        ),
    )
    release_eligible = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records)
    )

    assert [
        validated.critical_path_state,
        services_verified.critical_path_state,
        zero_state_passed.critical_path_state,
        fresh_rounds.critical_path_state,
        release_eligible.critical_path_state,
    ] == [
        CriticalPathState.CANDIDATE_VALIDATED,
        CriticalPathState.ZERO_STATE_FAILED,
        CriticalPathState.ZERO_STATE_PASSED,
        CriticalPathState.FRESH_ROUNDS_RUNNING,
        CriticalPathState.RELEASE_ELIGIBLE,
    ]
    assert [
        validated.next_action,
        services_verified.next_action,
        zero_state_passed.next_action,
        fresh_rounds.next_action,
        release_eligible.next_action,
    ] == [
        "VERIFY_LOCAL_SERVICES",
        "RUN_CLEAN_ZERO_STATE_V16",
        "RUN_FIVE_FRESH_HEADLESS_ROUNDS",
        "RUN_FIVE_FRESH_HUMAN_LIKE_ROUNDS",
        "FINALIZE_RELEASE_EVIDENCE",
    ]
    assert release_eligible.release_status == "COMPLETE"
    assert release_eligible.release_evidence == frozenset({"qual-fresh-v16"})

    # New validation governs the candidate while the exact prior baseline remains
    # in the immutable input evidence and auditable rejected-fact history.
    assert ("validation:aaaaaaaa", baseline_digest) in release_eligible.evidence_fingerprints
    assert any(
        fact.source_digest == baseline_digest
        and BASELINE_FINGERPRINT in fact.value
        and fact.reason == "lower-authority or older conflicting evidence"
        for fact in release_eligible.rejected_facts
    )


def test_relevant_tree_change_demotes_release_and_invalid_transitions_fail_closed(
    tmp_path: Path,
) -> None:
    """A new tree cannot inherit validation, live services, rounds, or release claims."""
    checkpoint_path = tmp_path / "tree-change-evidence.json"
    records = (
        _task_record(),
        _validation(CANDIDATE_FINGERPRINT, 800),
        _tree(CANDIDATE_FINGERPRINT, 700),
        _services(),
        _eligible_session("qual-clean-before-change", CANDIDATE_FINGERPRINT, 1000),
        EvidenceRecord(
            source="qualification:complete",
            scope=EvidenceScope.QUALIFICATION,
            observed_at=1100,
            fresh_headless_rounds=5,
            fresh_human_like_rounds=5,
        ),
    )
    before_change = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records)
    )
    assert before_change.critical_path_state is CriticalPathState.RELEASE_ELIGIBLE

    changed_records = records + (_tree(CHANGED_TREE_FINGERPRINT, 1200),)
    after_change = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, changed_records, reverse=True)
    )

    assert after_change.validated_fingerprint == CANDIDATE_FINGERPRINT
    assert after_change.current_tree_fingerprint == CHANGED_TREE_FINGERPRINT
    assert after_change.candidate_status == "UNVALIDATED"
    assert after_change.critical_path_state is (
        CriticalPathState.RECOVERED_UNVALIDATED_CANDIDATE
    )
    assert after_change.next_action == "VALIDATE_CURRENT_V16_CANDIDATE"
    assert after_change.release_status == "INCOMPLETE"
    assert not after_change.release_evidence
    assert after_change.rejected_release_evidence == frozenset(
        {"qual-clean-before-change"}
    )
    assert any(
        "session is not bound to the exact candidate fingerprint" in reasons
        for session_id, reasons in after_change.release_ineligibility_reasons
        if session_id == "qual-clean-before-change"
    )

    # Even explicit release/service/round claims cannot jump over exact validation.
    claimed_release = _eligible_session(
        "qual-claimed-for-changed-tree",
        CHANGED_TREE_FINGERPRINT,
        1300,
    )
    invalid_transition = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, changed_records + (claimed_release,))
    )
    assert invalid_transition.critical_path_state is (
        CriticalPathState.RECOVERED_UNVALIDATED_CANDIDATE
    )
    assert invalid_transition.next_action == "VALIDATE_CURRENT_V16_CANDIDATE"
    assert "qual-claimed-for-changed-tree" in (
        invalid_transition.rejected_release_evidence
    )
    assert not invalid_transition.active_downstream_tasks


def test_failed_and_restored_sessions_remain_diagnostic_only_after_restart(
    tmp_path: Path,
) -> None:
    checkpoint_path = tmp_path / "ineligible-session-evidence.json"
    failed = _eligible_session(
        "qual-failed-v16",
        CANDIDATE_FINGERPRINT,
        1000,
        clean_live_pass=False,
        defect=True,
    )
    restored = _eligible_session(
        "qual-restored-v16",
        CANDIDATE_FINGERPRINT,
        1100,
        session_brand_new=False,
        session_empty_at_start=False,
        session_restored=True,
        session_reused=True,
    )
    records = (
        _task_record(),
        _validation(CANDIDATE_FINGERPRINT, 800),
        _tree(CANDIDATE_FINGERPRINT, 700),
        _services(),
        failed,
        restored,
    )

    result = reconcile_restart_state(
        _persist_and_reload(checkpoint_path, records, reverse=True)
    )

    assert not result.release_evidence
    assert result.rejected_release_evidence == frozenset(
        {"qual-failed-v16", "qual-restored-v16"}
    )
    assert result.critical_path_state is CriticalPathState.ZERO_STATE_FAILED
    assert result.next_action == "RUN_CLEAN_ZERO_STATE_V16"
    reasons = dict(result.release_ineligibility_reasons)
    assert "session has a defect or defect status is unknown" in reasons[
        "qual-failed-v16"
    ]
    assert "session is restored or restore status is unknown" in reasons[
        "qual-restored-v16"
    ]
    assert "session is reused or reuse status is unknown" in reasons[
        "qual-restored-v16"
    ]


class _RecordedExternalJobController:
    """Offline implementation of the durable external-job protocol."""

    def __init__(self, result: ExternalJobResult) -> None:
        self.result = result
        self.reconciled: list[str] = []
        self.cancelled: list[tuple[str, str]] = []

    async def reconcile(self, job_id: str) -> ExternalJobResult:
        self.reconciled.append(job_id)
        return self.result

    async def cancel(self, job_id: str, reason: str) -> bool:
        self.cancelled.append((job_id, reason))
        return True


def test_durable_external_job_restart_has_one_lease_writer_and_idempotent_reconcile(
    tmp_path: Path,
) -> None:
    """Reconstruct from disk, reconcile once, and retain exclusive ownership."""
    calls = {"plan": 0, "gpu": 0, "publish": 0}

    def plan(_context: Any) -> StageResult:
        calls["plan"] += 1
        return StageResult(
            output={
                "candidate_fingerprint": CANDIDATE_FINGERPRINT,
                "plan_revision": 4,
            },
            plan_revision=4,
        )

    def gpu(_context: Any) -> StageResult:
        calls["gpu"] += 1
        return StageResult.pending("durable-v16-job", plan_revision=4)

    def publish(_context: Any) -> StageResult:
        calls["publish"] += 1
        return StageResult(
            output={"published_fingerprint": CANDIDATE_FINGERPRINT},
            plan_revision=4,
        )

    stages = (StageSpec("plan"), StageSpec("gpu"), StageSpec("publish"))
    handlers = {"plan": plan, "gpu": gpu, "publish": publish}
    initial_context = {
        "candidate_fingerprint": CANDIDATE_FINGERPRINT,
        "validated_fingerprint": CANDIDATE_FINGERPRINT,
        "interface_version": 16,
    }
    first = UnifiedOrchestrator(
        session_id="durable-v16-integration",
        session_dir=tmp_path,
        handlers=handlers,
        external_jobs=_RecordedExternalJobController(
            ExternalJobResult(ExternalJobState.RUNNING, response_revision=4)
        ),
        stages=stages,
        worker_id="process-before-restart",
    )
    first_result = asyncio.run(first.run(initial_context))
    assert first_result.state == "awaiting_external"
    assert calls == {"plan": 1, "gpu": 1, "publish": 0}

    controller = _RecordedExternalJobController(
        ExternalJobResult(
            ExternalJobState.SUCCEEDED,
            output={
                "asset": "durable.glb",
                "candidate_fingerprint": CANDIDATE_FINGERPRINT,
            },
            response_revision=4,
        )
    )
    resumed = UnifiedOrchestrator(
        session_id="durable-v16-integration",
        session_dir=tmp_path,
        handlers=handlers,
        external_jobs=controller,
        stages=stages,
        worker_id="agent-after-restart",
    )

    reconciled_once = asyncio.run(resumed.reconcile_pending())
    reconciled_twice = asyncio.run(resumed.reconcile_pending())
    completed = asyncio.run(resumed.run(initial_context))

    assert len(reconciled_once) == 1
    assert reconciled_once[0].state == CheckpointState.COMPLETED.value
    assert reconciled_twice == ()
    assert completed.state == "completed"
    assert controller.reconciled == ["durable-v16-job"]
    assert not controller.cancelled
    assert calls == {"plan": 1, "gpu": 1, "publish": 1}
    gpu_checkpoint = resumed.store.load("gpu")
    assert gpu_checkpoint is not None
    assert gpu_checkpoint.completion_state is CheckpointState.COMPLETED
    assert gpu_checkpoint.output["candidate_fingerprint"] == CANDIDATE_FINGERPRINT

    with resumed.ownership.worker("held-worker"):
        with pytest.raises(LeaseConflictError, match="held-worker"):
            asyncio.run(resumed.reconcile_pending())
    with resumed.ownership.worker("replacement-worker"):
        pass

    with resumed.approval_writer("writer-one"):
        with pytest.raises(LeaseConflictError, match="writer-one"):
            with resumed.approval_writer("writer-two"):
                pass
    with resumed.approval_writer("writer-two"):
        pass
