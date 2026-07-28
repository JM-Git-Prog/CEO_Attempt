"""Property-based tests for photo pipeline serialization round-trips.

# Feature: photo-to-playable-world

## Property 22: Depth Map NumPy Round-Trip

**Validates: Requirements 13.3**

For any float32 2D array (representing a depth map), saving via np.save then
loading via np.load SHALL produce a bit-identical array.

Uses Hypothesis with hypothesis.extra.numpy strategies.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def float32_depth_maps(draw: st.DrawFn) -> np.ndarray:
    """Generate arbitrary float32 2D arrays representing depth maps.

    Shape: (H, W) where H in [1, 200], W in [1, 200].
    Values: any valid float32 including negative, zero, positive, subnormals,
    inf, -inf, and NaN — all legal float32 bit patterns that np.save must
    preserve exactly.
    """
    height = draw(st.integers(min_value=1, max_value=200))
    width = draw(st.integers(min_value=1, max_value=200))

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=st.floats(
                width=32,
                allow_nan=True,
                allow_infinity=True,
                allow_subnormal=True,
            ),
        )
    )

    return depth_map


@st.composite
def single_pixel_depth_maps(draw: st.DrawFn) -> np.ndarray:
    """Generate single-pixel (1x1) float32 depth maps — edge case."""
    value = draw(
        st.floats(
            width=32,
            allow_nan=True,
            allow_infinity=True,
            allow_subnormal=True,
        )
    )
    return np.array([[value]], dtype=np.float32)


@st.composite
def small_depth_maps(draw: st.DrawFn) -> np.ndarray:
    """Generate small float32 depth maps (1-10 pixels per side)."""
    height = draw(st.integers(min_value=1, max_value=10))
    width = draw(st.integers(min_value=1, max_value=10))

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=st.floats(
                width=32,
                allow_nan=True,
                allow_infinity=True,
                allow_subnormal=True,
            ),
        )
    )

    return depth_map


# ---------------------------------------------------------------------------
# Property 22: Depth Map NumPy Round-Trip
# ---------------------------------------------------------------------------


class TestDepthMapNumpyRoundTrip:
    """Property 22: Depth Map NumPy Round-Trip.

    For any float32 2D array, np.save → np.load produces bit-identical array.
    """

    @given(depth_map=float32_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_npy_round_trip_bit_identical(self, depth_map: np.ndarray):
        """np.save → np.load produces bit-identical float32 2D array."""
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            # Save
            np.save(tmp_path, depth_map)

            # Load
            loaded = np.load(tmp_path)

            # Verify shape preserved
            assert loaded.shape == depth_map.shape, (
                f"Shape mismatch: expected {depth_map.shape}, got {loaded.shape}"
            )

            # Verify dtype preserved
            assert loaded.dtype == np.float32, (
                f"Dtype mismatch: expected float32, got {loaded.dtype}"
            )

            # Bit-identical comparison (handles NaN correctly via raw bytes)
            original_bytes = depth_map.tobytes()
            loaded_bytes = loaded.tobytes()
            assert original_bytes == loaded_bytes, (
                "Arrays are not bit-identical after round-trip"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=single_pixel_depth_maps())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_single_pixel_round_trip(self, depth_map: np.ndarray):
        """Single-pixel depth maps survive round-trip bit-identically."""
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            assert loaded.shape == (1, 1), (
                f"Expected (1, 1), got {loaded.shape}"
            )
            assert loaded.dtype == np.float32
            assert depth_map.tobytes() == loaded.tobytes(), (
                "Single-pixel array not bit-identical after round-trip"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=small_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_small_depth_map_round_trip(self, depth_map: np.ndarray):
        """Small depth maps (edge cases) survive round-trip bit-identically."""
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            assert loaded.shape == depth_map.shape
            assert loaded.dtype == np.float32
            assert depth_map.tobytes() == loaded.tobytes(), (
                f"Small depth map ({depth_map.shape}) not bit-identical after round-trip"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=float32_depth_maps())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_npy_round_trip_preserves_special_values(self, depth_map: np.ndarray):
        """Special float32 values (NaN, inf, -inf, zero, negative) are preserved."""
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            # Check NaN positions match
            nan_mask_original = np.isnan(depth_map)
            nan_mask_loaded = np.isnan(loaded)
            assert np.array_equal(nan_mask_original, nan_mask_loaded), (
                "NaN positions differ after round-trip"
            )

            # Check inf positions match
            inf_mask_original = np.isinf(depth_map)
            inf_mask_loaded = np.isinf(loaded)
            assert np.array_equal(inf_mask_original, inf_mask_loaded), (
                "Inf positions differ after round-trip"
            )

            # Where both are finite, values must be exactly equal
            finite_mask = np.isfinite(depth_map)
            if np.any(finite_mask):
                assert np.array_equal(
                    depth_map[finite_mask], loaded[finite_mask]
                ), "Finite values differ after round-trip"
        finally:
            tmp_path.unlink(missing_ok=True)
