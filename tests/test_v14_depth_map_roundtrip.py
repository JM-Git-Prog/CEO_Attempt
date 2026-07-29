"""Property-based test for Depth Map NumPy round-trip integrity (V14).

# Feature: photo-to-real-3d-world-v14

## Property 19: Depth Map NumPy Round-Trip

**Validates: Requirements 15.4**

For any float32 NumPy array representing a depth map, `np.save` followed
by `np.load` SHALL produce a bit-identical array.

Uses Hypothesis with hypothesis.extra.numpy for comprehensive float32
coverage including edge cases: zeros, infinities, NaN, negatives, subnormals,
and normal positive values representing realistic depth measurements.
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
def depth_map_realistic(draw: st.DrawFn) -> np.ndarray:
    """Generate float32 2D arrays representing realistic depth maps.

    Shape: (H, W) where H in [10, 500], W in [10, 500].
    Values: primarily positive depths (0.1 to 20.0), with occasional
    zeros, inf, and nan to test edge cases.
    """
    height = draw(st.integers(min_value=10, max_value=500))
    width = draw(st.integers(min_value=10, max_value=500))

    elements = st.one_of(
        # Positive depths typical for indoor scenes (meters)
        st.floats(
            min_value=np.float32(0.125).item(),
            max_value=np.float32(20.0).item(),
            allow_nan=False,
            allow_infinity=False,
            width=32,
        ),
        # Zeros
        st.just(0.0),
        # Occasional inf
        st.sampled_from([float("inf"), float("-inf")]),
        # Occasional NaN
        st.just(float("nan")),
    )

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=elements,
        )
    )

    return depth_map


@st.composite
def depth_map_edge_cases(draw: st.DrawFn) -> np.ndarray:
    """Generate depth maps with a rich mix of float32 edge cases.

    Includes: 0.0, -0.0, inf, -inf, nan, negative floats, subnormals,
    max/min float32, and typical indoor depth values.
    """
    height = draw(st.integers(min_value=10, max_value=200))
    width = draw(st.integers(min_value=10, max_value=200))

    elements = st.one_of(
        # Realistic depth values (meters)
        st.floats(
            min_value=np.float32(0.1).item(),
            max_value=np.float32(20.0).item(),
            allow_nan=False,
            allow_infinity=False,
            width=32,
        ),
        # Float32 edge cases
        st.sampled_from([
            np.float32(0.0),
            np.float32(-0.0),
            np.float32(np.inf),
            np.float32(-np.inf),
            np.float32(np.nan),
            np.finfo(np.float32).max,
            np.finfo(np.float32).min,
            np.finfo(np.float32).tiny,
            np.finfo(np.float32).smallest_subnormal,
        ]),
        # Negative values
        st.floats(
            min_value=np.float32(-100.0).item(),
            max_value=np.float32(-0.001).item(),
            allow_nan=False,
            allow_infinity=False,
            width=32,
        ),
    )

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=elements,
        )
    )

    return depth_map


# ---------------------------------------------------------------------------
# Property 19: Depth Map NumPy Round-Trip
# ---------------------------------------------------------------------------


class TestDepthMapNumpyRoundTrip:
    """Property 19: Depth Map NumPy Round-Trip.

    **Validates: Requirements 15.4**

    For any float32 NumPy array representing a depth map, np.save followed
    by np.load SHALL produce a bit-identical array.
    """

    @given(depth_map=depth_map_realistic())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_numpy_roundtrip_bit_identical(self, depth_map: np.ndarray) -> None:
        """np.save -> np.load produces a bit-identical float32 array.

        **Validates: Requirements 15.4**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            file_path = Path(f.name)

        try:
            np.save(file_path, depth_map)
            loaded = np.load(file_path)

            # Shape must be preserved
            assert loaded.shape == depth_map.shape, (
                f"Shape mismatch: original {depth_map.shape} vs loaded {loaded.shape}"
            )

            # Dtype must be preserved as float32
            assert loaded.dtype == np.float32, (
                f"Dtype mismatch: expected float32, got {loaded.dtype}"
            )

            # Bit-identical comparison (handles NaN == NaN)
            assert np.array_equal(loaded, depth_map, equal_nan=True), (
                f"Arrays not bit-identical after round-trip. "
                f"Shape: {depth_map.shape}"
            )
        finally:
            file_path.unlink(missing_ok=True)

    @given(depth_map=depth_map_edge_cases())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
    )
    def test_numpy_roundtrip_byte_level_equality(self, depth_map: np.ndarray) -> None:
        """np.save -> np.load preserves exact byte representation.

        This covers negative zero vs positive zero, NaN bit patterns,
        subnormals, and all other float32 edge cases at the byte level.

        **Validates: Requirements 15.4**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            file_path = Path(f.name)

        try:
            np.save(file_path, depth_map)
            loaded = np.load(file_path)

            # Byte-level comparison: strictest possible equality check
            original_bytes = depth_map.tobytes()
            loaded_bytes = loaded.tobytes()
            assert original_bytes == loaded_bytes, (
                f"Byte-level mismatch after round-trip. "
                f"Shape: {depth_map.shape}, "
                f"Byte lengths: {len(original_bytes)} vs {len(loaded_bytes)}"
            )
        finally:
            file_path.unlink(missing_ok=True)
