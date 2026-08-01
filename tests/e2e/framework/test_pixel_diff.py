"""Unit tests for the pixel_diff module.

Tests cover:
- Basic comparison with identical images (pass)
- Comparison with differing images (fail when over threshold)
- Per-stage threshold configuration
- Diff image generation on failure
- Image size mismatch error handling
- Structured result fields

Requirements: 3.1, 3.2, 3.4
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tests.e2e.framework.pixel_diff import (
    DEFAULT_STAGE_THRESHOLDS,
    ImageSizeMismatchError,
    PixelDiff,
    PixelDiffError,
    PixelDiffResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_solid_image(
    width: int = 100,
    height: int = 100,
    color: tuple[int, int, int, int] = (128, 128, 128, 255),
) -> Image.Image:
    """Create a solid color RGBA image."""
    img = Image.new("RGBA", (width, height), color)
    return img


def _make_image_with_diff(
    width: int = 100,
    height: int = 100,
    base_color: tuple[int, int, int, int] = (128, 128, 128, 255),
    diff_color: tuple[int, int, int, int] = (255, 0, 0, 255),
    diff_pixel_count: int = 10,
) -> tuple[Image.Image, Image.Image]:
    """Create a pair of images with a known number of differing pixels.

    Returns:
        Tuple of (expected, actual) where actual has diff_pixel_count pixels
        changed to diff_color.
    """
    expected = _make_solid_image(width, height, base_color)
    actual = expected.copy()

    # Change pixels starting from top-left, row by row
    pixels = actual.load()
    changed = 0
    for y in range(height):
        for x in range(width):
            if changed >= diff_pixel_count:
                break
            pixels[x, y] = diff_color
            changed += 1
        if changed >= diff_pixel_count:
            break

    return expected, actual


# ---------------------------------------------------------------------------
# Tests: Basic comparison
# ---------------------------------------------------------------------------


class TestPixelDiffIdenticalImages:
    """Tests that identical images always pass."""

    def test_identical_images_pass(self):
        """Identical images should produce 0% diff and pass."""
        differ = PixelDiff()
        img = _make_solid_image(50, 50)

        result = differ.compare(img, img.copy(), stage_name="canon")

        assert result.passed is True
        assert result.diff_pixel_count == 0
        assert result.diff_percentage == 0.0
        assert result.diff_image_path is None
        assert result.total_pixels == 50 * 50

    def test_identical_rgb_images_pass(self):
        """RGB images (not RGBA) should be handled correctly."""
        differ = PixelDiff()
        img = Image.new("RGB", (100, 100), (128, 128, 128))

        result = differ.compare(img, img.copy(), stage_name="world")

        assert result.passed is True
        assert result.diff_pixel_count == 0


class TestPixelDiffDifferingImages:
    """Tests that differing images are detected correctly."""

    def test_single_pixel_diff_detected(self):
        """A single differing pixel should be counted."""
        differ = PixelDiff()
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=1
        )

        result = differ.compare(expected, actual, stage_name="canon")

        assert result.diff_pixel_count == 1
        assert result.total_pixels == 10000
        # 1/10000 = 0.01% which is < 0.1% threshold for canon
        assert result.passed is True

    def test_exceeding_threshold_fails(self):
        """Exceeding the threshold percentage should fail."""
        differ = PixelDiff()
        # Canon threshold is 0.1%, so 11/10000 = 0.11% should fail
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=11
        )

        result = differ.compare(expected, actual, stage_name="canon")

        assert result.diff_pixel_count == 11
        assert result.diff_percentage == pytest.approx(0.11, abs=0.001)
        assert result.passed is False

    def test_at_threshold_passes(self):
        """Exactly at threshold should pass (<=)."""
        differ = PixelDiff()
        # Canon threshold is 0.1%, so 10/10000 = 0.1% should pass exactly
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=10
        )

        result = differ.compare(expected, actual, stage_name="canon")

        assert result.diff_pixel_count == 10
        assert result.diff_percentage == pytest.approx(0.1, abs=0.001)
        assert result.passed is True

    def test_dream_preview_higher_threshold(self):
        """Dream_preview allows 1.0% diff - more lenient."""
        differ = PixelDiff()
        # 100/10000 = 1.0% should pass for dream_preview
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=100
        )

        result = differ.compare(expected, actual, stage_name="dream_preview")

        assert result.diff_pixel_count == 100
        assert result.diff_percentage == pytest.approx(1.0, abs=0.001)
        assert result.passed is True

    def test_dream_preview_over_threshold_fails(self):
        """Dream_preview at 1.01% should fail."""
        differ = PixelDiff()
        # 101/10000 = 1.01% should fail for dream_preview
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=101
        )

        result = differ.compare(expected, actual, stage_name="dream_preview")

        assert result.diff_pixel_count == 101
        assert result.passed is False


# ---------------------------------------------------------------------------
# Tests: Per-stage threshold configuration
# ---------------------------------------------------------------------------


class TestPixelDiffThresholds:
    """Tests for per-stage threshold configuration."""

    def test_default_thresholds(self):
        """Default thresholds match the spec (0.1% for Canon/World, 1.0% for Dream/Blockout)."""
        differ = PixelDiff()
        thresholds = differ.stage_thresholds

        assert thresholds["canon"] == 0.1
        assert thresholds["world"] == 0.1
        assert thresholds["dream_preview"] == 1.0
        assert thresholds["blockout"] == 1.0

    def test_custom_thresholds_override(self):
        """Custom thresholds override defaults."""
        differ = PixelDiff(stage_thresholds={"canon": 0.5, "custom_stage": 2.0})
        thresholds = differ.stage_thresholds

        assert thresholds["canon"] == 0.5  # Overridden
        assert thresholds["world"] == 0.1  # Default preserved
        assert thresholds["custom_stage"] == 2.0  # New stage added

    def test_unknown_stage_uses_default(self):
        """Unknown stage names fall back to 0.1% default."""
        differ = PixelDiff()
        threshold = differ.get_threshold("unknown_stage")
        assert threshold == 0.1

    def test_get_threshold_returns_correct_value(self):
        """get_threshold returns the configured value for known stages."""
        differ = PixelDiff(stage_thresholds={"my_stage": 3.5})
        assert differ.get_threshold("my_stage") == 3.5
        assert differ.get_threshold("canon") == 0.1


# ---------------------------------------------------------------------------
# Tests: Diff image generation
# ---------------------------------------------------------------------------


class TestPixelDiffDiffImage:
    """Tests for diff image generation on failure."""

    def test_diff_image_generated_on_failure(self, tmp_path: Path):
        """A diff image should be generated when comparison fails."""
        differ = PixelDiff()
        # 20/10000 = 0.2% > 0.1% canon threshold
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=20
        )

        result = differ.compare(
            expected,
            actual,
            stage_name="canon",
            diff_output_dir=tmp_path,
        )

        assert result.passed is False
        assert result.diff_image_path is not None
        assert result.diff_image_path.exists()
        assert result.diff_image_path.name == "diff_canon.png"

        # Verify the diff image is a valid PNG
        diff_img = Image.open(result.diff_image_path)
        assert diff_img.size == (100, 100)

    def test_diff_image_not_generated_on_pass(self, tmp_path: Path):
        """No diff image on pass, even with output dir specified."""
        differ = PixelDiff()
        img = _make_solid_image(100, 100)

        result = differ.compare(
            img,
            img.copy(),
            stage_name="canon",
            diff_output_dir=tmp_path,
        )

        assert result.passed is True
        assert result.diff_image_path is None

    def test_diff_image_not_generated_without_output_dir(self):
        """No diff image generated when diff_output_dir is None."""
        differ = PixelDiff()
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=20
        )

        result = differ.compare(
            expected,
            actual,
            stage_name="canon",
            diff_output_dir=None,
        )

        assert result.passed is False
        assert result.diff_image_path is None

    def test_custom_diff_filename(self, tmp_path: Path):
        """Custom diff filename is respected."""
        differ = PixelDiff()
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=20
        )

        result = differ.compare(
            expected,
            actual,
            stage_name="canon",
            diff_output_dir=tmp_path,
            diff_filename="my_custom_diff.png",
        )

        assert result.diff_image_path is not None
        assert result.diff_image_path.name == "my_custom_diff.png"

    def test_diff_image_highlights_changed_pixels(self, tmp_path: Path):
        """Diff image should have magenta pixels where differences exist."""
        differ = PixelDiff()
        # Create images with 5 pixels different at top-left
        expected, actual = _make_image_with_diff(
            width=10, height=10, diff_pixel_count=5
        )

        result = differ.compare(
            expected,
            actual,
            stage_name="canon",
            diff_output_dir=tmp_path,
        )

        assert result.diff_image_path is not None
        diff_img = Image.open(result.diff_image_path).convert("RGBA")
        pixels = diff_img.load()

        # First 5 pixels in top row should be magenta (255, 0, 255, 255)
        for x in range(5):
            assert pixels[x, 0] == (255, 0, 255, 255), f"Pixel ({x}, 0) not magenta"

    def test_diff_output_dir_created_if_missing(self, tmp_path: Path):
        """diff_output_dir is created if it doesn't exist."""
        differ = PixelDiff()
        expected, actual = _make_image_with_diff(
            width=100, height=100, diff_pixel_count=20
        )
        nested_dir = tmp_path / "nested" / "path"

        result = differ.compare(
            expected,
            actual,
            stage_name="canon",
            diff_output_dir=nested_dir,
        )

        assert nested_dir.exists()
        assert result.diff_image_path is not None
        assert result.diff_image_path.exists()


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


