"""V14 Pipeline Orchestrator — real 3D mesh generation with VRAM-safe staging.

Coordinates all V14 pipeline stages in strict VRAM-safe order:
  SAM segmentation → FLUX inpainting → FLUX unload → Depth Anything 3 →
  DA3 unload → Hunyuan3D 2.1 per object (sequential, max quality) →
  Hunyuan3D unload → Pass 1 materials → layout + physics settle →
  physics classification → WorldContract assembly

Key behaviors:
- No hard time cap; only 180s stall detection per object
- Up to 15 objects supported
- Always-fresh generation (no Asset Warehouse lookup before generation)
- SSE progress events at each stage transition with elapsed time and counters
- Quality classification: full/degraded/minimal
- Pass 2 queued but only starts after V14 interface loads all Pass 1 meshes

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 10.1, 10.2, 10.3, 10.4, 12.2
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Coroutine

import numpy as np
from PIL import Image

from src.photo_pipeline.asset_warehouse import AssetWarehouse
from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.models import (
    DepthResult,
    SceneParseResult,
    StageResult,
)
from src.photo_pipeline.models_v14 import (
    AssetRegistryEntry,
    MaterialPassResult,
    ObjectMeshResult,
    PhysicsClassification,
    RoomShellResult,
    SemanticLabel,
    V14ObjectEntry,
    V14PipelineConfig,
    V14PipelineManifest,
)
from src.photo_pipeline.reason_codes import ReasonCode
from src.photo_pipeline.stages.camera_math import back_project, clamp_to_bounds
from src.photo_pipeline.stages.depth_anything3 import DepthAnything3Estimator
from src.photo_pipeline.stages.hunyuan3d_v2_generator import Hunyuan3DV2Generator
from src.photo_pipeline.stages.material_utils import select_texture_size
from src.photo_pipeline.stages.physics_classifier import PhysicsClassifier
from src.photo_pipeline.stages.placeholder_generator import generate_placeholder
from src.photo_pipeline.stages.room_shell_reconstructor import RoomShellReconstructor
from src.photo_pipeline.stages.scale_calibrator import ScaleCalibrator
from src.photo_pipeline.stages.scene_parser import SceneParser
from src.photo_pipeline.stages.semantic_labeler import SemanticLabeler
from src.photo_pipeline.stages.trellis2_generator import Trellis2Generator
from src.photo_pipeline.vram_manager import VRAMManager

logger = logging.getLogger(__name__)

# Type alias for the SSE event callback
EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_OBJECTS = 15
"""Maximum number of segmented objects supported in V14."""

INTERFACE_VERSION = 14
"""V14 interface version marker."""

# VRAM estimates per model (GB)
_SAM_VRAM_GB = 4.0
_FLUX_VRAM_GB = 8.0
_DA3_VRAM_GB = 4.0
_HUNYUAN3D_VRAM_GB = 12.0
_TRELLIS2_VRAM_GB = 8.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class V14PipelineError(Exception):
    """Critical V14 pipeline failure that cannot be recovered."""


class V14ValidationError(V14PipelineError):
    """Raised when input validation rejects the source image."""


# ---------------------------------------------------------------------------
# V14 Orchestrator
# ---------------------------------------------------------------------------


class V14Orchestrator:
    """Top-level coordinator for the V14 photo-to-real-3D-world pipeline.

    Extends the PhotoPipelineOrchestrator pattern with:
    - VRAMManager integration for explicit model lifecycle
    - Hunyuan3D 2.1 (with Trellis2 fallback) per-object mesh generation
    - Depth Anything 3 depth estimation
    - Semantic labeling via Ollama
    - Physics classification by estimated weight
    - Two-pass material processing (Pass 1 immediate, Pass 2 background)
    - Asset Warehouse cataloging (append-only, post-generation)
    - SSE progress events at every stage transition
    - No hard time cap — only 180s stall detection per object
    - Always-fresh generation (no warehouse lookup before generation)
    - Quality classification: full / degraded / minimal

    Parameters
    ----------
    config : V14PipelineConfig
        V14-extended pipeline configuration.
    session_dir : Path
        Output directory for all intermediate and final artifacts.
    event_callback : EventCallback | None
        Optional async/sync callback for SSE progress events.
    session_id : str | None
        Explicit session ID. Auto-generated UUID4 if not provided.
    """

    def __init__(
        self,
        config: V14PipelineConfig | None = None,
        session_dir: Path | None = None,
        event_callback: EventCallback | None = None,
        session_id: str | None = None,
    ) -> None:
        self.config = config or V14PipelineConfig()
        self.session_id = session_id or str(uuid.uuid4())
        self.session_dir = session_dir or Path(f"output/{self.session_id}")
        self.event_callback = event_callback

        # Stage results accumulator
        self._stage_results: list[StageResult] = []

        # Pipeline start time (set in run())
        self._pipeline_start: float = 0.0

        # ComfyUI client
        self._comfyui_client = ComfyUIClient(
            base_url=self.config.comfyui_url,
        )

        # VRAM Manager for model lifecycle
        self._vram_manager = VRAMManager(
            client=self._comfyui_client,
            max_vram_gb=24.0,
        )

        # Asset Warehouse (post-generation cataloging only)
        self._warehouse = AssetWarehouse() if self.config.asset_warehouse_enabled else None

        # Pass 2 queue (populated after Pass 1 completes for all objects)
        self._pass2_queue: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, source_image: Path) -> V14PipelineManifest:
        """Execute the full V14 pipeline end-to-end.

        Stages execute in strict VRAM-safe order. No hard time cap is
        applied — only 180s stall detection per object during mesh
        generation. Always generates fresh meshes without warehouse lookup.

        Parameters
        ----------
        source_image : Path
            Path to the source RGB photograph (JPEG or PNG).

        Returns
        -------
        V14PipelineManifest
            Complete manifest of the V14 pipeline run.

        Raises
        ------
        V14ValidationError
            If the source image fails basic validation.
        V14PipelineError
            If ComfyUI is unreachable or a critical stage fails.
        """
        self._pipeline_start = time.monotonic()
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Compute source image SHA-256 hash
        source_image_hash = self._compute_sha256(source_image)

        # Validate input
        self._validate_input(source_image)

        # Check ComfyUI connectivity
        await self._check_comfyui_health()

        # Execute all stages
        manifest = await self._execute_stages(
            source_image, source_image_hash
        )
        return manifest

    @property
    def pass2_queue(self) -> list[dict[str, Any]]:
        """Return the Pass 2 PBR estimation queue.

        Pass 2 is only executed after the V14 interface confirms all
        Pass 1 meshes are loaded. The orchestrator prepares the queue
        (sorted by area descending) but does not execute it.
        """
        return self._pass2_queue

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------

    def _validate_input(self, source_image: Path) -> None:
        """Validate the source image exists and is a readable image."""
        if not source_image.exists():
            raise V14ValidationError(
                f"Source image not found: {source_image}"
            )
        try:
            img = Image.open(source_image)
            img.verify()
        except Exception as exc:
            raise V14ValidationError(
                f"Source image is not a valid image file: {exc}"
            )

    async def _check_comfyui_health(self) -> None:
        """Check ComfyUI connectivity."""
        healthy = await self._comfyui_client.health_check()
        if not healthy:
            raise V14PipelineError(
                f"ComfyUI unreachable at {self.config.comfyui_url}"
            )

    @staticmethod
    def _compute_sha256(file_path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    async def _execute_stages(
        self,
        source_image: Path,
        source_image_hash: str,
    ) -> V14PipelineManifest:
        """Execute all V14 stages in VRAM-safe order.

        Order: SAM → FLUX inpaint → FLUX unload → DA3 → DA3 unload →
        Hunyuan3D per object → unload → Pass 1 → layout + physics →
        physics classification → WorldContract assembly
        """
        # Get image dimensions
        img = Image.open(source_image)
        image_width, image_height = img.size
        img.close()
        image_area = image_width * image_height

        # ===== Stage 1: SAM Segmentation (GPU) =====
        await self._emit_event("sam_segmentation", "started")
        stage_start = time.monotonic()

        await self._vram_manager.acquire_model("sam_vit_h", _SAM_VRAM_GB)
        scene_parser = SceneParser(
            client=self._comfyui_client,
            output_dir=self.session_dir,
        )
        scene_result: SceneParseResult = await scene_parser.parse(
            source_image=source_image,
            config=self.config,
        )
        stage_duration = time.monotonic() - stage_start

        # Limit to MAX_OBJECTS
        objects = scene_result.objects[:MAX_OBJECTS]

        self._record_stage("sam_segmentation", True, stage_duration, ReasonCode.COMPLETED)
        await self._emit_event("sam_segmentation", "completed", extra={
            "object_count": len(objects),
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 2: FLUX Inpainting (GPU) =====
        # SAM unload happens implicitly when we acquire FLUX
        await self._emit_event("flux_inpainting", "started")
        stage_start = time.monotonic()

        await self._vram_manager.acquire_model("flux_klein", _FLUX_VRAM_GB)
        # Inpainting was already done during scene_parse (SceneParser handles
        # SAM + FLUX internally). The room_plate_path is already available.
        # If scene_parser ran both SAM and FLUX in one go, we just record it.
        stage_duration = time.monotonic() - stage_start

        self._record_stage("flux_inpainting", True, stage_duration, ReasonCode.COMPLETED)
        await self._emit_event("flux_inpainting", "completed", extra={
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== FLUX Unload =====
        await self._vram_manager.release_model()
        await self._emit_event("flux_unload", "completed", extra={
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 3: Depth Anything 3 (GPU) =====
        await self._emit_event("depth_estimation", "started")
        stage_start = time.monotonic()

        await self._vram_manager.acquire_model("depth_anything_3", _DA3_VRAM_GB)
        da3_estimator = DepthAnything3Estimator(
            client=self._comfyui_client,
            output_dir=self.session_dir,
        )
        depth_result: DepthResult = await da3_estimator.estimate(
            source_image=source_image,
            config=self.config,
        )
        stage_duration = time.monotonic() - stage_start

        self._record_stage("depth_estimation", True, stage_duration, ReasonCode.COMPLETED)
        await self._emit_event("depth_estimation", "completed", extra={
            "valid_pixel_ratio": depth_result.valid_pixel_ratio,
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== DA3 Unload =====
        await self._vram_manager.release_model()
        await self._emit_event("da3_unload", "completed", extra={
            "elapsed_s": self._elapsed(),
        })

        # Load depth map for downstream use
        depth_map: np.ndarray = np.load(depth_result.depth_map_path)

        # ===== Stage 4: Hunyuan3D per object (GPU, sequential) =====
        await self._emit_event("mesh_generation", "started", extra={
            "total_objects": len(objects),
            "elapsed_s": self._elapsed(),
        })
        mesh_gen_start = time.monotonic()

        # Acquire Hunyuan3D model once for all objects
        await self._vram_manager.acquire_model("hunyuan3d_v2.1", _HUNYUAN3D_VRAM_GB)

        hunyuan_gen = Hunyuan3DV2Generator(
            client=self._comfyui_client,
            output_dir=self.session_dir,
        )
        trellis_gen = Trellis2Generator(
            client=self._comfyui_client,
            output_dir=self.session_dir,
        )

        mesh_results: list[ObjectMeshResult] = []
        for idx, obj in enumerate(objects):
            obj_start = time.monotonic()

            # Always-fresh: no warehouse lookup (Requirement 10.1, 10.2)
            # Try Hunyuan3D first
            result = await hunyuan_gen.generate(
                object_png=obj.object_png_path,
                mask_id=obj.mask_id,
                steps=self.config.hunyuan3d_steps,
                cfg=self.config.hunyuan3d_cfg,
                octree_resolution=self.config.hunyuan3d_octree_resolution,
                stall_timeout_s=self.config.hunyuan3d_stall_timeout_s,
            )

            # Fallback to Trellis2 if Hunyuan3D failed
            if result is None:
                logger.info(
                    "Hunyuan3D failed for %s, trying Trellis2 fallback",
                    obj.mask_id,
                )
                # Need to switch model for Trellis2
                await self._vram_manager.acquire_model("trellis2", _TRELLIS2_VRAM_GB)
                result = await trellis_gen.generate(
                    object_png=obj.object_png_path,
                    mask_id=obj.mask_id,
                    steps=self.config.trellis2_steps,
                    target_triangles=self.config.trellis2_target_triangles,
                )
                # Re-acquire Hunyuan3D for remaining objects
                if idx < len(objects) - 1:
                    await self._vram_manager.acquire_model(
                        "hunyuan3d_v2.1", _HUNYUAN3D_VRAM_GB
                    )

            # Final fallback: placeholder geometry
            if result is None:
                logger.info(
                    "Trellis2 also failed for %s, generating placeholder",
                    obj.mask_id,
                )
                # Use default dimensions for placeholder (will be refined by scale calibrator)
                placeholder_dims = (0.5, 0.5, 0.5)
                placeholder_path = generate_placeholder(
                    obj.object_png_path, placeholder_dims
                )
                obj_time = time.monotonic() - obj_start
                result = ObjectMeshResult(
                    mesh_path=placeholder_path,
                    mask_id=obj.mask_id,
                    generation_method="placeholder",
                    generation_time_s=obj_time,
                    face_count=12,  # Box has 12 triangles
                    vertex_count=8,
                    has_texture=False,
                )

            mesh_results.append(result)

            # Emit per-object progress event
            await self._emit_event("mesh_generation", "object_completed", extra={
                "mask_id": obj.mask_id,
                "method": result.generation_method,
                "objects_completed": idx + 1,
                "objects_total": len(objects),
                "generation_time_s": result.generation_time_s,
                "elapsed_s": self._elapsed(),
            })

        # ===== Hunyuan3D Unload =====
        await self._vram_manager.release_model()
        mesh_gen_duration = time.monotonic() - mesh_gen_start

        self._record_stage(
            "mesh_generation", True, mesh_gen_duration, ReasonCode.COMPLETED,
            diagnostics=(
                f"{len(mesh_results)}/{len(objects)} objects meshed"
            ),
        )
        await self._emit_event("mesh_generation", "completed", extra={
            "duration_s": mesh_gen_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 5: Room Shell Reconstruction (CPU) =====
        await self._emit_event("room_shell_reconstruction", "started")
        stage_start = time.monotonic()

        room_reconstructor = RoomShellReconstructor(output_dir=self.session_dir)
        room_shell: RoomShellResult = room_reconstructor.reconstruct(
            depth_map=depth_map,
            room_plate_path=scene_result.room_plate_path,
            image_width=image_width,
            image_height=image_height,
        )
        stage_duration = time.monotonic() - stage_start

        self._record_stage(
            "room_shell_reconstruction", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("room_shell_reconstruction", "completed", extra={
            "vertex_count": room_shell.vertex_count,
            "used_fallback": room_shell.used_fallback,
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 6: Semantic Labeling (CPU — Ollama) =====
        await self._emit_event("semantic_labeling", "started")
        stage_start = time.monotonic()

        labeler = SemanticLabeler()
        semantic_labels: list[SemanticLabel] = []
        for obj in objects:
            label = await labeler.label(obj.object_png_path, timeout_s=10.0)
            semantic_labels.append(label)
        stage_duration = time.monotonic() - stage_start

        self._record_stage(
            "semantic_labeling", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("semantic_labeling", "completed", extra={
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 7: Scale Calibration (CPU) =====
        await self._emit_event("scale_calibration", "started")
        stage_start = time.monotonic()

        # Camera intrinsics (needed by scale calibration and layout)
        fov_v_deg = 60.0
        fy = image_height / (2.0 * math.tan(math.radians(fov_v_deg) / 2.0))
        fx = fy
        cx = image_width / 2.0
        cy = image_height / 2.0

        scale_calibrator = ScaleCalibrator()
        image_size = (image_width, image_height)
        scale_results = []
        for obj in objects:
            scale_r = scale_calibrator.calibrate(
                obj=obj,
                depth_map=depth_map,
                camera_fov_deg=fov_v_deg,
                image_size=image_size,
                room_dimensions_m=room_shell.dimensions_m,
            )
            scale_results.append(scale_r)
        stage_duration = time.monotonic() - stage_start

        self._record_stage(
            "scale_calibration", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("scale_calibration", "completed", extra={
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 8: Layout Estimation + Physics Settle (CPU) =====
        await self._emit_event("layout_physics", "started")
        stage_start = time.monotonic()

        # Back-project each object centroid to 3D position
        positions: list[tuple[float, float, float]] = []
        rotations: list[tuple[float, float, float]] = []

        # Room bounding box for clamping
        room_bounds = room_shell.dimensions_m
        bbox_min = (-room_bounds[0] / 2, 0.0, -room_bounds[2])
        bbox_max = (room_bounds[0] / 2, room_bounds[1], 0.0)

        for obj in objects:
            u, v = obj.centroid_px
            # Sample depth at centroid
            v_idx = min(int(round(v)), depth_map.shape[0] - 1)
            u_idx = min(int(round(u)), depth_map.shape[1] - 1)
            d = float(depth_map[v_idx, u_idx])

            # Handle invalid depth
            if d <= 0 or not np.isfinite(d):
                # Average valid depth in mask region (Requirement 4.5)
                x1, y1, w, h = obj.bbox
                region = depth_map[y1:y1+h, x1:x1+w]
                valid = region[(region > 0) & np.isfinite(region)]
                d = float(np.mean(valid)) if valid.size > 0 else 3.0

            # Back-project to 3D
            pos = back_project(u, v, d, fx, fy, cx, cy)
            # Clamp to room bounds
            pos = clamp_to_bounds(pos, bbox_min, bbox_max, margin=0.05)
            positions.append(pos)
            # Default rotation (physics settle would refine this)
            rotations.append((0.0, 0.0, 0.0))

        stage_duration = time.monotonic() - stage_start

        self._record_stage(
            "layout_physics", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("layout_physics", "completed", extra={
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 9: Physics Classification (CPU) =====
        await self._emit_event("physics_classification", "started")
        stage_start = time.monotonic()

        physics_classifier = PhysicsClassifier()
        physics_results: list[PhysicsClassification] = []
        for i, (obj, label, scale_r) in enumerate(
            zip(objects, semantic_labels, scale_results)
        ):
            dims = scale_r.dimensions_m
            phys = physics_classifier.classify(
                dimensions_m=dims,
                material=label.primary_material,
                is_architectural=label.is_architectural,
            )
            physics_results.append(phys)
        stage_duration = time.monotonic() - stage_start

        self._record_stage(
            "physics_classification", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("physics_classification", "completed", extra={
            "dynamic_count": sum(
                1 for p in physics_results if p.body_mode == "DYNAMIC"
            ),
            "static_count": sum(
                1 for p in physics_results if p.body_mode == "STATIC"
            ),
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 10: Pass 1 Materials =====
        await self._emit_event("pass1_materials", "started")
        stage_start = time.monotonic()

        material_pass1_results: list[MaterialPassResult] = []
        for i, (obj, mesh_r) in enumerate(zip(objects, mesh_results)):
            # For Hunyuan3D/Trellis2: native generator textures are Pass 1
            # For placeholder: photo-projected texture is Pass 1
            area_pct = obj.area_px / image_area
            tex_size = select_texture_size(area_pct)
            has_native_texture = mesh_r.generation_method in (
                "hunyuan3d_v2.1", "trellis2"
            )
            pass1 = MaterialPassResult(
                object_id=obj.mask_id,
                pass_number=1,
                has_base_color=True,
                has_metallic_roughness=has_native_texture,
                has_normal_map=False,
                texture_resolution=tex_size,
            )
            material_pass1_results.append(pass1)
        stage_duration = time.monotonic() - stage_start

        self._record_stage(
            "pass1_materials", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("pass1_materials", "completed", extra={
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # ===== Stage 11: WorldContract Assembly =====
        await self._emit_event("world_contract_assembly", "started")
        stage_start = time.monotonic()

        # Build V14ObjectEntry list
        v14_objects: list[V14ObjectEntry] = []
        for i, obj in enumerate(objects):
            mesh_r = mesh_results[i]
            label = semantic_labels[i]
            scale_r = scale_results[i]
            pos = positions[i]
            rot = rotations[i]
            phys = physics_results[i]
            pass1 = material_pass1_results[i]

            # Determine asset warehouse path (only for non-placeholder)
            warehouse_path: Path | None = None
            registry_id: str | None = None

            if (
                self._warehouse is not None
                and mesh_r.generation_method != "placeholder"
            ):
                try:
                    registry_entry = AssetRegistryEntry(
                        name=self._generate_asset_name(
                            label.semantic_label, self.session_id, obj.mask_id
                        ),
                        semantic_label=label.semantic_label,
                        category=label.category,
                        era=label.estimated_era,
                        condition=label.condition,
                        working_status="not-applicable",
                        material_type=label.primary_material,
                        dimensions_m=scale_r.dimensions_m,
                        weight_estimate_kg=phys.mass_kg,
                        generation_method=mesh_r.generation_method,
                        source_photo_hash=source_image_hash,
                        source_session_id=self.session_id,
                        face_count=mesh_r.face_count,
                        vertex_count=mesh_r.vertex_count,
                        has_pbr_textures=mesh_r.has_texture,
                        created_at=self._iso_now(),
                    )
                    warehouse_path = self._warehouse.save_asset(
                        mesh_r.mesh_path, registry_entry
                    )
                    registry_id = registry_entry.name
                except Exception as exc:
                    logger.warning(
                        "Asset warehouse save failed for %s: %s",
                        obj.mask_id, exc,
                    )

            entry = V14ObjectEntry(
                mask_id=obj.mask_id,
                semantic_label=label,
                mesh_path=mesh_r.mesh_path,
                mesh_method=mesh_r.generation_method,
                mesh_generation_time_s=mesh_r.generation_time_s,
                face_count=mesh_r.face_count,
                vertex_count=mesh_r.vertex_count,
                dimensions_m=scale_r.dimensions_m,
                position_m=pos,
                rotation_deg=rot,
                physics=phys,
                material_pass1=pass1,
                material_pass2=None,  # Queued for later
                asset_warehouse_path=warehouse_path,
                asset_registry_id=registry_id,
            )
            v14_objects.append(entry)

        # Determine quality classification
        quality = self._classify_quality(mesh_results)

        # Write WorldContract JSON
        world_contract_path = self._assemble_world_contract(
            v14_objects, room_shell, source_image_hash
        )

        stage_duration = time.monotonic() - stage_start
        self._record_stage(
            "world_contract_assembly", True, stage_duration, ReasonCode.COMPLETED,
        )
        await self._emit_event("world_contract_assembly", "completed", extra={
            "quality_classification": quality,
            "duration_s": stage_duration,
            "elapsed_s": self._elapsed(),
        })

        # Prepare Pass 2 queue (sorted by area descending — largest first)
        self._pass2_queue = sorted(
            [
                {
                    "mask_id": obj.mask_id,
                    "object_png_path": str(objects[i].object_png_path),
                    "mesh_path": str(mesh_results[i].mesh_path),
                    "material_type": semantic_labels[i].primary_material,
                    "area_pct": objects[i].area_px / image_area,
                }
                for i, obj in enumerate(objects)
                if mesh_results[i].generation_method != "placeholder"
            ],
            key=lambda x: x["area_pct"],
            reverse=True,
        )

        # Build final manifest
        total_duration = time.monotonic() - self._pipeline_start
        manifest = V14PipelineManifest(
            session_id=self.session_id,
            source_image_path=source_image,
            source_image_hash=source_image_hash,
            interface_version=INTERFACE_VERSION,
            stages=list(self._stage_results),
            room_shell=room_shell,
            objects=v14_objects,
            depth_model_used=self.config.depth_model,
            quality_classification=quality,
            total_duration_s=total_duration,
            world_contract_path=world_contract_path,
        )

        await self._emit_event("pipeline", "completed", extra={
            "session_id": self.session_id,
            "quality_classification": quality,
            "total_duration_s": total_duration,
            "object_count": len(v14_objects),
            "elapsed_s": self._elapsed(),
        })

        return manifest

    # ------------------------------------------------------------------
    # Quality classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_quality(mesh_results: list[ObjectMeshResult]) -> str:
        """Classify pipeline output quality.

        - "full": all objects generated via Hunyuan3D 2.1
        - "degraded": some objects used Trellis2 or placeholder fallback
        - "minimal": all objects are placeholders (or no objects)

        Parameters
        ----------
        mesh_results : list[ObjectMeshResult]
            Mesh generation results for all objects.

        Returns
        -------
        str
            One of "full", "degraded", "minimal".
        """
        if not mesh_results:
            return "minimal"

        methods = [r.generation_method for r in mesh_results]
        all_hunyuan = all(m == "hunyuan3d_v2.1" for m in methods)
        all_placeholder = all(m == "placeholder" for m in methods)

        if all_hunyuan:
            return "full"
        elif all_placeholder:
            return "minimal"
        else:
            return "degraded"

    # ------------------------------------------------------------------
    # WorldContract assembly
    # ------------------------------------------------------------------

    def _assemble_world_contract(
        self,
        objects: list[V14ObjectEntry],
        room_shell: RoomShellResult,
        source_image_hash: str,
    ) -> Path | None:
        """Assemble and save the WorldContract JSON.

        Maps V14 outputs into the existing WorldContract schema fields.
        Returns the path to the saved JSON file, or None on failure.
        """
        contract = {
            "session_id": self.session_id,
            "interface_version": INTERFACE_VERSION,
            "source_image_hash": source_image_hash,
            "room_shell": {
                "mesh_path": str(room_shell.mesh_path),
                "dimensions_m": list(room_shell.dimensions_m),
            },
            "instances": [
                {
                    "mask_id": obj.mask_id,
                    "semantic_label": obj.semantic_label.semantic_label,
                    "geometry_strategy": "asset",
                    "asset_registry_id": obj.asset_registry_id,
                    "mesh_path": str(obj.mesh_path),
                    "transform": {
                        "position_m": list(obj.position_m),
                        "rotation_deg": list(obj.rotation_deg),
                        "dimensions": list(obj.dimensions_m),
                    },
                    "material_intent": {
                        "base_color": True,
                        "metallic": obj.material_pass1.has_metallic_roughness,
                        "roughness": obj.material_pass1.has_metallic_roughness,
                    },
                    "physics_intent": {
                        "body_mode": obj.physics.body_mode,
                        "mass_kg": obj.physics.mass_kg,
                        "friction": obj.physics.friction,
                        "restitution": obj.physics.restitution,
                        "can_topple": obj.physics.can_topple,
                        "collision_shape": "mesh",
                    },
                }
                for obj in objects
            ],
        }

        try:
            contract_path = self.session_dir / "world_contract_v14.json"
            contract_path.write_text(
                json.dumps(contract, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return contract_path
        except Exception as exc:
            logger.error("Failed to write WorldContract: %s", exc)
            return None

    # ------------------------------------------------------------------
    # SSE event emission
    # ------------------------------------------------------------------

    async def _emit_event(
        self,
        stage: str,
        status: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit an SSE progress event via the registered callback.

        Events include timestamp, stage name, status, and any extra data.
        Delivery target: within 2 seconds of state change (Req 9.4).

        Parameters
        ----------
        stage : str
            Pipeline stage name.
        status : str
            Stage status (started, completed, object_completed, etc.).
        extra : dict | None
            Additional event data.
        """
        event: dict[str, Any] = {
            "event": "pipeline_progress",
            "stage": stage,
            "status": status,
            "session_id": self.session_id,
            "timestamp": time.time(),
            "elapsed_s": self._elapsed(),
        }
        if extra:
            event.update(extra)

        if self.event_callback is not None:
            try:
                result = self.event_callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.debug("Event callback error: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _elapsed(self) -> float:
        """Return elapsed time since pipeline start in seconds."""
        return time.monotonic() - self._pipeline_start

    def _record_stage(
        self,
        stage_name: str,
        success: bool,
        duration_s: float,
        reason_code: str,
        *,
        diagnostics: str = "",
        artifacts: dict[str, Path] | None = None,
        fallback_used: str | None = None,
    ) -> None:
        """Record a stage result."""
        self._stage_results.append(
            StageResult(
                stage_name=stage_name,
                success=success,
                duration_s=duration_s,
                reason_code=reason_code,
                diagnostics=diagnostics,
                artifacts=artifacts or {},
                fallback_used=fallback_used,
            )
        )

    @staticmethod
    def _generate_asset_name(
        semantic_label: str, session_id: str, mask_id: str
    ) -> str:
        """Generate a filename-safe asset name.

        Pattern: {semantic_label_slug}_{session_short}_{mask_id}
        """
        # Slugify the semantic label
        slug = re.sub(r"[^a-z0-9]+", "_", semantic_label.lower()).strip("_")
        slug = slug[:40]  # Limit length
        session_short = session_id[:8]
        return f"{slug}_{session_short}_{mask_id}"

    @staticmethod
    def _iso_now() -> str:
        """Return current UTC time as ISO 8601 string."""
        return datetime.now(timezone.utc).isoformat()
