"""Integration tests for photo pipeline degradation paths.

Validates that the pipeline gracefully degrades when individual stages fail,
always producing a valid WorldContract and correct quality classification.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.6
"""

from __future__ import annotations

import asyncio
import json
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
    ObjectMeshResult,
    PhotoPipelineConfig,
    PipelineManifest,
    RoomMeshResult,
    ScaleResult,
    SceneParseResult,
    SegmentedObject,
)
from src.photo_pipeline.orchestrator import PhotoPipelineOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_image(tmp_path: Path, size: tuple[int, int] = (512, 512)) -> Path:
    """Create a minimal valid test image (512x512 RGB JPEG)."""
    img_path = tmp_path / "test_source.jpg"
    img = Image.new("RGB", size, color=(128, 100, 80))
    img.save(img_path, format="JPEG")
    return img_path


def _create_object_png(tmp_path: Path, mask_id: str) -> Path:
    """Create a minimal RGBA object PNG for a segmented object."""
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir(parents=True, exist_ok=True)
    png_path = obj_dir / f"{mask_id}.png"
    img = Image.new("RGBA", (64, 64), color=(200, 150, 100, 255))
    img.save(png_path)
    return png_path


def _make_segmented_objects(tmp_path: Path, count: int) -> list[SegmentedObject]:
    """Create N SegmentedObject instances with valid RGBA PNGs on disk."""
    objects = []
    for i in range(count):
        mask_id = f"obj_{i:03d}"
        png_path = _create_object_png(tmp_path, mask_id)
        objects.append(
            SegmentedObject(
                mask_id=mask_id,
                bbox=(i * 50, 10, 60, 80),
                area_px=4800,
                centroid_px=(float(i * 50 + 30), 50.0),
                object_png_path=png_path,
            )
        )
    return objects


def _make_valid_depth_result(tmp_path: Path, valid_ratio: float = 0.95) -> DepthResult:
    """Create a DepthResult with a valid depth map .npy file on disk."""
    depth_dir = tmp_path / "depth"
    depth_dir.mkdir(parents=True, exist_ok=True)

    depth_map = np.full((512, 512), 3.0, dtype=np.float32)
    normal_map = np.zeros((512, 512, 3), dtype=np.float32)
    normal_map[:, :, 1] = 1.0  # up-facing normals

    depth_path = depth_dir / "depth_map.npy"
    normal_path = depth_dir / "normal_map.npy"
    np.save(depth_path, depth_map)
    np.save(normal_path, normal_map)

    return DepthResult(
        depth_map_path=depth_path,
        normal_map_path=normal_path,
        valid_pixel_ratio=valid_ratio,
        depth_range_m=(0.5, 6.0),
    )


def _make_low_confidence_depth_result(tmp_path: Path) -> DepthResult:
    """Create a DepthResult with >50% invalid pixels (valid_pixel_ratio < 0.70).

    This triggers the depth fallback logic (interpolation → flat-floor).
    """
    depth_dir = tmp_path / "depth"
    depth_dir.mkdir(parents=True, exist_ok=True)

    # Create depth map where >50% of pixels are 0 (invalid)
    depth_map = np.zeros((512, 512), dtype=np.float32)
    # Only top-left quadrant has valid pixels (~25% valid → below the 5% min
    # for interpolation? No — 25% > 5%, but let's set only 2% valid so
    # interpolation also fails, triggering flat-floor.
    # Actually, let's make 3% valid so interpolation fails (< 5% threshold).
    valid_count = int(0.03 * 512 * 512)
    flat = depth_map.flatten()
    flat[:valid_count] = 3.0
    depth_map = flat.reshape((512, 512))

    normal_map = np.zeros((512, 512, 3), dtype=np.float32)
    normal_map[:, :, 1] = 1.0

    depth_path = depth_dir / "depth_map.npy"
    normal_path = depth_dir / "normal_map.npy"
    np.save(depth_path, depth_map)
    np.save(normal_path, normal_map)

    return DepthResult(
        depth_map_path=depth_path,
        normal_map_path=normal_path,
        valid_pixel_ratio=0.03,  # Well below the 0.70 threshold
        depth_range_m=(0.5, 6.0),
    )


