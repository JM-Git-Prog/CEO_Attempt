"""Tests for ObjectIsolator — SAM segmentation and RGBA Object_PNG production.

Tests the quality gate, mask matching, RGBA application, and the overall
segment() workflow.

Requirements tested:
- Req 9.1: Segment Canon → RGBA Object_PNG per object on transparent background
- Req 9.2: Each Object_PNG corresponds to exactly one Brief manifest UUID
- Req 9.3: Detect empty/broken segmentations (<1% coverage) automatically
- Req 9.4: Object_PNG used directly as mesh input (raw segmentation for MVP)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import numpy as np
import pytest

from src.unified_pipeline.models import ManifestObject, ObjectCanon
from src.unified_pipeline.object_isolator import (
    ObjectIsolator,
    SegmentationError,
    _build_sam_workflow,
    _compute_mask_area_fraction,
    _compute_mask_bbox,
    _compute_mask_centroid,
    _match_masks_to_manifest,
    apply_mask_to_image,
    quality_gate,
    MIN_COVERAGE_THRESHOLD,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def manifest() -> list[ManifestObject]:
    """Sample manifest with 3 objects."""
    return [
        ManifestObject(
            id="uuid-table",
            name="round table",
            role="furniture",
            count=1,
            material_hint="wood",
            is_architectural=False,
        ),
        ManifestObject(
            id="uuid-chair",
            name="chair",
            role="seating",
            count=2,
            material_hint="wood",
            is_architectural=False,
        ),
        ManifestObject(
            id="uuid-counter",
            name="counter",
            role="workspace",
            count=1,
            material_hint="granite",
            is_architectural=True,
        ),
    ]


@pytest.fixture
def sample_image() -> np.ndarray:
    """A simple 100x100 RGB image."""
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    # Red square in top-left
    img[10:40, 10:40] = [255, 0, 0]
    # Green square in center
    img[40:70, 40:70] = [0, 255, 0]
    # Blue rectangle bottom
    img[80:95, 20:80] = [0, 0, 255]
    return img


@pytest.fixture
def large_mask() -> np.ndarray:
    """A mask covering 30% of a 100x100 image."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:40, 10:40] = 255  # 30x30 = 900 pixels out of 10000 = 9%
    mask[40:70, 40:70] = 255  # 30x30 = 900 more = 18% total
    mask[70:100, 0:50] = 255  # 30x50 = 1500 more = 33% total
    return mask


@pytest.fixture
def small_mask() -> np.ndarray:
    """A mask covering <1% of a 100x100 image (only 50 pixels)."""
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[0:5, 0:10] = 255  # 5x10 = 50 pixels = 0.5%
    return mask


@pytest.fixture
def empty_mask() -> np.ndarray:
    """An all-zeros mask."""
    return np.zeros((100, 100), dtype=np.uint8)


@pytest.fixture
def canon_image_file(tmp_path: Path) -> Path:
    """Write a sample Canon image to disk and return its path."""
    from PIL import Image

    img = Image.new("RGB", (200, 200), color=(128, 64, 32))
    path = tmp_path / "canon.png"
    img.save(str(path))
    return path


# ─── Tests: Quality Gate ────────────────────────────────────────────────────────


class TestQualityGate:
    """Tests for the quality gate that rejects masks with <1% coverage."""

    def test_passes_good_mask(self, large_mask: np.ndarray):
        """A mask with substantial coverage passes the gate."""
        assert quality_gate(large_mask, "test-object") is True

    def test_rejects_small_mask(self, small_mask: np.ndarray):
        """A mask with <1% coverage fails the gate. (Req 9.3)"""
        assert quality_gate(small_mask, "test-object") is False

    def test_rejects_empty_mask(self, empty_mask: np.ndarray):
        """An empty mask fails the gate. (Req 9.3)"""
        assert quality_gate(empty_mask, "test-object") is False

    def test_threshold_boundary_pass(self):
        """A mask exactly at 1% coverage passes."""
        # 100x100 image, 1% = 100 pixels
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[0:10, 0:10] = 255  # exactly 100 pixels = 1%
        assert quality_gate(mask, "boundary") is True

    def test_threshold_boundary_fail(self):
        """A mask just under 1% coverage fails."""
        # 100x100 image, 99 pixels = 0.99%
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[0:9, 0:11] = 255  # 9x11 = 99 pixels = 0.99%
        assert quality_gate(mask, "boundary") is False


# ─── Tests: Mask Utilities ──────────────────────────────────────────────────────


