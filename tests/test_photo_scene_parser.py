"""Property-based tests for photo pipeline scene parser.

# Feature: photo-to-playable-world, Property 3: Object PNG Extraction Produces Correct Transparency

**Validates: Requirements 2.4**

Uses Hypothesis to verify that extract_object_png produces RGBA images with:
- RGBA format (4 channels)
- Identical width and height to the source
- Alpha == 0 exactly where mask == 0
- Alpha == 255 exactly where mask > 0
- RGB channels matching the source where mask > 0
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from PIL import Image

from src.photo_pipeline.stages.scene_parser import extract_object_png


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def rgb_image_and_mask(draw: st.DrawFn):
    """Generate a random RGB image and a matching binary mask.

    Produces:
    - source_image: uint8 array of shape (H, W, 3), random pixel values
    - mask: uint8 array of shape (H, W), values are 0 or 255
    """
    height = draw(st.integers(min_value=32, max_value=128))
    width = draw(st.integers(min_value=32, max_value=128))

    source_image = draw(
        arrays(
            dtype=np.uint8,
            shape=(height, width, 3),
            elements=st.integers(min_value=0, max_value=255),
        )
    )

    mask = draw(
        arrays(
            dtype=np.uint8,
            shape=(height, width),
            elements=st.sampled_from([0, 255]),
        )
    )

    return source_image, mask


# ---------------------------------------------------------------------------
# Test Class
# ---------------------------------------------------------------------------


class TestObjectPngExtractionTransparency:
    """Property 3: Object PNG Extraction Produces Correct Transparency.

    For any source RGB image and any binary mask of matching dimensions,
    the extracted Object_PNG SHALL have RGBA format, identical width and
    height to the source, and transparent (alpha=0) pixels exactly where
    the mask value is 0.
    """

    @given(data=rgb_image_and_mask())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_output_is_valid_rgba_png(
        self, data: tuple[np.ndarray, np.ndarray], tmp_path: Path
    ):
        """Output file is a valid PNG with RGBA mode."""
        source_image, mask = data
        output_path = tmp_path / "obj_test.png"

        result_path = extract_object_png(source_image, mask, output_path)

        assert result_path.exists(), "Output PNG was not created"
        img = Image.open(result_path)
        assert img.mode == "RGBA", f"Expected RGBA mode, got {img.mode}"

    @given(data=rgb_image_and_mask())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_output_dimensions_match_source(
        self, data: tuple[np.ndarray, np.ndarray], tmp_path: Path
    ):
        """Output dimensions match source dimensions (H, W)."""
        source_image, mask = data
        h, w = source_image.shape[:2]
        output_path = tmp_path / "obj_test.png"

        extract_object_png(source_image, mask, output_path)

        img = Image.open(output_path)
        # PIL size is (width, height)
        assert img.size == (w, h), (
            f"Expected size ({w}, {h}), got {img.size}"
        )

    @given(data=rgb_image_and_mask())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_alpha_zero_where_mask_zero(
        self, data: tuple[np.ndarray, np.ndarray], tmp_path: Path
    ):
        """Alpha channel == 0 exactly where mask == 0."""
        source_image, mask = data
        output_path = tmp_path / "obj_test.png"

        extract_object_png(source_image, mask, output_path)

        img = Image.open(output_path)
        output_array = np.array(img)
        alpha = output_array[:, :, 3]

        # Where mask is 0, alpha must be 0
        mask_zero = mask == 0
        assert np.all(alpha[mask_zero] == 0), (
            "Alpha should be 0 where mask is 0, but found non-zero alpha pixels"
        )

    @given(data=rgb_image_and_mask())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_alpha_255_where_mask_nonzero(
        self, data: tuple[np.ndarray, np.ndarray], tmp_path: Path
    ):
        """Alpha channel == 255 exactly where mask > 0."""
        source_image, mask = data
        output_path = tmp_path / "obj_test.png"

        extract_object_png(source_image, mask, output_path)

        img = Image.open(output_path)
        output_array = np.array(img)
        alpha = output_array[:, :, 3]

        # Where mask is nonzero, alpha must be 255
        mask_nonzero = mask > 0
        assert np.all(alpha[mask_nonzero] == 255), (
            "Alpha should be 255 where mask > 0, but found non-255 alpha pixels"
        )

    @given(data=rgb_image_and_mask())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_rgb_matches_source_where_mask_nonzero(
        self, data: tuple[np.ndarray, np.ndarray], tmp_path: Path
    ):
        """RGB channels in output match source where mask > 0."""
        source_image, mask = data
        output_path = tmp_path / "obj_test.png"

        extract_object_png(source_image, mask, output_path)

        img = Image.open(output_path)
        output_array = np.array(img)
        output_rgb = output_array[:, :, :3]

        # Where mask is nonzero, RGB must match source
        mask_nonzero = mask > 0
        assert np.all(output_rgb[mask_nonzero] == source_image[mask_nonzero]), (
            "RGB channels should match source where mask > 0"
        )
