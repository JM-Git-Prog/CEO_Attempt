"""
The Living Room Pipeline - End-to-end world building.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.camera_contract import build_camera_contract
from src.models import PipelineState, SceneConcept, SceneGraph, WorldSession
from src.telemetry import TelemetryRecorder
from src.orchestrator.interpreter import interpret_description
from src.canon_image.generator import generate_canon_image, generate_conditioned_canon
from src.floor_plan.builder import build_floor_plan
from src.floor_plan.renderer import render_blockout, render_floor_plan_svg
from src.floor_plan.validator import validate_floor_plan
from src.scene_graph.builder import build_scene_graph
from src.asset_factory.mesh_generator import generate_all_meshes
from src.assembler.godot_project import assemble_godot_project
from src.compiler_manifest import (
    ArtifactMetadata,
    CanonicalDocument,
    CompilerDiagnostic,
    CompilerManifestStore,
    CompilerVersions,
    ManifestBinding,
    TimingRecord,
    manifest_hash,
)
from src.export_adapters import assemble_godot_world_contract, export_glb_three_metadata
from src.orchestrator.llm import LLM_MODEL, generate_json
from src.orchestrator.prompts import (
    SEMANTIC_COMMAND_PLANNER_SYSTEM,
    semantic_command_planning_prompt,
)
from src.parity_gates import (
    run_runtime_smoke,
    validate_glb_reload,
    validate_godot_project,
    validate_upbge_inventory,
    write_gate_report,
)
from src.qa_evidence import (
    AppendOnlyQALedger,
    ArtifactBinding,
    CompilerGateEvidence,
    HumanVerdict,
    QABinding,
    QADecision,
    QAEvidenceEntry,
    create_human_evidence,
    create_vision_evidence,
    ollama_vision_invoker,
    run_qwen_screening,
)
from src.relationship_solver import solve_relationships
from src.semantic_commands import (
    CommandAuthorization,
    CommandOp,
    CommandProvenance,
    apply_semantic_command_batch,
)
from src.unsupported_feature_policy import (
    AdapterKind,
    FailureStage,
    FallbackPolicy,
    FallbackTrigger,
    decide_fallback,
)
from src.upbge_capabilities import discover_upbge
from src.upbge_compiler import CompilerOutputFlags, FIRST_PARTY_SCRIPT
from src.upbge_runtime import BoundedUPBGERuntimeSmokeRunner
from src.upbge_sidecar import run_upbge_sidecar
from src.world_contract import ExportPolicy, WorldContract, build_world_contract
from src.workflow_provenance import (
    historical_profile_for,
    normalize_interface_version,
    profile_by_id,
    profile_for,
    snapshot_session,
)

OUTPUT_BASE = Path("output")
V8_LLM_STAGE_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("V8_LLM_STAGE_TIMEOUT_SECONDS", "90"))
)


class _V11CompilationError(RuntimeError):
    """A classified post-prepare V11 failure that must reach a terminal manifest."""

    def __init__(
        self,
        message: str,
        *,
        terminal_status: str = "rejected",
        stage: str = "compile",
        code: str = "compilation_rejected",
    ) -> None:
        super().__init__(message)
        self.terminal_status = terminal_status
        self.stage = stage
        self.code = code


class SemanticBatchRejectedError(RuntimeError):
    """Typed semantic command rejection — mapped to HTTP 422, not 500."""

    def __init__(self, message: str, *, rejections: list[dict]) -> None:
        super().__init__(message)
        self.rejections = rejections


def _semantic_rejection_record(
    *,
    contract: WorldContract,
    model_id: str,
    prompt_hash: str,
    commands: object,
    rejections: list[dict],
) -> dict:
    """Create complete provenance even when command parsing/authorization rejects."""
    canonical = json.dumps(
        commands, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    before_hash = contract.content_hash()
    return {
        "schema_version": "semantic-command-batch-record/v1",
        "accepted": False,
        "model_id": model_id,
        "source_prompt_hash": prompt_hash,
        "canonical_commands_json": canonical,
        "command_log_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "before_hash": before_hash,
        "after_hash": before_hash,
        "camera_requests": [],
        "rejections": rejections,
    }


def _fallback_trigger(
    *, reason_code: str, status: str, available: bool | None = None, compatible: bool | None = None
) -> FallbackTrigger | None:
    """Map only explicit evidence to the profile's allowlisted fallback vocabulary."""
    if status == "timed_out" or reason_code in {"probe_timeout", "sidecar_timeout"}:
        return FallbackTrigger.TIMEOUT
    if reason_code in {"process_start_failed", "compiler_process_failure"}:
        return FallbackTrigger.PROCESS_FAILURE
    if reason_code == "unsupported_required_feature":
        return FallbackTrigger.UNSUPPORTED_REQUIRED_FEATURE
    if available is False:
        return FallbackTrigger.UNAVAILABLE
    if available is True and compatible is False:
        return FallbackTrigger.INCOMPATIBLE
    return None


def _artifact_media_type(role: str) -> str:
    return {
        "render": "image/png",
        "blend": "application/x-blender",
        "glb": "model/gltf-binary",
        "inventory": "application/json",
        "runtime_candidate": "application/x-blender",
        "godot_project": "text/plain",
        "godot_metadata": "application/json",
    }.get(role, "application/octet-stream")


def _infer_legacy_interface_version(session_id: str) -> int:
    """Infer pre-provenance sessions from their earliest revision-log event."""
    earliest: tuple[str, int] | None = None
    for version in range(3, 12):
        log_path = OUTPUT_BASE / "logs" / f"v{version}.jsonl"
        if not log_path.exists():
            continue
        with log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if f'"session_id":"{session_id}"' not in line:
                    continue
                try:
                    timestamp = str(json.loads(line).get("timestamp", ""))
                except json.JSONDecodeError:
                    continue
                candidate = (timestamp, version)
                if timestamp and (earliest is None or candidate < earliest):
                    earliest = candidate
    return earliest[1] if earliest else 8


