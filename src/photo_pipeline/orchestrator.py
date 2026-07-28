"""Photo Pipeline Orchestrator — top-level coordinator for photo-to-world.

Coordinates all pipeline stages in dependency order with configurable
concurrency, timeout enforcement, SSE progress events, and artifact
persistence. GPU stages run sequentially via semaphore; CPU stages
run in parallel where dependencies allow.

Stage execution order:
  Scene Parsing → Depth Estimation → [Object Gen parallel per object]
  → [Audio parallel per object] → Light Estimation → Scale Calibration
  → Layout Estimation → Physics Settle → WorldContract Assembly

Graceful degradation (Requirement 12):
  - Object_Generator failure → substitute placeholder mesh, continue
  - Audio_Synthesizer failure → assign silent placeholder WAV, continue
  - Depth low-confidence (>30% invalid pixels) → interpolation first,
    flat-floor only if reconstruction impossible
  - Pipeline succeeds as long as Room_Mesh + WorldContract validation pass
  - Zero object meshes acceptable (player explores empty room)
  - Record degradation path per object in manifest (fallbacks_triggered)
  - Classify output: "full", "degraded", or "minimal"

Requirements: 1.1, 1.2, 1.3, 1.4, 11.2, 11.3, 11.4, 11.5, 11.7,
              12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Callable, Coroutine

import numpy as np
from PIL import Image
from scipy import ndimage  # type: ignore[import-untyped]

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.photo_pipeline.compilation_bridge import (
    CompilationBridgeResult,
    run_compilation_chain,
)
from src.photo_pipeline.input_validator import (
    InputValidationResult,
    validate_photo_input,
)
from src.photo_pipeline.models import (
    AudioResult,
    DepthResult,
    LayoutResult,
    LightEstimateResult,
    ObjectManifestEntry,
    ObjectMeshResult,
    PhotoPipelineConfig,
    PipelineManifest,
    RoomMeshResult,
    ScaleResult,
    SceneParseResult,
    SegmentedObject,
    StageResult,
)
from src.photo_pipeline.reason_codes import ReasonCode

from src.photo_pipeline.stages.assembler import PhotoWorldContractAssembler
from src.photo_pipeline.stages.audio_synthesizer import AudioSynthesizer
from src.photo_pipeline.stages.collision_lod import CollisionLODGenerator
from src.photo_pipeline.stages.depth_estimator import DepthEstimator
from src.photo_pipeline.stages.layout_estimator import LayoutEstimator
from src.photo_pipeline.stages.light_estimator import LightEstimator
from src.photo_pipeline.stages.object_generator import (
    ObjectGenerator,
    create_placeholder,
    select_placeholder_type,
)
from src.photo_pipeline.stages.physics_settle import PhysicsSettle
from src.photo_pipeline.stages.room_reconstructor import RoomReconstructor
from src.photo_pipeline.stages.scale_calibrator import ScaleCalibrator
from src.photo_pipeline.stages.scene_parser import SceneParser

logger = logging.getLogger(__name__)

# Type alias for the SSE event callback
EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None] | None]

# ---------------------------------------------------------------------------
# Degradation thresholds (Requirement 12)
# ---------------------------------------------------------------------------

# Depth low-confidence threshold: >30% invalid pixels triggers interpolation
_DEPTH_LOW_CONFIDENCE_THRESHOLD = 0.70  # valid_pixel_ratio below this = low confidence

# Audio parameters for silent placeholder
_SILENT_WAV_SAMPLE_RATE = 44100
_SILENT_WAV_CHANNELS = 1
_SILENT_WAV_SAMPLE_WIDTH = 2  # 16-bit
_SILENT_WAV_DURATION_S = 0.1


class PipelineError(Exception):
    """Critical pipeline failure that cannot be recovered."""


class PipelineTimeoutError(PipelineError):
    """Raised when the pipeline exceeds its total timeout."""


class PipelineValidationError(PipelineError):
    """Raised when input validation rejects the source image."""


class PhotoPipelineOrchestrator:
    """Top-level coordinator for the photo-to-playable-world pipeline.

    Parameters
    ----------
    config : PhotoPipelineConfig
        Pipeline configuration (concurrency, timeouts, limits).
    session_dir : Path
        Output directory for all intermediate and final artifacts.
    event_callback : EventCallback | None
        Optional async/sync callback for SSE progress events.
        Called with a dict containing at minimum:
        {"event": str, "stage": str, "status": str, "timestamp": float}
    session_id : str | None
        Explicit session ID. Auto-generated UUID4 if not provided.
    """

    def __init__(
        self,
        config: PhotoPipelineConfig | None = None,
        session_dir: Path | None = None,
        event_callback: EventCallback | None = None,
        session_id: str | None = None,
    ) -> None:
        self.config = config or PhotoPipelineConfig()
        self.session_id = session_id or str(uuid.uuid4())
        self.session_dir = session_dir or Path(f"output/{self.session_id}")
        self.event_callback = event_callback

        # Concurrency semaphores
        self._gpu_semaphore = asyncio.Semaphore(self.config.gpu_concurrency)
        self._cpu_semaphore = asyncio.Semaphore(self.config.cpu_concurrency)

        # Stage results accumulator
        self._stage_results: list[StageResult] = []

        # ComfyUI client
        self._comfyui_client = ComfyUIClient(
            base_url=self.config.comfyui_url,
        )

    async def run(self, source_image: Path) -> PipelineManifest:
        """Execute the full photo pipeline end-to-end.

        Validates input, checks ComfyUI health, then executes stages in
        dependency order with timeout enforcement.

        Parameters
        ----------
        source_image : Path
            Path to the source RGB photograph (JPEG or PNG).

        Returns
        -------
        PipelineManifest
            Complete manifest of the pipeline run.

        Raises
        ------
        PipelineValidationError
            If the source image fails input validation.
        PipelineError
            If ComfyUI is unreachable or a critical stage fails.
        PipelineTimeoutError
            If the total pipeline timeout is exceeded.
        """
        pipeline_start = time.monotonic()
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # --- Pre-flight checks ---
        self._validate_input(source_image)
        await self._check_comfyui_health()

        # --- Execute stages with overall timeout ---
        try:
            result = await asyncio.wait_for(
                self._execute_stages(source_image, pipeline_start),
                timeout=self.config.pipeline_timeout_s,
            )
            return result
        except asyncio.TimeoutError:
            total_elapsed = time.monotonic() - pipeline_start
            await self._emit_event("pipeline", "timeout", extra={
                "elapsed_s": total_elapsed,
                "timeout_s": self.config.pipeline_timeout_s,
            })
            raise PipelineTimeoutError(
                f"Pipeline exceeded {self.config.pipeline_timeout_s}s timeout "
                f"(elapsed: {total_elapsed:.1f}s)"
            )

    async def run_full(
        self,
        source_image: Path,
        *,
        upbge_path: str | None = None,
        fullscreen: bool = True,
        launch_timeout_s: float = 10.0,
        smoke_timeout_s: float = 15.0,
    ) -> tuple[PipelineManifest, CompilationBridgeResult]:
        """Execute the full photo pipeline end-to-end including UPBGE compilation.

        Runs the complete chain:
            input validator → scene parser → depth estimator →
            room reconstructor → object generator → audio synthesizer →
            light estimator → scale calibrator → layout estimator →
            physics settle → assembler → UPBGE compile → parity →
            smoke → auto-launch

        Emits SSE events at each compilation stage transition.

        Parameters
        ----------
        source_image : Path
            Path to the source RGB photograph (JPEG or PNG).
        upbge_path : str | None
            Optional explicit path to UPBGE executable.
        fullscreen : bool
            Whether to launch blenderplayer in fullscreen mode.
        launch_timeout_s : float
            Seconds to wait confirming blenderplayer is running.
        smoke_timeout_s : float
            Timeout for smoke validation subprocess.

        Returns
        -------
        tuple[PipelineManifest, CompilationBridgeResult]
            The pipeline manifest and the compilation chain result.

        Raises
        ------
        PipelineValidationError
            If the source image fails input validation.
        PipelineError
            If ComfyUI is unreachable or a critical stage fails.
        PipelineTimeoutError
            If the total pipeline timeout is exceeded.

        Requirements: 1.1, 1.2, 1.3, 11.2
        """
        # --- Stage A: Run photo pipeline (stages 1-10) ---
        manifest = await self.run(source_image)

        if manifest.world_contract_path is None:
            raise PipelineError(
                "Photo pipeline completed but did not produce a WorldContract path"
            )

        # --- Stage B: Load WorldContract for compilation ---
        from src.world_contract import WorldContract

        contract_json = manifest.world_contract_path.read_text(encoding="utf-8")
        contract = WorldContract.model_validate_json(contract_json)

        # --- Stage C: Run compilation chain (UPBGE compile → parity → smoke → launch) ---
        await self._emit_event("upbge_compilation", "started")
        compile_start = time.monotonic()

        # run_compilation_chain is synchronous — run in executor to avoid blocking
        loop = asyncio.get_running_loop()
        compilation_result: CompilationBridgeResult = await loop.run_in_executor(
            None,
            lambda: run_compilation_chain(
                contract,
                self.session_dir,
                upbge_path=upbge_path,
                fullscreen=fullscreen,
                launch_timeout_s=launch_timeout_s,
                smoke_timeout_s=smoke_timeout_s,
            ),
        )
        compile_duration = time.monotonic() - compile_start

        # Emit per-stage SSE events based on what stages were reached
        if compilation_result.compiler_plan is not None:
            await self._emit_event("upbge_compilation", "plan_built", extra={
                "duration_s": compile_duration,
            })

        if compilation_result.sidecar_result is not None:
            sidecar_ok = compilation_result.sidecar_result.success
            await self._emit_event("upbge_sidecar", "completed" if sidecar_ok else "failed", extra={
                "success": sidecar_ok,
                "reason_code": compilation_result.sidecar_result.reason_code,
            })

        if compilation_result.parity_result is not None:
            parity_ok = compilation_result.parity_result.passed
            await self._emit_event("parity_gate", "passed" if parity_ok else "failed", extra={
                "passed": parity_ok,
            })

        if compilation_result.smoke_result is not None:
            smoke_ok = compilation_result.smoke_result.passed
            await self._emit_event("smoke_validation", "passed" if smoke_ok else "warning", extra={
                "passed": smoke_ok,
                "reason_code": getattr(compilation_result.smoke_result, "reason_code", ""),
            })

        if compilation_result.launch_result is not None:
            launch_ok = compilation_result.launch_result.success
            await self._emit_event("auto_launch", "launched" if launch_ok else "failed", extra={
                "success": launch_ok,
                "pid": getattr(compilation_result.launch_result, "pid", None),
                "reason_code": getattr(compilation_result.launch_result, "reason_code", ""),
            })

        # Final compilation event
        await self._emit_event("upbge_compilation", "completed" if compilation_result.success else "failed", extra={
            "success": compilation_result.success,
            "reason_code": compilation_result.reason_code,
            "total_compilation_ms": compilation_result.total_duration_ms,
        })

        # Record compilation as a stage in the manifest (informational — manifest is frozen,
        # so we log it separately)
        self._record_stage(
            "upbge_compilation",
            compilation_result.success,
            compile_duration,
            ReasonCode.COMPLETED if compilation_result.success else ReasonCode.COMPILATION_FAILED,
            diagnostics=compilation_result.diagnostic,
            artifacts={
                "runtime_candidate": compilation_result.runtime_candidate_path,
            } if compilation_result.runtime_candidate_path else {},
        )

        logger.info(
            "Full photo pipeline completed: compilation=%s, reason=%s, duration=%.1fs",
            "success" if compilation_result.success else "failed",
            compilation_result.reason_code,
            compile_duration,
        )

        return manifest, compilation_result

    def _validate_input(self, source_image: Path) -> None:
        """Validate the source image before any inference.

        Raises PipelineValidationError if the image fails any check.
        """
        result: InputValidationResult = validate_photo_input(source_image)
        if not result.valid:
            raise PipelineValidationError(
                f"Input validation failed ({result.reason_code}): "
                f"{result.diagnostic}"
            )

    async def _check_comfyui_health(self) -> None:
        """Check ComfyUI connectivity. Fail immediately if unreachable."""
        healthy = await self._comfyui_client.health_check()
        if not healthy:
            raise PipelineError(
                f"ComfyUI is unreachable at {self.config.comfyui_url}. "
                "Cannot proceed with GPU inference stages."
            )

    async def _execute_stages(
        self, source_image: Path, pipeline_start: float
    ) -> PipelineManifest:
        """Execute all pipeline stages in dependency order.

        GPU stages (SAM, MoGe-2, Hunyuan3D, audio) run sequentially
        via the GPU semaphore. CPU stages (light, scale, layout, physics,
        assembly) run in parallel where dependencies allow.
        """
        # Get image dimensions for later use
        img = Image.open(source_image)
        image_width, image_height = img.size

        # Upscale small images for better pipeline results
        MIN_DIM = 512
        if image_width < MIN_DIM or image_height < MIN_DIM:
            scale_factor = max(768 / image_width, 768 / image_height)
            new_w = int(image_width * scale_factor)
            new_h = int(image_height * scale_factor)
            img_resized = img.resize((new_w, new_h), Image.LANCZOS)
            upscaled_path = self.session_dir / "source_upscaled.png"
            img_resized.save(upscaled_path)
            source_image = upscaled_path
            image_width, image_height = new_w, new_h
            logger.info("Upscaled small image from original to %dx%d", new_w, new_h)
        img.close()

        # --- Stage 1: Scene Parsing (GPU - SAM) ---
        await self._emit_event("scene_parsing", "started")
        scene_start = time.monotonic()
        async with self._gpu_semaphore:
            scene_parser = SceneParser(
                client=self._comfyui_client,
                output_dir=self.session_dir,
            )
            scene_result: SceneParseResult = await scene_parser.parse(
                source_image=source_image,
                config=self.config,
            )
        scene_duration = time.monotonic() - scene_start
        self._record_stage("scene_parsing", True, scene_duration, ReasonCode.COMPLETED)
        await self._emit_event("scene_parsing", "completed", extra={
            "object_count": len(scene_result.objects),
            "duration_s": scene_duration,
        })

        # --- Stage 2: Depth Estimation (GPU - MoGe-2) ---
        await self._emit_event("depth_estimation", "started")
        depth_start = time.monotonic()
        async with self._gpu_semaphore:
            depth_estimator = DepthEstimator(
                client=self._comfyui_client,
                output_dir=self.session_dir,
            )
            depth_result: DepthResult = await depth_estimator.estimate(
                source_image=source_image,
                config=self.config,
            )
        depth_duration = time.monotonic() - depth_start
        self._record_stage("depth_estimation", True, depth_duration, ReasonCode.COMPLETED)
        await self._emit_event("depth_estimation", "completed", extra={
            "valid_pixel_ratio": depth_result.valid_pixel_ratio,
            "duration_s": depth_duration,
        })

        # --- Depth low-confidence handling (Requirement 12.3) ---
        # If >30% invalid pixels (valid_pixel_ratio < 0.70), attempt
        # interpolation of invalid pixels using valid neighbors before
        # falling back to flat-floor heuristic.
        depth_map: np.ndarray = np.load(depth_result.depth_map_path)
        depth_fallback_used: str | None = None

        if depth_result.valid_pixel_ratio < _DEPTH_LOW_CONFIDENCE_THRESHOLD:
            logger.info(
                "Depth map low-confidence: %.1f%% valid pixels (threshold: %.0f%%). "
                "Attempting interpolation with valid pixels.",
                depth_result.valid_pixel_ratio * 100,
                _DEPTH_LOW_CONFIDENCE_THRESHOLD * 100,
            )
            interpolated_map = self._interpolate_depth_map(depth_map)
            if interpolated_map is not None:
                depth_map = interpolated_map
                depth_fallback_used = "depth:interpolated_from_valid_pixels"
                logger.info("Depth interpolation succeeded — using reconstructed map.")
            else:
                # Interpolation impossible — flat-floor only
                depth_fallback_used = "depth:flat_floor_heuristic"
                logger.warning(
                    "Depth interpolation failed — insufficient valid pixels. "
                    "Downstream stages will rely on flat-floor room mesh."
                )

        # --- Stage 3: Room Reconstruction (GPU/CPU) ---
        await self._emit_event("room_reconstruction", "started")
        room_start = time.monotonic()
        room_reconstructor = RoomReconstructor(output_dir=self.session_dir)
        room_result: RoomMeshResult = await room_reconstructor.reconstruct(
            depth_map=depth_result.depth_map_path,
            room_plate=scene_result.room_plate_path,
            config=self.config,
        )
        room_duration = time.monotonic() - room_start
        self._record_stage("room_reconstruction", True, room_duration, ReasonCode.COMPLETED)
        await self._emit_event("room_reconstruction", "completed", extra={
            "used_heuristic": room_result.used_heuristic,
            "duration_s": room_duration,
        })

        # --- Stage 4: Object Generation (GPU - parallel per object) ---
        await self._emit_event("object_generation", "started")
        obj_gen_start = time.monotonic()
        object_generator = ObjectGenerator(
            client=self._comfyui_client,
            output_dir=self.session_dir,
        )
        mesh_results: list[ObjectMeshResult | None] = await self._run_parallel_gpu(
            [
                self._generate_single_object(object_generator, obj)
                for obj in scene_result.objects
            ]
        )

        # --- Graceful degradation (Requirement 12.1): substitute placeholder
        # meshes for any objects where generation failed entirely ---
        final_mesh_results: list[ObjectMeshResult | None] = []
        mesh_fallback_reasons: list[str | None] = []
        for i, (mesh_r, obj) in enumerate(
            zip(mesh_results, scene_result.objects)
        ):
            if mesh_r is None:
                # Substitute placeholder geometry
                placeholder_result = self._substitute_placeholder_mesh(obj)
                final_mesh_results.append(placeholder_result)
                mesh_fallback_reasons.append("mesh:placeholder_substituted")
                logger.info(
                    "Substituted placeholder mesh for %s (object gen failed)",
                    obj.mask_id,
                )
            else:
                final_mesh_results.append(mesh_r)
                mesh_fallback_reasons.append(None)
        mesh_results = final_mesh_results
        obj_gen_duration = time.monotonic() - obj_gen_start
        successful_meshes = sum(1 for r in mesh_results if r is not None)
        self._record_stage(
            "object_generation", True, obj_gen_duration, ReasonCode.COMPLETED,
            diagnostics=f"{successful_meshes}/{len(scene_result.objects)} objects meshed",
        )
        await self._emit_event("object_generation", "completed", extra={
            "successful": successful_meshes,
            "total": len(scene_result.objects),
            "duration_s": obj_gen_duration,
        })

        # --- Stage 5: Audio Synthesis (GPU - parallel per object) ---
        await self._emit_event("audio_synthesis", "started")
        audio_start = time.monotonic()
        audio_synthesizer = AudioSynthesizer(
            client=self._comfyui_client,
            output_dir=self.session_dir,
        )
        audio_results: list[AudioResult | None] = await self._run_parallel_gpu(
            [
                self._synthesize_single_audio(audio_synthesizer, obj)
                for obj in scene_result.objects
            ]
        )

        # --- Graceful degradation (Requirement 12.2): assign silent placeholder
        # for any objects where audio synthesis failed ---
        final_audio_results: list[AudioResult | None] = []
        audio_fallback_reasons: list[str | None] = []
        for i, (audio_r, obj) in enumerate(
            zip(audio_results, scene_result.objects)
        ):
            if audio_r is None:
                # Assign silent placeholder WAV
                silent_result = self._assign_silent_audio(obj.mask_id)
                final_audio_results.append(silent_result)
                audio_fallback_reasons.append("audio:silent_placeholder")
                logger.info(
                    "Assigned silent audio placeholder for %s (synthesis failed)",
                    obj.mask_id,
                )
            else:
                final_audio_results.append(audio_r)
                audio_fallback_reasons.append(None)
        audio_results = final_audio_results
        audio_duration = time.monotonic() - audio_start
        successful_audio = sum(1 for r in audio_results if r is not None)
        self._record_stage(
            "audio_synthesis", True, audio_duration, ReasonCode.COMPLETED,
            diagnostics=f"{successful_audio}/{len(scene_result.objects)} audio synthesized",
        )
        await self._emit_event("audio_synthesis", "completed", extra={
            "successful": successful_audio,
            "total": len(scene_result.objects),
            "duration_s": audio_duration,
        })

        # --- Stage 6: Light Estimation (CPU) ---
        await self._emit_event("light_estimation", "started")
        light_start = time.monotonic()
        async with self._cpu_semaphore:
            light_estimator = LightEstimator()
            light_result: LightEstimateResult = await light_estimator.estimate(
                source_image=source_image,
            )
        light_duration = time.monotonic() - light_start
        self._record_stage("light_estimation", True, light_duration, ReasonCode.COMPLETED)
        await self._emit_event("light_estimation", "completed", extra={
            "confidence": light_result.confidence,
            "duration_s": light_duration,
        })

        # --- Stage 7: Scale Calibration (CPU - parallel per object) ---
        await self._emit_event("scale_calibration", "started")
        scale_start = time.monotonic()
        scale_calibrator = ScaleCalibrator()
        image_size = (image_width, image_height)
        room_dimensions_m = room_result.dimensions_m

        scale_results: list[ScaleResult] = await self._run_parallel_cpu(
            [
                self._calibrate_single_scale(
                    scale_calibrator, obj, depth_map, image_size, room_dimensions_m
                )
                for obj in scene_result.objects
            ]
        )
        scale_duration = time.monotonic() - scale_start
        self._record_stage("scale_calibration", True, scale_duration, ReasonCode.COMPLETED)
        await self._emit_event("scale_calibration", "completed", extra={
            "object_count": len(scale_results),
            "duration_s": scale_duration,
        })

        # --- Stage 8: Layout Estimation (CPU) ---
        await self._emit_event("layout_estimation", "started")
        layout_start = time.monotonic()
        async with self._cpu_semaphore:
            layout_estimator = LayoutEstimator()
            layout_results: list[LayoutResult] = layout_estimator.estimate(
                objects=scene_result.objects,
                scales=scale_results,
                depth_map=depth_map,
                image_size=image_size,
                config=self.config,
            )
        layout_duration = time.monotonic() - layout_start
        self._record_stage("layout_estimation", True, layout_duration, ReasonCode.COMPLETED)
        await self._emit_event("layout_estimation", "completed", extra={
            "settled_count": sum(1 for lr in layout_results if lr.settled),
            "duration_s": layout_duration,
        })

        # --- Build ObjectManifestEntries (Requirement 12.5: record degradation path) ---
        object_entries: list[ObjectManifestEntry] = []
        for i, obj in enumerate(scene_result.objects):
            mesh_r = mesh_results[i] if i < len(mesh_results) else None
            audio_r = audio_results[i] if i < len(audio_results) else None
            scale_r = scale_results[i] if i < len(scale_results) else None
            layout_r = layout_results[i] if i < len(layout_results) else None

            fallbacks: list[str] = []

            # Record mesh degradation path
            mesh_fb = mesh_fallback_reasons[i] if i < len(mesh_fallback_reasons) else None
            if mesh_fb is not None:
                fallbacks.append(mesh_fb)
            elif mesh_r is not None and mesh_r.method_used != "hunyuan3d":
                fallbacks.append(f"mesh:{mesh_r.method_used}")
            if mesh_r is None:
                fallbacks.append("mesh:failed")

            # Record audio degradation path
            audio_fb = audio_fallback_reasons[i] if i < len(audio_fallback_reasons) else None
            if audio_fb is not None:
                fallbacks.append(audio_fb)
            elif audio_r is not None and audio_r.method_used != "comfyui_audio":
                fallbacks.append(f"audio:{audio_r.method_used}")
            if audio_r is None:
                fallbacks.append("audio:failed")

            # Record depth degradation path (applies globally to all objects)
            if depth_fallback_used is not None:
                fallbacks.append(depth_fallback_used)

            entry = ObjectManifestEntry(
                mask_id=obj.mask_id,
                bbox_px=obj.bbox,
                area_px=obj.area_px,
                centroid_px=obj.centroid_px,
                object_png_path=obj.object_png_path,
                mesh_path=mesh_r.mesh_path if mesh_r else None,
                mesh_method=mesh_r.method_used if mesh_r else None,
                mesh_gen_time_s=mesh_r.generation_time_s if mesh_r else 0.0,
                audio_path=audio_r.wav_path if audio_r else None,
                audio_method=audio_r.method_used if audio_r else None,
                material_category=audio_r.material_category if audio_r else "plastic",
                scale_m=scale_r.dimensions_m if scale_r else (1.0, 1.0, 1.0),
                scale_confidence=scale_r.confidence if scale_r else 0.0,
                position_m=layout_r.position_m if layout_r else (0.0, 0.0, 0.0),
                rotation_deg=layout_r.rotation_deg if layout_r else (0.0, 0.0, 0.0),
                settled=layout_r.settled if layout_r else False,
                collision_method=None,
                lod_levels=0,
                fallbacks_triggered=fallbacks,
            )
            object_entries.append(entry)

        # --- Stage 9: WorldContract Assembly ---
        await self._emit_event("assembly", "started")
        assembly_start = time.monotonic()
        assembler = PhotoWorldContractAssembler(
            session_id=self.session_id,
            room_mesh=room_result,
            objects=object_entries,
            light_estimate=light_result,
            image_width_px=image_width,
            image_height_px=image_height,
        )
        world_contract = assembler.assemble()
        assembly_duration = time.monotonic() - assembly_start
        self._record_stage("assembly", True, assembly_duration, ReasonCode.COMPLETED)
        await self._emit_event("assembly", "completed", extra={
            "duration_s": assembly_duration,
        })

        # --- Stage 10: Physics Settle (post-assembly) ---
        await self._emit_event("physics_settle", "started")
        settle_start = time.monotonic()
        physics_settle = PhysicsSettle()
        settle_result = physics_settle.settle(
            world_contract=world_contract,
            config=self.config,
        )
        world_contract = settle_result.settled_world_contract
        settle_duration = time.monotonic() - settle_start
        self._record_stage("physics_settle", True, settle_duration, ReasonCode.COMPLETED)
        await self._emit_event("physics_settle", "completed", extra={
            "unsettled": settle_result.total_unsettled,
            "iterations": settle_result.iterations_run,
            "duration_s": settle_duration,
        })

        # --- Persist WorldContract ---
        contract_path = self.session_dir / "world_contract.json"
        contract_path.write_text(world_contract.model_dump_json(indent=2))

        # --- Compute quality classification ---
        quality = self._classify_quality(
            mesh_results, audio_results, depth_fallback_used
        )

        # --- Build final manifest ---
        total_duration = time.monotonic() - pipeline_start
        manifest = PipelineManifest(
            session_id=self.session_id,
            source_image_path=source_image,
            stages=list(self._stage_results),
            objects=object_entries,
            quality_classification=quality,
            total_duration_s=total_duration,
            world_contract_path=contract_path,
        )

        await self._emit_event("pipeline", "completed", extra={
            "quality": quality,
            "total_duration_s": total_duration,
            "object_count": len(object_entries),
        })

        return manifest

    # ------------------------------------------------------------------
    # Parallel execution helpers
    # ------------------------------------------------------------------

    async def _run_parallel_gpu(
        self, coroutines: list[Any]
    ) -> list[Any]:
        """Run coroutines with GPU semaphore concurrency control.

        Each coroutine acquires the GPU semaphore before execution.
        Failures for individual items return None (graceful degradation).
        """
        tasks = [
            asyncio.create_task(self._with_gpu_semaphore(coro))
            for coro in coroutines
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        processed: list[Any] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("GPU task failed: %s", r)
                processed.append(None)
            else:
                processed.append(r)
        return processed

    async def _run_parallel_cpu(
        self, coroutines: list[Any]
    ) -> list[Any]:
        """Run coroutines with CPU semaphore concurrency control.

        Each coroutine acquires the CPU semaphore before execution.
        """
        tasks = [
            asyncio.create_task(self._with_cpu_semaphore(coro))
            for coro in coroutines
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        processed: list[Any] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("CPU task failed: %s", r)
                processed.append(None)
            else:
                processed.append(r)
        return processed

    async def _with_gpu_semaphore(self, coro: Any) -> Any:
        """Wrap a coroutine with GPU semaphore acquisition."""
        async with self._gpu_semaphore:
            return await coro

    async def _with_cpu_semaphore(self, coro: Any) -> Any:
        """Wrap a coroutine with CPU semaphore acquisition."""
        async with self._cpu_semaphore:
            return await coro

    # ------------------------------------------------------------------
    # Per-object stage wrappers
    # ------------------------------------------------------------------

    async def _generate_single_object(
        self, generator: ObjectGenerator, obj: SegmentedObject
    ) -> ObjectMeshResult | None:
        """Generate mesh for a single object with error handling."""
        try:
            return await generator.generate(
                object_png=obj.object_png_path,
                mask_id=obj.mask_id,
                config=self.config,
            )
        except Exception as exc:
            logger.warning(
                "Object generation failed for %s: %s", obj.mask_id, exc
            )
            return None

    async def _synthesize_single_audio(
        self, synthesizer: AudioSynthesizer, obj: SegmentedObject
    ) -> AudioResult | None:
        """Synthesize audio for a single object with error handling."""
        try:
            return await synthesizer.synthesize(
                object_png=obj.object_png_path,
                mask_id=obj.mask_id,
                config=self.config,
            )
        except Exception as exc:
            logger.warning(
                "Audio synthesis failed for %s: %s", obj.mask_id, exc
            )
            return None

    async def _calibrate_single_scale(
        self,
        calibrator: ScaleCalibrator,
        obj: SegmentedObject,
        depth_map: np.ndarray,
        image_size: tuple[int, int],
        room_dimensions_m: tuple[float, float, float],
    ) -> ScaleResult:
        """Calibrate scale for a single object (sync call wrapped as async)."""
        return calibrator.calibrate(
            obj=obj,
            depth_map=depth_map,
            camera_fov_deg=60.0,
            image_size=image_size,
            room_dimensions_m=room_dimensions_m,
        )

    # ------------------------------------------------------------------
    # Graceful degradation helpers (Requirements 12.1, 12.2, 12.3)
    # ------------------------------------------------------------------

    def _substitute_placeholder_mesh(
        self, obj: SegmentedObject
    ) -> ObjectMeshResult:
        """Create a placeholder mesh for an object whose generation failed.

        Uses select_placeholder_type from object_generator to choose an
        appropriate primitive (box, cylinder, sphere) based on the object's
        bounding box aspect ratio, then creates and exports the mesh.

        Requirement 12.1: Object_Generator failure for single object →
        substitute placeholder, continue remaining objects.

        Parameters
        ----------
        obj : SegmentedObject
            The segmented object that failed mesh generation.

        Returns
        -------
        ObjectMeshResult
            Result with a placeholder GLB path and method_used="placeholder".
        """
        obj_dir = self.session_dir / "objects"
        obj_dir.mkdir(parents=True, exist_ok=True)

        start_time = time.monotonic()

        # Determine bbox dimensions from the SegmentedObject
        _, _, bbox_w, bbox_h = obj.bbox

        # Create placeholder using the same logic as the object generator
        mesh = create_placeholder(
            object_png_path=obj.object_png_path,
            bbox_width=bbox_w,
            bbox_height=bbox_h,
            area_px=obj.area_px,
        )

        # Export as GLB
        glb_path = obj_dir / f"{obj.mask_id}.glb"
        mesh.export(str(glb_path), file_type="glb")

        elapsed = time.monotonic() - start_time

        return ObjectMeshResult(
            mesh_path=glb_path,
            method_used="placeholder",
            generation_time_s=elapsed,
            face_count=len(mesh.faces),
            vertex_count=len(mesh.vertices),
        )

    def _assign_silent_audio(self, mask_id: str) -> AudioResult:
        """Create a silent placeholder WAV for an object whose audio failed.

        Produces a minimal 0.1s silent WAV (mono, 44100Hz, 16-bit) when the
        Audio_Synthesizer fails for a specific object.

        Requirement 12.2: Audio_Synthesizer failure for single object →
        assign silent placeholder, continue.

        Parameters
        ----------
        mask_id : str
            Unique mask identifier for the object.

        Returns
        -------
        AudioResult
            Result with a silent WAV path and method_used="default".
        """
        obj_dir = self.session_dir / "objects"
        obj_dir.mkdir(parents=True, exist_ok=True)

        wav_path = obj_dir / f"{mask_id}_impact.wav"

        # Generate silent WAV
        n_samples = int(_SILENT_WAV_DURATION_S * _SILENT_WAV_SAMPLE_RATE)
        silence = np.zeros(n_samples, dtype=np.int16)

        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(_SILENT_WAV_CHANNELS)
            wf.setsampwidth(_SILENT_WAV_SAMPLE_WIDTH)
            wf.setframerate(_SILENT_WAV_SAMPLE_RATE)
            wf.writeframes(silence.tobytes())

        return AudioResult(
            wav_path=wav_path,
            method_used="default",
            duration_s=_SILENT_WAV_DURATION_S,
            material_category="plastic",
        )

    def _interpolate_depth_map(self, depth_map: np.ndarray) -> np.ndarray | None:
        """Attempt to reconstruct a low-confidence depth map via interpolation.

        Uses valid pixels as anchor points and interpolates invalid pixels
        using nearest-neighbor distance-weighted filling followed by Gaussian
        smoothing. Falls back to None if there are too few valid pixels to
        produce a meaningful interpolation (< 5% valid).

        Requirement 12.3: Depth low-confidence (>30% invalid pixels) →
        attempt reconstruction with valid pixels + interpolation, fallback
        to flat-floor only if impossible.

        Parameters
        ----------
        depth_map : np.ndarray
            2D float32 depth map with some invalid (0, inf, nan) pixels.

        Returns
        -------
        np.ndarray | None
            Interpolated depth map if sufficient valid data exists, or None
            if interpolation is impossible (< 5% valid pixels).
        """
        valid_mask = np.isfinite(depth_map) & (depth_map > 0.0)
        valid_ratio = np.count_nonzero(valid_mask) / max(depth_map.size, 1)

        # If fewer than 5% of pixels are valid, interpolation is not meaningful
        if valid_ratio < 0.05:
            logger.warning(
                "Only %.1f%% valid pixels — too few for interpolation.",
                valid_ratio * 100,
            )
            return None

        # Create output array starting with the valid values
        result = depth_map.copy()

        # Use scipy's distance_transform_edt to propagate nearest valid pixel
        # to all invalid positions (nearest-neighbor interpolation)
        invalid_mask = ~valid_mask
        if not np.any(invalid_mask):
            return result  # All valid, nothing to interpolate

        # Get indices of the nearest valid pixel for each invalid pixel
        _, indices = ndimage.distance_transform_edt(
            invalid_mask, return_distances=True, return_indices=True
        )

        # Fill invalid pixels with the value from the nearest valid pixel
        result[invalid_mask] = depth_map[
            indices[0][invalid_mask], indices[1][invalid_mask]
        ]

        # Apply light Gaussian smoothing to reduce discontinuities at fill boundaries
        # Use sigma=2.0 for gentle blending while preserving depth structure
        result = ndimage.gaussian_filter(result, sigma=2.0)

        # Ensure all values remain positive (smoothing near edges could create 0s)
        result = np.maximum(result, 0.01)

        return result.astype(np.float32)

    # ------------------------------------------------------------------
    # Progress and recording helpers
    # ------------------------------------------------------------------

    def _record_stage(
        self,
        stage_name: str,
        success: bool,
        duration_s: float,
        reason_code: ReasonCode,
        diagnostics: str = "",
        artifacts: dict[str, Path] | None = None,
        fallback_used: str | None = None,
    ) -> None:
        """Record a completed stage result."""
        self._stage_results.append(
            StageResult(
                stage_name=stage_name,
                success=success,
                duration_s=duration_s,
                reason_code=reason_code.value,
                diagnostics=diagnostics,
                artifacts=artifacts or {},
                fallback_used=fallback_used,
            )
        )

    async def _emit_event(
        self,
        stage: str,
        status: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit an SSE progress event via the callback.

        Events are emitted within 2s of stage transitions as required.
        If no callback is configured, this is a no-op.
        """
        if self.event_callback is None:
            return

        event: dict[str, Any] = {
            "event": "stage_transition",
            "stage": stage,
            "status": status,
            "session_id": self.session_id,
            "timestamp": time.time(),
        }
        if extra:
            event.update(extra)

        try:
            result = self.event_callback(event)
            # Support both sync and async callbacks
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("Event callback failed: %s", exc)

    # ------------------------------------------------------------------
    # Quality classification (Requirement 12.6)
    # ------------------------------------------------------------------

    def _classify_quality(
        self,
        mesh_results: list[ObjectMeshResult | None],
        audio_results: list[AudioResult | None] | None = None,
        depth_fallback_used: str | None = None,
    ) -> str:
        """Classify pipeline output quality.

        Classification rules:
        - "full": all objects used primary methods (hunyuan3d mesh,
          comfyui_audio audio), no depth fallback
        - "degraded": ≥1 fallback method triggered but ≥1 valid mesh exists
        - "minimal": zero object meshes generated (room-only, player explores
          empty room)

        Parameters
        ----------
        mesh_results : list[ObjectMeshResult | None]
            Results from object generation (may include placeholders).
        audio_results : list[AudioResult | None] | None
            Results from audio synthesis (may include silent placeholders).
        depth_fallback_used : str | None
            If not None, indicates a depth degradation path was triggered.

        Returns
        -------
        str
            One of "full", "degraded", or "minimal".
        """
        if not mesh_results:
            return "minimal"

        successful = [r for r in mesh_results if r is not None]
        if not successful:
            return "minimal"

        # Check if any fallback was triggered
        any_mesh_fallback = any(
            r.method_used != "hunyuan3d" for r in successful
        )
        any_audio_fallback = False
        if audio_results:
            audio_valid = [r for r in audio_results if r is not None]
            any_audio_fallback = any(
                r.method_used != "comfyui_audio" for r in audio_valid
            )

        has_depth_fallback = depth_fallback_used is not None

        if any_mesh_fallback or any_audio_fallback or has_depth_fallback:
            return "degraded"

        return "full"
