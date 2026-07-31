"""Tests for RoomPlateGenerator.

Tests the Room Plate generation logic including:
- Successful inpainting with object masks removed
- Combined mask building from multiple object masks
- Fallback to Canon when ComfyUI is unavailable
- Fallback on inpainting errors and timeouts
- Resolution mismatch detection
- Empty/invalid mask handling
- Zero masks case (Canon = Room_Plate)

Requirements: 16.2 (Room_Plate for shell texturing — Canon with objects removed)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from src.unified_pipeline.room_plate import RoomPlateGenerator
from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)


@pytest.fixture
def canon_image(tmp_path) -> Path:
    """Create a test Canon image (1024x768 RGB)."""
    canon_path = tmp_path / "canon.png"
    img = Image.new("RGB", (1024, 768), color=(128, 100, 80))
    img.save(canon_path)
    return canon_path


@pytest.fixture
def object_mask_file(tmp_path) -> Path:
    """Create a test object mask (white square in center)."""
    mask_path = tmp_path / "masks" / "mask_001.png"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    mask = np.zeros((768, 1024), dtype=np.uint8)
    # Object region: white square in center
    mask[300:500, 400:600] = 255
    Image.fromarray(mask, mode="L").save(mask_path)
    return mask_path


@pytest.fixture
def mock_client():
    """Create a mock ComfyUI client with success-path defaults."""
    client = MagicMock(spec=ComfyUIClient)
    client.health_check = AsyncMock(return_value=True)
    client.upload_image = AsyncMock(side_effect=["canon.png", "mask.png"])
    client.submit_workflow = AsyncMock(return_value="prompt-456")
    client.wait_for_completion = AsyncMock(
        return_value={"outputs": {"5": {"images": [{"filename": "room_plate.png"}]}}}
    )
    # get_output_image will be configured per test where needed
    client.get_output_image = AsyncMock()
    return client


@pytest.fixture
def generator(mock_client, tmp_path):
    """Create a RoomPlateGenerator with mocked client."""
    return RoomPlateGenerator(
        comfyui_client=mock_client,
        output_dir=tmp_path / "room_plates",
    )


class TestGenerate:
    """Tests for RoomPlateGenerator.generate()."""

    @pytest.mark.asyncio
    async def test_successful_inpainting(
        self, generator, mock_client, canon_image, tmp_path
    ):
        """Req 16.2: Generates Room_Plate with objects inpainted out."""
        # Setup: get_output_image returns a valid path
        output_path = tmp_path / "room_plates" / "test-session" / "room_plate.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Create the expected output file
        Image.new("RGB", (1024, 768), color=(130, 105, 85)).save(output_path)
        mock_client.get_output_image = AsyncMock(return_value=output_path)

        object_masks = [
            {"mask_path": str(canon_image.parent / "dummy_mask.png")}
        ]
        # Create a real mask file for the test
        mask_path = canon_image.parent / "dummy_mask.png"
        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[200:400, 300:500] = 255
        Image.fromarray(mask, mode="L").save(mask_path)

        result = await generator.generate(
            canon_path=str(canon_image),
            object_masks=[{"mask_path": str(mask_path)}],
            session_id="test-session",
        )

        assert result == str(output_path)
        mock_client.health_check.assert_awaited_once()
        mock_client.upload_image.assert_awaited()
        mock_client.submit_workflow.assert_awaited_once()
        mock_client.wait_for_completion.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zero_masks_returns_canon_copy(
        self, generator, mock_client, canon_image, tmp_path
    ):
        """No object masks → Canon IS the Room_Plate (no inpainting needed)."""
        result = await generator.generate(
            canon_path=str(canon_image),
            object_masks=[],
            session_id="no-masks",
        )

        result_path = Path(result)
        assert result_path.exists()
        # Verify it's a copy of the Canon
        result_img = Image.open(result_path)
        assert result_img.size == (1024, 768)
        # ComfyUI should not have been called
        mock_client.submit_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_comfyui_unavailable_fallback(
        self, generator, mock_client, canon_image, tmp_path
    ):
        """Falls back to Canon when ComfyUI is unreachable."""
        mock_client.health_check = AsyncMock(return_value=False)

        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[100:200, 100:200] = 255

        result = await generator.generate(
            canon_path=str(canon_image),
            object_masks=[{"mask_array": mask}],
            session_id="no-comfyui",
        )

        result_path = Path(result)
        assert result_path.exists()
        assert "room_plate.png" in result_path.name
        # Should not attempt workflow submission
        mock_client.submit_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_inpainting_error_fallback(
        self, generator, mock_client, canon_image, tmp_path
    ):
        """Falls back to Canon on ComfyUI execution error."""
        mock_client.submit_workflow = AsyncMock(
            side_effect=ComfyUIError("Workflow execution failed")
        )

        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[100:200, 100:200] = 255

        result = await generator.generate(
            canon_path=str(canon_image),
            object_masks=[{"mask_array": mask}],
            session_id="error-session",
        )

        result_path = Path(result)
        assert result_path.exists()
        assert result_path.name == "room_plate.png"

    @pytest.mark.asyncio
    async def test_timeout_fallback(
        self, generator, mock_client, canon_image, tmp_path
    ):
        """Falls back to Canon when inpainting times out."""
        mock_client.wait_for_completion = AsyncMock(
            side_effect=ComfyUITimeoutError("Exceeded 120s")
        )

        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[100:200, 100:200] = 255

        result = await generator.generate(
            canon_path=str(canon_image),
            object_masks=[{"mask_array": mask}],
            session_id="timeout-session",
        )

        result_path = Path(result)
        assert result_path.exists()

    @pytest.mark.asyncio
    async def test_resolution_mismatch_fallback(
        self, generator, mock_client, canon_image, tmp_path
    ):
        """Falls back when inpainted result has wrong resolution."""
        # Create mismatched output
        output_path = tmp_path / "room_plates" / "mismatch" / "room_plate.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (512, 384), color=(100, 100, 100)).save(output_path)
        mock_client.get_output_image = AsyncMock(return_value=output_path)

        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[100:200, 100:200] = 255

        result = await generator.generate(
            canon_path=str(canon_image),
            object_masks=[{"mask_array": mask}],
            session_id="mismatch",
        )

        # Should produce a valid result (fallback canon copy)
        result_path = Path(result)
        assert result_path.exists()
        result_img = Image.open(result_path)
        # Fallback should match canon resolution
        assert result_img.size == (1024, 768)

    @pytest.mark.asyncio
    async def test_canon_not_found_raises(self, generator):
        """Raises FileNotFoundError when Canon image doesn't exist."""
        with pytest.raises(FileNotFoundError, match="Canon image not found"):
            await generator.generate(
                canon_path="/nonexistent/canon.png",
                object_masks=[{"mask_path": "/some/mask.png"}],
                session_id="not-found",
            )


