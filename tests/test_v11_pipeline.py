from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src.camera_contract import camera_contract_for_plan
from src.compiler_manifest import read_terminal_manifest
from src.floor_plan.models import FloorPlan
from src.models import PipelineState, SceneConcept, SceneGraph
from src.parity_gates import validate_godot_project as real_validate_godot_project
from src.pipeline import WorldBuilder
from src.qa_evidence import QADecision, VisionScreening
from src.upbge_capabilities import UPBGECapabilityReport
from src.world_contract import ExportPolicy, build_world_contract

FIXTURE = Path(__file__).parent / "fixtures" / "current_runtime_characterization.json"


@pytest.fixture
def approved_inputs():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return FloorPlan.model_validate(payload["plan"]), SceneGraph.model_validate(payload["scene_graph"])


@pytest.fixture
def builder(tmp_path, monkeypatch, approved_inputs):
    from src import pipeline

    monkeypatch.setattr(pipeline, "OUTPUT_BASE", tmp_path)
    instance = WorldBuilder(session_id="v11pipe", interface_version=11)
    plan, scene = approved_inputs
    instance.session.floor_plan = plan
    instance.session.camera_contract = camera_contract_for_plan(plan)
    instance.session.composition_evidence = {"status": "accepted"}
    instance.session.plan_revision = 1
    instance.session.scene_concept = SceneConcept(
        era="1950s", mood="warm", palette="cream and chrome",
        architecture_notes="diner", key_objects=["table", "pendant"],
        lighting_notes="warm pendant", image_prompt="Interior photograph of a diner.",
    )
    instance.session.user_description = "A warm 1950s diner"
    return instance, scene


def _contract(builder: WorldBuilder, scene: SceneGraph):
    return build_world_contract(
        builder.session.floor_plan, scene, builder.session.camera_contract,
        session_id=builder.session.session_id, interface_version=11,
        profile_id=builder.session.workflow_profile_id, plan_revision=1,
        appearance_intent=builder.session.scene_concept,
        export_policy=ExportPolicy(targets=("upbge_blend", "upbge_runtime", "glb", "godot")),
    )


def test_semantic_noop_records_model_prompt_hash_and_non_null_log(builder, monkeypatch):
    instance, scene = builder
    from src import pipeline

    async def fake_scene(*args, **kwargs):
        return scene

    async def fake_json(**kwargs):
        assert kwargs["model"] == pipeline.LLM_MODEL
        assert kwargs["system"] == pipeline.SEMANTIC_COMMAND_PLANNER_SYSTEM
        return {"commands": []}

    monkeypatch.setattr(pipeline, "build_scene_graph", fake_scene)
    monkeypatch.setattr(pipeline, "generate_json", fake_json)
    monkeypatch.setattr(
        pipeline,
        "solve_relationships",
        lambda contract: SimpleNamespace(
            contract=contract,
            report=SimpleNamespace(
                success=True,
                model_dump=lambda **kwargs: {
                    "schema_version": "relationship-solver-report/v1",
                    "success": True,
                    "relations": [],
                    "hard_constraints": [],
                    "unsatisfied_constraints": [],
                },
            ),
        ),
    )
    asyncio.run(instance.step_build_scene_graph())

    record = instance.session.semantic_command_records[-1]
    assert record["accepted"] is True
    assert record["model_id"] == pipeline.LLM_MODEL
    assert len(record["source_prompt_hash"]) == 64
    assert record["command_log_hash"] == hashlib.sha256(b"[]").hexdigest()
    assert record["camera_requests"] == []
    assert instance.session.world_contract is not None


def test_schema_invalid_semantic_batch_gets_one_bounded_noop_repair(
    builder, monkeypatch
):
    instance, scene = builder
    from src import pipeline

    async def fake_scene(*args, **kwargs):
        return scene

    responses = [
        {"commands": [{
            "version": "semantic-command/v1",
            "command_id": "duplicate-existing-table",
            "op": "create_instance",
            "instance": {"id": "table_1", "name": "Duplicate table"},
        }]},
        {"commands": []},
    ]
    calls: list[str] = []

    async def fake_json(**kwargs):
        calls.append(kwargs["user"])
        return responses[len(calls) - 1]

    monkeypatch.setattr(pipeline, "build_scene_graph", fake_scene)
    monkeypatch.setattr(pipeline, "generate_json", fake_json)
    monkeypatch.setattr(
        pipeline,
        "solve_relationships",
        lambda contract: SimpleNamespace(
            contract=contract,
            report=SimpleNamespace(
                success=True,
                model_dump=lambda **kwargs: {
                    "schema_version": "relationship-solver-report/v1",
                    "success": True,
                    "relations": [],
                    "hard_constraints": [],
                    "unsatisfied_constraints": [],
                },
            ),
        ),
    )

    asyncio.run(instance.step_build_scene_graph())

    assert len(calls) == 2
    assert "BOUNDED SCHEMA REPAIR" in calls[1]
    assert len(instance.session.semantic_command_records) == 2
    rejected, accepted = instance.session.semantic_command_records
    assert rejected["accepted"] is False
    assert rejected["before_hash"] == rejected["after_hash"]
    assert {item["code"] for item in rejected["rejections"]} == {"schema_invalid"}
    assert accepted["accepted"] is True
    assert accepted["command_log_hash"] == hashlib.sha256(b"[]").hexdigest()
    assert instance.session.world_contract is not None


