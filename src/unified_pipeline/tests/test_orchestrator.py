"""Focused tests for durable UnifiedOrchestrator behavior.

Validates Requirements 27.1-27.6, 32.1-32.7, 33.1-33.9, and 34.4-34.11.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    CheckpointState,
    ExternalJobResult,
    ExternalJobState,
    LeaseConflictError,
    PipelineBlockedError,
    StageResult,
    StageSpec,
    StaleApprovalError,
    UnifiedOrchestrator,
)


class JobController:
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


def test_default_order_encodes_authority_gates_and_pass_order():
    names = [stage.name for stage in DEFAULT_STAGE_SPECS]

    assert names.index("brief") < names.index("canon_generation")
    assert names.index("canon_generation") < names.index("canon_approval")
    assert names.index("canon_approval") < names.index("segment")
    assert names.index("segment") < names.index("depth_estimation")
    assert names.index("depth_estimation") < names.index("spatial_reconstruction")
    assert names.index("spatial_reconstruction") < names.index("blockout_approval")
    assert names.index("blockout_approval") < names.index("mesh_generation")
    assert names.index("mesh_generation") < names.index("material_pass_1")
    assert names.index("parametric_room") < names.index("physics_classification")
    assert names.index("physics_settle") < names.index("world_contract")
    assert names.index("world_contract") < names.index("compile")
    assert names.index("compile") < names.index("automated_final_validation")
    assert names.index("automated_final_validation") < names.index("final_world_qa")
    assert names[-1] == "mode_toggle"


@pytest.mark.asyncio
async def test_pending_external_job_is_reconciled_without_duplicate_submission(tmp_path):
    calls = {"prepare": 0, "gpu": 0, "finish": 0}

    def prepare(_context):
        calls["prepare"] += 1
        return StageResult(output={"plan_revision": 1, "ready": True}, plan_revision=1)

    def gpu(_context):
        calls["gpu"] += 1
        return StageResult.pending("job-17", plan_revision=1)

    def finish(_context):
        calls["finish"] += 1
        return {"done": True}

    controller = JobController(ExternalJobResult(
        ExternalJobState.SUCCEEDED,
        output={"mesh": "table.glb"},
        response_revision=1,
    ))
    stages = (StageSpec("prepare"), StageSpec("gpu"), StageSpec("finish"))
    orchestrator = UnifiedOrchestrator(
        session_id="resume-session",
        session_dir=tmp_path,
        handlers={"prepare": prepare, "gpu": gpu, "finish": finish},
        external_jobs=controller,
        stages=stages,
    )

    first = await orchestrator.run({"source_hash": "a" * 64})
    second = await orchestrator.run()

    assert first.state == "awaiting_external"
    assert second.state == "completed"
    assert calls == {"prepare": 1, "gpu": 1, "finish": 1}
    assert controller.reconciled == ["job-17"]
    checkpoint = orchestrator.store.load("gpu")
    assert checkpoint is not None
    assert checkpoint.completion_state is CheckpointState.COMPLETED
    assert checkpoint.output == {"mesh": "table.glb"}
    assert checkpoint.external_job_id == "job-17"
    checkpoint_json = json.loads(orchestrator.store.path("gpu").read_text(encoding="utf-8"))
    for field in (
        "input_hashes", "output_hashes", "plan_revision", "approval_revision",
        "external_job_id", "attempt", "completion_state",
    ):
        assert field in checkpoint_json


@pytest.mark.asyncio
async def test_approval_requires_exclusive_writer_and_current_revision(tmp_path):
    stages = (
        StageSpec("plan"),
        StageSpec("blockout_approval", approval_for="plan"),
    )
    orchestrator = UnifiedOrchestrator(
        session_id="approval-session",
        session_dir=tmp_path,
        handlers={"plan": lambda _context: StageResult(
            output={"ready_for_approval": True}, plan_revision=3
        )},
        stages=stages,
    )

    blocked = await orchestrator.run()
    assert blocked.state == "awaiting_approval"

    with orchestrator.approval_writer("ui-1") as token:
        with pytest.raises(LeaseConflictError):
            with orchestrator.approval_writer("ui-2"):
                pass
        with pytest.raises(StaleApprovalError):
            orchestrator.record_approval(
                stage="blockout_approval",
                writer_id="ui-1",
                writer_token=token,
                plan_revision=2,
                approved=True,
            )
        decision = orchestrator.record_approval(
            stage="blockout_approval",
            writer_id="ui-1",
            writer_token=token,
            plan_revision=3,
            approved=True,
        )

    assert decision.approval_revision == 2
    completed = await orchestrator.run()
    assert completed.state == "completed"
    checkpoint = orchestrator.store.load("blockout_approval")
    assert checkpoint is not None and checkpoint.approval_revision == 2


@pytest.mark.asyncio
async def test_revision_invalidation_archives_artifacts_and_cancels_pending_job(tmp_path):
    artifact = tmp_path / "artifacts" / "candidate.glb"
    artifact.parent.mkdir()
    artifact.write_bytes(b"candidate")
    controller = JobController(ExternalJobResult(ExternalJobState.RUNNING))
    stages = (StageSpec("plan"), StageSpec("mesh"), StageSpec("publish"))

    def mesh(_context):
        return StageResult(
            external_job_id="mesh-job",
            artifact_paths=(str(artifact),),
            plan_revision=1,
        )

    orchestrator = UnifiedOrchestrator(
        session_id="invalidate-session",
        session_dir=tmp_path,
        handlers={
            "plan": lambda _context: StageResult(
                output={"plan_revision": 1}, plan_revision=1
            ),
            "mesh": mesh,
            "publish": lambda _context: {"published": True},
        },
        external_jobs=controller,
        stages=stages,
    )
    assert (await orchestrator.run()).state == "awaiting_external"

    archived = await orchestrator.invalidate_from(
        "plan", reason="user revised room dimensions", new_plan_revision=2
    )

    assert len(archived) == 2
    assert not artifact.exists()
    assert orchestrator.store.load("plan") is None
    assert orchestrator.store.load("mesh") is None
    assert controller.cancelled[0][0] == "mesh-job"
    manifests = list((tmp_path / "orchestrator" / "archive").glob("*/lineage.json"))
    assert manifests
    assert any(
        json.loads(path.read_text(encoding="utf-8"))["reason"]
        == "user revised room dimensions"
        for path in manifests
    )


@pytest.mark.asyncio
async def test_stall_recovery_is_bounded_to_the_current_object(tmp_path):
    now = [100.0]
    attempts: list[tuple[str, int, str]] = []

    def mesh(context):
        attempts.append((context.object_id or "", context.attempt, context.recovery_reason))
        if context.object_id == "table" and context.attempt == 1:
            return StageResult.pending("stalled-table", plan_revision=1)
        return StageResult(
            output={"object_id": context.object_id, "fallback": bool(context.recovery_reason)},
            plan_revision=1,
        )

    controller = JobController(ExternalJobResult(
        ExternalJobState.RUNNING, response_revision=1
    ))
    orchestrator = UnifiedOrchestrator(
        session_id="stall-session",
        session_dir=tmp_path,
        handlers={
            "plan": lambda _context: StageResult(
                output={"plan_revision": 1}, plan_revision=1
            ),
            "mesh": mesh,
        },
        external_jobs=controller,
        stages=(StageSpec("plan"), StageSpec("mesh", per_object=True)),
        stall_seconds=180,
        clock=lambda: now[0],
    )

    first = await orchestrator.run({"object_ids": ["table", "chair"]})
    now[0] += 181
    second = await orchestrator.run()

    assert first.state == "awaiting_external"
    assert second.state == "completed"
    assert attempts == [
        ("table", 1, ""),
        ("table", 2, "external job stalled for 181.0s"),
        ("chair", 1, ""),
    ]
    assert controller.cancelled[0][0] == "stalled-table"
    assert orchestrator.store.load("mesh", "chair").attempt == 1


@pytest.mark.asyncio
async def test_structural_and_parity_gates_precede_final_events(tmp_path):
    contract_hash = "c" * 64
    calls: list[str] = []

    def handler(name, output):
        def run(_context):
            calls.append(name)
            return output
        return run

    stages = tuple(StageSpec(name) for name in (
        "world_contract", "structural_gates", "compile", "parity_gate", "final_events"
    ))
    orchestrator = UnifiedOrchestrator(
        session_id="gated-session",
        session_dir=tmp_path,
        stages=stages,
        handlers={
            "world_contract": handler("world_contract", {
                "plan_revision": 1, "canonical_hash": contract_hash
            }),
            "structural_gates": handler("structural_gates", {"passed": True}),
            "compile": handler("compile", {"targets": ["browser", "godot"]}),
            "parity_gate": handler("parity_gate", {"passed": True}),
            "final_events": handler("final_events", {"published": True}),
        },
    )

    result = await orchestrator.run()

    assert result.state == "completed"
    assert result.canonical_hash == contract_hash
    assert calls == [stage.name for stage in stages]
    assert orchestrator.store.load("structural_gates").canonical_hash == contract_hash
    assert orchestrator.store.load("parity_gate").canonical_hash == contract_hash
    assert orchestrator.progress_events()[-1].finality == "final"
    assert json.loads(
        orchestrator.replay_sse()[0].split("data: ", 1)[1]
    )["current_stage"] == "world_contract"
    assert orchestrator.replay_websocket()[-1]["event"] == "pipeline.progress"


@pytest.mark.asyncio
async def test_failed_structural_gate_blocks_compile(tmp_path):
    stages = tuple(StageSpec(name) for name in (
        "world_contract", "structural_gates", "compile"
    ))
    orchestrator = UnifiedOrchestrator(
        session_id="blocked-gate-session",
        session_dir=tmp_path,
        stages=stages,
        handlers={
            "world_contract": lambda _context: {
                "plan_revision": 1, "canonical_hash": "d" * 64
            },
            "structural_gates": lambda _context: {
                "passed": False, "diagnostics": ["object outside room"]
            },
            "compile": lambda _context: pytest.fail("compiler must not run"),
        },
    )

    with pytest.raises(PipelineBlockedError, match="structural gates"):
        await orchestrator.run()
    assert orchestrator.store.load("compile") is None


@pytest.mark.asyncio
async def test_unresolved_flags_block_until_explicitly_resolved(tmp_path):
    orchestrator = UnifiedOrchestrator(
        session_id="flag-session",
        session_dir=tmp_path,
        stages=(StageSpec("only"),),
        handlers={"only": lambda _context: {"done": True}},
    )
    flag = orchestrator.raise_flag(
        "human_review", "ambiguous external state", stage="only"
    )

    with pytest.raises(PipelineBlockedError, match="human_review"):
        await orchestrator.run()
    orchestrator.resolve_flag(
        flag.flag_id, resolver_id="operator", resolution="service log verified no job"
    )

    assert (await orchestrator.run()).state == "completed"
    assert orchestrator.unresolved_flags == ()


def test_worker_lease_is_exclusive_even_within_one_process(tmp_path):
    orchestrator = UnifiedOrchestrator(
        session_id="lease-session",
        session_dir=tmp_path,
        stages=(),
        handlers={},
    )

    with orchestrator.ownership.worker("worker-one"):
        with pytest.raises(LeaseConflictError, match="worker-one"):
            with orchestrator.ownership.worker("worker-two"):
                pass


@pytest.mark.asyncio
async def test_v16_mode_toggle_is_blocked_when_automated_validation_fails(tmp_path):
    calls: list[str] = []
    orchestrator = UnifiedOrchestrator(
        session_id="v16-failed-validation",
        session_dir=tmp_path,
        stages=tuple(StageSpec(name) for name in (
            "automated_final_validation", "final_world_qa", "mode_toggle"
        )),
        handlers={
            "automated_final_validation": lambda _context: {"passed": False},
            "final_world_qa": lambda _context: {"approved": True},
            "mode_toggle": lambda _context: calls.append("mode_toggle") or {"published": True},
        },
    )

    with pytest.raises(PipelineBlockedError, match="automated validation"):
        await orchestrator.run()

    assert calls == []
    assert orchestrator.store.load("mode_toggle") is None
    assert all(event.finality == "provisional" for event in orchestrator.progress_events())


@pytest.mark.asyncio
async def test_v16_publication_becomes_final_only_after_both_gates_pass(tmp_path):
    calls: list[str] = []
    orchestrator = UnifiedOrchestrator(
        session_id="v16-passing-validation",
        session_dir=tmp_path,
        stages=tuple(StageSpec(name) for name in (
            "automated_final_validation", "final_world_qa", "mode_toggle"
        )),
        handlers={
            "automated_final_validation": lambda _context: {"passed": True},
            "final_world_qa": lambda _context: {"approved": True},
            "mode_toggle": lambda _context: calls.append("mode_toggle") or {"published": True},
        },
    )

    result = await orchestrator.run()

    assert result.state == "completed"
    assert calls == ["mode_toggle"]
    assert orchestrator._publication_authorized() is True
    assert orchestrator.progress_events()[-1].finality == "final"