class TestPixelDiffErrors:
    """Tests for error handling."""

    def test_size_mismatch_raises_error(self):
        """Different sized images should raise ImageSizeMismatchError."""
        differ = PixelDiff()
        img_a = _make_solid_image(100, 100)
        img_b = _make_solid_image(200, 100)

        with pytest.raises(ImageSizeMismatchError) as exc_info:
            differ.compare(img_a, img_b, stage_name="canon")

        assert exc_info.value.expected_size == (100, 100)
        assert exc_info.value.actual_size == (200, 100)
        assert "100x100" in str(exc_info.value)
        assert "200x100" in str(exc_info.value)

    def test_height_mismatch_raises_error(self):
        """Different height should also raise ImageSizeMismatchError."""
        differ = PixelDiff()
        img_a = _make_solid_image(100, 100)
        img_b = _make_solid_image(100, 200)

        with pytest.raises(ImageSizeMismatchError):
            differ.compare(img_a, img_b, stage_name="canon")


# ---------------------------------------------------------------------------
# Tests: compare_files convenience method
# ---------------------------------------------------------------------------


class TestPixelDiffCompareFiles:
    """Tests for the compare_files file-loading convenience method."""

    def test_compare_files_identical(self, tmp_path: Path):
        """Loading identical files should pass."""
        differ = PixelDiff()
        img = _make_solid_image(50, 50)
        path_a = tmp_path / "baseline.png"
        path_b = tmp_path / "actual.png"
        img.save(path_a)
        img.save(path_b)

        result = differ.compare_files(path_a, path_b, stage_name="world")

        assert result.passed is True
        assert result.diff_pixel_count == 0

    def test_compare_files_missing_raises_error(self, tmp_path: Path):
        """Missing file should raise PixelDiffError."""
        differ = PixelDiff()
        path_a = tmp_path / "does_not_exist.png"
        path_b = tmp_path / "also_missing.png"

        with pytest.raises(PixelDiffError, match="Failed to load expected"):
            differ.compare_files(path_a, path_b, stage_name="canon")


