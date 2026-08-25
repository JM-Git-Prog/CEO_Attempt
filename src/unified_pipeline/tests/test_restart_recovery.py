"""Focused unit coverage for the Task 11.4.1 recovery boundary."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.unified_pipeline.qualification import CANONICAL_PROMPT
from src.unified_pipeline.restart_recovery import (
    COMPLETED_LLM_TASKS,
    DOWNSTREAM_LLM_TASKS,
    REQUIRED_INSPECTION_STAGES,
    CriticalPathState,
    EvidenceRecord,
    EvidenceScope,
    evaluate_release_eligibility,
    reconcile_restart_state,
)


def _governing_records(
    *,
    validated_fingerprint: str = "baseline",
    candidate_fingerprint: str = "candidate",
    services_live: bool | None = None,
) -> tuple[EvidenceRecord, ...]:
    records = [
        EvidenceRecord(
            source="tasks",
            scope=EvidenceScope.TASK,
            observed_at=600,
            active_spec="unified-world-pipeline",
            active_interface="V16",
            completed_llm_tasks=COMPLETED_LLM_TASKS,
            active_llm_tasks=frozenset(),
        ),
        EvidenceRecord(
            source="validation",
            scope=EvidenceScope.VALIDATION,
            observed_at=400,
            validated_fingerprint=validated_fingerprint,
            candidate_status="VALIDATED",
            validation_green=True,
            validation_counts=(
                ("unified_strict_real", 922),
                ("routes", 36),
                ("mesh", 53),
            ),
            supporting_checks_green=True,
        ),
        EvidenceRecord(
            source="tree",
            scope=EvidenceScope.TREE,
            observed_at=700,
            current_tree_fingerprint=candidate_fingerprint,
        ),
    ]
    if services_live is not None:
        records.append(
            EvidenceRecord(
                source="services",
                scope=EvidenceScope.SERVICE,
                observed_at=800,
                services_live=services_live,
            )
        )
    return tuple(records)


def _eligible_session(session_id: str = "qual-fresh-session") -> EvidenceRecord:
    return EvidenceRecord(
        source=f"session:{session_id}",
        scope=EvidenceScope.SESSION,
        observed_at=900,
        release_session_id=session_id,
        active_interface="V16",
        candidate_fingerprint="candidate",
        services_live=True,
        clean_live_pass=True,
        session_brand_new=True,
        session_empty_at_start=True,
        session_restored=False,
        session_reused=False,
        canonical_prompt=CANONICAL_PROMPT,
        mocked=False,
        inspected_stages=REQUIRED_INSPECTION_STAGES,
        defect=False,
    )


def test_conflicting_restart_evidence_is_order_independent_and_auditable() -> None:
    records = _governing_records() + (
        EvidenceRecord(
            source="continuation",
            scope=EvidenceScope.CONTINUATION,
            observed_at=100,
            active_spec="llm-driven-upbge-runtime",
            active_interface="V11",
            active_llm_tasks=frozenset({10, 13, 14}),
        ),
        EvidenceRecord(
            source="session:c4195e57",
            scope=EvidenceScope.SESSION,
            observed_at=500,
            release_session_id="c4195e57",
            active_interface="V16",
            release_session_eligible=True,
            clean_live_pass=False,
        ),
    )

    forward = reconcile_restart_state(records)
    reverse = reconcile_restart_state(tuple(reversed(records)))

    assert forward == reverse
    assert forward.active_spec == "unified-world-pipeline"
    assert forward.active_interface == "V16"
    assert forward.completed_llm_tasks == COMPLETED_LLM_TASKS
    assert forward.superseded_claims == frozenset({"old Task 10 continuity"})
    assert forward.active_downstream_tasks == frozenset()
    assert forward.inactive_downstream_tasks == DOWNSTREAM_LLM_TASKS
    assert forward.validated_fingerprint == "baseline"
    assert forward.current_tree_fingerprint == "candidate"
    assert forward.candidate_status == "UNVALIDATED"
    assert forward.rejected_release_evidence == frozenset({"c4195e57"})
    assert forward.critical_path_state is CriticalPathState.RECOVERED_UNVALIDATED_CANDIDATE
    assert forward.next_action == "VALIDATE_CURRENT_V16_CANDIDATE"
    assert forward.supersession_links
    assert any(
        fact.concern == "Task 10 continuity" for fact in forward.rejected_facts
    )


def test_candidate_validation_is_bound_to_the_exact_tree_fingerprint() -> None:
    mismatch = reconcile_restart_state(_governing_records())
    exact = reconcile_restart_state(
        _governing_records(
            validated_fingerprint="candidate",
            candidate_fingerprint="candidate",
        )
    )

    assert mismatch.candidate_status == "UNVALIDATED"
    assert mismatch.next_action == "VALIDATE_CURRENT_V16_CANDIDATE"
    assert exact.candidate_status == "VALIDATED"
    assert exact.validated_test_counts == (
        ("mesh", 53),
        ("routes", 36),
        ("unified_strict_real", 922),
    )
    assert exact.supporting_checks_green is True
    assert exact.next_action == "VERIFY_LOCAL_SERVICES"


@pytest.mark.parametrize(
    ("changed", "expected_reason"),
    (
        ({"release_session_id": "c4195e57"}, "known diagnostic-only session"),
        ({"session_restored": True}, "session is restored or restore status is unknown"),
        ({"canonical_prompt": "almost canonical"}, "canonical prompt does not match exactly"),
        ({"mocked": True}, "qualification contains mocks or mock status is unknown"),
        (
            {"inspected_stages": frozenset({"brief", "plan"})},
            "required stages not inspected",
        ),
        ({"defect": True}, "session has a defect or defect status is unknown"),
    ),
)
def test_release_eligibility_fails_closed_for_ineligible_sessions(
    changed: dict[str, object], expected_reason: str
) -> None:
    record = replace(_eligible_session(), **changed)

    result = evaluate_release_eligibility(
        record,
        candidate_fingerprint="candidate",
        candidate_validated=True,
        services_live=True,
    )

    assert result.eligible is False
    assert any(expected_reason in reason for reason in result.reasons)


def test_complete_exact_release_evidence_advances_monotonically() -> None:
    qualification = EvidenceRecord(
        source="qualification",
        scope=EvidenceScope.QUALIFICATION,
        observed_at=1000,
        fresh_headless_rounds=5,
        fresh_human_like_rounds=5,
    )
    records = _governing_records(
        validated_fingerprint="candidate",
        candidate_fingerprint="candidate",
        services_live=True,
    ) + (_eligible_session(), qualification)

    result = reconcile_restart_state(records)

    assert result.release_evidence == frozenset({"qual-fresh-session"})
    assert not result.rejected_release_evidence
    assert result.release_status == "COMPLETE"
    assert result.critical_path_state is CriticalPathState.RELEASE_ELIGIBLE
    assert result.next_action == "FINALIZE_RELEASE_EVIDENCE"
    assert len(result.accepted_facts) >= 1
    assert all(len(digest) == 64 for _, digest in result.evidence_fingerprints)


def test_equal_authority_conflict_is_rejected_instead_of_order_selected() -> None:
    records = (
        EvidenceRecord(
            source="tasks-a",
            scope=EvidenceScope.TASK,
            observed_at=10,
            active_spec="unified-world-pipeline",
        ),
        EvidenceRecord(
            source="tasks-b",
            scope=EvidenceScope.TASK,
            observed_at=10,
            active_spec="llm-driven-upbge-runtime",
        ),
    )

    result = reconcile_restart_state(records)

    assert result.active_spec is None
    ambiguous = [
        fact
        for fact in result.rejected_facts
        if fact.concern == "active specification"
    ]
    assert len(ambiguous) == 2
    assert all(fact.reason == "ambiguous equal-authority evidence tie" for fact in ambiguous)
