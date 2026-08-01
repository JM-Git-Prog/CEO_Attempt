"""Pixel-level image comparison module for visual regression testing.

Wraps pixel comparison (pixelmatch Python package if available, otherwise a
Pillow-based implementation) to compare expected baselines against actual
screenshots. Supports per-stage threshold configuration and generates diff
images highlighting changed pixels on failure.

Requirements: 3.1, 3.2, 3.4
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PixelDiffResult:
    """Structured result of a pixel-level image comparison.

    Attributes:
        diff_pixel_count: Number of pixels that differ beyond the threshold.
        diff_percentage: Percentage of total pixels that differ (0.0–100.0).
        passed: Whether the comparison passed (diff_percentage <= threshold).
        diff_image_path: Path to the generated diff image, only set on failure.
        total_pixels: Total number of pixels in the compared images.
    """

    diff_pixel_count: int
    diff_percentage: float
    passed: bool
    diff_image_path: Path | None
    total_pixels: int


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PixelDiffError(Exception):
    """Raised when pixel comparison cannot be performed."""


class ImageSizeMismatchError(PixelDiffError):
    """Raised when the two images have different dimensions."""

    def __init__(
        self,
        expected_size: tuple[int, int],
        actual_size: tuple[int, int],
    ) -> None:
        self.expected_size = expected_size
        self.actual_size = actual_size
        super().__init__(
            f"Image size mismatch: expected {expected_size[0]}x{expected_size[1]}, "
            f"got {actual_size[0]}x{actual_size[1]}"
        )


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

# Per-stage default thresholds (percentage of differing pixels allowed).
# Canon and World stages require tighter matching; Dream_Preview and Blockout
# allow more variance due to generative model non-determinism.
DEFAULT_STAGE_THRESHOLDS: dict[str, float] = {
    "canon": 0.1,
    "world": 0.1,
    "dream_preview": 1.0,
    "blockout": 1.0,
}

# Color used to highlight differing pixels in the diff image (magenta).
_DIFF_HIGHLIGHT_COLOR = (255, 0, 255, 255)

# Color for matching pixels in the diff image (semi-transparent gray).
_MATCH_COLOR = (0, 0, 0, 40)

# Per-channel tolerance for individual pixel comparison.
# Two pixels are considered "different" if any channel differs by more than this.
_DEFAULT_PIXEL_TOLERANCE = 0


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class PixelDiff:
    """Pixel-level image comparison engine for visual regression testing.

    Compares two PIL Images pixel-by-pixel, counts differing pixels, and
    determines pass/fail based on a configurable threshold percentage. On
    failure, generates a diff image highlighting changed pixels in magenta.

    Usage:
        differ = PixelDiff(stage_thresholds={"canon": 0.1, "world": 0.1})
        result = differ.compare(
            expected=baseline_image,
            actual=screenshot_image,
            stage_name="canon",
            diff_output_dir=Path("artifacts/visual/"),
        )
        if not result.passed:
            print(f"FAIL: {result.diff_percentage:.3f}% pixels differ")
            print(f"Diff image: {result.diff_image_path}")
    """

    def __init__(
        self,
        stage_thresholds: dict[str, float] | None = None,
        pixel_tolerance: int = _DEFAULT_PIXEL_TOLERANCE,
    ) -> None:
        """Initialize the pixel diff engine.

        Args:
            stage_thresholds: Per-stage threshold configuration mapping stage
                name to max allowed diff percentage. Falls back to
                DEFAULT_STAGE_THRESHOLDS for unlisted stages.
            pixel_tolerance: Per-channel tolerance for pixel comparison.
                Two pixels are "different" if any channel differs by more
                than this value. Default 0 (exact match).
        """
        self._stage_thresholds = dict(DEFAULT_STAGE_THRESHOLDS)
        if stage_thresholds:
            self._stage_thresholds.update(stage_thresholds)
        self._pixel_tolerance = pixel_tolerance

    @property
    def stage_thresholds(self) -> dict[str, float]:
        """Current per-stage threshold configuration."""
        return dict(self._stage_thresholds)

    def get_threshold(self, stage_name: str) -> float:
        """Get the threshold for a specific stage.

        Args:
            stage_name: Pipeline stage name (e.g. "canon", "dream_preview").

        Returns:
            The threshold percentage for the stage. Returns 0.1 as default
            if the stage is not in the configured thresholds.
        """
        return self._stage_thresholds.get(stage_name, 0.1)

    def compare(
        self,
        expected: Image.Image,
        actual: Image.Image,
        stage_name: str,
        diff_output_dir: Path | None = None,
        diff_filename: str | None = None,
    ) -> PixelDiffResult:
        """Compare two images and return a structured diff result.

        Performs pixel-by-pixel comparison between the expected baseline and
        the actual screenshot. If the diff percentage exceeds the stage's
        configured threshold, generates a diff image highlighting changes.

        Args:
            expected: The golden baseline image (PNG loaded as PIL Image).
            actual: The captured screenshot to compare against baseline.
            stage_name: Pipeline stage name for threshold lookup.
            diff_output_dir: Directory to write the diff image on failure.
                If None, no diff image is generated (diff_image_path will
                be None even on failure).
            diff_filename: Optional custom filename for the diff image.
                Defaults to "diff_{stage_name}.png".

        Returns:
            PixelDiffResult with comparison metrics and pass/fail status.

        Raises:
            ImageSizeMismatchError: If the images have different dimensions.
            PixelDiffError: If the images cannot be compared (e.g. invalid mode).
        """
        # Validate image dimensions match
        if expected.size != actual.size:
            raise ImageSizeMismatchError(
                expected_size=expected.size,
                actual_size=actual.size,
            )

        # Convert both images to RGBA for consistent comparison
        expected_rgba = expected.convert("RGBA")
        actual_rgba = actual.convert("RGBA")

        # Convert to numpy arrays for efficient comparison
        expected_arr = np.array(expected_rgba, dtype=np.int16)
        actual_arr = np.array(actual_rgba, dtype=np.int16)

        # Compute per-pixel channel differences
        channel_diff = np.abs(expected_arr - actual_arr)

        # A pixel is "different" if ANY channel exceeds the tolerance
        diff_mask = np.any(channel_diff > self._pixel_tolerance, axis=2)

        # Count differing pixels
        diff_pixel_count = int(np.sum(diff_mask))
        total_pixels = expected_rgba.width * expected_rgba.height
        diff_percentage = (diff_pixel_count / total_pixels) * 100.0 if total_pixels > 0 else 0.0

        # Determine pass/fail based on stage threshold
        threshold = self.get_threshold(stage_name)
        passed = diff_percentage <= threshold

        # Generate diff image on failure (if output dir specified)
        diff_image_path: Path | None = None
        if not passed and diff_output_dir is not None:
            diff_image_path = self._generate_diff_image(
                expected_rgba=expected_rgba,
                actual_rgba=actual_rgba,
                diff_mask=diff_mask,
                output_dir=diff_output_dir,
                filename=diff_filename or f"diff_{stage_name}.png",
            )

        return PixelDiffResult(
            diff_pixel_count=diff_pixel_count,
            diff_percentage=diff_percentage,
            passed=passed,
            diff_image_path=diff_image_path,
            total_pixels=total_pixels,
        )

    def compare_files(
        self,
        expected_path: Path | str,
        actual_path: Path | str,
        stage_name: str,
        diff_output_dir: Path | None = None,
        diff_filename: str | None = None,
    ) -> PixelDiffResult:
        """Compare two image files and return a structured diff result.

        Convenience wrapper around compare() that loads images from file paths.

        Args:
            expected_path: Path to the golden baseline PNG file.
            actual_path: Path to the actual screenshot PNG file.
            stage_name: Pipeline stage name for threshold lookup.
            diff_output_dir: Directory to write the diff image on failure.
            diff_filename: Optional custom filename for the diff image.

        Returns:
            PixelDiffResult with comparison metrics and pass/fail status.

        Raises:
            PixelDiffError: If either file cannot be loaded.
            ImageSizeMismatchError: If the images have different dimensions.
        """
        expected_path = Path(expected_path)
        actual_path = Path(actual_path)

        try:
            expected = Image.open(expected_path)
        except Exception as e:
            raise PixelDiffError(
                f"Failed to load expected baseline image: {expected_path}: {e}"
            ) from e

        try:
            actual = Image.open(actual_path)
        except Exception as e:
            raise PixelDiffError(
                f"Failed to load actual screenshot image: {actual_path}: {e}"
            ) from e

        return self.compare(
            expected=expected,
            actual=actual,
            stage_name=stage_name,
            diff_output_dir=diff_output_dir,
            diff_filename=diff_filename,
        )

    def _generate_diff_image(
        self,
        expected_rgba: Image.Image,
        actual_rgba: Image.Image,
        diff_mask: Any,  # numpy bool array
        output_dir: Path,
        filename: str,
    ) -> Path:
        """Generate a diff image highlighting changed pixels.

        Creates an image where:
        - Differing pixels are highlighted in magenta (255, 0, 255)
        - Matching pixels show a dimmed version of the actual image

        Args:
            expected_rgba: The expected image in RGBA mode.
            actual_rgba: The actual image in RGBA mode.
            diff_mask: Boolean numpy array (H×W) where True = pixel differs.
            output_dir: Directory to save the diff image.
            filename: Filename for the diff image.

        Returns:
            Path to the saved diff image.
        """
        # Create the diff visualization
        actual_arr = np.array(actual_rgba, dtype=np.uint8)

        # Start with a dimmed copy of the actual image
        diff_arr = (actual_arr.astype(np.float32) * 0.3).astype(np.uint8)
        diff_arr[:, :, 3] = 255  # Full opacity

        # Highlight differing pixels in magenta
        diff_arr[diff_mask] = _DIFF_HIGHLIGHT_COLOR

        # Save the diff image
        diff_image = Image.fromarray(diff_arr, mode="RGBA")

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        diff_path = output_dir / filename
        diff_image.save(diff_path, format="PNG")

        return diff_path