class TestMaskUtilities:
    """Tests for mask utility functions."""

    def test_centroid_center(self):
        """Centroid of a centered square is at (0.5, 0.5)."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[25:75, 25:75] = 255
        cy, cx = _compute_mask_centroid(mask)
        assert abs(cy - 0.5) < 0.05
        assert abs(cx - 0.5) < 0.05

    def test_centroid_top_left(self):
        """Centroid of a top-left corner block is near (0.1, 0.1)."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[0:20, 0:20] = 255
        cy, cx = _compute_mask_centroid(mask)
        assert cy < 0.15
        assert cx < 0.15

    def test_centroid_empty(self):
        """Empty mask returns default centroid (0.5, 0.5)."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        cy, cx = _compute_mask_centroid(mask)
        assert cy == 0.5
        assert cx == 0.5

    def test_area_fraction(self, large_mask: np.ndarray):
        """Area fraction is correctly computed."""
        area = _compute_mask_area_fraction(large_mask)
        assert area > 0.0
        assert area <= 1.0

    def test_area_fraction_empty(self, empty_mask: np.ndarray):
        """Empty mask has 0 area fraction."""
        assert _compute_mask_area_fraction(empty_mask) == 0.0

    def test_area_fraction_full(self):
        """Full mask has area fraction == 1.0."""
        mask = np.ones((100, 100), dtype=np.uint8) * 255
        assert _compute_mask_area_fraction(mask) == 1.0

    def test_bbox(self):
        """Bounding box is correctly computed."""
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[20:50, 30:70] = 255
        y_min, x_min, y_max, x_max = _compute_mask_bbox(mask)
        assert y_min == 20
        assert x_min == 30
        assert y_max == 49
        assert x_max == 69

    def test_bbox_empty(self, empty_mask: np.ndarray):
        """Empty mask returns (0, 0, 0, 0) bbox."""
        assert _compute_mask_bbox(empty_mask) == (0, 0, 0, 0)


# ─── Tests: Mask Matching ───────────────────────────────────────────────────────


class TestMaskMatching:
    """Tests for matching SAM masks to manifest objects."""

    def test_matches_architectural_first(self, manifest: list[ManifestObject]):
        """Architectural objects get the largest masks first. (Req 9.2)"""
        # 3 masks of different sizes
        masks = [
            np.zeros((100, 100), dtype=np.uint8),  # Small (5%)
            np.zeros((100, 100), dtype=np.uint8),  # Medium (15%)
            np.zeros((100, 100), dtype=np.uint8),  # Large (30%)
        ]
        masks[0][0:5, 0:100] = 255  # 500 px = 5%
        masks[1][0:15, 0:100] = 255  # 1500 px = 15%
        masks[2][0:30, 0:100] = 255  # 3000 px = 30%

        result = _match_masks_to_manifest(masks, manifest, (100, 100))

        # Counter is architectural → should get the largest mask
        counter_mask = result.get("uuid-counter")
        assert counter_mask is not None
        counter_area = _compute_mask_area_fraction(counter_mask)
        assert counter_area == pytest.approx(0.30, abs=0.01)

    def test_returns_empty_for_no_masks(self, manifest: list[ManifestObject]):
        """No masks → empty result."""
        result = _match_masks_to_manifest([], manifest, (100, 100))
        assert result == {}

    def test_returns_empty_for_no_manifest(self):
        """No manifest → empty result."""
        masks = [np.ones((100, 100), dtype=np.uint8) * 255]
        result = _match_masks_to_manifest(masks, [], (100, 100))
        assert result == {}

    def test_assigns_unique_masks(self, manifest: list[ManifestObject]):
        """Each manifest object gets a different mask. (Req 9.2)"""
        masks = [
            np.zeros((100, 100), dtype=np.uint8),
            np.zeros((100, 100), dtype=np.uint8),
            np.zeros((100, 100), dtype=np.uint8),
        ]
        masks[0][0:20, 0:100] = 255
        masks[1][20:50, 0:100] = 255
        masks[2][50:100, 0:100] = 255

        result = _match_masks_to_manifest(masks, manifest, (100, 100))

        # Each object should get a mask
        assert len(result) == 3
        # All masks should be different objects (check different areas)
        areas = [
            _compute_mask_area_fraction(m) for m in result.values()
        ]
        assert len(set(round(a, 4) for a in areas)) == 3

    def test_fewer_masks_than_objects(self, manifest: list[ManifestObject]):
        """When there are fewer masks than objects, only some get matched."""
        masks = [np.ones((100, 100), dtype=np.uint8) * 255]
        result = _match_masks_to_manifest(masks, manifest, (100, 100))
        # Only 1 mask available, so only 1 object gets matched
        assert len(result) == 1


# ─── Tests: Apply Mask to Image ─────────────────────────────────────────────────


class TestApplyMask:
    """Tests for RGBA PNG generation from mask + image."""

    def test_produces_rgba_png(
        self, sample_image: np.ndarray, large_mask: np.ndarray, tmp_path: Path
    ):
        """Output is a valid RGBA PNG. (Req 9.1)"""
        from PIL import Image

        output = tmp_path / "object.png"
        result = apply_mask_to_image(sample_image, large_mask, output)

        assert result.exists()
        img = Image.open(result)
        assert img.mode == "RGBA"
        assert img.size == (100, 100)

    def test_transparent_background(
        self, sample_image: np.ndarray, tmp_path: Path
    ):
        """Areas outside the mask are fully transparent. (Req 9.1)"""
        from PIL import Image

        # Mask only top-left 10x10
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[0:10, 0:10] = 255

        output = tmp_path / "object.png"
        apply_mask_to_image(sample_image, mask, output)

        img = np.array(Image.open(output))
        # Check alpha channel outside mask region is 0
        assert img[50, 50, 3] == 0  # Center should be transparent
        # Check alpha channel inside mask region is 255
        assert img[5, 5, 3] == 255  # Inside mask should be opaque

    def test_preserves_color_inside_mask(
        self, sample_image: np.ndarray, tmp_path: Path
    ):
        """RGB values are preserved where mask is True."""
        from PIL import Image

        # Mask the red square area (10:40, 10:40)
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[10:40, 10:40] = 255

        output = tmp_path / "object.png"
        apply_mask_to_image(sample_image, mask, output)

        img = np.array(Image.open(output))
        # Check a pixel inside the red square
        assert img[20, 20, 0] == 255  # R
        assert img[20, 20, 1] == 0  # G
        assert img[20, 20, 2] == 0  # B
        assert img[20, 20, 3] == 255  # A

    def test_creates_parent_directories(
        self, sample_image: np.ndarray, large_mask: np.ndarray, tmp_path: Path
    ):
        """Output directory is created if it doesn't exist."""
        output = tmp_path / "nested" / "deep" / "object.png"
        result = apply_mask_to_image(sample_image, large_mask, output)
        assert result.exists()