def _make_room_mesh_result(tmp_path: Path) -> RoomMeshResult:
    """Create a RoomMeshResult with a placeholder GLB file."""
    room_path = tmp_path / "room_mesh.glb"
    room_path.write_bytes(b"placeholder_glb")
    return RoomMeshResult(
        mesh_path=room_path,
        dimensions_m=(5.0, 2.7, 4.0),
        vertex_count=5000,
        face_count=3000,
        used_heuristic=False,
    )


def _make_light_estimate() -> LightEstimateResult:
    """Create a valid LightEstimateResult."""
    return LightEstimateResult(
        sun_direction=(0.3, -0.8, -0.5),
        color_temperature_k=5500,
        intensity=50.0,
        ambient_intensity=0.3,
        ambient_color="#E8E8E8",
        confidence=0.8,
    )


def _make_scale_result() -> ScaleResult:
    """Create a valid ScaleResult for a typical object."""
    return ScaleResult(
        dimensions_m=(0.3, 0.5, 0.3),
        scale_factor=1.0,
        confidence=0.8,
    )


def _make_layout_result() -> LayoutResult:
    """Create a valid LayoutResult for an object on the floor."""
    return LayoutResult(
        position_m=(1.0, 0.25, -2.0),
        rotation_deg=(0.0, 0.0, 0.0),
        settled=True,
        pre_settle_position_m=(1.0, 0.5, -2.0),
    )


# ---------------------------------------------------------------------------
# Test Case 1: All object generators fail → degraded classification
# ---------------------------------------------------------------------------


class TestAllObjectGeneratorsFail:
    """All Object_Generator methods fail → placeholder geometry → 'degraded'.

    Requirement 12.1: Substitute Placeholder_Geometry on generator failure.
    Requirement 12.6: Quality classification is 'degraded' when fallbacks used.
    """

    @pytest.mark.asyncio
    async def test_all_generators_fail_produces_degraded_world(self, tmp_path: Path):
        """When all object generators fail, pipeline substitutes placeholders
        and classifies output as 'degraded'."""
        source_image = _create_test_image(tmp_path)
        objects = _make_segmented_objects(tmp_path, count=3)
        scene_result = SceneParseResult(
            room_plate_path=source_image,
            objects=objects,
            background_mask_path=source_image,
        )
        depth_result = _make_valid_depth_result(tmp_path)
        room_result = _make_room_mesh_result(tmp_path)
        light_result = _make_light_estimate()
        scale_result = _make_scale_result()
        layout_result = _make_layout_result()

        config = PhotoPipelineConfig(pipeline_timeout_s=60)
        orchestrator = PhotoPipelineOrchestrator(
            config=config,
            session_dir=tmp_path / "session",
            session_id="test-degraded-001",
        )

        def settle_passthrough(*args, **kwargs):
            world_contract = args[1] if len(args) > 1 else kwargs.get("world_contract")
            result = MagicMock()
            result.total_unsettled = 0
            result.iterations_run = 100
            result.settled_world_contract = world_contract
            return result

        with (
            patch.object(
                orchestrator, "_validate_input", return_value=None
            ),
            patch.object(
                orchestrator, "_check_comfyui_health", new_callable=AsyncMock
            ),
            patch(
                "src.photo_pipeline.orchestrator.SceneParser.parse",
                new_callable=AsyncMock,
                return_value=scene_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.DepthEstimator.estimate",
                new_callable=AsyncMock,
                return_value=depth_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.RoomReconstructor.reconstruct",
                new_callable=AsyncMock,
                return_value=room_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.ObjectGenerator.generate",
                new_callable=AsyncMock,
                side_effect=RuntimeError("All generation methods exhausted"),
            ),
            patch(
                "src.photo_pipeline.orchestrator.AudioSynthesizer.synthesize",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Audio synthesis unavailable"),
            ),
            patch(
                "src.photo_pipeline.orchestrator.LightEstimator.estimate",
                new_callable=AsyncMock,
                return_value=light_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.ScaleCalibrator.calibrate",
                return_value=scale_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.LayoutEstimator.estimate",
                return_value=[layout_result] * 3,
            ),
            patch(
                "src.photo_pipeline.orchestrator.PhysicsSettle.settle",
                side_effect=settle_passthrough,
            ),
        ):
            manifest = await orchestrator.run(source_image)

        # Assertions
        assert manifest.quality_classification == "degraded"
        assert len(manifest.objects) == 3

        # Each object should have placeholder substituted fallback recorded
        for obj_entry in manifest.objects:
            assert "mesh:placeholder_substituted" in obj_entry.fallbacks_triggered
            assert obj_entry.mesh_method == "placeholder"

        # WorldContract JSON should exist in session_dir
        contract_path = tmp_path / "session" / "world_contract.json"
        assert contract_path.exists()

        # Validate that the JSON is parseable
        contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
        assert "schema_version" in contract_data
        assert contract_data["schema_version"] == "world-contract/v1"


