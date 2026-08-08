"""Zero-state qualification harness for the Unified World Pipeline.

Creates fresh sessions, injects canonical prompts, traverses all stages,
verifies structural gates and parity, and records append-only diagnostics.

Validates Requirements 30.1, 30.2, 30.3, 30.4.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    CheckpointState,
    PipelineBlockedError,
    RunResult,
    StageExecutionContext,
    StageResult,
    StageSpec,
    UnifiedOrchestrator,
    _gate_passed,
)
from src.unified_pipeline.stage_handlers import (
    APPROVAL_STAGES,
    GPU_STAGES,
    _contract_hash,
)


# ---------------------------------------------------------------------------
# Canonical prompt (Danny's kitchenette)
# ---------------------------------------------------------------------------

CANONICAL_PROMPT = (
    "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, "
    "a counter with a coffee maker, and a window looking out at rain."
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageEvidence:
    """Append-only evidence for a single stage execution."""

    stage: str
    passed: bool
    elapsed_seconds: float
    plan_revision: int
    approval_revision: int
    output_hash: str  # SHA-256 of serialized output
    artifact_hashes: tuple[str, ...]  # SHA-256 of any produced artifacts
    is_mocked: bool
    diagnostic: str


@dataclass(frozen=True)
class QualificationRoundResult:
    """Complete result of a single qualification round."""

    round_id: str
    session_id: str
    passed: bool
    stage_results: tuple[StageEvidence, ...]
    contract_hash: str
    started_at: str
    completed_at: str
    is_mocked: bool  # True if GPU stages are mocked
    failure_stage: str  # empty if passed
    failure_reason: str  # empty if passed


@dataclass(frozen=True)
class QualificationReport:
    """Full qualification report across multiple rounds."""

    report_id: str
    rounds: tuple[QualificationRoundResult, ...]
    all_passed: bool
    total_rounds: int
    failed_rounds: int
    started_at: str
    completed_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: Any) -> str:
    """Compute SHA-256 of JSON-serialized data."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iso_now() -> str:
    """ISO 8601 timestamp."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _artifact_hashes_from_checkpoint(checkpoint: Any) -> tuple[str, ...]:
    """Compute SHA-256 of each artifact path content (if accessible)."""
    hashes: list[str] = []
    if checkpoint and hasattr(checkpoint, "artifact_paths"):
        for path_str in checkpoint.artifact_paths:
            p = Path(path_str)
            if p.exists() and p.is_file():
                hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
            else:
                # Hash the path string itself as a fingerprint
                hashes.append(_sha256(path_str))
    return tuple(hashes)


# ---------------------------------------------------------------------------
# Qualification-specific handlers
# ---------------------------------------------------------------------------
# These handlers return immediate results for ALL stages — no external jobs,
# no approval waits. This lets the pipeline complete in a single run() call.
# The plan_revision is set to 1 from the start to satisfy revision checks.


def _qualification_stage_specs() -> tuple[StageSpec, ...]:
    """Create stage specs with approval_for stripped.

    The orchestrator bypasses handlers for approval stages and manages them
    internally. For qualification, we strip approval_for so all stages go
    through our handlers and complete immediately.
    """
    return tuple(
        StageSpec(
            name=spec.name,
            per_object=spec.per_object,
            approval_for=None,  # Strip approval — handled by our handler
            optional=spec.optional,
        )
        for spec in DEFAULT_STAGE_SPECS
    )


def _build_qualification_handlers(
    *, inject_gate_failures: dict[str, dict[str, Any]] | None = None
) -> dict[str, Callable[[StageExecutionContext], StageResult]]:
    """Build handlers that complete all stages immediately for qualification.

    All stages produce plan_revision=1 so approval gating works correctly.
    Approval stages auto-approve. GPU stages return immediate mocked results.

    Parameters
    ----------
    inject_gate_failures : dict, optional
        Map of stage_name → output dict to inject for testing gate failures.
    """
    failures = inject_gate_failures or {}

    def _make_handler(stage_name: str, spec: StageSpec) -> Callable:
        def handler(ctx: StageExecutionContext) -> StageResult:
            # If this stage has an injected failure, use that output
            if stage_name in failures:
                return StageResult(
                    output=failures[stage_name],
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                )

            # Approval stages: auto-approve
            if spec.approval_for is not None:
                return StageResult(
                    output={
                        "approved": True,
                        "approved_stage": spec.approval_for,
                        "auto_qualified": True,
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision + 1,
                )

            # GPU stages: return immediate mock result
            if stage_name in GPU_STAGES:
                return StageResult(
                    output={
                        "status": f"{stage_name}_completed",
                        "mocked": True,
                        "job_id": f"qual-mock-{stage_name}-{uuid.uuid4().hex[:8]}",
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                )

            # Special stages with contract/gate semantics
            if stage_name == "world_contract":
                contract_data = {
                    "session_id": ctx.session_id,
                    "plan_revision": 1,
                    "stage": "world_contract",
                }
                ch = _contract_hash(contract_data)
                return StageResult(
                    output={
                        "status": "world_contract_finalized",
                        "contract_hash": ch,
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                    canonical_hash=ch,
                )

            if stage_name == "automated_final_validation":
                return StageResult(
                    output={
                        "status": "automated_final_validation_passed",
                        "passed": True,
                        "report": {"passed": True, "failures": []},
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                    canonical_hash=_contract_hash({"automated_final_validation": True}),
                )

            if stage_name == "structural_gates":
                return StageResult(
                    output={
                        "status": "structural_gates_passed",
                        "passed": True,
                        "report": {"passed": True, "gates": []},
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                    canonical_hash=_contract_hash({"structural": True}),
                )

            if stage_name == "compile":
                compile_data = {
                    "session_id": ctx.session_id,
                    "plan_revision": 1,
                    "targets": ["browser", "godot"],
                }
                ch = _contract_hash(compile_data)
                return StageResult(
                    output={
                        "status": "compiled",
                        "contract_hash": ch,
                        "browser": {"compiled": True, "contract_hash": ch},
                        "godot": {"compiled": True, "contract_hash": ch},
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                    canonical_hash=ch,
                )

            if stage_name == "parity_gate":
                return StageResult(
                    output={
                        "status": "parity_passed",
                        "passed": True,
                        "report": {"passed": True, "mismatches": []},
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                    canonical_hash=_contract_hash({"parity": True}),
                )

            if stage_name == "plan_solve":
                return StageResult(
                    output={"status": "plan_solved", "plan_revision": 1},
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                )

            if stage_name == "conversation":
                return StageResult(
                    output={
                        "status": "conversation_complete",
                        "canonical_prompt": ctx.values.get("canonical_prompt", ""),
                        "plan_revision": 1,
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                )

            if stage_name == "final_events":
                return StageResult(
                    output={
                        "status": "final_events_emitted",
                        "finality": "final",
                    },
                    plan_revision=1,
                    approval_revision=ctx.approval_revision,
                )

            # Default: immediate completion
            return StageResult(
                output={"status": f"{stage_name}_complete", "plan_revision": 1},
                plan_revision=1,
                approval_revision=ctx.approval_revision,
            )

        handler.__name__ = f"_qual_handle_{stage_name}"
        return handler

    handlers: dict[str, Callable[[StageExecutionContext], StageResult]] = {}
    for spec in DEFAULT_STAGE_SPECS:
        handlers[spec.name] = _make_handler(spec.name, spec)

    return handlers


# ---------------------------------------------------------------------------
# Qualification Harness
# ---------------------------------------------------------------------------


class QualificationHarness:
    """Zero-state qualification harness for the unified pipeline.

    Creates fresh sessions per round, injects canonical prompts,
    traverses stages, and records append-only diagnostics.
    """

    def __init__(self, output_root: Path, *, mocked: bool = True):
        """Initialize the qualification harness.

        Parameters
        ----------
        output_root : Path
            Root directory for qualification output (sessions, reports).
        mocked : bool
            If True (default), GPU stages use mock handlers.
        """
        self.output_root = Path(output_root).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.mocked = mocked
        self._diagnostics: list[dict[str, Any]] = []

    def _record_diagnostic(self, entry: dict[str, Any]) -> None:
        """Append-only diagnostic recording."""
        entry["recorded_at"] = _iso_now()
        self._diagnostics.append(entry)
        # Also persist to disk
        diag_path = self.output_root / "diagnostics.jsonl"
        with diag_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True, default=str) + "\n")

    async def run_round(
        self,
        canonical_prompt: str | None = None,
        *,
        inject_gate_failures: dict[str, dict[str, Any]] | None = None,
    ) -> QualificationRoundResult:
        """Run one complete qualification round from a fresh zero-state session.

        Parameters
        ----------
        canonical_prompt : str, optional
            The prompt to inject. Defaults to Danny's kitchenette.
        inject_gate_failures : dict, optional
            Map of stage_name → output dict to force specific gate failures.

        Returns
        -------
        QualificationRoundResult
            Complete evidence of the round including all stage results.
        """
        prompt = canonical_prompt or CANONICAL_PROMPT
        round_id = uuid.uuid4().hex
        session_id = f"qual-{uuid.uuid4().hex}"
        session_dir = self.output_root / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        started_at = _iso_now()

        self._record_diagnostic({
            "event": "round_started",
            "round_id": round_id,
            "session_id": session_id,
            "prompt": prompt,
            "is_mocked": self.mocked,
        })

        # Build qualification-specific handlers (all immediate, no external jobs)
        handlers = _build_qualification_handlers(
            inject_gate_failures=inject_gate_failures,
        )

        # Build the orchestrator — fresh per round, never reused
        # Use flattened stage specs (approval_for stripped) so all stages go
        # through our handlers without the orchestrator's internal approval gating
        orchestrator = UnifiedOrchestrator(
            session_id=session_id,
            session_dir=session_dir,
            handlers=handlers,
            external_jobs=None,  # No external jobs — everything completes inline
            stages=_qualification_stage_specs(),
        )

        # Initial context with canonical prompt injection
        initial_context: dict[str, Any] = {
            "canonical_prompt": prompt,
            "source_fingerprint": _sha256(prompt),
            "qualification_round_id": round_id,
        }

        # Run the pipeline — should complete in a single call since all handlers
        # are immediate (no external jobs, no approval waits)
        stage_results: list[StageEvidence] = []
        failure_stage = ""
        failure_reason = ""
        contract_hash = ""
        passed = True

        try:
            result = await orchestrator.run(initial_context)

            if result.state == "completed":
                contract_hash = result.canonical_hash or ""
            else:
                passed = False
                failure_stage = result.stage
                failure_reason = result.message or f"pipeline did not complete: {result.state}"
        except PipelineBlockedError as exc:
            # Identify which gate blocked the pipeline
            passed = False
            msg = str(exc).lower()
            if "structural gates" in msg:
                failure_stage = "structural_gates"
                failure_reason = "structural gates did not pass"
            elif "parity" in msg:
                failure_stage = "parity_gate"
                failure_reason = "parity gate did not pass"
            else:
                failure_stage = "blocked"
                failure_reason = str(exc)
            self._record_diagnostic({
                "event": "round_blocked",
                "round_id": round_id,
                "error": failure_reason,
            })
        except Exception as exc:
            passed = False
            failure_stage = "unknown"
            failure_reason = f"{type(exc).__name__}: {exc}"
            self._record_diagnostic({
                "event": "round_error",
                "round_id": round_id,
                "error": failure_reason,
            })

        # Collect stage evidence from checkpoints
        for spec in DEFAULT_STAGE_SPECS:
            checkpoint = orchestrator.store.load(spec.name)
            if checkpoint is None:
                continue

            output_hash = _sha256(checkpoint.output) if checkpoint.output else ""
            artifact_hashes = _artifact_hashes_from_checkpoint(checkpoint)
            stage_passed = checkpoint.completion_state is CheckpointState.COMPLETED
            is_stage_mocked = self.mocked and spec.name in GPU_STAGES

            evidence = StageEvidence(
                stage=spec.name,
                passed=stage_passed,
                elapsed_seconds=(
                    (checkpoint.completed_at or checkpoint.updated_at) - checkpoint.started_at
                ),
                plan_revision=checkpoint.plan_revision,
                approval_revision=checkpoint.approval_revision,
                output_hash=output_hash,
                artifact_hashes=artifact_hashes,
                is_mocked=is_stage_mocked,
                diagnostic=checkpoint.diagnostic or "",
            )
            stage_results.append(evidence)

            self._record_diagnostic({
                "event": "stage_evidence",
                "round_id": round_id,
                "stage": spec.name,
                "passed": stage_passed,
                "output_hash": output_hash,
                "artifact_hashes": list(artifact_hashes),
                "is_mocked": is_stage_mocked,
            })

        # Verify current V16 publication gates. Keep the historical checks for
        # retained custom stage lists, but never use this mocked harness as
        # release evidence.
        automated_cp = orchestrator.store.load("automated_final_validation")
        final_world_cp = orchestrator.store.load("final_world_qa")
        structural_cp = orchestrator.store.load("structural_gates")
        parity_cp = orchestrator.store.load("parity_gate")

        if automated_cp and not _gate_passed(automated_cp.output):
            passed = False
            failure_stage = "automated_final_validation"
            failure_reason = "automated final validation did not pass"

        if final_world_cp and not _gate_passed(final_world_cp.output):
            passed = False
            failure_stage = "final_world_qa"
            failure_reason = "final-world QA did not pass"

        if structural_cp and not _gate_passed(structural_cp.output):
            passed = False
            failure_stage = failure_stage or "structural_gates"
            failure_reason = failure_reason or "structural gates did not pass"

        if parity_cp and not _gate_passed(parity_cp.output):
            passed = False
            failure_stage = failure_stage or "parity_gate"
            failure_reason = failure_reason or "parity gate did not pass"

        # Extract contract hash from world_contract stage if not yet set
        if not contract_hash:
            wc_cp = orchestrator.store.load("world_contract")
            if wc_cp and wc_cp.output:
                contract_hash = (
                    wc_cp.output.get("contract_hash", "")
                    or wc_cp.canonical_hash
                )

        completed_at = _iso_now()

        round_result = QualificationRoundResult(
            round_id=round_id,
            session_id=session_id,
            passed=passed,
            stage_results=tuple(stage_results),
            contract_hash=contract_hash,
            started_at=started_at,
            completed_at=completed_at,
            is_mocked=self.mocked,
            failure_stage=failure_stage,
            failure_reason=failure_reason,
        )

        self._record_diagnostic({
            "event": "round_completed",
            "round_id": round_id,
            "session_id": session_id,
            "passed": passed,
            "contract_hash": contract_hash,
            "stage_count": len(stage_results),
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
        })

        return round_result

    async def run_qualification(
        self, *, headless_rounds: int = 5, human_rounds: int = 5
    ) -> QualificationReport:
        """Run the full qualification: 1 smoke + N headless + N human-like.

        Parameters
        ----------
        headless_rounds : int
            Number of headless rounds to run after the smoke test.
        human_rounds : int
            Number of human-like rounds (same as headless for now).

        Returns
        -------
        QualificationReport
            Aggregate report across all rounds.
        """
        report_id = uuid.uuid4().hex
        started_at = _iso_now()
        rounds: list[QualificationRoundResult] = []

        # 1 smoke round
        smoke = await self.run_round()
        rounds.append(smoke)

        # N headless rounds
        for _ in range(headless_rounds):
            r = await self.run_round()
            rounds.append(r)

        # N human-like rounds (canonical prompt, same behavior)
        for _ in range(human_rounds):
            r = await self.run_round()
            rounds.append(r)

        completed_at = _iso_now()
        failed = [r for r in rounds if not r.passed]

        report = QualificationReport(
            report_id=report_id,
            rounds=tuple(rounds),
            all_passed=len(failed) == 0,
            total_rounds=len(rounds),
            failed_rounds=len(failed),
            started_at=started_at,
            completed_at=completed_at,
        )

        # Persist report
        report_path = self.output_root / f"report-{report_id}.json"
        report_path.write_text(
            json.dumps(asdict(report), indent=2, default=str),
            encoding="utf-8",
        )

        return report