class TestBuildInpaintMask:
    """Tests for RoomPlateGenerator._build_inpaint_mask()."""

    def test_combines_multiple_masks(self, generator, canon_image, tmp_path):
        """Multiple object masks are combined via union (OR)."""
        session_dir = tmp_path / "room_plates" / "combine"
        session_dir.mkdir(parents=True, exist_ok=True)

        mask1 = np.zeros((768, 1024), dtype=np.uint8)
        mask1[100:200, 100:200] = 255

        mask2 = np.zeros((768, 1024), dtype=np.uint8)
        mask2[400:500, 600:700] = 255

        object_masks = [
            {"mask_array": mask1},
            {"mask_array": mask2},
        ]

        result_path = generator._build_inpaint_mask(
            object_masks, session_dir, canon_image
        )

        # Verify combined mask
        combined = np.array(Image.open(result_path).convert("L"))
        # Both regions should be white
        assert combined[150, 150] == 255  # mask1 region
        assert combined[450, 650] == 255  # mask2 region
        # Non-masked region should be black
        assert combined[300, 300] == 0

    def test_mask_from_file_path(
        self, generator, canon_image, object_mask_file, tmp_path
    ):
        """Loads mask from file path correctly."""
        session_dir = tmp_path / "room_plates" / "file-mask"
        session_dir.mkdir(parents=True, exist_ok=True)

        object_masks = [{"mask_path": str(object_mask_file)}]

        result_path = generator._build_inpaint_mask(
            object_masks, session_dir, canon_image
        )

        combined = np.array(Image.open(result_path).convert("L"))
        # Center region should be white (from the mask file)
        assert combined[400, 500] == 255
        # Corner should be black
        assert combined[0, 0] == 0

    def test_skips_invalid_masks(self, generator, canon_image, tmp_path):
        """Invalid mask descriptors are skipped without crashing."""
        session_dir = tmp_path / "room_plates" / "invalid"
        session_dir.mkdir(parents=True, exist_ok=True)

        mask_valid = np.zeros((768, 1024), dtype=np.uint8)
        mask_valid[100:200, 100:200] = 255

        object_masks = [
            {"mask_path": "/nonexistent/mask.png"},  # missing file
            {"mask_array": mask_valid},  # valid
            {"bad_key": "no mask here"},  # bad descriptor
        ]

        result_path = generator._build_inpaint_mask(
            object_masks, session_dir, canon_image
        )

        combined = np.array(Image.open(result_path).convert("L"))
        # Only the valid mask should appear
        assert combined[150, 150] == 255
        assert combined[500, 500] == 0

    def test_mask_resized_to_match_canon(self, generator, canon_image, tmp_path):
        """Masks with different dimensions are resized to match Canon."""
        session_dir = tmp_path / "room_plates" / "resize"
        session_dir.mkdir(parents=True, exist_ok=True)

        # Create a mask with different dimensions (512x384)
        small_mask = np.zeros((384, 512), dtype=np.uint8)
        small_mask[100:200, 100:200] = 255

        object_masks = [{"mask_array": small_mask}]

        result_path = generator._build_inpaint_mask(
            object_masks, session_dir, canon_image
        )

        # Combined mask should have Canon dimensions
        combined = Image.open(result_path)
        assert combined.size == (1024, 768)