# ---------------------------------------------------------------------------
# Test Case 2: Zero objects segmented → minimal classification
# ---------------------------------------------------------------------------


class TestZeroObjectsSegmented:
    """Zero objects segmented → room-only → 'minimal' classification.

    Requirement 12.4: Pipeline produces valid WorldContract with zero objects.
    Requirement 12.6: Quality classification is 'minimal' for room-only.
    """

    @pytest.mark.asyncio
    async def test_zero_objects_produces_minimal_world(self, tmp_path: Path):
        """When scene parser returns zero objects, pipeline produces room-only
        WorldContract classified as 'minimal'."""
        source_image = _create_test_image(tmp_path)

        # Scene result with EMPTY objects list
        scene_result = SceneParseResult(
            room_plate_path=source_image,
            objects=[],  # Zero objects
            background_mask_path=source_image,
        )
        depth_result = _make_valid_depth_result(tmp_path)
        room_result = _make_room_mesh_result(tmp_path)
        light_result = _make_light_estimate()

        config = PhotoPipelineConfig(pipeline_timeout_s=60)
        orchestrator = PhotoPipelineOrchestrator(
            config=config,
            session_dir=tmp_path / "session",
            session_id="test-minimal-001",
        )

        def settle_passthrough(*args, **kwargs):
            world_contract = args[1] if len(args) > 1 else kwargs.get("world_contract")
            result = MagicMock()
            result.total_unsettled = 0
            result.iterations_run = 0
            result.settled_world_contract = world_contract
            return result

        with (
            patch.object(
                orchestrator, "_validate_input", return_value=None
            ),
            patch.object(
                orchestrator, "_check_comfyui_health", new_callable=AsyncMock
            ),
            patch(
                "src.photo_pipeline.orchestrator.SceneParser.parse",
                new_callable=AsyncMock,
                return_value=scene_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.DepthEstimator.estimate",
                new_callable=AsyncMock,
                return_value=depth_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.RoomReconstructor.reconstruct",
                new_callable=AsyncMock,
                return_value=room_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.LightEstimator.estimate",
                new_callable=AsyncMock,
                return_value=light_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.PhysicsSettle.settle",
                side_effect=settle_passthrough,
            ),
        ):
            manifest = await orchestrator.run(source_image)

        # Assertions
        assert manifest.quality_classification == "minimal"
        assert manifest.objects == []

        # WorldContract JSON should still exist (room-only)
        contract_path = tmp_path / "session" / "world_contract.json"
        assert contract_path.exists()

        # Validate parseable JSON with valid schema
        contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
        assert contract_data["schema_version"] == "world-contract/v1"

        # Verify instances is empty (no objects)
        assert contract_data["instances"] == []


# ---------------------------------------------------------------------------
# Test Case 3: Depth estimation fails → flat-floor heuristic
# ---------------------------------------------------------------------------


