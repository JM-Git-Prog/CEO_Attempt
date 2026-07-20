"""
The Living Room Pipeline - End-to-end world building.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from src.models import PipelineState, SceneConcept, SceneGraph, WorldSession
from src.orchestrator.interpreter import interpret_description
from src.canon_image.generator import generate_canon_image
from src.scene_graph.builder import build_scene_graph
from src.asset_factory.mesh_generator import generate_all_meshes
from src.assembler.godot_project import assemble_godot_project

OUTPUT_BASE = Path("output")


class WorldBuilder:
    """Orchestrates the full world-building pipeline."""

    def __init__(self, session_id: Optional[str] = None):
        self.session = WorldSession(session_id=session_id or str(uuid.uuid4())[:8])
        self.output_dir = OUTPUT_BASE / self.session.session_id
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _progress(self, msg: str):
        self.session.progress_messages.append(msg)
        print(f"[{self.session.session_id}] {msg}")

    async def step_interpret(self, description: str) -> SceneConcept:
        self.session.state = PipelineState.GENERATING_CONCEPT
        self.session.user_description = description
        self._progress("Interpreting your description...")
        concept = await interpret_description(description)
        self.session.scene_concept = concept
        self._progress(f"Scene concept ready: {concept.era}, {concept.mood}")
        return concept

    async def step_generate_image(self, attempt: int = 1) -> Path:
        self.session.state = PipelineState.GENERATING_IMAGE
        self._progress("Generating canon image...")
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        image_path = await generate_canon_image(self.session.scene_concept, self.session.session_id, attempt)
        self.session.canon_image_path = str(image_path)
        self._progress(f"Canon image generated: {image_path.name}")
        return image_path

    async def step_build_scene_graph(self) -> SceneGraph:
        self.session.state = PipelineState.BUILDING_SCENE_GRAPH
        self._progress("Building spatial layout...")
        if not self.session.scene_concept:
            raise RuntimeError("No scene concept")
        scene = await build_scene_graph(self.session.scene_concept)
        self.session.scene_graph = scene
        self._progress(f"Scene graph ready: {len(scene.objects)} objects, {len(scene.lights)} lights, {len(scene.doors)} doors")
        return scene

    def step_generate_assets(self) -> dict[str, Path]:
        self.session.state = PipelineState.GENERATING_ASSETS
        self._progress("Generating 3D assets...")
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
        mesh_paths = generate_all_meshes(self.session.scene_graph, self.output_dir)
        self._progress(f"Generated {len(mesh_paths)} mesh assets")
        return mesh_paths

    def step_assemble(self, mesh_paths: dict[str, Path]) -> Path:
        self.session.state = PipelineState.ASSEMBLING_WORLD
        self._progress("Assembling Godot project...")
        if not self.session.scene_graph:
            raise RuntimeError("No scene graph")
        project_path = assemble_godot_project(self.session.scene_graph, self.output_dir, mesh_paths)
        self.session.output_path = str(project_path)
        self.session.state = PipelineState.READY
        self._progress(f"World ready at: {project_path}")
        return project_path

    async def build_full(self, description: str) -> Path:
        """Run the entire pipeline end-to-end."""
        try:
            await self.step_interpret(description)
            await self.step_generate_image()
            await self.step_build_scene_graph()
            mesh_paths = self.step_generate_assets()
            return self.step_assemble(mesh_paths)
        except Exception as e:
            self.session.state = PipelineState.ERROR
            self.session.error = str(e)
            raise
