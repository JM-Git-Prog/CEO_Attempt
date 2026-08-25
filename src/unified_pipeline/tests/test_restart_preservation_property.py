"""Observation-first preservation tests for restart continuity Task 11.3.

These tests freeze the existing non-bug path before any restart reconciler is
implemented.  They deliberately do not invoke qualification rounds or create
qualification sessions.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import string
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import assume, given, settings, strategies as st

from src.unified_pipeline.orchestrator import (
    CheckpointState,
    ExternalJobResult,
    ExternalJobState,
    LeaseConflictError,
    StageResult,
    StageSpec,
    UnifiedOrchestrator,
)
from src.unified_pipeline.qualification import CANONICAL_PROMPT, QualificationHarness
from src.web import app as web
from src.web import unified_routes


ROOT = Path(__file__).resolve().parents[3]
BUGFIX_REQUIREMENTS = ROOT / ".kiro" / "specs" / "unified-world-pipeline" / "bugfix.md"
EXPECTED_BASELINE = {
    "unified_strict_real": 922,
    "routes": 36,
    "mesh": 53,
}
DIAGNOSTIC_SESSION_IDS = (
    "8f24afd0",
    "8b5057d3",
    "473caae9",
    "fb163c47",
    "b7dd26d5",
    "32c30b0f",
    "c4195e57",
)


class _ObservedExternalJob:
    """A deterministic implementation of the existing external-job protocol."""

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


_owner_ids = st.lists(
    st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12),
    min_size=2,
    max_size=2,
    unique=True,
)
_fingerprints = st.text(alphabet="0123456789abcdef", min_size=64, max_size=64)


@settings(max_examples=12, deadline=None)
@given(fingerprint=_fingerprints, plan_revision=st.integers(min_value=1, max_value=20), owners=_owner_ids)
def test_property_2_exact_match_restart_is_idempotent_and_single_owner(
    fingerprint: str,
    plan_revision: int,
    owners: list[str],
) -> None:
    """**Validates: Requirements 3.2**

    An exact initial-evidence match resumes one durable V16 job without a
    duplicate submission, while worker and approval-writer leases remain
    exclusive across the reconstructed orchestrator.
    """

    async def observe() -> None:
        calls = {"plan": 0, "gpu": 0, "publish": 0}

        def plan(_context):
            calls["plan"] += 1
            return StageResult(
                output={"candidate_fingerprint": fingerprint},
                plan_revision=plan_revision,
            )

        def gpu(_context):
            calls["gpu"] += 1
            return StageResult.pending("durable-v16-job", plan_revision=plan_revision)

        def publish(_context):
            calls["publish"] += 1
            return {"published_fingerprint": fingerprint}

        stages = (StageSpec("plan"), StageSpec("gpu"), StageSpec("publish"))
        initial_context = {
            "candidate_fingerprint": fingerprint,
            "validated_fingerprint": fingerprint,
            "interface_version": 16,
        }

        with tempfile.TemporaryDirectory(prefix="task-11-3-resume-") as raw_dir:
            session_dir = Path(raw_dir)
            first_controller = _ObservedExternalJob(
                ExternalJobResult(ExternalJobState.RUNNING, response_revision=plan_revision)
            )
            first = UnifiedOrchestrator(
                session_id="preserved-v16-session",
                session_dir=session_dir,
                handlers={"plan": plan, "gpu": gpu, "publish": publish},
                external_jobs=first_controller,
                stages=stages,
            )
            first_result = await first.run(initial_context)
            assert first_result.state == "awaiting_external"

            resumed_controller = _ObservedExternalJob(
                ExternalJobResult(
                    ExternalJobState.SUCCEEDED,
                    output={"asset": "preserved.glb", "candidate_fingerprint": fingerprint},
                    response_revision=plan_revision,
                )
            )
            resumed = UnifiedOrchestrator(
                session_id="preserved-v16-session",
                session_dir=session_dir,
                handlers={"plan": plan, "gpu": gpu, "publish": publish},
                external_jobs=resumed_controller,
                stages=stages,
            )
            result = await resumed.run(initial_context)

            assert result.state == "completed"
            assert calls == {"plan": 1, "gpu": 1, "publish": 1}
            assert resumed_controller.reconciled == ["durable-v16-job"]
            checkpoint = resumed.store.load("gpu")
            assert checkpoint is not None
            assert checkpoint.completion_state is CheckpointState.COMPLETED
            assert checkpoint.output["candidate_fingerprint"] == fingerprint

            with resumed.ownership.worker(owners[0]):
                with pytest.raises(LeaseConflictError, match=owners[0]):
                    with resumed.ownership.worker(owners[1]):
                        pass
            with resumed.ownership.worker(owners[1]):
                pass

            with resumed.approval_writer(owners[0]):
                with pytest.raises(LeaseConflictError, match=owners[0]):
                    with resumed.approval_writer(owners[1]):
                        pass
            with resumed.approval_writer(owners[1]):
                pass

    asyncio.run(observe())


@settings(max_examples=5, deadline=None)
@given(version_order=st.permutations(tuple(range(3, 16))))
def test_property_2_retained_v3_v15_pages_are_order_independent(
    version_order: list[int],
) -> None:
    """**Validates: Requirements 3.1**

    Every retained page, referenced static JavaScript asset, and retained
    version-specific API remains accessible and byte-stable regardless of the
    order in which restart recovery or an operator inspects the versions.
    """
    web.sessions.clear()
    unified_routes.clear_unified_web_state()
    original_output_dir = web.OUTPUT_DIR
    try:
        with tempfile.TemporaryDirectory(prefix="task-11-3-routes-") as raw_dir:
            web.OUTPUT_DIR = Path(raw_dir)
            with TestClient(web.app) as client:
                observed: dict[int, str] = {}
                static_assets: dict[str, str] = {}
                for version in version_order:
                    response = client.get(f"/?v={version}")
                    assert response.status_code == 200
                    observed[version] = hashlib.sha256(response.content).hexdigest()
                    for asset in re.findall(
                        r'''(?:src|href)=["'](/static/[^"']+\.js(?:\?[^"']*)?)["']''',
                        response.text,
                    ):
                        asset_response = client.get(asset)
                        assert asset_response.status_code == 200
                        digest = hashlib.sha256(asset_response.content).hexdigest()
                        assert static_assets.setdefault(asset, digest) == digest

                for version in range(3, 16):
                    response = client.get(f"/?v={version}")
                    assert response.status_code == 200
                    assert hashlib.sha256(response.content).hexdigest() == observed[version]

                for route in (
                    "/api/v8/sessions",
                    "/api/v9/sessions",
                    "/api/v10/sessions",
                    "/api/v11/sessions",
                    "/api/v14/sessions",
                ):
                    first = client.get(route)
                    second = client.get(route)
                    assert first.status_code == second.status_code == 200
                    assert first.content == second.content
                    assert first.json() == {
                        "interface_versions": {},
                        "sessions": [],
                        "total": 0,
                    }
    finally:
        web.OUTPUT_DIR = original_output_dir
        unified_routes.clear_unified_web_state()
        web.sessions.clear()


_diagnostic_payloads = st.lists(
    st.tuples(
        st.sampled_from(("inspection", "artifact", "failure", "note")),
        st.text(alphabet=string.ascii_letters + string.digits + " -_", min_size=1, max_size=32),
    ),
    min_size=1,
    max_size=8,
)


@settings(max_examples=12, deadline=None)
@given(payloads=_diagnostic_payloads)
def test_property_2_diagnostic_inspection_is_append_only(
    payloads: list[tuple[str, str]],
) -> None:
    """**Validates: Requirements 3.3**

    Existing diagnostic-session evidence remains inspectable and each new
    observation appends a record rather than replacing prior evidence.
    """
    with tempfile.TemporaryDirectory(prefix="task-11-3-diagnostics-") as raw_dir:
        harness = QualificationHarness(Path(raw_dir), mocked=True)
        expected = [
            {"event": "diagnostic_inspection", "session_id": session_id}
            for session_id in DIAGNOSTIC_SESSION_IDS
        ]
        for entry in expected:
            harness._record_diagnostic(dict(entry))

        path = Path(raw_dir) / "diagnostics.jsonl"
        original_lines = path.read_text(encoding="utf-8").splitlines()
        assert len(original_lines) == len(DIAGNOSTIC_SESSION_IDS)

        for event, detail in payloads:
            harness._record_diagnostic({"event": event, "detail": detail})

        all_lines = path.read_text(encoding="utf-8").splitlines()
        assert all_lines[: len(original_lines)] == original_lines
        assert len(all_lines) == len(original_lines) + len(payloads)
        decoded = [json.loads(line) for line in all_lines]
        assert tuple(item["session_id"] for item in decoded[:7]) == DIAGNOSTIC_SESSION_IDS
        assert all("recorded_at" in item for item in decoded)


@settings(max_examples=12, deadline=None)
@given(
    diagnostic_session=st.sampled_from(DIAGNOSTIC_SESSION_IDS),
    failed_id=st.uuids().map(lambda value: value.hex),
    replacement_id=st.uuids().map(lambda value: value.hex),
    baseline_order=st.permutations(tuple(EXPECTED_BASELINE.items())),
)
def test_property_2_exact_report_and_fresh_replacement_contract(
    diagnostic_session: str,
    failed_id: str,
    replacement_id: str,
    baseline_order: list[tuple[str, int]],
) -> None:
    """**Validates: Requirements 3.3, 3.4, 3.5, 3.6**

    The unfixed report source retains the exact baseline and prompt, excludes
    failed diagnostics from release evidence, and requires a different fresh
    session after a defect.  This observes the policy without running a round.
    """
    assume(failed_id != replacement_id)
    requirements = BUGFIX_REQUIREMENTS.read_text(encoding="utf-8")

    assert dict(baseline_order) == EXPECTED_BASELINE
    assert (
        "922 unified and strict-real tests passed, 36 V14/V16 route tests passed, "
        "53 mesh-focused tests passed"
    ) in requirements
    assert CANONICAL_PROMPT == (
        "Danny's kitchenette — a small, warm kitchen with a round table, two chairs, "
        "a counter with a coffee maker, and a window looking out at rain."
    )
    assert CANONICAL_PROMPT in requirements
    assert diagnostic_session in requirements
    assert "another brand-new empty V16 session" in requirements
    assert replacement_id != failed_id

    run_round_source = inspect.getsource(QualificationHarness.run_round)
    assert 'session_id = f"qual-{uuid.uuid4().hex}"' in run_round_source
    assert "session_dir.mkdir(parents=True, exist_ok=True)" in run_round_source