class TestDepthEstimationFails:
    """Depth estimation fails → flat-floor heuristic → pipeline still completes.

    Requirement 12.3: Low-confidence depth with insufficient valid pixels for
    interpolation results in flat-floor fallback but pipeline still completes.
    """

    @pytest.mark.asyncio
    async def test_depth_failure_uses_flat_floor_and_completes(self, tmp_path: Path):
        """When depth estimation produces very low valid_pixel_ratio (<5% valid
        for interpolation), pipeline records fallback and still completes."""
        source_image = _create_test_image(tmp_path)
        objects = _make_segmented_objects(tmp_path, count=2)

        scene_result = SceneParseResult(
            room_plate_path=source_image,
            objects=objects,
            background_mask_path=source_image,
        )
        # Depth result with very low valid ratio — triggers low-confidence path
        # and interpolation will fail (<5% valid), resulting in flat-floor fallback
        depth_result = _make_low_confidence_depth_result(tmp_path)
        room_result = _make_room_mesh_result(tmp_path)
        light_result = _make_light_estimate()
        scale_result = _make_scale_result()
        layout_result = _make_layout_result()

        mesh_result = ObjectMeshResult(
            mesh_path=tmp_path / "session" / "objects" / "obj_000.glb",
            method_used="hunyuan3d",
            generation_time_s=45.0,
            face_count=1200,
            vertex_count=600,
        )
        # Create the mock GLB file on disk
        (tmp_path / "session" / "objects").mkdir(parents=True, exist_ok=True)
        (tmp_path / "session" / "objects" / "obj_000.glb").write_bytes(b"glb")
        (tmp_path / "session" / "objects" / "obj_001.glb").write_bytes(b"glb")

        mesh_result_1 = ObjectMeshResult(
            mesh_path=tmp_path / "session" / "objects" / "obj_001.glb",
            method_used="hunyuan3d",
            generation_time_s=50.0,
            face_count=800,
            vertex_count=400,
        )

        audio_result = AudioResult(
            wav_path=tmp_path / "audio.wav",
            method_used="comfyui_audio",
            duration_s=0.5,
            material_category="wood",
        )

        config = PhotoPipelineConfig(pipeline_timeout_s=60)
        orchestrator = PhotoPipelineOrchestrator(
            config=config,
            session_dir=tmp_path / "session",
            session_id="test-depth-fail-001",
        )

        generate_call_count = [0]
        mesh_results_list = [mesh_result, mesh_result_1]

        async def mock_generate(object_png, mask_id, config):
            idx = generate_call_count[0]
            generate_call_count[0] += 1
            return mesh_results_list[idx]

        def settle_passthrough(*args, **kwargs):
            world_contract = args[1] if len(args) > 1 else kwargs.get("world_contract")
            result = MagicMock()
            result.total_unsettled = 0
            result.iterations_run = 100
            result.settled_world_contract = world_contract
            return result

        with (
            patch.object(
                orchestrator, "_validate_input", return_value=None
            ),
            patch.object(
                orchestrator, "_check_comfyui_health", new_callable=AsyncMock
            ),
            patch(
                "src.photo_pipeline.orchestrator.SceneParser.parse",
                new_callable=AsyncMock,
                return_value=scene_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.DepthEstimator.estimate",
                new_callable=AsyncMock,
                return_value=depth_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.RoomReconstructor.reconstruct",
                new_callable=AsyncMock,
                return_value=room_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.ObjectGenerator.generate",
                new_callable=AsyncMock,
                side_effect=mock_generate,
            ),
            patch(
                "src.photo_pipeline.orchestrator.AudioSynthesizer.synthesize",
                new_callable=AsyncMock,
                return_value=audio_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.LightEstimator.estimate",
                new_callable=AsyncMock,
                return_value=light_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.ScaleCalibrator.calibrate",
                return_value=scale_result,
            ),
            patch(
                "src.photo_pipeline.orchestrator.LayoutEstimator.estimate",
                return_value=[layout_result, layout_result],
            ),
            patch(
                "src.photo_pipeline.orchestrator.PhysicsSettle.settle",
                side_effect=settle_passthrough,
            ),
        ):
            manifest = await orchestrator.run(source_image)

        # Pipeline should still complete
        assert manifest is not None
        assert manifest.session_id == "test-depth-fail-001"

        # Quality is "degraded" because of depth fallback even though meshes
        # used primary method
        assert manifest.quality_classification == "degraded"

        # Each object should have the depth fallback recorded in fallbacks
        for obj_entry in manifest.objects:
            assert "depth:flat_floor_heuristic" in obj_entry.fallbacks_triggered

        # WorldContract file should exist
        contract_path = tmp_path / "session" / "world_contract.json"
        assert contract_path.exists()

        # Validate parseable JSON with valid schema
        contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
        assert contract_data["schema_version"] == "world-contract/v1"
