"""Integration test for the full photo pipeline with mocked ComfyUI stages.

Tests end-to-end: source photo → scene parse → depth → objects → audio →
assembly → WorldContract validation. All GPU/inference stages are mocked
to return deterministic fixtures.

Requirements: 1.1, 1.2, 8.1
"""

from __future__ import annotations

import asyncio
import json
import struct
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

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
from src.photo_pipeline.orchestrator import PhotoPipelineOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_image(tmp_path: Path) -> Path:
    """Create a minimal valid 512x512 RGB PNG for pipeline input."""
    img = Image.new("RGB", (512, 512), color=(128, 100, 80))
    img_path = tmp_path / "test_photo.png"
    img.save(img_path)
    return img_path


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Provide a clean session directory for pipeline output."""
    sdir = tmp_path / "session_output"
    sdir.mkdir()
    return sdir


@pytest.fixture
def object_pngs(tmp_path: Path) -> list[Path]:
    """Create 3 fake object RGBA PNGs."""
    pngs: list[Path] = []
    objects_dir = tmp_path / "objects"
    objects_dir.mkdir()
    for i in range(3):
        img = Image.new("RGBA", (64, 64), color=(200, 150, 100, 255))
        p = objects_dir / f"obj_{i}.png"
        img.save(p)
        pngs.append(p)
    return pngs


@pytest.fixture
def depth_npy(tmp_path: Path) -> Path:
    """Create a valid 512x512 depth map .npy file (all values 2.5m)."""
    depth = np.full((512, 512), 2.5, dtype=np.float32)
    p = tmp_path / "depth_map.npy"
    np.save(p, depth)
    return p


@pytest.fixture
def normal_npy(tmp_path: Path) -> Path:
    """Create a valid 512x512x3 normal map .npy file."""
    normals = np.zeros((512, 512, 3), dtype=np.float32)
    normals[:, :, 1] = 1.0  # all normals pointing up
    p = tmp_path / "normal_map.npy"
    np.save(p, normals)
    return p


@pytest.fixture
def room_plate(tmp_path: Path) -> Path:
    """Create a fake room plate image."""
    img = Image.new("RGB", (512, 512), color=(200, 200, 200))
    p = tmp_path / "room_plate.png"
    img.save(p)
    return p


@pytest.fixture
def background_mask(tmp_path: Path) -> Path:
    """Create a fake background mask."""
    img = Image.new("L", (512, 512), color=0)
    p = tmp_path / "bg_mask.png"
    img.save(p)
    return p


@pytest.fixture
def glb_files(tmp_path: Path) -> list[Path]:
    """Create 3 minimal placeholder GLB files."""
    glbs: list[Path] = []
    meshes_dir = tmp_path / "meshes"
    meshes_dir.mkdir()
    for i in range(3):
        p = meshes_dir / f"obj_{i}.glb"
        # Write minimal valid GLB header (magic + version + length)
        p.write_bytes(
            b"glTF"
            + struct.pack("<I", 2)
            + struct.pack("<I", 12)
        )
        glbs.append(p)
    return glbs


@pytest.fixture
def wav_files(tmp_path: Path) -> list[Path]:
    """Create 3 minimal WAV files (0.1s silence)."""
    wavs: list[Path] = []
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    for i in range(3):
        p = audio_dir / f"obj_{i}_impact.wav"
        n_samples = int(0.1 * 44100)
        silence = np.zeros(n_samples, dtype=np.int16)
        with wave.open(str(p), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            wf.writeframes(silence.tobytes())
        wavs.append(p)
    return wavs


def _make_scene_parse_result(
    object_pngs: list[Path],
    room_plate: Path,
    background_mask: Path,
) -> SceneParseResult:
    """Build a deterministic SceneParseResult with 3 objects."""
    objects = [
        SegmentedObject(
            mask_id=f"obj_{i}",
            bbox=(i * 100, 50, 80, 80),
            area_px=6400,
            centroid_px=(i * 100 + 40.0, 90.0),
            object_png_path=object_pngs[i],
        )
        for i in range(3)
    ]
    return SceneParseResult(
        room_plate_path=room_plate,
        objects=objects,
        background_mask_path=background_mask,
    )


def _make_depth_result(depth_npy: Path, normal_npy: Path) -> DepthResult:
    """Build a deterministic DepthResult with good confidence."""
    return DepthResult(
        depth_map_path=depth_npy,
        normal_map_path=normal_npy,
        valid_pixel_ratio=0.95,
        depth_range_m=(0.5, 5.0),
    )


def _make_room_mesh_result(tmp_path: Path) -> RoomMeshResult:
    """Build a deterministic RoomMeshResult."""
    mesh_path = tmp_path / "room.glb"
    mesh_path.write_bytes(
        b"glTF" + struct.pack("<I", 2) + struct.pack("<I", 12)
    )
    return RoomMeshResult(
        mesh_path=mesh_path,
        dimensions_m=(5.0, 2.7, 4.0),
        vertex_count=5000,
        face_count=2500,
        used_heuristic=False,
    )


def _make_object_mesh_results(glb_files: list[Path]) -> list[ObjectMeshResult]:
    """Build deterministic ObjectMeshResults for 3 objects."""
    return [
        ObjectMeshResult(
            mesh_path=glb_files[i],
            method_used="hunyuan3d",
            generation_time_s=5.0 + i,
            face_count=1200 + i * 100,
            vertex_count=600 + i * 50,
        )
        for i in range(3)
    ]


def _make_audio_results(wav_files: list[Path]) -> list[AudioResult]:
    """Build deterministic AudioResults for 3 objects."""
    materials = ["wood", "metal", "plastic"]
    return [
        AudioResult(
            wav_path=wav_files[i],
            method_used="comfyui_audio",
            duration_s=0.5,
            material_category=materials[i],
        )
        for i in range(3)
    ]


def _make_light_estimate() -> LightEstimateResult:
    """Build a deterministic LightEstimateResult."""
    return LightEstimateResult(
        sun_direction=(0.3, -0.9, 0.2),
        color_temperature_k=5500,
        intensity=60.0,
        ambient_intensity=0.3,
        ambient_color="#E8E8E8",
        confidence=0.85,
    )


def _make_scale_results() -> list[ScaleResult]:
    """Build deterministic ScaleResults for 3 objects."""
    return [
        ScaleResult(
            dimensions_m=(0.4, 0.6, 0.3),
            scale_factor=1.0,
            confidence=0.8,
        ),
        ScaleResult(
            dimensions_m=(0.8, 1.2, 0.5),
            scale_factor=1.0,
            confidence=0.75,
        ),
        ScaleResult(
            dimensions_m=(0.3, 0.3, 0.3),
            scale_factor=1.0,
            confidence=0.9,
        ),
    ]


def _make_layout_results() -> list[LayoutResult]:
    """Build deterministic LayoutResults for 3 objects."""
    return [
        LayoutResult(
            position_m=(1.0, 0.3, 1.5),
            rotation_deg=(0.0, 45.0, 0.0),
            settled=True,
            pre_settle_position_m=(1.0, 0.5, 1.5),
        ),
        LayoutResult(
            position_m=(-1.0, 0.6, 2.0),
            rotation_deg=(0.0, 0.0, 0.0),
            settled=True,
            pre_settle_position_m=(-1.0, 0.8, 2.0),
        ),
        LayoutResult(
            position_m=(0.5, 0.15, 0.8),
            rotation_deg=(0.0, 90.0, 0.0),
            settled=True,
            pre_settle_position_m=(0.5, 0.3, 0.8),
        ),
    ]


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------


class TestPhotoPipelineE2E:
    """End-to-end integration test for the photo pipeline with mocked stages.

    Validates Requirements 1.1, 1.2, 8.1:
    - Pipeline runs without exceptions
    - WorldContract is produced and passes schema validation
    - PipelineManifest contains all expected data
    - SSE events are emitted for all stage transitions
    - All objects appear in the manifest
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_produces_valid_manifest(
        self,
        tmp_path: Path,
        test_image: Path,
        session_dir: Path,
        object_pngs: list[Path],
        depth_npy: Path,
        normal_npy: Path,
        room_plate: Path,
        background_mask: Path,
        glb_files: list[Path],
        wav_files: list[Path],
    ):
        """Test the orchestrator runs end-to-end and produces a valid manifest.

        Validates:
        1. The orchestrator runs without exceptions
        2. PipelineManifest is returned with correct fields
        3. WorldContract JSON is written to session_dir
        4. SSE events were emitted (collecting callback)
        5. All objects appear in the manifest with correct data
        """
        # Collect SSE events
        collected_events: list[dict] = []

        async def event_collector(event: dict) -> None:
            collected_events.append(event)


        # Build deterministic mock return values
        scene_result = _make_scene_parse_result(
            object_pngs, room_plate, background_mask
        )
        depth_result = _make_depth_result(depth_npy, normal_npy)
        room_result = _make_room_mesh_result(tmp_path)
        mesh_results = _make_object_mesh_results(glb_files)
        audio_results = _make_audio_results(wav_files)
        light_result = _make_light_estimate()
        scale_results = _make_scale_results()
        layout_results = _make_layout_results()

        # Configure the orchestrator
        config = PhotoPipelineConfig(
            comfyui_url="http://localhost:8188",
            max_objects=30,
            pipeline_timeout_s=300,
        )
        orchestrator = PhotoPipelineOrchestrator(
            config=config,
            session_dir=session_dir,
            event_callback=event_collector,
            session_id="test-session-e2e",
        )


        # --- Patch all external stages ---
        with (
            patch(
                "src.photo_pipeline.orchestrator.validate_photo_input"
            ) as mock_validate,
            patch.object(
                orchestrator._comfyui_client,
                "health_check",
                new_callable=AsyncMock,
            ) as mock_health,
            patch(
                "src.photo_pipeline.orchestrator.SceneParser"
            ) as MockSceneParser,
            patch(
                "src.photo_pipeline.orchestrator.DepthEstimator"
            ) as MockDepthEstimator,
            patch(
                "src.photo_pipeline.orchestrator.RoomReconstructor"
            ) as MockRoomReconstructor,
            patch(
                "src.photo_pipeline.orchestrator.ObjectGenerator"
            ) as MockObjectGenerator,
            patch(
                "src.photo_pipeline.orchestrator.AudioSynthesizer"
            ) as MockAudioSynthesizer,
            patch(
                "src.photo_pipeline.orchestrator.LightEstimator"
            ) as MockLightEstimator,
            patch(
                "src.photo_pipeline.orchestrator.ScaleCalibrator"
            ) as MockScaleCalibrator,
            patch(
                "src.photo_pipeline.orchestrator.LayoutEstimator"
            ) as MockLayoutEstimator,
            patch(
                "src.photo_pipeline.orchestrator.PhysicsSettle"
            ) as MockPhysicsSettle,
        ):

            # Mock input validation: pass
            from src.photo_pipeline.input_validator import InputValidationResult
            from src.photo_pipeline.reason_codes import ReasonCode

            mock_validate.return_value = InputValidationResult(
                valid=True,
                reason_code=ReasonCode.COMPLETED,
                diagnostic="Valid image",
            )

            # Mock ComfyUI health check: healthy
            mock_health.return_value = True

            # Mock SceneParser.parse()
            scene_parser_inst = MockSceneParser.return_value
            scene_parser_inst.parse = AsyncMock(return_value=scene_result)

            # Mock DepthEstimator.estimate()
            depth_inst = MockDepthEstimator.return_value
            depth_inst.estimate = AsyncMock(return_value=depth_result)

            # Mock RoomReconstructor.reconstruct()
            room_inst = MockRoomReconstructor.return_value
            room_inst.reconstruct = AsyncMock(return_value=room_result)


            # Mock ObjectGenerator.generate() — returns per-object meshes
            obj_gen_inst = MockObjectGenerator.return_value
            call_count_obj = [0]

            async def mock_generate_obj(**kwargs):
                idx = call_count_obj[0]
                call_count_obj[0] += 1
                if idx < len(mesh_results):
                    return mesh_results[idx]
                return mesh_results[-1]

            obj_gen_inst.generate = mock_generate_obj

            # Mock AudioSynthesizer.synthesize() — per-object audio
            audio_inst = MockAudioSynthesizer.return_value
            call_count_audio = [0]

            async def mock_synthesize(**kwargs):
                idx = call_count_audio[0]
                call_count_audio[0] += 1
                if idx < len(audio_results):
                    return audio_results[idx]
                return audio_results[-1]

            audio_inst.synthesize = mock_synthesize

            # Mock LightEstimator.estimate()
            light_inst = MockLightEstimator.return_value
            light_inst.estimate = AsyncMock(return_value=light_result)


            # Mock ScaleCalibrator.calibrate() — per-object scales
            scale_inst = MockScaleCalibrator.return_value
            call_count_scale = [0]

            def mock_calibrate(**kwargs):
                idx = call_count_scale[0]
                call_count_scale[0] += 1
                if idx < len(scale_results):
                    return scale_results[idx]
                return scale_results[-1]

            scale_inst.calibrate = mock_calibrate

            # Mock LayoutEstimator.estimate() — returns all layouts
            layout_inst = MockLayoutEstimator.return_value
            layout_inst.estimate = MagicMock(return_value=layout_results)

            # Mock PhysicsSettle.settle() — returns contract unchanged
            from src.photo_pipeline.stages.physics_settle import (
                PhysicsSettleResult,
                SettledObjectInfo,
            )

            def mock_settle(world_contract, config=None):
                return PhysicsSettleResult(
                    settled_world_contract=world_contract,
                    object_info=[],
                    total_unsettled=0,
                    total_dynamic=3,
                    iterations_run=50,
                    wall_time_s=0.5,
                    warning_issued=False,
                )

            physics_inst = MockPhysicsSettle.return_value
            physics_inst.settle = mock_settle


            # --- Execute the pipeline ---
            manifest = await orchestrator.run(test_image)

            # --- Assertions ---

            # 1. Orchestrator ran without exceptions — we reached here
            assert manifest is not None
            assert isinstance(manifest, PipelineManifest)

            # 2. PipelineManifest has correct fields
            assert manifest.session_id == "test-session-e2e"
            assert manifest.source_image_path == test_image
            assert manifest.source_type == "photo"
            assert manifest.quality_classification in (
                "full", "degraded", "minimal"
            )
            assert manifest.total_duration_s > 0.0

            # 3. WorldContract JSON was written to session_dir
            contract_path = session_dir / "world_contract.json"
            assert contract_path.exists()
            contract_json = json.loads(
                contract_path.read_text(encoding="utf-8")
            )
            # Validate it looks like a WorldContract
            assert contract_json["schema_version"] == "world-contract/v1"
            assert contract_json["coordinate_system"] == (
                "right-handed-x-right-y-up-z-depth"
            )
            assert "room" in contract_json
            assert "instances" in contract_json
            assert "materials" in contract_json
            assert "lights" in contract_json


            # Validate via Pydantic model deserialization
            from src.world_contract import WorldContract

            validated_contract = WorldContract.model_validate_json(
                contract_path.read_text(encoding="utf-8")
            )
            assert validated_contract is not None
            assert len(validated_contract.instances) == 3
            assert len(validated_contract.lights) >= 2

            # 4. SSE events were emitted for stage transitions
            assert len(collected_events) > 0
            event_stages = [e["stage"] for e in collected_events]
            # Every major stage should have been emitted
            assert "scene_parsing" in event_stages
            assert "depth_estimation" in event_stages
            assert "object_generation" in event_stages
            assert "audio_synthesis" in event_stages
            assert "light_estimation" in event_stages
            assert "scale_calibration" in event_stages
            assert "layout_estimation" in event_stages
            assert "assembly" in event_stages
            assert "physics_settle" in event_stages
            assert "pipeline" in event_stages

            # Verify each stage has started+completed events
            for stage in [
                "scene_parsing",
                "depth_estimation",
                "object_generation",
                "audio_synthesis",
                "assembly",
            ]:
                stage_events = [
                    e for e in collected_events if e["stage"] == stage
                ]
                statuses = [e["status"] for e in stage_events]
                assert "started" in statuses, (
                    f"{stage} missing 'started' event"
                )
                assert "completed" in statuses, (
                    f"{stage} missing 'completed' event"
                )


            # 5. All objects appear in the manifest with correct data
            assert len(manifest.objects) == 3
            for i, obj_entry in enumerate(manifest.objects):
                assert obj_entry.mask_id == f"obj_{i}"
                assert obj_entry.mesh_path is not None
                assert obj_entry.audio_path is not None
                assert obj_entry.mesh_method == "hunyuan3d"
                assert obj_entry.audio_method == "comfyui_audio"
                assert obj_entry.scale_m is not None
                assert obj_entry.position_m is not None
                assert obj_entry.settled is True

            # Verify stages recorded in manifest
            assert len(manifest.stages) > 0
            stage_names = [s.stage_name for s in manifest.stages]
            assert "scene_parsing" in stage_names
            assert "depth_estimation" in stage_names
            assert "object_generation" in stage_names
            assert "audio_synthesis" in stage_names
            assert "assembly" in stage_names
            assert "physics_settle" in stage_names

            # All stages should be successful
            for stage in manifest.stages:
                assert stage.success is True

            # Quality classification should be "full" since all
            # primary methods succeeded
            assert manifest.quality_classification == "full"

            # world_contract_path should be set
            assert manifest.world_contract_path is not None
            assert manifest.world_contract_path == contract_path