# ─── Tests: SAM Workflow ────────────────────────────────────────────────────────


class TestSAMWorkflow:
    """Tests for the SAM ComfyUI workflow builder."""

    def test_workflow_has_load_image(self):
        """Workflow includes LoadImage node."""
        wf = _build_sam_workflow("test.png")
        assert "1" in wf
        assert wf["1"]["class_type"] == "LoadImage"
        assert wf["1"]["inputs"]["image"] == "test.png"

    def test_workflow_has_sam_model_loader(self):
        """Workflow includes SAM model loader."""
        wf = _build_sam_workflow("test.png")
        assert "2" in wf
        assert "SAMModelLoader" in wf["2"]["class_type"]

    def test_workflow_has_auto_segmentation(self):
        """Workflow includes SAM auto-segmentation node."""
        wf = _build_sam_workflow("test.png")
        assert "3" in wf
        assert "SAMAutoSegmentation" in wf["3"]["class_type"]

    def test_workflow_connections(self):
        """Workflow nodes are properly connected."""
        wf = _build_sam_workflow("test.png")
        # SAM model feeds from node 2
        assert wf["3"]["inputs"]["sam_model"] == ["2", 0]
        # Image feeds from node 1
        assert wf["3"]["inputs"]["image"] == ["1", 0]


# ─── Tests: ObjectIsolator Integration ──────────────────────────────────────────


