"""
The Living Room Pipeline - End-to-end world building.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

from src.camera_contract import build_camera_contract
from src.models import PipelineState, SceneConcept, SceneGraph, WorldSession
from src.telemetry import TelemetryRecorder
from src.orchestrator.interpreter import interpret_description
from src.canon_image.generator import generate_canon_image, generate_conditioned_canon
from src.floor_plan.builder import build_floor_plan
from src.floor_plan.renderer import render_blockout, render_floor_plan_svg
from src.scene_graph.builder import build_scene_graph
from src.asset_factory.mesh_generator import generate_all_meshes
from src.assembler.godot_project import assemble_godot_project
from src.workflow_provenance import (
    historical_profile_for,
    normalize_interface_version,
    profile_by_id,
    profile_for,
    snapshot_session,
)

OUTPUT_BASE = Path("output")
V8_LLM_STAGE_TIMEOUT_SECONDS = max(
    1.0, float(os.getenv("V8_LLM_STAGE_TIMEOUT_SECONDS", "30"))
)


def _infer_legacy_interface_version(session_id: str) -> int:
    """Infer pre-provenance sessions from their earliest revision-log event."""
    earliest: tuple[str, int] | None = None
    for version in (3, 4, 5, 6, 7, 8, 9):
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

    def __init__(self, session_id: Optional[str] = None, interface_version: int = 9):
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
            plan, warnings = await build_floor_plan(
                self.session.user_description,
                self.session.scene_concept,
                current=current,
                feedback=feedback,
                timeout_seconds=self._llm_timeout(),
            )
        self.session.floor_plan = plan
        if self.session.interface_version >= 9:
            self.session.camera_contract = build_camera_contract(plan)
        else:
            self.session.camera_contract = None
        self.session.canon_alignment = None
        self.session.plan_revision += 1
        self.session.plan_warnings = warnings
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

    async def step_generate_image(self, attempt: int = 1) -> Path:
        self.session.state = PipelineState.GENERATING_IMAGE
        self._progress("Generating plan-conditioned canon image...")
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
        }
        if self.session.floor_plan_approved and self.session.blockout_path:
            with self.telemetry.substep("canon_image", "generate_conditioned_canon"):
                generation = await generate_conditioned_canon(
                    self.session.scene_concept,
                    Path(self.session.blockout_path),
                    self.session.session_id,
                    attempt,
                    workflow_context=workflow_context,
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
        self.session.canon_alignment = generation.alignment
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

    def step_assemble(self, mesh_paths: dict[str, Path]) -> Path:
        self.session.state = PipelineState.ASSEMBLING_WORLD
        self._progress("Assembling Godot project...")
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
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
            self.session.floor_plan_approved = True
            await self.step_generate_image()
            await self.step_build_scene_graph()
            mesh_paths = self.step_generate_assets()
            return self.step_assemble(mesh_paths)
        except Exception as e:
            self.session.state = PipelineState.ERROR
            self.session.error = str(e)
            raise