class WorldBuilder:
    """Orchestrates the full world-building pipeline."""

    def __init__(self, session_id: Optional[str] = None, interface_version: int = 11):
        resolved_id = session_id or str(uuid.uuid4())[:8]
        self.output_dir = OUTPUT_BASE / resolved_id
        self.output_dir.mkdir(parents=True, exist_ok=True)
        session_path = self.output_dir / "session.json"
        if session_id and session_path.exists():
            payload = json.loads(session_path.read_text(encoding="utf-8"))
            version = normalize_interface_version(
                payload.get("interface_version") or _infer_legacy_interface_version(resolved_id)
            )
            profile_id = payload.get("workflow_profile_id")
            if payload.get("workflow_profile"):
                profile = profile_by_id(payload["workflow_profile"]["id"])
                if payload["workflow_profile"] != profile:
                    raise ValueError("Persisted workflow profile differs from its immutable contract")
            elif profile_id:
                profile = profile_by_id(profile_id)
            else:
                profile = historical_profile_for(version)
            payload.update(
                interface_version=version,
                workflow_profile_id=profile["id"],
                workflow_profile=profile,
            )
            self.session = WorldSession.model_validate(payload)
        else:
            version = normalize_interface_version(interface_version)
            profile = profile_for(version)
            self.session = WorldSession(
                session_id=resolved_id,
                interface_version=version,
                workflow_profile_id=profile["id"],
                workflow_profile=profile,
            )
        self.telemetry = TelemetryRecorder(
            self.output_dir,
            interface_version=self.session.interface_version,
            workflow_profile=self.session.workflow_profile,
        )

    def save_session(self) -> None:
        """Persist resumable state plus an immutable workflow input/output snapshot."""
        snapshot_session(self.session, self.output_dir)
        (self.output_dir / "session.json").write_text(
            self.session.model_dump_json(indent=2), encoding="utf-8"
        )

    def _progress(self, msg: str):
        self.session.progress_messages.append(msg)
        print(f"[{self.session.session_id}] {msg}")

    def _llm_timeout(self) -> float | None:
        """Bound V8 model work without changing retained-version behavior."""
        if self.session.interface_version >= 8:
            return V8_LLM_STAGE_TIMEOUT_SECONDS
        return None

    async def step_interpret(self, description: str) -> SceneConcept:
        self.session.state = PipelineState.GENERATING_CONCEPT
        self.session.user_description = description
        self._progress("Interpreting your description...")
        with self.telemetry.substep("interpret", "interpret_description"):
            concept = await interpret_description(
                description, timeout_seconds=self._llm_timeout()
            )
        self.session.scene_concept = concept
        self._progress(f"Scene concept ready: {concept.era}, {concept.mood}")
        return concept

    async def step_build_floor_plan(self, feedback: str = ""):
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        self.session.state = PipelineState.GENERATING_PLAN
        self._progress("Planning room dimensions, fixtures, furniture, circulation, and canon camera...")
        current = self.session.floor_plan if feedback else None
        with self.telemetry.substep("floor_plan", "build_floor_plan"):
            plan_stage = self.session.workflow_profile.get("stages", {}).get("plan", {})
            plan, warnings, validation = await build_floor_plan(
                self.session.user_description,
                self.session.scene_concept,
                current=current,
                feedback=feedback,
                timeout_seconds=self._llm_timeout(),
                strict_validation=self.session.interface_version >= 10,
                placement_policy=plan_stage.get("placement", "retained-keyword-v1"),
            )
        if self.session.interface_version >= 11 and not validation.valid:
            self.session.floor_plan = plan
            self.session.plan_warnings = warnings
            self.session.plan_validation = validation
            reasons = "; ".join(issue.message for issue in validation.blockers)
            raise ValueError(f"V11 typed Plan constraints are unresolved: {reasons}")
        self.session.floor_plan = plan
        if self.session.interface_version >= 11:
            from src.composition_sidecar import qualify_v11_composition

            composition_policy = plan_stage.get("composition_policy", {})
            plan, composition = qualify_v11_composition(plan, composition_policy)
            self.session.floor_plan = plan
            self.session.composition_evidence = composition.model_dump(mode="json")
            self.session.camera_contract = (
                build_camera_contract(plan) if composition.status == "accepted" else None
            )
        elif self.session.interface_version >= 9:
            self.session.composition_evidence = None
            self.session.camera_contract = build_camera_contract(plan)
        else:
            self.session.composition_evidence = None
            self.session.camera_contract = None
        self.session.canon_alignment = None
        self.session.canon_attempt = 0
        self.session.canon_alignment_reviews.clear()
        self.session.plan_revision += 1
        self.session.plan_warnings = warnings
        self.session.plan_validation = validation
        version = self.session.plan_revision
        json_path = self.output_dir / f"floor_plan_v{version}.json"
        svg_path = self.output_dir / f"floor_plan_v{version}.svg"
        blockout_path = self.output_dir / f"blockout_v{version}.png"
        with self.telemetry.substep("floor_plan", "persist_plan"):
            json_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        with self.telemetry.substep("floor_plan", "render_floor_plan_svg"):
            render_floor_plan_svg(plan, svg_path)
        with self.telemetry.substep("floor_plan", "render_blockout"):
            blockout_detail = (self.session.workflow_profile.get("stages", {})
                               .get("canon", {}).get("blockout_detail", "primitive"))
            render_blockout(
                plan,
                blockout_path,
                self.session.scene_concept,
                camera_contract=self.session.camera_contract,
                blockout_detail=blockout_detail,
            )
        self.session.floor_plan_path = str(svg_path)
        self.session.blockout_path = str(blockout_path)
        self.session.floor_plan_approved = False
        self._progress(f"Plan v{version} ready with {len(plan.items)} placed items and {len(plan.openings)} openings")
        return plan

    async def step_generate_image(
        self,
        attempt: int = 1,
        *,
        generation_feedback: str = "",
        retry_mode: str = "initial",
    ) -> Path:
        self.session.state = PipelineState.GENERATING_IMAGE
        self._progress("Generating plan-conditioned canon image...")
        if self.session.interface_version >= 11 and self.session.floor_plan_approved:
            composition = self.session.composition_evidence or {}
            if composition.get("status") != "accepted" or self.session.camera_contract is None:
                raise RuntimeError(
                    "V11 Canon generation requires accepted full-bounds composition evidence "
                    "and an immutable Camera_Contract"
                )
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        workflow_context = {
            "interface_version": self.session.interface_version,
            "workflow_profile_id": self.session.workflow_profile_id,
            "workflow_profile": self.session.workflow_profile,
            "user_description": self.session.user_description,
            "floor_plan": self.session.floor_plan,
            "plan_revision": self.session.plan_revision,
            "camera_contract": self.session.camera_contract,
            "canon_attempt": attempt,
            "generation_feedback": generation_feedback,
            "retry_mode": retry_mode,
        }
        if self.session.floor_plan_approved and self.session.blockout_path:
            # Inject plan-derived count constraints into the concept for FLUX prompting
            if self.session.floor_plan:
                plan = self.session.floor_plan
                from collections import Counter
                import re as _re
                base_names = Counter(
                    _re.sub(r'\s*\d+$', '', item.name).strip() for item in plan.items
                )
                count_lines = []
                for name, count in base_names.items():
                    count_lines.append(f"EXACTLY {count} {name}" + ("s" if count > 1 else ""))
                opening_parts = []
                for o in plan.openings:
                    opening_parts.append(f"1 {o.kind} on {o.wall} wall")
                
                count_block = ". ".join(count_lines)
                opening_block = ". ".join(opening_parts)
                
                conditioning_objects = [
                    f"MANDATORY COUNTS — {count_block}.",
                    f"OPENINGS — {opening_block}.",
                    f"DO NOT ADD extra objects. DO NOT duplicate any item. "
                    f"The blockout shows exactly {len(plan.items)} distinct objects — "
                    f"match this count precisely in the render.",
                ]
                if self.session.interface_version >= 11:
                    conditioning_metadata = {
                        "schema_version": "canon-conditioning/v1",
                        "plan_revision": self.session.plan_revision,
                        "prompt_lines": conditioning_objects,
                    }
                    immutable_conditioning = CanonicalDocument.from_value(
                        conditioning_metadata
                    )
                    if all(
                        record.sha256 != immutable_conditioning.sha256
                        for record in self.session.conditioning_records
                    ):
                        self.session.conditioning_records += (immutable_conditioning,)
                    self.session.conditioning_metadata = conditioning_metadata
                    workflow_context["plan_conditioning"] = immutable_conditioning.value()
                    concept_for_generation = self.session.scene_concept.model_copy(deep=True)
                else:
                    # Retained profiles preserve their historical persisted prompt mutation.
                    self.session.scene_concept.key_objects = conditioning_objects
                    concept_for_generation = self.session.scene_concept
            else:
                concept_for_generation = self.session.scene_concept
            with self.telemetry.substep("canon_image", "generate_conditioned_canon"):
                generation = await generate_conditioned_canon(
                    concept_for_generation,
                    Path(self.session.blockout_path),
                    self.session.session_id,
                    attempt,
                    workflow_context=workflow_context,
                    plan_conditioning=tuple(
                        (workflow_context.get("plan_conditioning") or {}).get(
                            "prompt_lines", ()
                        )
                    ),
                )
        else:
            with self.telemetry.substep("canon_image", "generate_canon_image"):
                generation = await generate_canon_image(
                    self.session.scene_concept,
                    self.session.session_id,
                    attempt,
                    workflow_context=workflow_context,
                )
        image_path = generation.image_path
        self.session.canon_image_path = str(image_path)
        self.session.canon_provider = generation.provider
        alignment = generation.alignment
        if (
            os.getenv("QUALIFICATION_MOCK_E2E") == "1"
            and generation.provider == "Mock fallback"
        ):
            screening = dict(alignment or {})
            alignment = {
                **screening,
                "status": "not_applicable",
                "passed": False,
                "reason": "deterministic_mock_provider",
                "screening_status": screening.get("status"),
                "screening_passed": screening.get("passed"),
            }
        self.session.canon_alignment = alignment
        self.session.canon_attempt = attempt
        for manifest in generation.manifests:
            manifest_path = str(manifest)
            if manifest_path not in self.session.generation_manifests:
                self.session.generation_manifests.append(manifest_path)
        self._progress(f"Canon image generated: {image_path.name}")
        return image_path

    async def step_build_scene_graph(self) -> SceneGraph:
        self.session.state = PipelineState.BUILDING_SCENE_GRAPH
        self._progress("Building spatial layout...")
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        with self.telemetry.substep("scene_graph", "build_scene_graph"):
            scene = await build_scene_graph(
                self.session.scene_concept,
                self.session.floor_plan,
                timeout_seconds=self._llm_timeout(),
                enforce_plan_lights=self.session.interface_version >= 8,
            )
        self.session.scene_graph = scene
        if self.session.interface_version >= 11:
            if not self.session.floor_plan or not self.session.camera_contract:
                raise RuntimeError("V11 requires an approved Plan and Camera_Contract")
            canon_hash = None
            if self.session.canon_image_path and Path(self.session.canon_image_path).is_file():
                canon_hash = hashlib.sha256(
                    Path(self.session.canon_image_path).read_bytes()
                ).hexdigest()
            contract = build_world_contract(
                self.session.floor_plan,
                scene,
                self.session.camera_contract,
                session_id=self.session.session_id,
                interface_version=self.session.interface_version,
                profile_id=self.session.workflow_profile_id,
                plan_revision=self.session.plan_revision,
                appearance_intent=self.session.scene_concept.model_dump(mode="json"),
                canon_hash=canon_hash,
                export_policy=ExportPolicy(targets=(
                    "upbge_blend", "upbge_runtime", "reference_render",
                    "glb", "godot", "three_js",
                )),
            )

            semantic_instruction = (
                "The approved Plan already contains resolved typed spatial relationships. "
                "Do not emit set_relation commands or reinterpret object placement. Propose "
                "only safe non-spatial semantic enrichment that is explicitly supported by "
                "the allowlisted IDs; an empty commands array is valid. Original appearance "
                f"brief: {self.session.user_description}"
            )
            command_prompt = semantic_command_planning_prompt(
                contract, semantic_instruction
            )
            prompt_hash = hashlib.sha256(
                (SEMANTIC_COMMAND_PLANNER_SYSTEM + "\n" + command_prompt).encode("utf-8")
            ).hexdigest()
            response = await generate_json(
                system=SEMANTIC_COMMAND_PLANNER_SYSTEM,
                user=command_prompt,
                model=LLM_MODEL,
                timeout_seconds=self._llm_timeout(),
            )
            if set(response) != {"commands"} or not isinstance(response.get("commands"), list):
                record = _semantic_rejection_record(
                    contract=contract,
                    model_id=LLM_MODEL,
                    prompt_hash=prompt_hash,
                    commands=response.get("commands", response),
                    rejections=[{
                        "command_index": None,
                        "command_id": None,
                        "op": None,
                        "code": "schema_invalid",
                        "field": "commands",
                        "message": "planner response must contain exactly one commands array",
                    }],
                )
                self.session.semantic_command_records.append(record)
                raise SemanticBatchRejectedError(
                    "Semantic command batch rejected: invalid commands envelope",
                    rejections=[{
                        "command_index": None, "command_id": None, "op": None,
                        "code": "schema_invalid", "field": "commands",
                        "message": "planner response must contain exactly one commands array",
                    }],
                )

            authorization = CommandAuthorization(
                principal_id=f"pipeline:{self.session.session_id}",
                authorized_model_ids=frozenset({LLM_MODEL}),
                allowed_ops=frozenset(
                    op for op in CommandOp if op != CommandOp.SET_RELATION
                ),
                mutable_instance_ids=frozenset(item.id for item in contract.instances),
                mutable_material_ids=frozenset(item.id for item in contract.materials),
                mutable_light_ids=frozenset(item.id for item in contract.lights),
                mutable_interaction_ids=frozenset(item.id for item in contract.interactions),
            )
            provenance = CommandProvenance(
                model_id=LLM_MODEL, source_prompt_hash=prompt_hash
            )
            commands = response["commands"]
            batch = apply_semantic_command_batch(
                contract,
                commands,
                authorization=authorization,
                provenance=provenance,
            )
            if not batch.accepted or batch.record is None:
                record = _semantic_rejection_record(
                    contract=contract,
                    model_id=LLM_MODEL,
                    prompt_hash=prompt_hash,
                    commands=commands,
                    rejections=[item.model_dump(mode="json") for item in batch.rejections],
                )
                self.session.semantic_command_records.append(record)
                repair_prompt = command_prompt + (
                    "\n\nBOUNDED REPAIR:\n"
                    "The previous optional semantic commands were rejected. The approved "
                    "Plan and Camera_Contract already contain all requested instances and "
                    "placement. Never recreate, remove, replace, relate, or move allowlisted "
                    "Plan objects, lights, or the camera. Return exactly {\"commands\":[]} "
                    "unless a fully valid non-spatial edit against an existing mutable ID is "
                    "certain.\nREJECTION SUMMARY:\n"
                    + json.dumps([
                        {
                            "command_index": item.command_index,
                            "code": item.code,
                            "field": item.field,
                        }
                        for item in batch.rejections
                    ], sort_keys=True, separators=(",", ":"))
                )
                repair_hash = hashlib.sha256(
                    (SEMANTIC_COMMAND_PLANNER_SYSTEM + "\n" + repair_prompt).encode("utf-8")
                ).hexdigest()
                repaired_response = await generate_json(
                    system=SEMANTIC_COMMAND_PLANNER_SYSTEM,
                    user=repair_prompt,
                    model=LLM_MODEL,
                    timeout_seconds=self._llm_timeout(),
                )
                if (
                    set(repaired_response) != {"commands"}
                    or not isinstance(repaired_response.get("commands"), list)
                ):
                    repaired_record = _semantic_rejection_record(
                        contract=contract,
                        model_id=LLM_MODEL,
                        prompt_hash=repair_hash,
                        commands=repaired_response.get("commands", repaired_response),
                        rejections=[{
                            "command_index": None,
                            "command_id": None,
                            "op": None,
                            "code": "schema_invalid",
                            "field": "commands",
                            "message": "repair response must contain exactly one commands array",
                        }],
                    )
                    self.session.semantic_command_records.append(repaired_record)
                    raise SemanticBatchRejectedError(
                        "Semantic command batch rejected: invalid bounded repair envelope",
                        rejections=[{
                            "command_index": None, "command_id": None, "op": None,
                            "code": "schema_invalid", "field": "commands",
                            "message": "repair response must contain exactly one commands array",
                        }],
                    )
                commands = repaired_response["commands"]
                prompt_hash = repair_hash
                batch = apply_semantic_command_batch(
                    contract,
                    commands,
                    authorization=authorization,
                    provenance=CommandProvenance(
                        model_id=LLM_MODEL, source_prompt_hash=repair_hash
                    ),
                )
                if not batch.accepted or batch.record is None:
                    repaired_record = _semantic_rejection_record(
                        contract=contract,
                        model_id=LLM_MODEL,
                        prompt_hash=repair_hash,
                        commands=commands,
                        rejections=[
                            item.model_dump(mode="json") for item in batch.rejections
                        ],
                    )
                    self.session.semantic_command_records.append(repaired_record)
                    reasons = "; ".join(item.message for item in batch.rejections)
                    raise SemanticBatchRejectedError(
                        f"Semantic command batch rejected after bounded repair: {reasons}",
                        rejections=[
                            item.model_dump(mode="json") for item in batch.rejections
                        ],
                    )

            accepted_record = batch.record.model_dump(mode="json")
            accepted_record.update({
                "accepted": True,
                "camera_requests": [
                    item.model_dump(mode="json", exclude_none=True)
                    for item in batch.camera_requests
                ],
                "rejections": [],
            })
            self.session.semantic_command_records.append(accepted_record)
            contract = batch.contract

            solved = solve_relationships(contract)
            self.session.relationship_solver_report = solved.report.model_dump(mode="json")
            if not solved.report.success or solved.contract is None:
                # Last-resort spatial repair (proven 59/60 on reproduced failures,
                # <=19ms - see src/solver_repair.py). Fixed items never move; a
                # genuinely unsatisfiable contract still fails, but now with its
                # input ARCHIVED so the failure is always reproducible.
                from src.solver_repair import attempt_repair

                repaired_contract = attempt_repair(contract)
                if repaired_contract is not None:
                    self.session.relationship_solver_report = {
                        "schema_version": "relationship-solver-report/v1",
                        "success": True,
                        "repaired_by": "solver_repair/v1",
                        "note": ("greedy solve failed; spatial repair produced a "
                                 "physically-valid contract (relation offsets relaxed "
                                 "by displacement; fixed items untouched)"),
                    }
                    contract = repaired_contract
                else:
                    unsat_path = self.output_dir / "world_contract_UNSAT_input.json"
                    try:
                        unsat_path.write_bytes(contract.canonical_bytes())
                    except Exception:
                        unsat_path.write_text(contract.model_dump_json(), encoding="utf-8")
                    raise RuntimeError("World relationship constraints could not be satisfied")
            else:
                contract = solved.contract
            canonical = contract.canonical_bytes()
            contract_path = self.output_dir / f"world_contract_{contract.content_hash()[:16]}.json"
            if contract_path.exists() and contract_path.read_bytes() != canonical:
                raise RuntimeError("immutable WorldContract path contains different bytes")
            if not contract_path.exists():
                contract_path.write_bytes(canonical)
            self.session.world_contract = contract.model_dump(mode="json")
        self._progress(f"Scene graph ready: {len(scene.objects)} objects, {len(scene.lights)} lights, {len(scene.doors)} doors")
        return scene

    async def step_refine_world(self, feedback: str, render_path: Path) -> dict:
        """Compare a captured world render to the canon and apply one visual revision."""
        from src.scene_graph.refiner import refine_scene_graph

        if not self.session.scene_graph or not self.session.scene_concept:
            raise RuntimeError("Build a world before revising it")
        if not self.session.canon_image_path:
            raise RuntimeError("No canon image is available for comparison")
        self.session.state = PipelineState.REFINING_WORLD
        self._progress(f"Comparing world to canon: {feedback}")
        with self.telemetry.substep("refine_world", "refine_scene_graph"):
            revised, report = await refine_scene_graph(
                self.session.scene_graph,
                self.session.scene_concept,
                Path(self.session.canon_image_path),
                render_path,
                feedback,
                self.session.floor_plan,
            )
        self.session.scene_graph = revised
        self.session.world_revision += 1
        self.session.render_paths.append(str(render_path))
        record = {"revision": self.session.world_revision, "feedback": feedback, **report}
        self.session.revision_history.append(record)
        with self.telemetry.substep("refine_world", "persist_scene_graph"):
            (self.output_dir / f"scene_graph_v{self.session.world_revision}.json").write_text(
                revised.model_dump_json(indent=2), encoding="utf-8"
            )
        with self.telemetry.substep("refine_world", "persist_revision_history"):
            (self.output_dir / "revision_history.json").write_text(
                __import__("json").dumps(self.session.revision_history, indent=2), encoding="utf-8"
            )
        self._progress(f"World revision {self.session.world_revision} planned: {report['summary']}")
        return report

    def step_generate_assets(self) -> dict[str, Path]:
        self.session.state = PipelineState.GENERATING_ASSETS
        self._progress("Generating 3D assets...")
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
        with self.telemetry.substep("assets", "generate_all_meshes"):
            mesh_paths = generate_all_meshes(self.session.scene_graph, self.output_dir)
        self._progress(f"Generated {len(mesh_paths)} mesh assets")
        return mesh_paths

    def _run_v11_qa(
        self,
        *,
        parity_report: dict,
        runtime_report: dict | None,
        runtime_applicable: bool,
        reference_render: Path | None = None,
    ) -> QAEvidenceEntry:
        """Bind local visual screening and compiler gates to immutable artifact hashes."""
        from PIL import Image, ImageDraw

        if not self.session.floor_plan or not self.session.blockout_path or not self.session.canon_image_path:
            raise RuntimeError("V11 QA requires Floor Plan, Blockout, and Canon artifacts")
        plan = self.session.floor_plan
        qa_plan = self.output_dir / f"floor_plan_qa_v{self.session.plan_revision}.png"
        if not qa_plan.exists():
            image = Image.new("RGB", (1024, 768), "white")
            draw = ImageDraw.Draw(image)
            margin = 70
            scale = min(
                (image.width - margin * 2) / plan.room.width,
                (image.height - margin * 2) / plan.room.depth,
            )
            cx, cy = image.width / 2, image.height / 2
            draw.rectangle(
                (
                    cx - plan.room.width * scale / 2,
                    cy - plan.room.depth * scale / 2,
                    cx + plan.room.width * scale / 2,
                    cy + plan.room.depth * scale / 2,
                ),
                outline="black", width=5,
            )
            for item in plan.items:
                x = cx + item.x * scale
                y = cy - item.z * scale
                draw.rectangle(
                    (
                        x - item.width * scale / 2, y - item.depth * scale / 2,
                        x + item.width * scale / 2, y + item.depth * scale / 2,
                    ),
                    outline="#345995", width=3,
                )
                draw.text((x + 4, y + 4), item.id, fill="black")
            image.save(qa_plan)
        core_images = (
            qa_plan, Path(self.session.blockout_path), Path(self.session.canon_image_path)
        )
        screening = run_qwen_screening(
            core_images,
            invoker=lambda prompt, paths: ollama_vision_invoker(
                prompt, paths,
                base_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
            ),
            user_prompt=self.session.user_description,
        )
        artifacts = [
            ArtifactBinding.from_path(qa_plan, role="floor_plan"),
            ArtifactBinding.from_path(self.session.blockout_path, role="blockout"),
            ArtifactBinding.from_path(self.session.canon_image_path, role="canon"),
        ]
        plan_source = Path(self.session.floor_plan_path) if self.session.floor_plan_path else None
        if plan_source is not None and plan_source.is_file() and plan_source != qa_plan:
            artifacts.append(ArtifactBinding.from_path(plan_source, role="floor_plan_source"))
        if runtime_applicable:
            if reference_render is None or not reference_render.is_file():
                raise RuntimeError("Native V11 QA requires an UPBGE reference render")
            artifacts.append(ArtifactBinding.from_path(reference_render, role="upbge_reference"))
        parity_hash = hashlib.sha256(
            json.dumps(
                parity_report, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        artifacts.append(ArtifactBinding(
            role="structural_parity_report", sha256=parity_hash,
        ))
        runtime_hash = None
        runtime_passed = None
        if runtime_applicable:
            if runtime_report is None:
                raise RuntimeError("Native V11 QA requires runtime smoke evidence")
            runtime_hash = hashlib.sha256(
                json.dumps(
                    runtime_report, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False, allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            runtime_passed = bool(runtime_report.get("passed"))
            artifacts.append(ArtifactBinding(
                role="runtime_smoke_report", sha256=runtime_hash,
            ))
        compiler_evidence = CompilerGateEvidence(
            parity_report_hash=parity_hash,
            parity_passed=bool(parity_report.get("passed")),
            runtime_smoke_report_hash=runtime_hash,
            runtime_applicable=runtime_applicable,
            runtime_passed=runtime_passed,
        )
        binding = QABinding(
            session_id=self.session.session_id,
            interface_version=self.session.interface_version,
            workflow_profile_id=self.session.workflow_profile_id,
            plan_revision=self.session.plan_revision,
            canon_attempt=self.session.canon_attempt,
            artifacts=tuple(artifacts),
        )
        entry = create_vision_evidence(
            binding, screening, compiler_evidence=compiler_evidence
        )
        appended = AppendOnlyQALedger(self.output_dir / "qa_evidence.jsonl").append(entry)
        stored = appended.entry
        if not any(
            item.get("submission_hash") == stored.submission_hash
            for item in self.session.qa_evidence
        ):
            self.session.qa_evidence.append(stored.model_dump(mode="json"))
        return stored

    def adjudicate_v11_qa(
        self, reviewer_id: str, verdict: str, rationale: str
    ) -> QAEvidenceEntry:
        """Append a human verdict for the latest immutable human-required V11 evidence."""
        if self.session.interface_version < 11:
            raise RuntimeError("Human V11 QA adjudication is unavailable for retained profiles")
        ledger = AppendOnlyQALedger(self.output_dir / "qa_evidence.jsonl")
        history = ledger.entries()
        if not history:
            raise RuntimeError("No V11 QA evidence is available for adjudication")
        latest = history[-1]
        if latest.decision == QADecision.COMPILER_REJECTED or (
            latest.compiler_evidence is not None and not latest.compiler_evidence.passed
        ):
            raise RuntimeError("Compiler failures cannot be overridden by human QA")
        if latest.decision != QADecision.HUMAN_REQUIRED:
            raise RuntimeError("Only the latest human-required QA entry can be adjudicated")
        human = HumanVerdict(
            reviewer_id=reviewer_id, verdict=verdict, rationale=rationale
        )
        candidate = create_human_evidence(
            latest.binding,
            human,
            compiler_evidence=latest.compiler_evidence,
        )
        appended = ledger.append(candidate)
        stored = appended.entry
        if not any(
            item.get("submission_hash") == stored.submission_hash
            for item in self.session.qa_evidence
        ):
            self.session.qa_evidence.append(stored.model_dump(mode="json"))
        if stored.decision == QADecision.HUMAN_APPROVED:
            status = (self.session.compiler_result or {}).get("status")
            if status not in {"native_success", "fallback_success", "adapter_success"}:
                raise RuntimeError("QA cannot approve an incomplete compiler outcome")
            self.session.state = PipelineState.READY
            self.session.error = None
        elif stored.decision == QADecision.HUMAN_REJECTED:
            self.session.state = PipelineState.ERROR
            self.session.error = f"Human QA rejected the world: {rationale}"
        else:
            raise RuntimeError("Human QA did not produce a terminal verdict")
        self.save_session()
        return stored

    def _assemble_v11(self, mesh_paths: dict[str, Path]) -> Path:
        if not self.session.world_contract:
            raise RuntimeError("V11 WorldContract has not been built")
        contract = WorldContract.model_validate(self.session.world_contract)
        world_stage = self.session.workflow_profile.get("stages", {}).get("world", {})
        output_policy = world_stage.get("outputs", {})
        outputs = CompilerOutputFlags(
            render=bool(output_policy.get("render", False)),
            blend=bool(output_policy.get("blend", False)),
            glb=bool(output_policy.get("glb", False)),
            runtime=bool(output_policy.get("runtime", False)),
        )
        try:
            primary_adapter = AdapterKind(world_stage["primary_adapter"])
            fallback_value = world_stage.get("fallback_adapter")
            fallback_adapter = AdapterKind(fallback_value) if fallback_value else None
            fallback_policy = FallbackPolicy(
                primary_adapter=primary_adapter,
                fallback_adapter=fallback_adapter,
                allowed_triggers=frozenset(
                    FallbackTrigger(value)
                    for value in world_stage.get("fallback_triggers", ())
                ),
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError(f"Invalid V11 world adapter profile: {exc}") from exc
        if primary_adapter not in {AdapterKind.UPBGE, AdapterKind.GODOT}:
            raise RuntimeError(f"Unsupported primary adapter: {primary_adapter.value}")

        probe_started_at = datetime.now(timezone.utc)
        probe_started_monotonic = time.monotonic()
        capability = None
        if primary_adapter == AdapterKind.UPBGE:
            capability = discover_upbge(explicit_path=os.getenv("UPBGE_PATH"))
            capability_payload = capability.to_dict()
            compiler = CompilerVersions(
                product=capability.product or "UPBGE",
                product_version=capability.product_version or "unavailable",
                blender_version=capability.blender_api_version,
                python_version=capability.python_version,
                compiler_version="upbge-compiler-plan/v1",
                runtime_capable=capability.supports_game_runtime,
            )
            compiler_script_path = FIRST_PARTY_SCRIPT
        else:
            capability_payload = {
                "available": True,
                "verified": True,
                "compatible": True,
                "product": "Godot WorldContract Adapter",
                "reason_code": "profile_selected",
            }
            compiler = CompilerVersions(
                product="Godot WorldContract Adapter",
                product_version="export-adapter/v1",
                compiler_version="godot-world-contract-adapter/v1",
                runtime_capable=False,
            )
            compiler_script_path = Path(__file__).with_name("export_adapters.py")
        probe_ended_at = datetime.now(timezone.utc)
        probe_timing = TimingRecord(
            stage="capability_probe",
            started_at=probe_started_at,
            ended_at=probe_ended_at,
            duration_ms=round((time.monotonic() - probe_started_monotonic) * 1000, 3),
        )
        empty_command_hash = hashlib.sha256(b"[]").hexdigest()
        command_hash = empty_command_hash
        if self.session.semantic_command_records:
            command_hash = (
                self.session.semantic_command_records[-1].get("command_log_hash")
                or empty_command_hash
            )
        binding = ManifestBinding(
            session_id=self.session.session_id,
            interface_version=self.session.interface_version,
            workflow_profile_id=self.session.workflow_profile_id,
            workflow_profile=CanonicalDocument.from_value(self.session.workflow_profile),
            world_contract_version=contract.schema_version,
            world_contract_hash=contract.content_hash(),
            world_contract=CanonicalDocument.from_value(contract),
            plan_revision=self.session.plan_revision,
            plan_hash=contract.source.plan_hash,
            camera_contract_id=contract.camera.id,
            camera_contract_hash=contract.source.camera_contract_hash,
            compiler_script_hash=hashlib.sha256(
                compiler_script_path.read_bytes()
            ).hexdigest(),
            command_log_hash=command_hash,
        )
        store = CompilerManifestStore(self.output_dir / "compiler_manifests")
        prepared, prepared_path = store.prepare(
            binding=binding,
            compiler=compiler,
            configuration={
                "profile_world": world_stage,
                "outputs": dict(outputs.requested_names()),
                "capability": capability_payload,
                "routing": {
                    "primary_adapter": primary_adapter.value,
                    "fallback_adapter": (
                        fallback_adapter.value if fallback_adapter else None
                    ),
                },
            },
            input_bytes=len(contract.canonical_bytes()),
        )
        self.session.compiler_manifests.append(str(prepared_path))
        self.session.export_results = {}
        self.session.parity_report = None
        self.session.runtime_smoke_report = None
        self.telemetry.record_compiler_event(
            phase="prepared",
            compilation_id=prepared.compilation_id,
            target=primary_adapter.value,
            status=prepared.status,
            manifest_sha256=manifest_hash(prepared),
        )
        attempt_root = self.output_dir / "compilations" / prepared.compilation_id
        attempt_root.mkdir(parents=True, exist_ok=False)
        started_at = datetime.now(timezone.utc)
        started_monotonic = time.monotonic()
        artifacts: list[ArtifactMetadata] = []
        diagnostics: list[CompilerDiagnostic] = []
        reference_render: Path | None = None
        runtime_report: dict | None = None
        parity_report: dict | None = None
        glb_report: dict | None = None
        project_path: Path | None = None
        producing_adapter: AdapterKind | None = None
        terminal_status = "failed"
        pending_error: Exception | None = None
        self.session.compiler_result = {
            "target": primary_adapter.value,
            "status": "failure",
            "capability": capability_payload,
            "compilation_id": prepared.compilation_id,
            "prepared_manifest": str(prepared_path),
        }

        def add_artifact(path: str | Path, role: str, media_type: str | None = None) -> None:
            artifact_path = Path(path)
            if not artifact_path.is_file() or any(
                item.path == str(artifact_path) for item in artifacts
            ):
                return
            artifacts.append(ArtifactMetadata.from_path(
                artifact_path,
                media_type=media_type or _artifact_media_type(role),
                target_role=role,
            ))

        def run_godot_adapter(
            *, route_kind: str, failure: dict | None = None
        ) -> tuple[Path, str]:
            nonlocal parity_report, producing_adapter
            if not bool(output_policy.get("godot", False)):
                raise _V11CompilationError(
                    "Godot output is disabled by the workflow profile",
                    terminal_status="rejected", stage="fallback",
                    code="godot_output_disabled",
                )
            producing_adapter = AdapterKind.GODOT
            update = {"target": "godot", "status": "failure"}
            if failure is not None:
                update["primary_failure"] = failure
            self.session.compiler_result.update(update)
            route_root = attempt_root / route_kind
            project, export_result = assemble_godot_world_contract(
                contract, route_root, mesh_paths
            )
            self.session.export_results["godot"] = export_result.model_dump(mode="json")
            for item in export_result.artifacts:
                add_artifact(item.path, item.target_role, item.media_type)
            if export_result.status == "rejected":
                raise _V11CompilationError(
                    "Godot adapter rejected required features",
                    terminal_status="rejected", stage="fallback", code="adapter_rejected",
                )
            if not export_result.manifests:
                raise _V11CompilationError(
                    "Godot adapter emitted no metadata manifest",
                    terminal_status="rejected", stage="parity",
                    code="metadata_manifest_missing",
                )
            parity = validate_godot_project(
                contract, project, export_result.manifests[0].path
            )
            parity_report = parity.model_dump(mode="json")
            self.session.parity_report = parity_report
            add_artifact(
                write_gate_report(
                    parity, attempt_root / "reports" / "structural_parity.json"
                ),
                "structural_parity_report", "application/json",
            )
            if not parity.passed or not parity.artifact_accepted:
                raise _V11CompilationError(
                    "Godot adapter failed artifact-backed structural parity",
                    terminal_status="rejected", stage="parity", code="godot_parity_failed",
                )
            success_status = (
                "fallback_success" if route_kind == "fallback" else "adapter_success"
            )
            result_status = (
                success_status if export_result.status == "success" else "partial_export"
            )
            completed = {
                "target": "godot", "status": result_status,
                "capability": capability_payload,
                "adapter": export_result.model_dump(mode="json"),
                "route_kind": route_kind,
            }
            if failure is not None:
                completed["primary_failure"] = failure
            self.session.compiler_result.update(completed)
            return project, result_status

        def run_fallback(
            *, failure: dict, trigger: FallbackTrigger | None, stage: FailureStage
        ) -> tuple[Path, str]:
            if trigger is None:
                raise _V11CompilationError(
                    "Primary adapter failure has no allowlisted fallback trigger",
                    terminal_status="rejected", stage=stage.value,
                    code=str(failure.get("reason_code", "fallback_not_permitted")),
                )
            decision = decide_fallback(
                fallback_policy, stage=stage, trigger=trigger, retries_used=0
            )
            if not decision.allowed or decision.selected_adapter is None:
                status = "timed_out" if trigger == FallbackTrigger.TIMEOUT else "rejected"
                raise _V11CompilationError(
                    f"Fallback denied by profile: {decision.reason_code}",
                    terminal_status=status, stage=stage.value, code=decision.reason_code,
                )
            if decision.selected_adapter != AdapterKind.GODOT:
                raise _V11CompilationError(
                    f"Unsupported fallback adapter: {decision.selected_adapter.value}",
                    terminal_status="rejected", stage="fallback",
                    code="unsupported_fallback_adapter",
                )
            diagnostics.append(CompilerDiagnostic(
                stage=stage.value,
                code=str(failure.get("reason_code", trigger.value)),
                severity="warning",
                message=f"Declared Godot fallback selected: {decision.reason_code}",
                violated_limit=failure.get("violated_limit"),
            ))
            return run_godot_adapter(route_kind="fallback", failure=failure)

        try:
            if primary_adapter == AdapterKind.GODOT:
                project_path, _ = run_godot_adapter(route_kind="primary")
            elif capability is not None and capability.compatible:
                sidecar = run_upbge_sidecar(
                    capability, contract.canonical_bytes(), attempt_root / "native",
                    outputs=outputs,
                )
                if not sidecar.success:
                    failure = sidecar.to_dict()
                    trigger = _fallback_trigger(
                        reason_code=sidecar.reason_code, status=sidecar.status
                    )
                    project_path, _ = run_fallback(
                        failure=failure, trigger=trigger, stage=FailureStage.COMPILE
                    )
                else:
                    producing_adapter = AdapterKind.UPBGE
                    artifact_paths = {item.role: Path(item.path) for item in sidecar.artifacts}
                    for role, path in artifact_paths.items():
                        add_artifact(path, role)
                    inventory_path = artifact_paths.get("inventory")
                    if inventory_path is None:
                        raise _V11CompilationError(
                            "UPBGE compiler emitted no inventory",
                            terminal_status="rejected", stage="parity",
                            code="inventory_missing",
                        )
                    parity = validate_upbge_inventory(contract, inventory_path)
                    parity_report = parity.model_dump(mode="json")
                    self.session.parity_report = parity_report
                    add_artifact(
                        write_gate_report(
                            parity, attempt_root / "reports" / "structural_parity.json"
                        ),
                        "structural_parity_report", "application/json",
                    )
                    if not parity.passed or not parity.artifact_accepted:
                        raise _V11CompilationError(
                            "UPBGE structural parity failed",
                            terminal_status="rejected", stage="parity",
                            code="upbge_parity_failed",
                        )
                    glb_path = artifact_paths.get("glb")
                    if not outputs.glb or glb_path is None:
                        raise _V11CompilationError(
                            "Native acceptance requires a requested GLB artifact",
                            terminal_status="rejected", stage="export",
                            code="native_glb_required",
                        )
                    reloaded = validate_glb_reload(
                        glb_path,
                        expected_stable_ids=tuple(item.id for item in contract.instances),
                        expected_camera_ids=(contract.camera.id,),
                        expected_light_ids=tuple(item.id for item in contract.lights),
                        require_lights=bool(contract.lights),
                    )
                    glb_report = reloaded.model_dump(mode="json")
                    self.session.compiler_result["glb_reload"] = glb_report
                    add_artifact(
                        write_gate_report(
                            reloaded, attempt_root / "reports" / "glb_reload.json"
                        ),
                        "glb_reload_report", "application/json",
                    )
                    if not reloaded.passed or not reloaded.artifact_accepted:
                        raise _V11CompilationError(
                            "Native GLB reload validation failed",
                            terminal_status="rejected", stage="parity",
                            code="glb_reload_failed",
                        )
                    runtime_candidate = artifact_paths.get("runtime_candidate")
                    if not outputs.runtime or runtime_candidate is None:
                        raise _V11CompilationError(
                            "Native QA requires a runtime candidate and smoke evidence",
                            terminal_status="rejected", stage="runtime_smoke",
                            code="native_runtime_required",
                        )
                    smoke = run_runtime_smoke(
                        engine_path=capability.executable_path,
                        package_path=runtime_candidate,
                        required_interactions=tuple(item.id for item in contract.interactions),
                        runner=BoundedUPBGERuntimeSmokeRunner(),
                    )
                    runtime_report = smoke.model_dump(mode="json")
                    self.session.runtime_smoke_report = runtime_report
                    add_artifact(
                        write_gate_report(
                            smoke, attempt_root / "reports" / "runtime_smoke.json"
                        ),
                        "runtime_smoke_report", "application/json",
                    )
                    runtime_required = bool(
                        world_stage.get("runtime_required_for_native", False)
                    )
                    if runtime_required and (
                        not smoke.passed or not smoke.artifact_accepted
                    ):
                        raise _V11CompilationError(
                            "Required native runtime smoke failed",
                            terminal_status="rejected", stage="runtime_smoke",
                            code="runtime_smoke_failed",
                        )
                    portable_partial = not smoke.passed
                    if bool(output_policy.get("three_js", False)):
                        export_result = export_glb_three_metadata(
                            contract, attempt_root / "exports" / "three", glb_path=glb_path
                        )
                        self.session.export_results["glb"] = export_result.model_dump(mode="json")
                        for item in export_result.artifacts:
                            add_artifact(item.path, item.target_role, item.media_type)
                        if export_result.status == "rejected":
                            raise _V11CompilationError(
                                "GLB/Three adapter rejected required features",
                                terminal_status="rejected", stage="export",
                                code="adapter_rejected",
                            )
                        portable_partial = portable_partial or export_result.status == "partial"
                    reference_render = artifact_paths.get("render")
                    if outputs.render and reference_render is None:
                        raise _V11CompilationError(
                            "Native QA requires the requested UPBGE reference render",
                            terminal_status="rejected", stage="qa",
                            code="reference_render_missing",
                        )
                    project_path = Path(sidecar.output_dir or attempt_root / "native")
                    native_status = "partial_export" if portable_partial else "native_success"
                    self.session.compiler_result.update({
                        "target": "upbge", "status": native_status,
                        "capability": capability_payload, "sidecar": sidecar.to_dict(),
                        "glb_reload": glb_report,
                    })
            else:
                if capability is None:
                    raise RuntimeError("UPBGE capability evidence is unavailable")
                capability_failure = capability_payload
                trigger = _fallback_trigger(
                    reason_code=capability.reason_code,
                    status="rejected",
                    available=capability.available,
                    compatible=capability.compatible,
                )
                project_path, _ = run_fallback(
                    failure=capability_failure,
                    trigger=trigger,
                    stage=FailureStage.CAPABILITY_PROBE,
                )
            terminal_status = "completed"
        except _V11CompilationError as exc:
            terminal_status = exc.terminal_status
            diagnostics.append(CompilerDiagnostic(
                stage=exc.stage, code=exc.code, severity="error", message=str(exc),
            ))
            self.session.compiler_result.update({"status": "failure", "error": str(exc)})
            pending_error = exc
        except TimeoutError as exc:
            terminal_status = "timed_out"
            diagnostics.append(CompilerDiagnostic(
                stage="compile", code="timeout", severity="error", message=str(exc),
            ))
            self.session.compiler_result.update({"status": "failure", "error": str(exc)})
            pending_error = exc
        except Exception as exc:
            terminal_status = "failed"
            diagnostics.append(CompilerDiagnostic(
                stage="compile", code="unexpected_error", severity="error", message=str(exc),
            ))
            self.session.compiler_result.update({"status": "failure", "error": str(exc)})
            pending_error = exc
        finally:
            for candidate in sorted(attempt_root.rglob("*")):
                if candidate.is_file():
                    try:
                        role = "available:" + candidate.relative_to(attempt_root).as_posix()
                        add_artifact(candidate, role)
                    except OSError:
                        continue
            ended_at = datetime.now(timezone.utc)
            compile_timing = TimingRecord(
                stage="world_compilation",
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=round((time.monotonic() - started_monotonic) * 1000, 3),
            )
            timings = (probe_timing, compile_timing)
            terminal, terminal_path = store.terminate(
                prepared,
                status=terminal_status,
                timings=timings,
                diagnostics=tuple(diagnostics),
                artifacts=tuple(artifacts),
            )
            self.session.compiler_manifests.append(str(terminal_path))
            self.session.compiler_result.update({
                "compilation_id": terminal.compilation_id,
                "duration_ms": compile_timing.duration_ms,
                "prepared_manifest": str(prepared_path),
                "prepared_manifest_sha256": manifest_hash(prepared),
                "terminal_manifest": str(terminal_path),
                "terminal_manifest_sha256": manifest_hash(terminal),
                "terminal_status": terminal.status,
                "artifacts": [item.model_dump(mode="json") for item in artifacts],
                "parity_passed": bool(parity_report and parity_report.get("passed")),
                "runtime_smoke": runtime_report,
                "producing_adapter": producing_adapter.value if producing_adapter else None,
            })
            attempt_record = CanonicalDocument.from_value({
                "schema_version": "compiler-attempt-record/v1",
                "compilation_id": terminal.compilation_id,
                "profile_id": self.session.workflow_profile_id,
                "primary_adapter": primary_adapter.value,
                "fallback_adapter": fallback_adapter.value if fallback_adapter else None,
                "result": self.session.compiler_result,
                "exports": self.session.export_results,
                "parity_report": parity_report,
                "runtime_smoke_report": runtime_report,
            })
            self.session.compiler_attempt_records += (attempt_record,)
            self.telemetry.record_compiler_event(
                phase="terminal",
                compilation_id=terminal.compilation_id,
                target=str(self.session.compiler_result.get("target", primary_adapter.value)),
                status=str(self.session.compiler_result.get("status", terminal.status)),
                manifest_sha256=manifest_hash(terminal),
                producing_adapter=(
                    producing_adapter.value if producing_adapter else None
                ),
                artifact_roles=tuple(item.target_role for item in artifacts),
                parity_status=(
                    "passed" if parity_report and parity_report.get("passed") else
                    "failed" if parity_report is not None else "not_run"
                ),
                runtime_status=(
                    "passed" if runtime_report and runtime_report.get("passed") else
                    "failed" if runtime_report is not None else "not_applicable"
                ),
            )
        if pending_error is not None:
            raise pending_error
        if project_path is None or parity_report is None:
            raise RuntimeError("V11 compiler completed without a project or parity evidence")

        self.session.runtime_smoke_report = runtime_report
        self._run_v11_qa(
            parity_report=parity_report,
            runtime_report=runtime_report,
            runtime_applicable=producing_adapter == AdapterKind.UPBGE,
            reference_render=reference_render,
        )
        return project_path

    def step_assemble(self, mesh_paths: dict[str, Path]) -> Path:
        self.session.state = PipelineState.ASSEMBLING_WORLD
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
        world_stage = self.session.workflow_profile.get("stages", {}).get("world", {})
        contract_routed = world_stage.get("contract") == "world-contract/v1"
        if contract_routed:
            primary = world_stage.get("primary_adapter", "unconfigured")
            fallback = world_stage.get("fallback_adapter")
            route_label = f"{primary} primary"
            if fallback:
                route_label += f" with declared {fallback} fallback"
            self._progress(f"Compiling WorldContract via profile route: {route_label}...")
            try:
                with self.telemetry.substep("assemble", "compile_world_contract"):
                    project_path = self._assemble_v11(mesh_paths)
                self.session.output_path = str(project_path)
                compiler_status = (self.session.compiler_result or {}).get("status")
                if compiler_status not in {
                    "native_success", "fallback_success", "adapter_success"
                }:
                    raise RuntimeError(
                        f"V11 compiler did not produce an accepted world: {compiler_status}"
                    )
                if not self.session.qa_evidence:
                    raise RuntimeError("V11 compilation produced no QA evidence")
                decision = self.session.qa_evidence[-1].get("decision")
                if decision in {
                    QADecision.COMPILER_REJECTED.value,
                    QADecision.HUMAN_REJECTED.value,
                }:
                    raise RuntimeError(f"V11 QA rejected the world: {decision}")
                if decision == QADecision.HUMAN_REQUIRED.value:
                    self.session.state = PipelineState.AWAITING_QA
                    self._progress(f"World compiled at {project_path}; human QA is required")
                    return project_path
                if decision not in {
                    QADecision.AUTO_ACCEPTED.value,
                    QADecision.HUMAN_APPROVED.value,
                }:
                    raise RuntimeError(f"Unsupported V11 QA decision: {decision}")
                self.session.state = PipelineState.READY
                self.session.error = None
                self._progress(f"World ready at: {project_path}")
                return project_path
            except Exception as exc:
                self.session.state = PipelineState.ERROR
                self.session.error = str(exc)
                raise
        else:
            self._progress("Assembling Godot project...")
            with self.telemetry.substep("assemble", "assemble_godot_project"):
                project_path = assemble_godot_project(
                    self.session.scene_graph, self.output_dir, mesh_paths
                )
        self.session.output_path = str(project_path)
        self.session.state = PipelineState.READY
        self._progress(f"World ready at: {project_path}")
        return project_path

    async def build_full(self, description: str) -> Path:
        """Run the entire pipeline end-to-end."""
        try:
            await self.step_interpret(description)
            await self.step_build_floor_plan()
            if (
                self.session.interface_version >= 10
                and not validate_floor_plan(self.session.floor_plan, tolerance="strict").valid
            ):
                raise RuntimeError("Plan has unresolved geometry blockers and cannot be approved")
            if self.session.interface_version >= 11 and (
                (self.session.composition_evidence or {}).get("status") != "accepted"
                or self.session.camera_contract is None
            ):
                raise RuntimeError(
                    "Plan has no accepted full-bounds composition candidate and cannot be approved"
                )
            self.session.floor_plan_approved = True
            await self.step_generate_image()
            await self.step_build_scene_graph()
            mesh_paths = self.step_generate_assets()
            return self.step_assemble(mesh_paths)
        except Exception as e:
            self.session.state = PipelineState.ERROR
            self.session.error = str(e)
            raise
