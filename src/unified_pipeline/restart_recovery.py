"""Deterministic restart-continuity reconciliation for Unified Pipeline V16.

This module is deliberately outside the durable runtime orchestrator.  It reconciles
restart evidence into an operator checkpoint without changing session checkpoints,
retained interfaces, qualification artifacts, or external jobs.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from .qualification import CANONICAL_PROMPT


COMPLETED_LLM_TASKS = frozenset(range(1, 13))
DOWNSTREAM_LLM_TASKS = frozenset({13, 14})
DIAGNOSTIC_SESSION_IDS = frozenset(
    {
        "8f24afd0",
        "8b5057d3",
        "473caae9",
        "fb163c47",
        "b7dd26d5",
        "32c30b0f",
        "c4195e57",
    }
)
REQUIRED_INSPECTION_STAGES = frozenset(
    {"brief", "plan", "blockout", "canon", "world", "compare"}
)


class EvidenceScope(str, Enum):
    """Concern scope carried by one restart evidence record."""

    TASK = "task"
    MEMORY = "memory"
    CONTINUATION = "continuation"
    VALIDATION = "validation"
    TREE = "tree"
    SERVICE = "service"
    SESSION = "session"
    QUALIFICATION = "qualification"
    UNKNOWN = "unknown"


class CriticalPathState(str, Enum):
    """Monotonic V16 recovery states used to select exactly one next action."""

    RECOVERED_UNVALIDATED_CANDIDATE = "RECOVERED_UNVALIDATED_CANDIDATE"
    CANDIDATE_VALIDATED = "CANDIDATE_VALIDATED"
    SERVICES_VERIFIED = "SERVICES_VERIFIED"
    ZERO_STATE_RUNNING = "ZERO_STATE_RUNNING"
    ZERO_STATE_FAILED = "ZERO_STATE_FAILED"
    ZERO_STATE_PASSED = "ZERO_STATE_PASSED"
    FRESH_ROUNDS_RUNNING = "FRESH_ROUNDS_RUNNING"
    RELEASE_ELIGIBLE = "RELEASE_ELIGIBLE"


@dataclass(frozen=True)
class EvidenceRecord:
    """Normalized immutable fact from one scoped recovery source.

    ``source_digest`` binds the complete source payload.  ``revision`` and the
    explicit tree fingerprints prevent green evidence from floating to a newer
    candidate.  Session eligibility fields are intentionally optional: missing
    proof fails closed rather than being inferred from a claimed status.
    """

    source: str
    observed_at: int | float | str
    scope: EvidenceScope = EvidenceScope.UNKNOWN
    source_digest: str = ""
    revision: int | str | None = None
    tree_fingerprint: str | None = None
    supersedes: tuple[str, ...] = ()

    active_spec: str | None = None
    active_interface: str | None = None
    completed_llm_tasks: frozenset[int] | None = None
    active_llm_tasks: frozenset[int] | None = None

    validated_fingerprint: str | None = None
    current_tree_fingerprint: str | None = None
    candidate_fingerprint: str | None = None
    candidate_status: str | None = None
    validation_green: bool | None = None
    validation_counts: tuple[tuple[str, int], ...] = ()
    supporting_checks_green: bool | None = None

    services_live: bool | None = None
    release_status: str | None = None
    release_session_id: str | None = None
    release_session_eligible: bool | None = None
    clean_live_pass: bool | None = None
    session_brand_new: bool | None = None
    session_empty_at_start: bool | None = None
    session_restored: bool | None = None
    session_reused: bool | None = None
    canonical_prompt: str | None = None
    mocked: bool | None = None
    inspected_stages: frozenset[str] | None = None
    required_stages: frozenset[str] | None = None
    defect: bool | None = None
    fresh_headless_rounds: int | None = None
    fresh_human_like_rounds: int | None = None
    next_action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, EvidenceScope):
            object.__setattr__(self, "scope", EvidenceScope(str(self.scope)))
        object.__setattr__(self, "supersedes", tuple(sorted(self.supersedes)))
        for field_name in (
            "completed_llm_tasks",
            "active_llm_tasks",
            "inspected_stages",
            "required_stages",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, frozenset):
                object.__setattr__(self, field_name, frozenset(value))
        if self.validation_counts:
            object.__setattr__(
                self,
                "validation_counts",
                tuple(sorted((str(name), int(count)) for name, count in self.validation_counts)),
            )
        if not self.source_digest:
            payload = {
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "source_digest"
            }
            object.__setattr__(self, "source_digest", _digest(payload))


@dataclass(frozen=True)
class RecoverySnapshot:
    """Typed collection of normalized evidence visible at one restart."""

    records: tuple[EvidenceRecord, ...]


@dataclass(frozen=True)
class AuditFact:
    """One accepted or rejected conclusion with provenance."""

    concern: str
    source: str
    source_digest: str
    value: str
    reason: str
    superseded_by: str | None = None


@dataclass(frozen=True)
class ReleaseEligibility:
    """Fail-closed result for one possible qualification session."""

    session_id: str
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReconciliationResult:
    """Evidence-honest restart checkpoint and its audit trail."""

    active_spec: str | None
    active_interface: str | None
    completed_llm_tasks: frozenset[int]
    superseded_claims: frozenset[str]
    active_downstream_tasks: frozenset[int]
    inactive_downstream_tasks: frozenset[int]
    validated_fingerprint: str | None
    current_tree_fingerprint: str | None
    candidate_status: str
    validated_test_counts: tuple[tuple[str, int], ...]
    supporting_checks_green: bool | None
    service_status: str
    release_status: str
    release_evidence: frozenset[str]
    rejected_release_evidence: frozenset[str]
    release_ineligibility_reasons: tuple[tuple[str, tuple[str, ...]], ...]
    critical_path_state: CriticalPathState
    next_action: str
    accepted_facts: tuple[AuditFact, ...]
    rejected_facts: tuple[AuditFact, ...]
    evidence_fingerprints: tuple[tuple[str, str], ...]
    supersession_links: tuple[tuple[str, str], ...]


_SCOPE_BY_SOURCE = {
    "tasks": EvidenceScope.TASK,
    "task": EvidenceScope.TASK,
    "memory": EvidenceScope.MEMORY,
    "continuation": EvidenceScope.CONTINUATION,
    "validation": EvidenceScope.VALIDATION,
    "tree": EvidenceScope.TREE,
    "service": EvidenceScope.SERVICE,
    "services": EvidenceScope.SERVICE,
    "session": EvidenceScope.SESSION,
    "qualification": EvidenceScope.QUALIFICATION,
}

_TASK_AUTHORITY = {
    EvidenceScope.TASK: 50,
    EvidenceScope.MEMORY: 30,
    EvidenceScope.QUALIFICATION: 20,
    EvidenceScope.SESSION: 15,
    EvidenceScope.CONTINUATION: 10,
    EvidenceScope.UNKNOWN: 0,
}
_VALIDATION_AUTHORITY = {
    EvidenceScope.VALIDATION: 50,
    EvidenceScope.TREE: 20,
    EvidenceScope.QUALIFICATION: 10,
    EvidenceScope.UNKNOWN: 0,
}
_TREE_AUTHORITY = {
    EvidenceScope.TREE: 50,
    EvidenceScope.VALIDATION: 20,
    EvidenceScope.UNKNOWN: 0,
}
_SERVICE_AUTHORITY = {
    EvidenceScope.SERVICE: 50,
    EvidenceScope.QUALIFICATION: 20,
    EvidenceScope.SESSION: 10,
    EvidenceScope.UNKNOWN: 0,
}
_QUALIFICATION_AUTHORITY = {
    EvidenceScope.QUALIFICATION: 50,
    EvidenceScope.SESSION: 30,
    EvidenceScope.UNKNOWN: 0,
}


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        canonical = [_canonicalize(item) for item in value]
        return sorted(canonical, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _canonicalize(value), sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _infer_scope(source: str) -> EvidenceScope:
    normalized = source.strip().lower()
    if normalized in _SCOPE_BY_SOURCE:
        return _SCOPE_BY_SOURCE[normalized]
    for token, scope in _SCOPE_BY_SOURCE.items():
        if token in normalized:
            return scope
    return EvidenceScope.UNKNOWN


def normalize_evidence(raw: Any) -> EvidenceRecord:
    """Normalize a typed record or immutable fixture into production evidence."""
    if isinstance(raw, EvidenceRecord):
        return raw

    source = str(getattr(raw, "source", "unknown"))
    raw_scope = getattr(raw, "scope", None)
    scope = _infer_scope(source) if raw_scope is None else EvidenceScope(str(raw_scope))
    kwargs: dict[str, Any] = {
        "source": source,
        "scope": scope,
        "observed_at": getattr(raw, "observed_at", 0),
    }
    for item in fields(EvidenceRecord):
        if item.name in {"source", "scope", "observed_at", "source_digest"}:
            continue
        if hasattr(raw, item.name):
            kwargs[item.name] = getattr(raw, item.name)

    raw_digest = getattr(raw, "source_digest", "")
    if raw_digest:
        kwargs["source_digest"] = str(raw_digest)
    return EvidenceRecord(**kwargs)


def normalize_recovery_snapshot(snapshot: Any) -> RecoverySnapshot:
    """Return order-independent, digest-bound evidence for reconciliation."""
    raw_records: Iterable[Any]
    if isinstance(snapshot, RecoverySnapshot):
        raw_records = snapshot.records
    elif hasattr(snapshot, "records"):
        raw_records = getattr(snapshot, "records")
    else:
        raw_records = snapshot
    records = tuple(
        sorted(
            (normalize_evidence(record) for record in raw_records),
            key=lambda record: (record.scope.value, record.source, record.source_digest),
        )
    )
    return RecoverySnapshot(records=records)


def _timestamp_key(value: int | float | str) -> tuple[int, float, str]:
    if isinstance(value, (int, float)):
        return (2, float(value), "")
    text = str(value)
    try:
        return (2, float(text), "")
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (2, parsed.timestamp(), "")
    except ValueError:
        return (1, 0.0, text)


def _audit_sort_key(fact: AuditFact) -> tuple[str, str, str, str, str]:
    return (fact.concern, fact.source, fact.source_digest, fact.reason, fact.value)


def _value_key(value: Any) -> str:
    return json.dumps(_canonicalize(value), sort_keys=True, separators=(",", ":"), default=str)


def _explicit_superseder(
    record: EvidenceRecord, records: tuple[EvidenceRecord, ...]
) -> EvidenceRecord | None:
    for candidate in records:
        if candidate is record:
            continue
        if record.source in candidate.supersedes or record.source_digest in candidate.supersedes:
            return candidate
    return None


def _resolve_claim(
    records: tuple[EvidenceRecord, ...],
    *,
    field_name: str,
    concern: str,
    authority: Mapping[EvidenceScope, int],
) -> tuple[Any, EvidenceRecord | None, list[AuditFact], list[AuditFact]]:
    """Resolve one concern, rejecting same-rank/same-time contradictory ties."""
    candidates = [record for record in records if getattr(record, field_name) is not None]
    accepted: list[AuditFact] = []
    rejected: list[AuditFact] = []
    active: list[EvidenceRecord] = []

    for record in candidates:
        superseder = _explicit_superseder(record, records)
        if superseder is not None:
            rejected.append(
                AuditFact(
                    concern=concern,
                    source=record.source,
                    source_digest=record.source_digest,
                    value=_value_key(getattr(record, field_name)),
                    reason="explicitly superseded evidence",
                    superseded_by=superseder.source_digest,
                )
            )
        else:
            active.append(record)

    if not active:
        return None, None, accepted, rejected

    best_authority = max(authority.get(record.scope, -1) for record in active)
    authoritative = [
        record for record in active if authority.get(record.scope, -1) == best_authority
    ]
    best_timestamp = max(_timestamp_key(record.observed_at) for record in authoritative)
    finalists = [
        record
        for record in authoritative
        if _timestamp_key(record.observed_at) == best_timestamp
    ]
    distinct_values = {_value_key(getattr(record, field_name)) for record in finalists}
    if len(distinct_values) > 1:
        for record in finalists:
            rejected.append(
                AuditFact(
                    concern=concern,
                    source=record.source,
                    source_digest=record.source_digest,
                    value=_value_key(getattr(record, field_name)),
                    reason="ambiguous equal-authority evidence tie",
                )
            )
        for record in active:
            if record not in finalists:
                rejected.append(
                    AuditFact(
                        concern=concern,
                        source=record.source,
                        source_digest=record.source_digest,
                        value=_value_key(getattr(record, field_name)),
                        reason="non-governing evidence after ambiguous authority tie",
                    )
                )
        return None, None, accepted, rejected

    winner = min(finalists, key=lambda record: record.source_digest)
    value = getattr(winner, field_name)
    accepted.append(
        AuditFact(
            concern=concern,
            source=winner.source,
            source_digest=winner.source_digest,
            value=_value_key(value),
            reason="governing concern-specific evidence",
        )
    )
    for record in active:
        if record is winner:
            continue
        rejected.append(
            AuditFact(
                concern=concern,
                source=record.source,
                source_digest=record.source_digest,
                value=_value_key(getattr(record, field_name)),
                reason=(
                    "duplicate corroborating evidence"
                    if _value_key(getattr(record, field_name)) == _value_key(value)
                    else "lower-authority or older conflicting evidence"
                ),
                superseded_by=winner.source_digest,
            )
        )
    return value, winner, accepted, rejected


def _is_diagnostic_session(session_id: str) -> bool:
    return any(
        session_id == diagnostic_id or session_id.startswith(f"{diagnostic_id}-")
        for diagnostic_id in DIAGNOSTIC_SESSION_IDS
    )


def evaluate_release_eligibility(
    record: EvidenceRecord,
    *,
    candidate_fingerprint: str | None,
    candidate_validated: bool,
    services_live: bool,
) -> ReleaseEligibility:
    """Evaluate structured release proof; any absent required fact is ineligible."""
    session_id = record.release_session_id or "<missing-session-id>"
    reasons: list[str] = []
    if record.release_session_id is None:
        reasons.append("missing session identity")
    elif _is_diagnostic_session(record.release_session_id):
        reasons.append("known diagnostic-only session")
    if not candidate_validated:
        reasons.append("candidate fingerprint is not validated")
    session_fingerprint = record.candidate_fingerprint or record.current_tree_fingerprint
    if not candidate_fingerprint or session_fingerprint != candidate_fingerprint:
        reasons.append("session is not bound to the exact candidate fingerprint")
    if record.active_interface != "V16":
        reasons.append("session is not V16")
    if record.session_brand_new is not True:
        reasons.append("session is not proven brand-new")
    if record.session_empty_at_start is not True:
        reasons.append("session is not proven empty at start")
    if record.session_restored is not False:
        reasons.append("session is restored or restore status is unknown")
    if record.session_reused is not False:
        reasons.append("session is reused or reuse status is unknown")
    if record.canonical_prompt != CANONICAL_PROMPT:
        reasons.append("canonical prompt does not match exactly")
    if not services_live or record.services_live is False:
        reasons.append("required services are not proven live")
    if record.mocked is not False:
        reasons.append("qualification contains mocks or mock status is unknown")
    required_stages = record.required_stages or REQUIRED_INSPECTION_STAGES
    inspected_stages = record.inspected_stages or frozenset()
    missing_stages = sorted(required_stages - inspected_stages)
    if missing_stages:
        reasons.append(f"required stages not inspected: {','.join(missing_stages)}")
    if record.defect is not False:
        reasons.append("session has a defect or defect status is unknown")
    if record.clean_live_pass is not True:
        reasons.append("session has no complete clean live pass")
    return ReleaseEligibility(
        session_id=session_id,
        eligible=not reasons,
        reasons=tuple(reasons),
    )


def _append_audit(
    accepted: list[AuditFact],
    rejected: list[AuditFact],
    resolved: tuple[Any, EvidenceRecord | None, list[AuditFact], list[AuditFact]],
) -> tuple[Any, EvidenceRecord | None]:
    value, record, accepted_items, rejected_items = resolved
    accepted.extend(accepted_items)
    rejected.extend(rejected_items)
    return value, record


def reconcile_restart_state(snapshot: Any) -> ReconciliationResult:
    """Reconcile restart facts independently by concern and fail closed.

    The function is pure: it creates no session, reads no service, mutates no
    checkpoint, and never changes retained interface routing.
    """
    normalized = normalize_recovery_snapshot(snapshot)
    records = normalized.records
    accepted: list[AuditFact] = []
    rejected: list[AuditFact] = []

    active_spec, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="active_spec",
            concern="active specification",
            authority=_TASK_AUTHORITY,
        ),
    )
    active_interface, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="active_interface",
            concern="active interface",
            authority=_TASK_AUTHORITY,
        ),
    )
    completed_tasks_value, task_record = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="completed_llm_tasks",
            concern="completed llm-driven tasks",
            authority=_TASK_AUTHORITY,
        ),
    )
    active_tasks_value, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="active_llm_tasks",
            concern="active llm-driven tasks",
            authority=_TASK_AUTHORITY,
        ),
    )
    completed_tasks = frozenset(completed_tasks_value or ())
    claimed_active_tasks = frozenset(active_tasks_value or ())

    validated_fingerprint, validation_record = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="validated_fingerprint",
            concern="validated implementation fingerprint",
            authority=_VALIDATION_AUTHORITY,
        ),
    )
    current_fingerprint, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="current_tree_fingerprint",
            concern="current candidate fingerprint",
            authority=_TREE_AUTHORITY,
        ),
    )
    services_value, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="services_live",
            concern="required service readiness",
            authority=_SERVICE_AUTHORITY,
        ),
    )
    services_live = services_value is True

    validation_positive = bool(
        validation_record
        and (
            validation_record.validation_green is True
            or validation_record.candidate_status == "VALIDATED"
        )
    )
    candidate_validated = bool(
        validation_positive
        and validated_fingerprint
        and current_fingerprint
        and validated_fingerprint == current_fingerprint
    )
    candidate_status = "VALIDATED" if candidate_validated else "UNVALIDATED"

    superseded_claims: set[str] = set()
    supersession_links: set[tuple[str, str]] = set()
    if 10 in completed_tasks:
        for record in records:
            if (
                record.scope in {EvidenceScope.CONTINUATION, EvidenceScope.MEMORY}
                and record.active_llm_tasks
                and 10 in record.active_llm_tasks
            ):
                superseded_claims.add("old Task 10 continuity")
                if task_record is not None:
                    supersession_links.add((record.source_digest, task_record.source_digest))
                rejected.append(
                    AuditFact(
                        concern="Task 10 continuity",
                        source=record.source,
                        source_digest=record.source_digest,
                        value="active Task 10",
                        reason="completed task truth explicitly supersedes historical continuity",
                        superseded_by=(task_record.source_digest if task_record else None),
                    )
                )

    session_records = [record for record in records if record.release_session_id]
    eligibility_results = [
        evaluate_release_eligibility(
            record,
            candidate_fingerprint=current_fingerprint,
            candidate_validated=candidate_validated,
            services_live=services_live,
        )
        for record in session_records
    ]
    eligible_sessions = frozenset(
        result.session_id for result in eligibility_results if result.eligible
    )
    rejected_sessions = frozenset(
        result.session_id for result in eligibility_results if not result.eligible
    )
    for record, result in zip(session_records, eligibility_results):
        fact = AuditFact(
            concern="release session eligibility",
            source=record.source,
            source_digest=record.source_digest,
            value=result.session_id,
            reason=("eligible release evidence" if result.eligible else "; ".join(result.reasons)),
        )
        (accepted if result.eligible else rejected).append(fact)

    headless_rounds_value, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="fresh_headless_rounds",
            concern="fresh headless qualification rounds",
            authority=_QUALIFICATION_AUTHORITY,
        ),
    )
    human_rounds_value, _ = _append_audit(
        accepted,
        rejected,
        _resolve_claim(
            records,
            field_name="fresh_human_like_rounds",
            concern="fresh human-like qualification rounds",
            authority=_QUALIFICATION_AUTHORITY,
        ),
    )
    headless_rounds = int(headless_rounds_value or 0)
    human_rounds = int(human_rounds_value or 0)

    if not candidate_validated:
        critical_path_state = CriticalPathState.RECOVERED_UNVALIDATED_CANDIDATE
        next_action = "VALIDATE_CURRENT_V16_CANDIDATE"
    elif not services_live:
        critical_path_state = CriticalPathState.CANDIDATE_VALIDATED
        next_action = "VERIFY_LOCAL_SERVICES"
    elif not eligible_sessions:
        has_failed_session = any(record.defect is True for record in session_records)
        has_running_session = any(
            record.clean_live_pass is None and record.defect is False
            for record in session_records
        )
        if has_failed_session:
            critical_path_state = CriticalPathState.ZERO_STATE_FAILED
        elif has_running_session:
            critical_path_state = CriticalPathState.ZERO_STATE_RUNNING
        else:
            critical_path_state = CriticalPathState.SERVICES_VERIFIED
        next_action = "RUN_CLEAN_ZERO_STATE_V16"
    elif headless_rounds < 5:
        critical_path_state = CriticalPathState.ZERO_STATE_PASSED
        next_action = "RUN_FIVE_FRESH_HEADLESS_ROUNDS"
    elif human_rounds < 5:
        critical_path_state = CriticalPathState.FRESH_ROUNDS_RUNNING
        next_action = "RUN_FIVE_FRESH_HUMAN_LIKE_ROUNDS"
    else:
        critical_path_state = CriticalPathState.RELEASE_ELIGIBLE
        next_action = "FINALIZE_RELEASE_EVIDENCE"

    release_status = (
        "COMPLETE"
        if critical_path_state is CriticalPathState.RELEASE_ELIGIBLE
        else "INCOMPLETE"
    )
    if critical_path_state is CriticalPathState.RELEASE_ELIGIBLE:
        active_downstream_tasks = claimed_active_tasks & DOWNSTREAM_LLM_TASKS
    else:
        active_downstream_tasks = frozenset()
    inactive_downstream_tasks = DOWNSTREAM_LLM_TASKS - active_downstream_tasks

    validation_counts = validation_record.validation_counts if validation_record else ()
    supporting_checks_green = (
        validation_record.supporting_checks_green if validation_record else None
    )
    ineligibility_reasons = tuple(
        sorted(
            (result.session_id, result.reasons)
            for result in eligibility_results
            if not result.eligible
        )
    )

    return ReconciliationResult(
        active_spec=active_spec,
        active_interface=active_interface,
        completed_llm_tasks=completed_tasks,
        superseded_claims=frozenset(superseded_claims),
        active_downstream_tasks=active_downstream_tasks,
        inactive_downstream_tasks=inactive_downstream_tasks,
        validated_fingerprint=validated_fingerprint,
        current_tree_fingerprint=current_fingerprint,
        candidate_status=candidate_status,
        validated_test_counts=validation_counts,
        supporting_checks_green=supporting_checks_green,
        service_status="LIVE" if services_live else "UNVERIFIED",
        release_status=release_status,
        release_evidence=eligible_sessions,
        rejected_release_evidence=rejected_sessions,
        release_ineligibility_reasons=ineligibility_reasons,
        critical_path_state=critical_path_state,
        next_action=next_action,
        accepted_facts=tuple(sorted(accepted, key=_audit_sort_key)),
        rejected_facts=tuple(sorted(rejected, key=_audit_sort_key)),
        evidence_fingerprints=tuple(
            sorted((record.source, record.source_digest) for record in records)
        ),
        supersession_links=tuple(sorted(supersession_links)),
    )
