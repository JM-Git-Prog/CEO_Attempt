"""Property-based tests for photo pipeline depth estimator.

# Feature: photo-to-playable-world

## Property 4: Normal Map Contains Unit Vectors

**Validates: Requirements 3.2**

For any valid depth map (2D float32 array with all positive finite values),
the computed normal map SHALL contain vectors with magnitude within [0.99, 1.01]
at every pixel where depth gradients are computable.

## Property 5: Depth Fallback Threshold

**Validates: Requirements 3.6**

For any depth map where more than 50% of pixels have invalid (zero or infinite)
depth values, the system SHALL use the flat-floor heuristic. For any depth map
where 50% or fewer pixels are invalid, the system SHALL use the actual depth data.

Uses Hypothesis with numpy strategies.
"""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from src.photo_pipeline.stages.depth_estimator import (
    compute_normals_from_depth,
    validate_depth_map,
    create_flat_floor_depth_map,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def valid_depth_maps(draw: st.DrawFn) -> np.ndarray:
    """Generate random positive finite float32 depth maps.

    Shape: (H, W) where H in [10, 100], W in [10, 100].
    Values: positive finite floats in [0.1, 50.0].
    """
    height = draw(st.integers(min_value=10, max_value=100))
    width = draw(st.integers(min_value=10, max_value=100))

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=st.floats(
                min_value=0.1,
                max_value=50.0,
                allow_nan=False,
                allow_infinity=False,
            ),
        )
    )

    return depth_map


@st.composite
def depth_maps_with_controlled_invalid_ratio(draw: st.DrawFn):
    """Generate depth maps with a controlled ratio of invalid pixels.

    Returns (depth_map, target_invalid_ratio) where invalid pixels are
    set to 0.0, inf, or nan.
    """
    height = draw(st.integers(min_value=10, max_value=50))
    width = draw(st.integers(min_value=10, max_value=50))
    total_pixels = height * width

    # Choose an invalid ratio that clearly falls on one side of the threshold
    # Either > 0.50 (use fallback) or <= 0.50 (use actual depth)
    invalid_ratio = draw(
        st.one_of(
            # More than 50% invalid -> should trigger fallback
            st.floats(min_value=0.51, max_value=0.99),
            # 50% or fewer invalid -> should NOT trigger fallback
            st.floats(min_value=0.0, max_value=0.49),
        )
    )

    # Start with all valid values
    depth_map = np.random.default_rng(draw(st.integers(0, 2**32 - 1))).uniform(
        0.1, 50.0, size=(height, width)
    ).astype(np.float32)

    # Compute how many pixels to invalidate
    num_invalid = int(round(invalid_ratio * total_pixels))
    num_invalid = min(num_invalid, total_pixels)

    # Randomly choose pixels to invalidate
    if num_invalid > 0:
        flat_indices = np.random.default_rng(
            draw(st.integers(0, 2**32 - 1))
        ).choice(total_pixels, size=num_invalid, replace=False)

        # Choose invalid value type for each pixel
        invalid_types = draw(
            st.lists(
                st.sampled_from([0.0, float("inf"), float("-inf"), float("nan")]),
                min_size=num_invalid,
                max_size=num_invalid,
            )
        )

        flat_map = depth_map.flatten()
        for idx, inv_val in zip(flat_indices, invalid_types):
            flat_map[idx] = np.float32(inv_val)
        depth_map = flat_map.reshape(height, width)

    return depth_map, invalid_ratio


# ---------------------------------------------------------------------------
# Property 4: Normal Map Contains Unit Vectors
# ---------------------------------------------------------------------------


