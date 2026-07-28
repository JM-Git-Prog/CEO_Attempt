"""Property-based tests for photo pipeline scale calibrator.

# Feature: photo-to-playable-world

## Property 12: Scale Calibration Produces Clamped Metric Dimensions

**Validates: Requirements 7.1, 7.2**

For any pixel footprint > 0, positive depth value, valid camera FOV (> 0°,
< 180°), and room dimensions, the scale calibrator SHALL produce object
dimensions in meters where each axis is clamped to [0.01, room_dimension_on_that_axis].

Uses Hypothesis to generate:
- Random pixel footprints (1 to 4000 pixels)
- Random depth values (0.01 to 100.0 meters)
- Random FOV values (1.0 to 179.0 degrees)
- Random image dimensions (100 to 8192 pixels)
- Random room dimensions (1.0 to 20.0 meters per axis)
"""

from __future__ import annotations

import math

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.stages.scale_calibrator import (
    pixel_to_meters,
    clamp_dimensions,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random pixel footprints (1 to 4000 pixels)
pixel_footprints = st.floats(min_value=1.0, max_value=4000.0, allow_nan=False, allow_infinity=False)

# Random depth values (0.01 to 100.0 meters)
depth_values = st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False)

# Random FOV values (1.0 to 179.0 degrees)
fov_values = st.floats(min_value=1.0, max_value=179.0, allow_nan=False, allow_infinity=False)

# Random image dimensions (100 to 8192 pixels)
image_dims = st.integers(min_value=100, max_value=8192)

# Random room dimensions (1.0 to 20.0 meters per axis)
room_dim_values = st.floats(min_value=1.0, max_value=20.0, allow_nan=False, allow_infinity=False)


@st.composite
def room_dimensions(draw: st.DrawFn) -> tuple[float, float, float]:
    """Generate random room dimensions (width, height, depth) in meters."""
    w = draw(room_dim_values)
    h = draw(room_dim_values)
    d = draw(room_dim_values)
    return (w, h, d)


@st.composite
def raw_dimensions(draw: st.DrawFn) -> tuple[float, float, float]:
    """Generate raw (unclamped) object dimensions that might be out of bounds.

    Range includes values below the minimum (0.001) and above typical room
    dimensions (up to 50.0) to thoroughly exercise clamping.
    """
    dim_strategy = st.floats(min_value=0.001, max_value=50.0, allow_nan=False, allow_infinity=False)
    w = draw(dim_strategy)
    h = draw(dim_strategy)
    d = draw(dim_strategy)
    return (w, h, d)


# ---------------------------------------------------------------------------
# Property 12: Scale Calibration Produces Clamped Metric Dimensions
# ---------------------------------------------------------------------------


class TestScaleCalibrationClamping:
    """Property 12: Scale Calibration Produces Clamped Metric Dimensions.

    **Validates: Requirements 7.1, 7.2**

    For any pixel footprint > 0, positive depth, valid FOV (0°-180°), and
    room dimensions, output dims are clamped to [0.01, room_dim] per axis.
    """

    @given(
        pixel_size=pixel_footprints,
        depth_m=depth_values,
        fov_deg=fov_values,
        image_dim=image_dims,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_pixel_to_meters_returns_positive_finite(
        self,
        pixel_size: float,
        depth_m: float,
        fov_deg: float,
        image_dim: int,
    ):
        """pixel_to_meters always returns a positive finite float for valid inputs."""
        result = pixel_to_meters(pixel_size, depth_m, fov_deg, image_dim)

        assert result > 0, (
            f"pixel_to_meters returned non-positive: {result} "
            f"(pixel_size={pixel_size}, depth_m={depth_m}, "
            f"fov_deg={fov_deg}, image_dim={image_dim})"
        )
        assert math.isfinite(result), (
            f"pixel_to_meters returned non-finite: {result} "
            f"(pixel_size={pixel_size}, depth_m={depth_m}, "
            f"fov_deg={fov_deg}, image_dim={image_dim})"
        )

    @given(
        dims=raw_dimensions(),
        room_dims=room_dimensions(),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_clamp_dimensions_within_bounds(
        self,
        dims: tuple[float, float, float],
        room_dims: tuple[float, float, float],
    ):
        """clamp_dimensions output has each axis in [0.01, room_dim_on_that_axis]."""
        result = clamp_dimensions(dims, room_dims)

        for i, (clamped_val, room_dim) in enumerate(zip(result, room_dims)):
            axis_name = ["width", "height", "depth"][i]
            upper_bound = max(0.01, room_dim)

            assert clamped_val >= 0.01, (
                f"{axis_name} axis below minimum: {clamped_val} < 0.01 "
                f"(input_dim={dims[i]}, room_dim={room_dim})"
            )
            assert clamped_val <= upper_bound, (
                f"{axis_name} axis above room dimension: {clamped_val} > {upper_bound} "
                f"(input_dim={dims[i]}, room_dim={room_dim})"
            )

    @given(
        pixel_size=pixel_footprints,
        depth_m=depth_values,
        fov_deg=fov_values,
        image_dim=image_dims,
        room_dims=room_dimensions(),
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_combined_calibration_produces_clamped_output(
        self,
        pixel_size: float,
        depth_m: float,
        fov_deg: float,
        image_dim: int,
        room_dims: tuple[float, float, float],
    ):
        """Combined: for any valid inputs, calibrator never produces dimensions outside [0.01, room_dim].

        This test exercises the full path: pixel_to_meters → compute raw dims → clamp.
        """
        # Compute raw dimension on one axis via pixel_to_meters
        raw_dim = pixel_to_meters(pixel_size, depth_m, fov_deg, image_dim)

        # Build raw dimensions tuple (using the heuristic: depth ≈ 60% of width)
        raw_width = raw_dim
        raw_height = raw_dim  # treat same for symmetry in this property test
        raw_depth = raw_dim * 0.6
        raw_dims = (raw_width, raw_height, raw_depth)

        # Clamp
        result = clamp_dimensions(raw_dims, room_dims)

        for i, (clamped_val, room_dim) in enumerate(zip(result, room_dims)):
            axis_name = ["width", "height", "depth"][i]
            upper_bound = max(0.01, room_dim)

            assert 0.01 <= clamped_val <= upper_bound, (
                f"{axis_name} axis out of clamped bounds: {clamped_val} "
                f"not in [0.01, {upper_bound}] "
                f"(raw_dim={raw_dims[i]}, room_dim={room_dim}, "
                f"pixel_size={pixel_size}, depth_m={depth_m}, "
                f"fov_deg={fov_deg}, image_dim={image_dim})"
            )
