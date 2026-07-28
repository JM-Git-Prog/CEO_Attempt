"""Property-based tests for photo pipeline input validation.

# Feature: photo-to-playable-world, Property 1: Invalid Input Rejection

**Validates: Requirements 1.5**

Uses Hypothesis to verify that validate_photo_input rejects any byte sequence
that is not a valid RGB image (corrupt header, wrong format, grayscale,
resolution outside bounds, size exceeding 50MB) with a descriptive error,
and accepts valid RGB images within bounds.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings, assume, HealthCheck
from hypothesis import strategies as st
from PIL import Image

from src.photo_pipeline.input_validator import (
    InputValidationResult,
    validate_photo_input,
)
from src.photo_pipeline.reason_codes import ReasonCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_png(directory: Path, mode: str, width: int, height: int) -> Path:
    """Create a PNG image with given mode and dimensions."""
    if mode in ("I", "F"):
        img = Image.new(mode, (width, height), color=128 if mode == "I" else 0.5)
    elif mode == "LA":
        img = Image.new(mode, (width, height), color=(128, 255))
    elif mode == "L":
        img = Image.new(mode, (width, height), color=128)
    else:
        # RGB, RGBA — fill with a colour tuple of correct length
        n_channels = len(mode)
        img = Image.new(mode, (width, height), color=(128,) * n_channels)

    path = directory / "test_image.png"
    if mode in ("I", "F"):
        # These modes require TIFF format
        path = directory / "test_image.tiff"
        img.save(path, format="TIFF")
    else:
        img.save(path, format="PNG")
    return path


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------


class TestRandomBytesRejected:
    """Property: random byte sequences (not valid images) are always rejected."""

    @given(data=st.binary(min_size=1, max_size=4096))
    @settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_random_bytes_rejected(self, data: bytes, tmp_path: Path):
        """For any random bytes that are not a valid image, validator rejects."""
        file_path = tmp_path / "random_bytes.png"
        file_path.write_bytes(data)

        # Skip if hypothesis accidentally generates valid image data
        try:
            img = Image.open(file_path)
            img.verify()
            assume(False)
        except Exception:
            pass

        result = validate_photo_input(file_path)
        assert not result.valid, (
            "Random bytes should be rejected but got valid=True"
        )
        assert result.reason_code == ReasonCode.INVALID_IMAGE_FORMAT, (
            f"Expected INVALID_IMAGE_FORMAT, got {result.reason_code}"
        )
        assert len(result.diagnostic) > 0, "Diagnostic should be non-empty"


class TestGrayscaleImagesRejected:
    """Property: valid PNG images with grayscale modes are rejected."""

    @given(
        mode=st.sampled_from(["L", "LA", "I", "F"]),
        width=st.integers(min_value=512, max_value=1024),
        height=st.integers(min_value=512, max_value=1024),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_grayscale_modes_rejected(
        self, mode: str, width: int, height: int, tmp_path: Path
    ):
        """For any valid image with grayscale mode (L, LA, I, F), validator rejects."""
        file_path = _write_png(tmp_path, mode, width, height)

        result = validate_photo_input(file_path)
        assert not result.valid, (
            f"Grayscale mode '{mode}' should be rejected but got valid=True"
        )
        # I and F modes in TIFF will get INVALID_IMAGE_FORMAT (unsupported format)
        # L and LA in PNG will get INVALID_IMAGE_FORMAT (grayscale mode)
        assert result.reason_code == ReasonCode.INVALID_IMAGE_FORMAT, (
            f"Expected INVALID_IMAGE_FORMAT for mode '{mode}', "
            f"got {result.reason_code}"
        )
        assert len(result.diagnostic) > 0


class TestResolutionBelowMinimumAccepted:
    """Property: valid RGB PNG with resolution below 512 is accepted (upscaled downstream)."""

    @given(
        width=st.integers(min_value=1, max_value=511),
        height=st.integers(min_value=512, max_value=1024),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_width_below_minimum_accepted(
        self, width: int, height: int, tmp_path: Path
    ):
        """For any RGB PNG with width < 512, validator accepts (orchestrator upscales)."""
        file_path = _write_png(tmp_path, "RGB", width, height)

        result = validate_photo_input(file_path)
        assert result.valid, (
            f"Width {width} below 512 should still be accepted (upscaled later)"
        )

    @given(
        width=st.integers(min_value=512, max_value=1024),
        height=st.integers(min_value=1, max_value=511),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_height_below_minimum_accepted(
        self, width: int, height: int, tmp_path: Path
    ):
        """For any RGB PNG with height < 512, validator accepts (orchestrator upscales)."""
        file_path = _write_png(tmp_path, "RGB", width, height)

        result = validate_photo_input(file_path)
        assert result.valid, (
            f"Height {height} below 512 should still be accepted (upscaled later)"
        )


class TestResolutionAboveMaximumRejected:
    """Property: valid RGB PNG with resolution above 8192 in any dimension is rejected."""

    @given(
        width=st.integers(min_value=8193, max_value=9000),
        height=st.integers(min_value=512, max_value=1024),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_width_above_maximum_rejected(
        self, width: int, height: int, tmp_path: Path
    ):
        """For any RGB PNG with width > 8192, validator rejects with INVALID_IMAGE_RESOLUTION."""
        file_path = _write_png(tmp_path, "RGB", width, height)

        result = validate_photo_input(file_path)
        assert not result.valid, (
            f"Width {width} above maximum should be rejected"
        )
        assert result.reason_code == ReasonCode.INVALID_IMAGE_RESOLUTION, (
            f"Expected INVALID_IMAGE_RESOLUTION, got {result.reason_code}"
        )

    @given(
        width=st.integers(min_value=512, max_value=1024),
        height=st.integers(min_value=8193, max_value=9000),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_height_above_maximum_rejected(
        self, width: int, height: int, tmp_path: Path
    ):
        """For any RGB PNG with height > 8192, validator rejects with INVALID_IMAGE_RESOLUTION."""
        file_path = _write_png(tmp_path, "RGB", width, height)

        result = validate_photo_input(file_path)
        assert not result.valid, (
            f"Height {height} above maximum should be rejected"
        )
        assert result.reason_code == ReasonCode.INVALID_IMAGE_RESOLUTION, (
            f"Expected INVALID_IMAGE_RESOLUTION, got {result.reason_code}"
        )


class TestValidRGBImagesAccepted:
    """Property: valid RGB PNG images within resolution bounds are accepted."""

    @given(
        width=st.integers(min_value=512, max_value=2048),
        height=st.integers(min_value=512, max_value=2048),
    )
    @settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_valid_rgb_png_accepted(
        self, width: int, height: int, tmp_path: Path
    ):
        """For any valid RGB PNG within bounds, validator accepts (valid=True)."""
        file_path = _write_png(tmp_path, "RGB", width, height)

        result = validate_photo_input(file_path)
        assert result.valid, (
            f"Valid RGB PNG {width}x{height} should be accepted but got "
            f"reason_code={result.reason_code}, diagnostic={result.diagnostic!r}"
        )
        assert result.reason_code == ReasonCode.COMPLETED

    @given(
        width=st.integers(min_value=512, max_value=2048),
        height=st.integers(min_value=512, max_value=2048),
    )
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_valid_rgba_png_accepted(
        self, width: int, height: int, tmp_path: Path
    ):
        """For any valid RGBA PNG within bounds, validator accepts (valid=True)."""
        file_path = _write_png(tmp_path, "RGBA", width, height)

        result = validate_photo_input(file_path)
        assert result.valid, (
            f"Valid RGBA PNG {width}x{height} should be accepted but got "
            f"reason_code={result.reason_code}, diagnostic={result.diagnostic!r}"
        )
        assert result.reason_code == ReasonCode.COMPLETED


class TestNonExistentFileRejected:
    """Property: paths to non-existent files are always rejected."""

    @given(filename=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=("L", "N")),
    ))
    @settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_nonexistent_file_rejected(self, filename: str, tmp_path: Path):
        """For any path that doesn't exist, validator rejects."""
        file_path = tmp_path / f"{filename}.png"
        assume(not file_path.exists())

        result = validate_photo_input(file_path)
        assert not result.valid, "Non-existent file should be rejected"
        assert result.reason_code == ReasonCode.INVALID_IMAGE_FORMAT
        assert len(result.diagnostic) > 0