def test_semantic_rejection_is_atomic_persisted_and_raised(builder, monkeypatch):
    instance, scene = builder
    from src import pipeline

    async def fake_scene(*args, **kwargs):
        return scene

    async def fake_json(**kwargs):
        return {"commands": [{
            "version": "semantic-command/v1", "command_id": "bad-style",
            "op": "set_style", "material_id": "missing-material",
            "style": {"roughness": 0.2},
        }]}

    monkeypatch.setattr(pipeline, "build_scene_graph", fake_scene)
    monkeypatch.setattr(pipeline, "generate_json", fake_json)
    with pytest.raises(RuntimeError, match="Semantic command batch rejected"):
        asyncio.run(instance.step_build_scene_graph())

    record = instance.session.semantic_command_records[-1]
    assert record["accepted"] is False
    assert record["before_hash"] == record["after_hash"]
    assert record["command_log_hash"]
    assert {item["code"] for item in record["rejections"]} == {
        "immutable_authority", "dangling_reference"
    }
    assert instance.session.world_contract is None


def test_post_plan_semantic_relation_is_unauthorized_and_atomic(builder, monkeypatch):
    instance, scene = builder
    from src import pipeline

    async def fake_scene(*args, **kwargs):
        return scene

    async def fake_json(**kwargs):
        return {"commands": [{
            "version": "semantic-command/v1",
            "command_id": "duplicate-plan-authority",
            "op": "set_relation",
            "subject_id": "table_1",
            "relation": {"kind": "south_of", "target_id": "pendant_1"},
        }]}

    monkeypatch.setattr(pipeline, "build_scene_graph", fake_scene)
    monkeypatch.setattr(pipeline, "generate_json", fake_json)

    with pytest.raises(RuntimeError, match="Semantic command batch rejected"):
        asyncio.run(instance.step_build_scene_graph())

    record = instance.session.semantic_command_records[-1]
    assert record["accepted"] is False
    assert record["before_hash"] == record["after_hash"]
    assert "unauthorized" in {item["code"] for item in record["rejections"]}
    assert instance.session.world_contract is None


def _prepare_assembly(instance: WorldBuilder, scene: SceneGraph):
    instance.session.scene_graph = scene
    instance.session.world_contract = _contract(instance, scene).model_dump(mode="json")
    instance.session.semantic_command_records = [{
        "command_log_hash": hashlib.sha256(b"[]").hexdigest()
    }]


