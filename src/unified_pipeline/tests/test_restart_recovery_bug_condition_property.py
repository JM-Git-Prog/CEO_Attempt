"""Exploration property for conflicting restart-continuity evidence.

Property 1: Bug Condition - Restart Recovery Reconciles Conflicting Evidence

This began as an observation-first test against the unfixed retrieval-order path.
Task 11.4.1 now wires the same generated snapshots and expected-behavior
assertions to the production restart reconciler; the property itself remains
unchanged for Task 11.4.2 verification.

**Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from hypothesis import given, settings, strategies as st

from src.unified_pipeline.restart_recovery import (
    ReconciliationResult,
    reconcile_restart_state,
)


CANONICAL_PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)
DIAGNOSTIC_SESSION_IDS = (
    "8f24afd0",
    "8b5057d3",
    "473caae9",
    "fb163c47",
    "b7dd26d5",
    "32c30b0f",
    "c4195e57",
)
COMPLETED_LLM_TASKS = frozenset(range(1, 13))
DOWNSTREAM_LLM_TASKS = frozenset({13, 14})
RECORD_NAMES = (
    "tasks",
    "continuation",
    "validation",
    "tree",
    "session",
    "qualification",
)


@dataclass(frozen=True)
class EvidenceRecord:
    """One immutable, scoped claim visible to restart recovery."""

    source: str
    observed_at: int
    active_spec: str | None = None
    active_interface: str | None = None
    completed_llm_tasks: frozenset[int] | None = None
    active_llm_tasks: frozenset[int] | None = None
    validated_fingerprint: str | None = None
    current_tree_fingerprint: str | None = None
    candidate_status: str | None = None
    release_status: str | None = None
    release_session_id: str | None = None
    release_session_eligible: bool | None = None
    clean_live_pass: bool | None = None
    next_action: str | None = None


@dataclass(frozen=True, repr=False)
class RecoverySnapshot:
    """Immutable restart fixture in which every specified bug trigger holds."""

    records: tuple[EvidenceRecord, ...]
    baseline_fingerprint: str
    candidate_fingerprint: str
    diagnostic_session_id: str
    source_order: tuple[str, ...]

    def __repr__(self) -> str:
        """Keep Hypothesis counterexamples concise but evidence-complete."""
        return (
            "RecoverySnapshot("
            f"baseline_fingerprint={self.baseline_fingerprint!r}, "
            f"candidate_fingerprint={self.candidate_fingerprint!r}, "
            f"diagnostic_session_id={self.diagnostic_session_id!r}, "
            f"source_order={self.source_order!r}, "
            "stale_task_10=True, completed_tasks='1-12', "
            "no_clean_live_pass=True, premature_tasks=(13, 14))"
        )


def _bug_facts(snapshot: RecoverySnapshot) -> dict[str, bool]:
    """Evaluate each required bug-condition component independently."""
    records = {record.source: record for record in snapshot.records}
    continuation = records["continuation"]
    tasks = records["tasks"]
    session = records["session"]
    qualification = records["qualification"]

    return {
        "stale_task_10": (
            10 in (continuation.active_llm_tasks or frozenset())
            and tasks.completed_llm_tasks == COMPLETED_LLM_TASKS
        ),
        "conflicting_scopes": (
            continuation.active_spec == "llm-driven-upbge-runtime"
            and tasks.active_spec == "unified-world-pipeline"
        ),
        "fingerprint_mismatch": (
            snapshot.candidate_fingerprint != snapshot.baseline_fingerprint
        ),
        "diagnostic_session_reuse": (
            session.release_session_id in DIAGNOSTIC_SESSION_IDS
            and session.release_session_eligible is True
        ),
        "no_clean_live_pass": qualification.clean_live_pass is False,
        "premature_downstream_activation": (
            DOWNSTREAM_LLM_TASKS
            <= (continuation.active_llm_tasks or frozenset())
        ),
    }


def is_bug_condition(snapshot: RecoverySnapshot) -> bool:
    """Formal C(X): at least one conflicting/unvalidated claim exists."""
    return any(_bug_facts(snapshot).values())


def _expected_behavior_violations(
    result: ReconciliationResult,
    snapshot: RecoverySnapshot,
) -> tuple[str, ...]:
    """Return named violations of the Property 1 expected result."""
    checks = {
        "V16 remains the governing active interface": (
            result.active_spec == "unified-world-pipeline"
            and result.active_interface == "V16"
        ),
        "llm-driven Tasks 1-12 remain complete": (
            result.completed_llm_tasks == COMPLETED_LLM_TASKS
        ),
        "old Task 10 continuity is superseded": (
            "old Task 10 continuity" in result.superseded_claims
        ),
        "Tasks 13-14 remain inactive": (
            not result.active_downstream_tasks
            and result.inactive_downstream_tasks == DOWNSTREAM_LLM_TASKS
        ),
        "validation remains bound to the exact baseline fingerprint": (
            result.validated_fingerprint == snapshot.baseline_fingerprint
            and result.validated_fingerprint != snapshot.candidate_fingerprint
            and result.current_tree_fingerprint == snapshot.candidate_fingerprint
        ),
        "newer repairs remain unvalidated": result.candidate_status == "UNVALIDATED",
        "release qualification remains incomplete": (
            result.release_status == "INCOMPLETE"
        ),
        "diagnostic sessions are rejected": (
            not result.release_evidence
            and snapshot.diagnostic_session_id in result.rejected_release_evidence
        ),
        "the first unmet V16 gate is selected": (
            result.next_action == "VALIDATE_CURRENT_V16_CANDIDATE"
        ),
    }
    return tuple(name for name, passed in checks.items() if not passed)


def expected_behavior(
    result: ReconciliationResult,
    snapshot: RecoverySnapshot,
) -> bool:
    """Formal P(R(X)) from the restart-continuity design."""
    return not _expected_behavior_violations(result, snapshot)


@st.composite
def bug_condition_snapshots(draw: st.DrawFn) -> RecoverySnapshot:
    """Generate all required conflicts plus arbitrary source-order permutations."""
    seed = draw(st.integers(min_value=0, max_value=255))
    diagnostic_session_id = draw(st.sampled_from(DIAGNOSTIC_SESSION_IDS))
    source_order = tuple(draw(st.permutations(RECORD_NAMES)))

    baseline_fingerprint = sha256(f"baseline:{seed}".encode("ascii")).hexdigest()
    candidate_fingerprint = sha256(f"candidate:{seed}".encode("ascii")).hexdigest()

    by_source = {
        "tasks": EvidenceRecord(
            source="tasks",
            observed_at=600,
            active_spec="unified-world-pipeline",
            active_interface="V16",
            completed_llm_tasks=COMPLETED_LLM_TASKS,
            active_llm_tasks=frozenset(),
            next_action="VALIDATE_CURRENT_V16_CANDIDATE",
        ),
        "continuation": EvidenceRecord(
            source="continuation",
            observed_at=100,
            active_spec="llm-driven-upbge-runtime",
            active_interface="V11",
            completed_llm_tasks=frozenset(range(1, 10)),
            active_llm_tasks=frozenset({10, 13, 14}),
            next_action="RESUME_TASK_10",
        ),
        "validation": EvidenceRecord(
            source="validation",
            observed_at=400,
            validated_fingerprint=baseline_fingerprint,
            candidate_status="VALIDATED",
            release_status="QUALIFIED",
        ),
        "tree": EvidenceRecord(
            source="tree",
            observed_at=700,
            current_tree_fingerprint=candidate_fingerprint,
            candidate_status="UNVALIDATED",
            next_action="VALIDATE_CURRENT_V16_CANDIDATE",
        ),
        "session": EvidenceRecord(
            source="session",
            observed_at=500,
            active_interface="V16",
            release_status="QUALIFIED",
            release_session_id=diagnostic_session_id,
            release_session_eligible=True,
            clean_live_pass=False,
        ),
        "qualification": EvidenceRecord(
            source="qualification",
            observed_at=300,
            active_interface="V16",
            release_status="INCOMPLETE",
            clean_live_pass=False,
            next_action="VERIFY_LOCAL_SERVICES",
        ),
    }
    records = tuple(by_source[name] for name in source_order)
    snapshot = RecoverySnapshot(
        records=records,
        baseline_fingerprint=baseline_fingerprint,
        candidate_fingerprint=candidate_fingerprint,
        diagnostic_session_id=diagnostic_session_id,
        source_order=source_order,
    )

    # The strategy must never dilute Task 11.2 into a partial bug fixture.
    assert all(_bug_facts(snapshot).values())
    return snapshot


# Property 1: Bug Condition - Restart Recovery Reconciles Conflicting Evidence
@given(snapshot=bug_condition_snapshots())
@settings(max_examples=100, deadline=None, derandomize=True)
def test_property_1_restart_recovery_reconciles_conflicting_evidence(
    snapshot: RecoverySnapshot,
) -> None:
    """Every bug-condition snapshot must reconcile to evidence-honest V16 truth.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6**
    **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6**
    """
    assert is_bug_condition(snapshot)

    result = reconcile_restart_state(snapshot)
    violations = _expected_behavior_violations(result, snapshot)

    assert expected_behavior(result, snapshot), (
        "unfixed restart recovery violated Property 1: "
        f"{violations!r}; result={result!r}"
    )
