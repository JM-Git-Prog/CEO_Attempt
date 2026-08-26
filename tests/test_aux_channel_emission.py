"""Unit tests for emit_reference_aux_channels — at-birth auxiliary-channel emission.

Validates that when a MetricPlan is provided, the Canon generator emits a lossless
multi-channel container beside the visible PNG containing depth (Z) and instance_id
channels. The visible PNG itself is never modified.

**Validates: Requirements 2.1, 2.2, 2.3, 3.6**
"""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from PIL import Image

from src.unified_pipeline.canon_generator import (
    emit_reference_aux_channels,
    SceneCanonGenerator,
)
from src.unified_pipeline.models import (
    ArtBible,
    BlockoutResult,
    Brief,
    CameraContract,
    ControlledCameraDepth,
    ManifestObject,
    MetricPlan,
    SceneCanon,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    """Temporary output directory for Canon images."""
    return tmp_path / "canons"


@pytest.fixture
def sample_depth_map() -> np.ndarray:
    """A 768x1024 float32 depth map with finite values and some inf (no geometry)."""
    depth = np.full((768, 1024), 5.0, dtype=np.float32)
    # Upper-left corner has no geometry
    depth[:100, :100] = np.inf
    # Gradient in center
    depth[200:500, 200:800] = np.linspace(1.0, 10.0, 600, dtype=np.float32)
    return depth


@pytest.fixture
def sample_instance_id_map() -> np.ndarray:
    """A 768x1024 int32 instance-ID map. 0 = background, 1+ = objects."""
    ids = np.zeros((768, 1024), dtype=np.int32)
    # Object 1 in center
    ids[200:400, 300:600] = 1
    # Object 2 in lower-right
    ids[500:700, 600:900] = 2
    return ids


@pytest.fixture
def canon_png_path(tmp_path: Path) -> Path:
    """Create a synthetic visible PNG at a Canon path."""
    canon_dir = tmp_path / "canons" / "test_session"
    canon_dir.mkdir(parents=True)
    png_path = canon_dir / "canon_v1.png"
    img = Image.new("RGB", (1024, 768), color=(128, 100, 80))
    img.save(png_path, format="PNG")
    return png_path


@pytest.fixture
def sample_camera() -> CameraContract:
    """Standard CameraContract."""
    return CameraContract(
        position=(2.0, 1.6, 3.0),
        target=(0.0, 1.0, 0.0),
        up=(0.0, 1.0, 0.0),
        vfov=60.0,
        aspect=1024.0 / 768.0,
        near=0.1,
        far=100.0,
        raster_width=1024,
        raster_height=768,
        camera_hash="cam_hash_test_001",
    )


@pytest.fixture
def sample_plan() -> MetricPlan:
    """A MetricPlan with object placements for depth rendering."""
    return MetricPlan(
        room_dimensions=(4.0, 3.0, 2.7),
        object_placements=(
            {
                "object_id": "obj_0",
                "name": "round_table",
                "position": [0.0, 0.0, 0.0],
                "dimensions": [0.8, 0.75, 0.8],
            },
            {
                "object_id": "obj_1",
                "name": "chair",
                "position": [1.0, 0.0, 0.5],
                "dimensions": [0.5, 0.9, 0.5],
            },
        ),
    )


# ─── Tests: emit_reference_aux_channels (unit) ────────────────────────────────


class TestEmitReferenceAuxChannels:
    """Unit tests for the emit_reference_aux_channels helper function."""

    def test_writes_aux_file_beside_png(
        self, canon_png_path: Path, sample_depth_map: np.ndarray, sample_instance_id_map: np.ndarray
    ):
        """Aux container is written beside the visible PNG with .aux.exr extension."""
        aux_path = emit_reference_aux_channels(
            canon_image_path=canon_png_path,
            depth_map=sample_depth_map,
            instance_id_map=sample_instance_id_map,
            camera_hash="cam_hash_test_001",
            plan_revision=1,
        )

        assert aux_path.exists()
        assert aux_path.suffix == ".exr"
        assert aux_path.stem == "canon_v1.aux"
        assert aux_path.parent == canon_png_path.parent

    def test_aux_file_is_nonempty(
        self, canon_png_path: Path, sample_depth_map: np.ndarray, sample_instance_id_map: np.ndarray
    ):
        """The aux container has nonzero size (lossless content written)."""
        aux_path = emit_reference_aux_channels(
            canon_image_path=canon_png_path,
            depth_map=sample_depth_map,
            instance_id_map=sample_instance_id_map,
            camera_hash="cam_hash_test_001",
            plan_revision=1,
        )

        assert aux_path.stat().st_size > 0

    def test_visible_png_unchanged(
        self, canon_png_path: Path, sample_depth_map: np.ndarray, sample_instance_id_map: np.ndarray
    ):
        """The visible PNG is byte-identical after aux emission (Req 3.6)."""
        original_bytes = canon_png_path.read_bytes()

        emit_reference_aux_channels(
            canon_image_path=canon_png_path,
            depth_map=sample_depth_map,
            instance_id_map=sample_instance_id_map,
            camera_hash="cam_hash_test_001",
            plan_revision=1,
        )

        assert canon_png_path.read_bytes() == original_bytes

    def test_aux_contains_depth_channel(
        self, canon_png_path: Path, sample_depth_map: np.ndarray, sample_instance_id_map: np.ndarray
    ):
        """The aux container contains a Z (depth) channel that is lossless."""
        aux_path = emit_reference_aux_channels(
            canon_image_path=canon_png_path,
            depth_map=sample_depth_map,
            instance_id_map=sample_instance_id_map,
            camera_hash="cam_hash_test_001",
            plan_revision=1,
        )

        # Verify by loading — try OpenEXR first, then npz fallback
        channels = _load_aux_channels(aux_path)
        assert "Z" in channels
        # Depth values should round-trip losslessly (float32)
        loaded_depth = channels["Z"]
        # Replace sentinel (1e30 for EXR) back to inf for comparison
        loaded_depth[loaded_depth >= 1e29] = np.inf
        np.testing.assert_array_equal(loaded_depth, sample_depth_map)

    def test_aux_contains_instance_id_channel(
        self, canon_png_path: Path, sample_depth_map: np.ndarray, sample_instance_id_map: np.ndarray
    ):
        """The aux container contains an instance_id channel."""
        aux_path = emit_reference_aux_channels(
            canon_image_path=canon_png_path,
            depth_map=sample_depth_map,
            instance_id_map=sample_instance_id_map,
            camera_hash="cam_hash_test_001",
            plan_revision=1,
        )

        channels = _load_aux_channels(aux_path)
        assert "instance_id" in channels
        loaded_ids = channels["instance_id"].astype(np.int32)
        np.testing.assert_array_equal(loaded_ids, sample_instance_id_map)

    def test_mismatched_shapes_raises_valueerror(self, canon_png_path: Path):
        """ValueError raised if depth_map and instance_id_map have different shapes."""
        depth = np.zeros((768, 1024), dtype=np.float32)
        ids = np.zeros((512, 512), dtype=np.int32)

        with pytest.raises(ValueError, match="shape"):
            emit_reference_aux_channels(
                canon_image_path=canon_png_path,
                depth_map=depth,
                instance_id_map=ids,
                camera_hash="cam_hash_test_001",
                plan_revision=1,
            )

    def test_returns_correct_path(
        self, canon_png_path: Path, sample_depth_map: np.ndarray, sample_instance_id_map: np.ndarray
    ):
        """Return value is the aux container path."""
        result = emit_reference_aux_channels(
            canon_image_path=canon_png_path,
            depth_map=sample_depth_map,
            instance_id_map=sample_instance_id_map,
            camera_hash="cam_hash_test_001",
            plan_revision=1,
        )

        assert isinstance(result, Path)
        expected = canon_png_path.with_suffix(".aux.exr")
        assert result == expected

    def test_small_depth_map_roundtrips(self, tmp_path: Path):
        """Minimal case: 4x4 depth + instance IDs round-trip correctly."""
        png_path = tmp_path / "canon_v3.png"
        Image.new("RGB", (4, 4), color=(50, 60, 70)).save(png_path)

        depth = np.array(
            [[1.0, 2.0, np.inf, 4.0]] * 4, dtype=np.float32
        )
        ids = np.array(
            [[0, 1, 0, 2]] * 4, dtype=np.int32
        )

        aux_path = emit_reference_aux_channels(
            canon_image_path=png_path,
            depth_map=depth,
            instance_id_map=ids,
            camera_hash="hash_abc",
            plan_revision=3,
        )

        channels = _load_aux_channels(aux_path)
        loaded_depth = channels["Z"]
        loaded_depth[loaded_depth >= 1e29] = np.inf
        np.testing.assert_array_equal(loaded_depth, depth)
        np.testing.assert_array_equal(channels["instance_id"].astype(np.int32), ids)


# ─── Tests: generate() with plan parameter ────────────────────────────────────


class TestGenerateWithPlan:
    """Verify generate() emits aux channels when a plan is provided."""

    @pytest.fixture
    def setup_environment(self, tmp_path: Path):
        """Set up a blockout PNG and generator for testing."""
        # Create blockout image
        blockout_dir = tmp_path / "blockouts"
        blockout_dir.mkdir()
        blockout_path = blockout_dir / "blockout_v1.png"
        Image.new("RGB", (1024, 768), color=(200, 200, 200)).save(blockout_path)

        # Generator with tmp output
        output_dir = tmp_path / "canons"
        generator = SceneCanonGenerator(output_dir=output_dir)

        blockout = BlockoutResult(
            image_path=str(blockout_path),
            plan_revision=1,
            camera_hash="cam_hash_test_001",
            approved=True,
        )

        camera = CameraContract(
            position=(2.0, 1.6, 3.0),
            target=(0.0, 1.0, 0.0),
            up=(0.0, 1.0, 0.0),
            vfov=60.0,
            aspect=1024.0 / 768.0,
            raster_width=1024,
            raster_height=768,
            camera_hash="cam_hash_test_001",
        )

        plan = MetricPlan(
            room_dimensions=(4.0, 3.0, 2.7),
            object_placements=(
                {
                    "object_id": "obj_0",
                    "name": "round_table",
                    "position": [0.0, 0.0, 0.0],
                    "dimensions": [0.8, 0.75, 0.8],
                },
            ),
        )

        brief = Brief(
            room_purpose="cafe",
            object_manifest=(
                ManifestObject(id="obj_0", name="round_table", role="furniture"),
            ),
        )

        art_bible = ArtBible(
            material_palette=("wood", "brass"),
            color_palette=("warm_brown", "cream"),
            lighting_direction={"type": "warm_overhead"},
            immutable=True,
        )

        return {
            "generator": generator,
            "blockout": blockout,
            "camera": camera,
            "plan": plan,
            "brief": brief,
            "art_bible": art_bible,
            "output_dir": output_dir,
        }

    @pytest.mark.asyncio
    async def test_generate_with_plan_emits_aux_file(self, setup_environment, tmp_path: Path):
        """When plan is provided, generate() writes aux channels beside PNG."""
        env = setup_environment

        # Mock ComfyUI client to return a synthetic PNG
        with patch(
            "src.unified_pipeline.canon_generator.ComfyUIClient"
        ) as mock_client_cls:
            client_instance = AsyncMock()
            mock_client_cls.return_value = client_instance
            client_instance.upload_image.return_value = "blockout_v1.png"
            client_instance.submit_workflow.return_value = "prompt_001"
            client_instance.wait_for_completion.return_value = None

            # get_output_image writes a synthetic PNG
            async def fake_get_output(prompt_id, output_dir, filename="output.png"):
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / filename
                Image.new("RGB", (1024, 768), color=(128, 100, 80)).save(out_path)
                return out_path

            client_instance.get_output_image.side_effect = fake_get_output

            # Mock vision validation to avoid network calls
            with patch(
                "src.unified_pipeline.canon_generator._validate_presence_via_vision",
                return_value={"obj_0": "present"},
            ):
                result = await env["generator"].generate(
                    blockout=env["blockout"],
                    art_bible=env["art_bible"],
                    brief=env["brief"],
                    camera=env["camera"],
                    plan=env["plan"],
                    session_id="test_session",
                    seed=42,
                )

        # The visible PNG should exist
        assert Path(result.image_path).exists()

        # The aux file should exist beside it
        aux_path = Path(result.image_path).with_suffix(".aux.exr")
        assert aux_path.exists(), (
            f"Aux channel file not emitted beside PNG at {aux_path}"
        )
        assert aux_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_generate_without_plan_no_aux_file(self, setup_environment, tmp_path: Path):
        """When plan is None (default), generate() does NOT emit aux channels."""
        env = setup_environment

        with patch(
            "src.unified_pipeline.canon_generator.ComfyUIClient"
        ) as mock_client_cls:
            client_instance = AsyncMock()
            mock_client_cls.return_value = client_instance
            client_instance.upload_image.return_value = "blockout_v1.png"
            client_instance.submit_workflow.return_value = "prompt_001"
            client_instance.wait_for_completion.return_value = None

            async def fake_get_output(prompt_id, output_dir, filename="output.png"):
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / filename
                Image.new("RGB", (1024, 768), color=(128, 100, 80)).save(out_path)
                return out_path

            client_instance.get_output_image.side_effect = fake_get_output

            with patch(
                "src.unified_pipeline.canon_generator._validate_presence_via_vision",
                return_value={"obj_0": "present"},
            ):
                result = await env["generator"].generate(
                    blockout=env["blockout"],
                    art_bible=env["art_bible"],
                    brief=env["brief"],
                    camera=env["camera"],
                    # plan is NOT provided (defaults to None)
                    session_id="test_session_no_plan",
                    seed=42,
                )

        # The visible PNG should exist
        assert Path(result.image_path).exists()

        # No aux file should be present (backward compat)
        aux_path = Path(result.image_path).with_suffix(".aux.exr")
        assert not aux_path.exists(), (
            "Aux file should NOT be emitted when plan is None"
        )

    @pytest.mark.asyncio
    async def test_generate_png_bytes_unchanged_with_plan(self, setup_environment, tmp_path: Path):
        """Visible PNG is byte-identical whether or not aux emission occurs (Req 3.6)."""
        env = setup_environment

        # We'll capture what gets written to the PNG
        png_bytes_with_plan: bytes | None = None
        png_bytes_without_plan: bytes | None = None

        for use_plan, storage_name in [(True, "with"), (False, "without")]:
            with patch(
                "src.unified_pipeline.canon_generator.ComfyUIClient"
            ) as mock_client_cls:
                client_instance = AsyncMock()
                mock_client_cls.return_value = client_instance
                client_instance.upload_image.return_value = "blockout_v1.png"
                client_instance.submit_workflow.return_value = "prompt_001"
                client_instance.wait_for_completion.return_value = None

                async def fake_get_output(prompt_id, output_dir, filename="output.png"):
                    output_dir.mkdir(parents=True, exist_ok=True)
                    out_path = output_dir / filename
                    # Deterministic content based on seed (same for both calls)
                    img = Image.new("RGB", (1024, 768), color=(128, 100, 80))
                    img.save(out_path, format="PNG")
                    return out_path

                client_instance.get_output_image.side_effect = fake_get_output

                with patch(
                    "src.unified_pipeline.canon_generator._validate_presence_via_vision",
                    return_value={"obj_0": "present"},
                ):
                    result = await env["generator"].generate(
                        blockout=env["blockout"],
                        art_bible=env["art_bible"],
                        brief=env["brief"],
                        camera=env["camera"],
                        plan=env["plan"] if use_plan else None,
                        session_id=f"test_{storage_name}",
                        seed=42,
                    )

                png_data = Path(result.image_path).read_bytes()
                if use_plan:
                    png_bytes_with_plan = png_data
                else:
                    png_bytes_without_plan = png_data

        # PNG bytes should be identical — aux emission never touches the visible RGB
        assert png_bytes_with_plan == png_bytes_without_plan


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _load_aux_channels(aux_path: Path) -> dict[str, np.ndarray]:
    """Load channels from an aux container (OpenEXR or npz fallback).

    Returns dict mapping channel name → float32 ndarray.
    """
    # Try OpenEXR first
    try:
        import OpenEXR  # type: ignore[import]
        import Imath  # type: ignore[import]

        exr_file = OpenEXR.InputFile(str(aux_path))
        header = exr_file.header()
        channels = header.get("channels", {})
        dw = header["dataWindow"]
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1

        result = {}
        for ch_name in channels:
            raw = exr_file.channel(ch_name, Imath.PixelType(Imath.PixelType.FLOAT))
            arr = np.frombuffer(raw, dtype=np.float32).reshape(height, width)
            result[ch_name] = arr.copy()
        exr_file.close()
        return result

    except ImportError:
        # Fall back to npz loading
        data = np.load(str(aux_path), allow_pickle=False)
        result = {}
        for key in data.files:
            if not key.startswith("_"):
                result[key] = data[key].astype(np.float32)
        return result