def test_unavailable_upbge_uses_declared_artifact_backed_fallback(
    builder, monkeypatch
):
    instance, scene = builder
    _prepare_assembly(instance, scene)
    from src import pipeline

    monkeypatch.setattr(pipeline, "discover_upbge", lambda **kwargs: UPBGECapabilityReport(
        available=False, verified=False, compatible=False, reason_code="not_found"
    ))
    calls = []

    def validate(contract, project, metadata):
        assert Path(project, "project.godot").is_file()
        assert Path(metadata).is_file()
        calls.append((Path(project), Path(metadata)))
        return real_validate_godot_project(contract, project, metadata)

    monkeypatch.setattr(pipeline, "validate_godot_project", validate)
    monkeypatch.setattr(instance, "_run_v11_qa", lambda **kwargs: None)
    first = instance._assemble_v11({})
    first_manifest = read_terminal_manifest(instance.session.compiler_manifests[-1])
    second = instance._assemble_v11({})

    assert calls and first_manifest.status == "completed"
    assert instance.session.compiler_result["status"] == "fallback_success"
    assert instance.session.runtime_smoke_report is None
    assert first != second and first.exists() and second.exists()
    assert first.parent.parent.name != second.parent.parent.name
    assert instance.session.parity_report["target"] == "godot"
    assert len(instance.session.compiler_attempt_records) == 2
    attempts = [record.value() for record in instance.session.compiler_attempt_records]
    assert attempts[0]["compilation_id"] != attempts[1]["compilation_id"]
    assert all(item["result"]["status"] == "fallback_success" for item in attempts)
    telemetry_events = [
        json.loads(line)
        for line in (instance.output_dir / "telemetry_events.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert sum(item["event"] == "compiler_prepared" for item in telemetry_events) == 2
    assert sum(item["event"] == "compiler_terminal" for item in telemetry_events) == 2

    instance.save_session()
    snapshot = json.loads(
        Path(instance.session.workflow_records[-1]).read_text(encoding="utf-8")
    )
    assert len(snapshot["compiler_attempt_records"]) == 2
    assert snapshot["compiler_result"]["compilation_id"] == attempts[-1]["compilation_id"]
    assert snapshot["structural_parity_report"]["target"] == "godot"
    assert snapshot["runtime_smoke_report"] is None
    assert any(
        item.get("target_role") == "structural_parity_report"
        for item in snapshot["compiler_result"]["artifacts"]
    )


def test_fallback_exception_still_writes_one_failed_terminal_manifest(builder, monkeypatch):
    instance, scene = builder
    _prepare_assembly(instance, scene)
    from src import pipeline

    monkeypatch.setattr(pipeline, "discover_upbge", lambda **kwargs: UPBGECapabilityReport(
        available=False, verified=False, compatible=False, reason_code="not_found"
    ))
    monkeypatch.setattr(
        pipeline, "assemble_godot_world_contract",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fallback exploded")),
    )

    with pytest.raises(RuntimeError, match="fallback exploded"):
        instance._assemble_v11({})

    assert len(instance.session.compiler_manifests) == 2
    terminal = read_terminal_manifest(instance.session.compiler_manifests[-1])
    assert terminal.status == "failed"
    assert len(terminal.timings) == 2
    assert {item.stage for item in terminal.timings} == {
        "capability_probe", "world_compilation"
    }
    assert terminal.diagnostics[-1].code == "unexpected_error"
    assert instance.session.compiler_result["terminal_manifest"].endswith("terminal.json")


def _qa_artifacts(instance: WorldBuilder):
    blockout = instance.output_dir / "blockout.png"
    canon = instance.output_dir / "canon.png"
    Image.new("RGB", (16, 16), "white").save(blockout)
    Image.new("RGB", (16, 16), "gray").save(canon)
    instance.session.blockout_path = str(blockout)
    instance.session.canon_image_path = str(canon)
    instance.session.canon_attempt = 1


def test_native_qa_binds_all_artifacts_reports_and_runtime_status(builder, monkeypatch):
    instance, _scene = builder
    _qa_artifacts(instance)
    floor_plan_source = instance.output_dir / "floor_plan_v1.svg"
    floor_plan_source.write_text("<svg/>", encoding="utf-8")
    instance.session.floor_plan_path = str(floor_plan_source)
    reference = instance.output_dir / "reference.png"
    Image.new("RGB", (16, 16), "navy").save(reference)
    from src import pipeline

    monkeypatch.setattr(
        pipeline, "run_qwen_screening",
        lambda *args, **kwargs: VisionScreening(
            status="unavailable", diagnostic="local vision unavailable"
        ),
    )
    parity = {"passed": True, "artifact_accepted": True, "target": "upbge"}
    runtime = {"passed": True, "artifact_accepted": True, "status": "completed"}

    with pytest.raises(RuntimeError, match="reference render"):
        instance._run_v11_qa(
            parity_report=parity, runtime_report=runtime, runtime_applicable=True
        )
    entry = instance._run_v11_qa(
        parity_report=parity, runtime_report=runtime, runtime_applicable=True,
        reference_render=reference,
    )

    artifacts = {artifact.role: artifact for artifact in entry.binding.artifacts}
    assert {
        "floor_plan", "floor_plan_source", "blockout", "canon", "upbge_reference",
        "structural_parity_report", "runtime_smoke_report",
    } <= artifacts.keys()
    assert entry.binding.interface_version == 11
    assert entry.binding.workflow_profile_id == instance.session.workflow_profile_id
    assert entry.binding.plan_revision == 1
    assert entry.binding.canon_attempt == 1
    assert artifacts["upbge_reference"].sha256 == hashlib.sha256(reference.read_bytes()).hexdigest()
    assert artifacts["structural_parity_report"].sha256 == entry.compiler_evidence.parity_report_hash
    assert artifacts["runtime_smoke_report"].sha256 == (
        entry.compiler_evidence.runtime_smoke_report_hash
    )
    assert entry.compiler_evidence.runtime_passed is True


def test_human_required_qa_dedupes_and_can_be_adjudicated(builder, monkeypatch):
    instance, _scene = builder
    _qa_artifacts(instance)
    from src import pipeline

    monkeypatch.setattr(
        pipeline, "run_qwen_screening",
        lambda *args, **kwargs: VisionScreening(
            status="unavailable", diagnostic="local vision unavailable"
        ),
    )
    parity = {"passed": True, "artifact_accepted": True, "target": "godot"}
    first = instance._run_v11_qa(
        parity_report=parity, runtime_report=None, runtime_applicable=False
    )
    second = instance._run_v11_qa(
        parity_report=parity, runtime_report=None, runtime_applicable=False
    )

    assert first.decision == QADecision.HUMAN_REQUIRED
    assert first.evidence_id == second.evidence_id
    assert len(instance.session.qa_evidence) == 1
    instance.session.compiler_result = {"status": "fallback_success"}
    approved = instance.adjudicate_v11_qa("reviewer-1", "approved", "checked artifacts")
    assert approved.decision == QADecision.HUMAN_APPROVED
    assert approved.supersedes == first.evidence_id
    assert instance.session.state == PipelineState.READY
    with pytest.raises(RuntimeError, match="latest human-required"):
        instance.adjudicate_v11_qa("reviewer-2", "rejected", "too late")


def test_human_rejection_sets_error_and_compiler_rejection_cannot_be_overridden(
    builder, monkeypatch
):
    instance, _scene = builder
    _qa_artifacts(instance)
    from src import pipeline

    monkeypatch.setattr(
        pipeline, "run_qwen_screening",
        lambda *args, **kwargs: VisionScreening(status="unavailable", diagnostic="offline"),
    )
    parity = {"passed": True, "artifact_accepted": True}
    instance._run_v11_qa(
        parity_report=parity, runtime_report=None, runtime_applicable=False
    )
    instance.session.compiler_result = {"status": "fallback_success"}
    rejected = instance.adjudicate_v11_qa("reviewer-1", "rejected", "visual mismatch")
    assert rejected.decision == QADecision.HUMAN_REJECTED
    assert instance.session.state == PipelineState.ERROR

    other = WorldBuilder(session_id="compilerbad", interface_version=11)
    other.session.floor_plan = instance.session.floor_plan
    other.session.plan_revision = 1
    _qa_artifacts(other)
    other._run_v11_qa(
        parity_report={"passed": False, "artifact_accepted": False},
        runtime_report=None, runtime_applicable=False,
    )
    with pytest.raises(RuntimeError, match="Compiler failures cannot be overridden"):
        other.adjudicate_v11_qa("reviewer-2", "approved", "override")


def test_step_assemble_waits_for_human_qa_instead_of_marking_ready(builder, monkeypatch):
    instance, scene = builder
    instance.session.scene_graph = scene
    project = instance.output_dir / "compiled"
    project.mkdir()

    def fake_assemble(mesh_paths):
        instance.session.compiler_result = {"status": "fallback_success"}
        instance.session.qa_evidence = [{"decision": "human_required"}]
        return project

    monkeypatch.setattr(instance, "_assemble_v11", fake_assemble)
    assert instance.step_assemble({}) == project
    assert instance.session.state == PipelineState.AWAITING_QA
    assert instance.session.output_path == str(project)


def test_v11_canon_profile_has_complete_bounded_alignment_policy():
    from src.workflow_provenance import profile_for

    profile = profile_for(11)
    policy = profile["stages"]["canon"]["alignment_policy"]
    assert policy == {
        "method": "bounded-camera-review-v1",
        "aligned_min_edge_iou": 0.04,
        "aligned_max_drift_px": 12.0,
        "misaligned_max_drift_px": 20.0,
        "misaligned_max_edge_iou": 0.015,
        "max_retries": 2,
        "manual_review_for_inconclusive": True,
    }
    assert profile["stages"]["plan"]["composition_policy"]["minimum_inset_m"] >= 0.22


def test_v11_canon_conditioning_does_not_mutate_persisted_concept(builder, monkeypatch):
    instance, _scene = builder
    from src import pipeline

    blockout = instance.output_dir / "blockout.png"
    Image.new("RGB", (16, 16), "white").save(blockout)
    instance.session.blockout_path = str(blockout)
    instance.session.floor_plan_approved = True
    original = instance.session.scene_concept.model_dump(mode="json")
    generated = instance.output_dir / "generated.png"
    Image.new("RGB", (16, 16), "gray").save(generated)
    captured = {}

    async def fake_generate(concept, *args, **kwargs):
        captured["concept"] = concept
        captured["plan_conditioning"] = kwargs.get("plan_conditioning")
        return SimpleNamespace(
            image_path=generated, provider="test", alignment=None, manifests=()
        )

    monkeypatch.setattr(pipeline, "generate_conditioned_canon", fake_generate)
    asyncio.run(instance.step_generate_image())

    assert instance.session.scene_concept.model_dump(mode="json") == original
    assert captured["concept"] is not instance.session.scene_concept
    assert captured["concept"].key_objects == instance.session.scene_concept.key_objects
    assert captured["plan_conditioning"]
    assert instance.session.conditioning_metadata["schema_version"] == "canon-conditioning/v1"
    assert len(instance.session.conditioning_records) == 1
    assert instance.session.conditioning_records[0].value() == instance.session.conditioning_metadata


@pytest.mark.parametrize(
    ("marker", "provider", "expected_status"),
    [
        ("1", "Mock fallback", "not_applicable"),
        (None, "Mock fallback", "misaligned"),
        ("1", "FLUX.2 Klein · ComfyUI", "misaligned"),
    ],
)
def test_mock_alignment_is_not_applicable_only_for_explicit_mock_qualification(
    builder, monkeypatch, marker, provider, expected_status
):
    instance, _scene = builder
    from src import pipeline

    blockout = instance.output_dir / "blockout.png"
    generated = instance.output_dir / "generated.png"
    Image.new("RGB", (16, 16), "white").save(blockout)
    Image.new("RGB", (16, 16), "gray").save(generated)
    instance.session.blockout_path = str(blockout)
    instance.session.floor_plan_approved = True
    if marker is None:
        monkeypatch.delenv("QUALIFICATION_MOCK_E2E", raising=False)
    else:
        monkeypatch.setenv("QUALIFICATION_MOCK_E2E", marker)

    async def fake_generate(*args, **kwargs):
        return SimpleNamespace(
            image_path=generated,
            provider=provider,
            alignment={"status": "misaligned", "passed": False},
            manifests=(),
        )

    monkeypatch.setattr(pipeline, "generate_conditioned_canon", fake_generate)
    asyncio.run(instance.step_generate_image())

    assert instance.session.canon_alignment["status"] == expected_status
    if expected_status == "not_applicable":
        assert instance.session.canon_alignment["reason"] == "deterministic_mock_provider"
        assert instance.session.canon_alignment["screening_status"] == "misaligned"
    else:
        assert "reason" not in instance.session.canon_alignment


def test_v10_retained_assembly_branch_is_unchanged(tmp_path, monkeypatch, approved_inputs):
    from src import pipeline

    monkeypatch.setattr(pipeline, "OUTPUT_BASE", tmp_path)
    instance = WorldBuilder(session_id="v10keep", interface_version=10)
    _plan, scene = approved_inputs
    instance.session.scene_graph = scene
    expected = instance.output_dir / "godot_project"
    calls = []

    def retained(scene_arg, output_dir, mesh_paths):
        calls.append((scene_arg, output_dir, mesh_paths))
        expected.mkdir()
        return expected

    monkeypatch.setattr(pipeline, "assemble_godot_project", retained)
    monkeypatch.setattr(
        instance, "_assemble_v11",
        lambda *_: (_ for _ in ()).throw(AssertionError("V11 branch used for V10")),
    )
    assert instance.step_assemble({}) == expected
    assert calls == [(scene, instance.output_dir, {})]
    assert instance.session.state == PipelineState.READY


def test_profile_selected_godot_primary_does_not_probe_or_label_fallback(
    builder, monkeypatch
):
    instance, scene = builder
    _prepare_assembly(instance, scene)
    from src import pipeline

    profile = json.loads(json.dumps(instance.session.workflow_profile))
    profile["stages"]["world"]["primary_adapter"] = "godot"
    profile["stages"]["world"]["fallback_adapter"] = None
    profile["stages"]["world"]["fallback_triggers"] = []
    instance.session.workflow_profile = profile
    monkeypatch.setattr(
        pipeline,
        "discover_upbge",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("profile-selected Godot must not probe UPBGE")
        ),
    )
    monkeypatch.setattr(instance, "_run_v11_qa", lambda **kwargs: None)

    project = instance._assemble_v11({})
    terminal = read_terminal_manifest(instance.session.compiler_manifests[-1])

    assert project.is_dir()
    assert terminal.status == "completed"
    assert terminal.compiler.product == "Godot WorldContract Adapter"
    assert instance.session.compiler_result["status"] == "adapter_success"
    assert instance.session.compiler_result["route_kind"] == "primary"
    assert "primary_failure" not in instance.session.compiler_result