class TestObjectIsolator:
    """Integration tests for the ObjectIsolator class."""

    def test_init_defaults(self):
        """Default initialization creates valid instance."""
        isolator = ObjectIsolator()
        assert isolator._output_dir == Path("output/objects")
        assert isolator._comfyui_url == "http://127.0.0.1:8188"
        assert isolator._timeout_s == 120

    def test_init_custom(self, tmp_path: Path):
        """Custom initialization parameters work."""
        isolator = ObjectIsolator(
            output_dir=tmp_path / "custom",
            comfyui_url="http://custom:9999",
            timeout_s=60,
        )
        assert isolator._output_dir == tmp_path / "custom"
        assert isolator._comfyui_url == "http://custom:9999"
        assert isolator._timeout_s == 60

    @pytest.mark.asyncio
    async def test_segment_raises_on_missing_canon(
        self, manifest: list[ManifestObject]
    ):
        """segment() raises SegmentationError if Canon file doesn't exist."""
        isolator = ObjectIsolator()
        with pytest.raises(SegmentationError, match="not found"):
            await isolator.segment(
                "/nonexistent/canon.png",
                manifest,
                session_id="test",
            )

    @pytest.mark.asyncio
    async def test_segment_raises_on_empty_sam_result(
        self,
        canon_image_file: Path,
        manifest: list[ManifestObject],
        tmp_path: Path,
    ):
        """segment() raises SegmentationError if SAM returns no masks."""
        isolator = ObjectIsolator(output_dir=tmp_path / "out")

        with patch.object(
            isolator, "_run_sam", new_callable=AsyncMock, return_value=[]
        ):
            with pytest.raises(SegmentationError, match="no masks"):
                await isolator.segment(
                    str(canon_image_file),
                    manifest,
                    session_id="test",
                )

    @pytest.mark.asyncio
    async def test_segment_produces_object_canons(
        self,
        canon_image_file: Path,
        manifest: list[ManifestObject],
        tmp_path: Path,
    ):
        """segment() produces ObjectCanon results for each matched mask. (Req 9.1, 9.2, 9.4)"""
        isolator = ObjectIsolator(output_dir=tmp_path / "out")

        # Create 3 good masks (all > 1% coverage on 200x200 image)
        masks = [
            np.zeros((200, 200), dtype=np.uint8),
            np.zeros((200, 200), dtype=np.uint8),
            np.zeros((200, 200), dtype=np.uint8),
        ]
        masks[0][0:60, 0:200] = 255  # 30% coverage
        masks[1][60:120, 0:200] = 255  # 30% coverage
        masks[2][120:200, 0:200] = 255  # 40% coverage

        with patch.object(
            isolator, "_run_sam", new_callable=AsyncMock, return_value=masks
        ):
            results = await isolator.segment(
                str(canon_image_file),
                manifest,
                session_id="test-session",
            )

        # Should produce one ObjectCanon per object
        assert len(results) == 3
        for result in results:
            assert isinstance(result, ObjectCanon)
            assert result.provenance == "raw_segmentation"
            assert result.mask_coverage > MIN_COVERAGE_THRESHOLD
            assert result.approved is False
            assert Path(result.image_path).exists()

    @pytest.mark.asyncio
    async def test_segment_skips_failed_quality_gate(
        self,
        canon_image_file: Path,
        manifest: list[ManifestObject],
        tmp_path: Path,
    ):
        """segment() skips objects whose masks fail quality gate. (Req 9.3)"""
        isolator = ObjectIsolator(output_dir=tmp_path / "out")

        # 1 good mask, 2 tiny masks (< 1% coverage on 200x200)
        masks = [
            np.zeros((200, 200), dtype=np.uint8),  # Large (30%)
            np.zeros((200, 200), dtype=np.uint8),  # Tiny (< 1%)
            np.zeros((200, 200), dtype=np.uint8),  # Tiny (< 1%)
        ]
        masks[0][0:60, 0:200] = 255  # 30%
        masks[1][0:2, 0:2] = 255  # 4 pixels on 200x200 = 0.01%
        masks[2][0:1, 0:3] = 255  # 3 pixels = 0.0075%

        with patch.object(
            isolator, "_run_sam", new_callable=AsyncMock, return_value=masks
        ):
            results = await isolator.segment(
                str(canon_image_file),
                manifest,
                session_id="test-session",
            )

        # Only 1 object should pass quality gate
        assert len(results) == 1
        assert results[0].mask_coverage > MIN_COVERAGE_THRESHOLD

    @pytest.mark.asyncio
    async def test_segment_maps_uuids_correctly(
        self,
        canon_image_file: Path,
        manifest: list[ManifestObject],
        tmp_path: Path,
    ):
        """Each ObjectCanon has the correct object_id from manifest. (Req 9.2)"""
        isolator = ObjectIsolator(output_dir=tmp_path / "out")

        masks = [
            np.zeros((200, 200), dtype=np.uint8),
            np.zeros((200, 200), dtype=np.uint8),
            np.zeros((200, 200), dtype=np.uint8),
        ]
        masks[0][0:60, 0:200] = 255
        masks[1][60:120, 0:200] = 255
        masks[2][120:200, 0:200] = 255

        with patch.object(
            isolator, "_run_sam", new_callable=AsyncMock, return_value=masks
        ):
            results = await isolator.segment(
                str(canon_image_file),
                manifest,
                session_id="test-session",
            )

        # All result IDs should be from the manifest
        result_ids = {r.object_id for r in results}
        manifest_ids = {o.id for o in manifest}
        assert result_ids.issubset(manifest_ids)

    @pytest.mark.asyncio
    async def test_segment_output_files_in_session_dir(
        self,
        canon_image_file: Path,
        manifest: list[ManifestObject],
        tmp_path: Path,
    ):
        """Output files are stored in output/objects/{session_id}/."""
        isolator = ObjectIsolator(output_dir=tmp_path / "out")

        masks = [
            np.zeros((200, 200), dtype=np.uint8),
            np.zeros((200, 200), dtype=np.uint8),
            np.zeros((200, 200), dtype=np.uint8),
        ]
        masks[0][0:60, 0:200] = 255
        masks[1][60:120, 0:200] = 255
        masks[2][120:200, 0:200] = 255

        with patch.object(
            isolator, "_run_sam", new_callable=AsyncMock, return_value=masks
        ):
            results = await isolator.segment(
                str(canon_image_file),
                manifest,
                session_id="my-session",
            )

        for result in results:
            path = Path(result.image_path)
            assert "my-session" in str(path)
            assert path.suffix == ".png"