class TestNormalMapUnitVectors:
    """Property 4: Normal Map Contains Unit Vectors.

    For any valid depth map (positive finite float32 values), computed normals
    have magnitude within [0.99, 1.01] at every pixel.
    """

    @given(depth_map=valid_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normals_are_unit_vectors(self, depth_map: np.ndarray):
        """Every computed normal vector has magnitude in [0.99, 1.01]."""
        normals = compute_normals_from_depth(depth_map)

        # Verify output shape
        h, w = depth_map.shape
        assert normals.shape == (h, w, 3), (
            f"Expected shape ({h}, {w}, 3), got {normals.shape}"
        )

        # Compute magnitudes of all normal vectors
        magnitudes = np.linalg.norm(normals, axis=2)

        # All magnitudes should be within [0.99, 1.01]
        assert np.all(magnitudes >= 0.99), (
            f"Found normal with magnitude < 0.99: min={magnitudes.min():.6f}"
        )
        assert np.all(magnitudes <= 1.01), (
            f"Found normal with magnitude > 1.01: max={magnitudes.max():.6f}"
        )

    @given(depth_map=valid_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normals_have_positive_z_component(self, depth_map: np.ndarray):
        """All normals point toward the camera (positive Z component)."""
        normals = compute_normals_from_depth(depth_map)

        # The Z component is set to 1.0 before normalization, so it must
        # remain positive after normalization
        z_components = normals[:, :, 2]
        assert np.all(z_components > 0), (
            f"Found normal with non-positive Z: min Z={z_components.min():.6f}"
        )

    @given(depth_map=valid_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_normals_dtype_is_float32(self, depth_map: np.ndarray):
        """Output normal map is float32."""
        normals = compute_normals_from_depth(depth_map)
        assert normals.dtype == np.float32, (
            f"Expected float32, got {normals.dtype}"
        )


# ---------------------------------------------------------------------------
# Property 5: Depth Fallback Threshold
# ---------------------------------------------------------------------------


class TestDepthFallbackThreshold:
    """Property 5: Depth Fallback Threshold.

    For any depth map where >50% pixels are invalid -> flat-floor heuristic;
    <=50% invalid -> use actual depth.
    """

    @given(data=depth_maps_with_controlled_invalid_ratio())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_validate_depth_map_returns_correct_ratio(
        self, data: tuple[np.ndarray, float]
    ):
        """validate_depth_map returns the ratio of valid pixels."""
        depth_map, target_invalid_ratio = data

        valid_ratio = validate_depth_map(depth_map)

        # valid_ratio should be between 0 and 1
        assert 0.0 <= valid_ratio <= 1.0, (
            f"valid_ratio out of bounds: {valid_ratio}"
        )

        # The ratio should correspond to actual valid pixel count
        total = depth_map.size
        valid_mask = np.isfinite(depth_map) & (depth_map > 0.0)
        expected_valid_count = int(np.count_nonzero(valid_mask))
        expected_ratio = expected_valid_count / total if total > 0 else 0.0

        assert abs(valid_ratio - expected_ratio) < 1e-6, (
            f"Expected valid_ratio={expected_ratio:.6f}, got {valid_ratio:.6f}"
        )

    @given(data=depth_maps_with_controlled_invalid_ratio())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_fallback_triggered_when_more_than_50_percent_invalid(
        self, data: tuple[np.ndarray, float]
    ):
        """When >50% pixels are invalid (valid_ratio < 0.5), fallback is used."""
        depth_map, target_invalid_ratio = data

        valid_ratio = validate_depth_map(depth_map)

        # Only test when we clearly have >50% invalid pixels
        assume(target_invalid_ratio > 0.50)

        # With >50% invalid, valid_ratio should be < 0.5
        # The system uses fallback when valid_ratio < 0.5
        assert valid_ratio < 0.5, (
            f"Expected valid_ratio < 0.5 for {target_invalid_ratio:.2%} invalid, "
            f"got {valid_ratio:.4f}"
        )

    @given(data=depth_maps_with_controlled_invalid_ratio())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_no_fallback_when_50_percent_or_fewer_invalid(
        self, data: tuple[np.ndarray, float]
    ):
        """When <=50% pixels are invalid (valid_ratio >= 0.5), actual depth is used."""
        depth_map, target_invalid_ratio = data

        valid_ratio = validate_depth_map(depth_map)

        # Only test when we clearly have <=50% invalid pixels
        assume(target_invalid_ratio <= 0.49)

        # With <=50% invalid, valid_ratio should be >= 0.5
        # The system uses actual depth when valid_ratio >= 0.5
        assert valid_ratio >= 0.5, (
            f"Expected valid_ratio >= 0.5 for {target_invalid_ratio:.2%} invalid, "
            f"got {valid_ratio:.4f}"
        )

    @given(
        height=st.integers(min_value=10, max_value=100),
        width=st.integers(min_value=10, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_flat_floor_depth_map_is_all_valid(self, height: int, width: int):
        """Flat floor fallback produces a fully valid depth map."""
        fallback = create_flat_floor_depth_map(height, width)

        # Verify shape
        assert fallback.shape == (height, width), (
            f"Expected shape ({height}, {width}), got {fallback.shape}"
        )

        # Verify all values are the fallback constant (4.0m)
        assert np.all(fallback == 4.0), "Flat floor should be uniformly 4.0m"

        # Verify 100% valid
        valid_ratio = validate_depth_map(fallback)
        assert valid_ratio == 1.0, (
            f"Flat floor should have valid_ratio=1.0, got {valid_ratio}"
        )

    @given(
        height=st.integers(min_value=10, max_value=100),
        width=st.integers(min_value=10, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_flat_floor_dtype_is_float32(self, height: int, width: int):
        """Flat floor fallback produces float32 arrays."""
        fallback = create_flat_floor_depth_map(height, width)
        assert fallback.dtype == np.float32, (
            f"Expected float32, got {fallback.dtype}"
        )
