"""Property-based tests for depth map NumPy round-trip integrity.

# Feature: photo-to-playable-world

## Property 22: Depth Map NumPy Round-Trip

**Validates: Requirements 13.3**

For any float32 2D array (representing a depth map), saving via `np.save`
then loading via `np.load` SHALL produce a bit-identical array.

Uses Hypothesis with numpy strategies for comprehensive float32 coverage
including edge cases: zeros, infinities, NaN, very small/large finite values.
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
    """Generate random float32 2D arrays representing depth maps.

    Shape: (H, W) where H in [1, 128], W in [1, 128].
    Values: any float32 including zeros, subnormals, infinities, and NaN.
    """
    height = draw(st.integers(min_value=1, max_value=128))
    width = draw(st.integers(min_value=1, max_value=128))

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
def realistic_depth_maps(draw: st.DrawFn) -> np.ndarray:
    """Generate depth maps with realistic metric depth values.

    Shape: (H, W) where H in [1, 256], W in [1, 256].
    Values: positive finite floats in [0.01, 100.0] representing meters.
    """
    height = draw(st.integers(min_value=1, max_value=256))
    width = draw(st.integers(min_value=1, max_value=256))

    depth_map = draw(
        arrays(
            dtype=np.float32,
            shape=(height, width),
            elements=st.floats(
                min_value=np.float32(0.01).item(),
                max_value=np.float32(100.0).item(),
                allow_nan=False,
                allow_infinity=False,
                width=32,
            ),
        )
    )

    return depth_map


@st.composite
def edge_case_depth_maps(draw: st.DrawFn) -> np.ndarray:
    """Generate depth maps with edge-case float32 values.

    Includes: zeros, negative zeros, infinities, NaN, subnormals,
    very small/large finite values, and mixed combinations.
    """
    height = draw(st.integers(min_value=1, max_value=64))
    width = draw(st.integers(min_value=1, max_value=64))

    # Special float32 values
    special_values = st.sampled_from([
        0.0,
        -0.0,
        float("inf"),
        float("-inf"),
        float("nan"),
        np.finfo(np.float32).max,
        np.finfo(np.float32).min,
        np.finfo(np.float32).tiny,  # smallest positive normal
        np.finfo(np.float32).smallest_subnormal,
        -np.finfo(np.float32).max,
        1.0,
        -1.0,
        np.float32(1e-38),  # subnormal range
        np.float32(1e-45),  # smallest subnormal
    ])

    # Mix special values with regular floats
    elements = st.one_of(
        special_values,
        st.floats(width=32, allow_nan=True, allow_infinity=True, allow_subnormal=True),
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
# Property 22: Depth Map NumPy Round-Trip
# ---------------------------------------------------------------------------


class TestDepthMapNumpyRoundTrip:
    """Property 22: Depth Map NumPy Round-Trip.

    For any float32 2D array, np.save -> np.load produces bit-identical array.
    """

    @given(depth_map=float32_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_roundtrip_bit_identical_arbitrary_float32(
        self, depth_map: np.ndarray
    ):
        """Any float32 2D array survives np.save/np.load bit-identically.

        **Validates: Requirements 13.3**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            # Verify shape preserved
            assert loaded.shape == depth_map.shape, (
                f"Shape mismatch: {depth_map.shape} -> {loaded.shape}"
            )

            # Verify dtype preserved
            assert loaded.dtype == np.float32, (
                f"Dtype mismatch: expected float32, got {loaded.dtype}"
            )

            # Bit-identical comparison using array_equal with equal_nan=True
            # This compares NaN == NaN as True (bit-level equality for NaN)
            assert np.array_equal(loaded, depth_map, equal_nan=True), (
                f"Arrays not bit-identical after round-trip. "
                f"Shape: {depth_map.shape}, "
                f"Differences at: {np.argwhere(~np.equal(loaded, depth_map) & ~(np.isnan(loaded) & np.isnan(depth_map)))[:5]}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=realistic_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_roundtrip_realistic_depth_values(self, depth_map: np.ndarray):
        """Realistic metric depth maps survive round-trip bit-identically.

        **Validates: Requirements 13.3**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            assert loaded.shape == depth_map.shape
            assert loaded.dtype == np.float32
            assert np.array_equal(loaded, depth_map, equal_nan=True), (
                "Realistic depth map not bit-identical after round-trip"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=edge_case_depth_maps())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_roundtrip_edge_case_values(self, depth_map: np.ndarray):
        """Edge-case float32 values (inf, NaN, subnormals, zeros) survive round-trip.

        **Validates: Requirements 13.3**
        """
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            assert loaded.shape == depth_map.shape
            assert loaded.dtype == np.float32

            # Bit-level comparison using raw bytes for absolute certainty
            original_bytes = depth_map.tobytes()
            loaded_bytes = loaded.tobytes()
            assert original_bytes == loaded_bytes, (
                f"Byte-level mismatch after round-trip. "
                f"Array shape: {depth_map.shape}, "
                f"Original bytes len: {len(original_bytes)}, "
                f"Loaded bytes len: {len(loaded_bytes)}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(
        height=st.integers(min_value=1, max_value=512),
        width=st.integers(min_value=1, max_value=512),
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_roundtrip_preserves_shape_and_dtype(
        self, height: int, width: int
    ):
        """Shape and dtype (float32) are preserved through save/load cycle.

        **Validates: Requirements 13.3**
        """
        depth_map = np.zeros((height, width), dtype=np.float32)

        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            assert loaded.shape == (height, width), (
                f"Shape not preserved: expected ({height}, {width}), got {loaded.shape}"
            )
            assert loaded.dtype == np.float32, (
                f"Dtype not preserved: expected float32, got {loaded.dtype}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(depth_map=float32_depth_maps())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_roundtrip_negative_zero_preserved(self, depth_map: np.ndarray):
        """Negative zeros are preserved as distinct from positive zeros.

        **Validates: Requirements 13.3**
        """
        # Inject some negative zeros to ensure they're tested
        if depth_map.size > 0:
            depth_map.flat[0] = np.float32(-0.0)

        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            np.save(tmp_path, depth_map)
            loaded = np.load(tmp_path)

            # Byte-level check preserves -0.0 vs +0.0 distinction
            assert depth_map.tobytes() == loaded.tobytes(), (
                "Negative zero not preserved through round-trip"
            )
        finally:
            tmp_path.unlink(missing_ok=True)