class TestLoadMask:
    """Tests for RoomPlateGenerator._load_mask()."""

    def test_load_from_array(self, generator):
        """Loads mask from numpy array."""
        mask = np.zeros((768, 1024), dtype=np.uint8)
        mask[0:100, 0:100] = 200  # Any nonzero value

        result = generator._load_mask(
            {"mask_array": mask}, (768, 1024)
        )

        assert result is not None
        assert result.shape == (768, 1024)
        # Should be binarized to 255
        assert result[50, 50] == 255
        assert result[500, 500] == 0

    def test_load_from_file(self, generator, object_mask_file):
        """Loads mask from PNG file path."""
        result = generator._load_mask(
            {"mask_path": str(object_mask_file)}, (768, 1024)
        )

        assert result is not None
        assert result.shape == (768, 1024)
        # Center should be white (where the mask square is)
        assert result[400, 500] == 255

    def test_missing_file_returns_none(self, generator):
        """Returns None for nonexistent mask file."""
        result = generator._load_mask(
            {"mask_path": "/does/not/exist.png"}, (768, 1024)
        )
        assert result is None

    def test_bad_descriptor_returns_none(self, generator):
        """Returns None for descriptor missing both keys."""
        result = generator._load_mask(
            {"some_other_key": "value"}, (768, 1024)
        )
        assert result is None

    def test_non_ndarray_mask_array_returns_none(self, generator):
        """Returns None when mask_array is not a numpy array."""
        result = generator._load_mask(
            {"mask_array": "not an array"}, (768, 1024)
        )
        assert result is None


class TestFallbackCopyCanon:
    """Tests for fallback behavior (Canon used as Room_Plate)."""

    def test_creates_valid_copy(self, generator, canon_image, tmp_path):
        """Fallback produces a valid RGB image matching Canon dimensions."""
        output_path = tmp_path / "room_plates" / "fallback" / "room_plate.png"

        result = generator._fallback_copy_canon(canon_image, output_path)

        assert result.exists()
        img = Image.open(result)
        assert img.size == (1024, 768)
        assert img.mode == "RGB"

    def test_creates_parent_directories(self, generator, canon_image, tmp_path):
        """Fallback creates output directories if they don't exist."""
        deep_path = tmp_path / "a" / "b" / "c" / "room_plate.png"

        result = generator._fallback_copy_canon(canon_image, deep_path)

        assert result.exists()


class TestWorkflowBuilding:
    """Tests for _build_inpaint_workflow()."""

    def test_workflow_structure(self, generator):
        """Workflow has correct ComfyUI node structure."""
        workflow = generator._build_inpaint_workflow("canon.png", "mask.png")

        # Should have 5 nodes
        assert len(workflow) == 5
        # Node 1: LoadImage for Canon
        assert workflow["1"]["class_type"] == "LoadImage"
        assert workflow["1"]["inputs"]["image"] == "canon.png"
        # Node 2: LoadImage for mask
        assert workflow["2"]["class_type"] == "LoadImage"
        assert workflow["2"]["inputs"]["image"] == "mask.png"
        # Node 3: FluxFillModelLoader
        assert workflow["3"]["class_type"] == "FluxFillModelLoader"
        assert "flux1-fill-dev" in workflow["3"]["inputs"]["model_name"]
        # Node 4: FluxFillInpaint
        assert workflow["4"]["class_type"] == "FluxFillInpaint"
        assert workflow["4"]["inputs"]["steps"] == 20
        # Node 5: SaveImage
        assert workflow["5"]["class_type"] == "SaveImage"

    def test_workflow_connections(self, generator):
        """Workflow nodes are wired correctly."""
        workflow = generator._build_inpaint_workflow("c.png", "m.png")

        inpaint_inputs = workflow["4"]["inputs"]
        # Model from loader
        assert inpaint_inputs["model"] == ["3", 0]
        # Image from Canon loader
        assert inpaint_inputs["image"] == ["1", 0]
        # Mask from mask loader
        assert inpaint_inputs["mask"] == ["2", 0]

        # SaveImage takes inpaint output
        assert workflow["5"]["inputs"]["images"] == ["4", 0]