# ---------------------------------------------------------------------------
# Tests: Structured result fields
# ---------------------------------------------------------------------------


class TestPixelDiffResultStructure:
    """Tests verifying PixelDiffResult has all required fields."""

    def test_result_is_dataclass(self):
        """PixelDiffResult should be a frozen dataclass."""
        result = PixelDiffResult(
            diff_pixel_count=5,
            diff_percentage=0.05,
            passed=True,
            diff_image_path=None,
            total_pixels=10000,
        )
        assert result.diff_pixel_count == 5
        assert result.diff_percentage == 0.05
        assert result.passed is True
        assert result.diff_image_path is None
        assert result.total_pixels == 10000

    def test_result_total_pixels_computed_correctly(self):
        """total_pixels should equal width * height."""
        differ = PixelDiff()
        img = _make_solid_image(200, 150)

        result = differ.compare(img, img.copy(), stage_name="canon")

        assert result.total_pixels == 200 * 150


# ---------------------------------------------------------------------------
# Tests: Pixel tolerance
# ---------------------------------------------------------------------------


class TestPixelDiffTolerance:
    """Tests for per-channel pixel tolerance."""

    def test_within_tolerance_passes(self):
        """Small differences within tolerance should not count as diffs."""
        differ = PixelDiff(pixel_tolerance=5)
        expected = _make_solid_image(10, 10, (128, 128, 128, 255))
        # Differ by only 3 in red channel - within tolerance of 5
        actual = _make_solid_image(10, 10, (131, 128, 128, 255))

        result = differ.compare(expected, actual, stage_name="canon")

        assert result.diff_pixel_count == 0
        assert result.passed is True

    def test_exceeding_tolerance_counts(self):
        """Differences exceeding tolerance should be counted."""
        differ = PixelDiff(pixel_tolerance=5)
        expected = _make_solid_image(10, 10, (128, 128, 128, 255))
        # Differ by 6 in red channel - exceeds tolerance of 5
        actual = _make_solid_image(10, 10, (134, 128, 128, 255))

        result = differ.compare(expected, actual, stage_name="canon")

        assert result.diff_pixel_count == 100  # All 10x10 pixels differ