# ─── Tests: Inpainting Stub ────────────────────────────────────────────────────


class TestInpaintingStub:
    """Tests for the stubbed inpainting interface."""

    def test_returns_same_object_canon(self):
        """Stub returns the input ObjectCanon unchanged."""
        isolator = ObjectIsolator()
        canon = ObjectCanon(
            object_id="test-id",
            object_name="test object",
            image_path="/tmp/test.png",
            mask_coverage=0.25,
            approved=False,
            provenance="raw_segmentation",
        )
        result = isolator.complete_inpainting(canon)
        assert result == canon

    def test_preserves_all_fields(self):
        """Stub preserves all ObjectCanon fields."""
        isolator = ObjectIsolator()
        canon = ObjectCanon(
            object_id="uuid-123",
            object_name="coffee maker",
            image_path="/output/objects/session/uuid-123.png",
            mask_coverage=0.15,
            approved=True,
            provenance="raw_segmentation",
        )
        result = isolator.complete_inpainting(canon)
        assert result.object_id == "uuid-123"
        assert result.object_name == "coffee maker"
        assert result.image_path == "/output/objects/session/uuid-123.png"
        assert result.mask_coverage == 0.15
        assert result.provenance == "raw_segmentation"


# ─── Tests: Region Separation ───────────────────────────────────────────────────


class TestRegionSeparation:
    """Tests for _separate_regions method."""

    def test_binary_mask_returns_one(self):
        """A simple binary mask returns a single mask."""
        isolator = ObjectIsolator()
        binary = np.zeros((100, 100), dtype=np.uint8)
        binary[10:50, 10:50] = 255
        result = isolator._separate_regions(binary)
        assert len(result) == 1

    def test_multi_label_separates(self):
        """Multi-label composite returns one mask per label."""
        isolator = ObjectIsolator()
        labels = np.zeros((100, 100), dtype=np.uint8)
        labels[0:30, 0:100] = 50  # Label 1 (30%)
        labels[30:60, 0:100] = 100  # Label 2 (30%)
        labels[60:100, 0:100] = 200  # Label 3 (40%)
        result = isolator._separate_regions(labels)
        assert len(result) == 3

    def test_empty_returns_none(self):
        """All-zero image returns empty list."""
        isolator = ObjectIsolator()
        empty = np.zeros((100, 100), dtype=np.uint8)
        result = isolator._separate_regions(empty)
        assert result == []

    def test_filters_tiny_regions(self):
        """Regions below MIN_COVERAGE_THRESHOLD are filtered out."""
        isolator = ObjectIsolator()
        labels = np.zeros((100, 100), dtype=np.uint8)
        labels[0:50, 0:100] = 128  # 50% — should pass
        labels[99, 99] = 200  # 1 pixel = 0.01% — should be filtered
        result = isolator._separate_regions(labels)
        # Only the large region should remain
        assert len(result) == 1
