"""Property-based tests for Texture Size Selection.

# Feature: photo-to-real-3d-world-v14

## Property 14: Texture Size Selection

**Validates: Requirements 11.4**

For any object screen-space area percentage, texture dimensions SHALL be
256×256 for area < 2%, 512×512 for 2% ≤ area ≤ 10%, and 1024×1024 for
area > 10%.

Uses Hypothesis with strategies generating:
- area_pct floats from 0.0 to 1.0 (valid range)
- Boundary values near the 0.02 and 0.10 thresholds
- Negative and >1.0 edge cases
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from src.photo_pipeline.stages.material_utils import select_texture_size


# ---------------------------------------------------------------------------
# Constants (mirrored from implementation for oracle comparison)
# ---------------------------------------------------------------------------

SMALL_SIZE = (256, 256)    # area < 2%
MEDIUM_SIZE = (512, 512)   # 2% ≤ area ≤ 10%
LARGE_SIZE = (1024, 1024)  # area > 10%

THRESHOLD_LOW = 0.02   # boundary between small and medium
THRESHOLD_HIGH = 0.10  # boundary between medium and large


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid area percentages in [0.0, 1.0]
_valid_area_pct = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Small area: strictly less than 2%
_small_area = st.floats(
    min_value=0.0, max_value=0.019999999, allow_nan=False, allow_infinity=False
)

# Medium area: 2% to 10% inclusive
_medium_area = st.floats(
    min_value=0.02, max_value=0.10, allow_nan=False, allow_infinity=False
)

# Large area: strictly greater than 10%
_large_area = st.floats(
    min_value=0.100000001, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Negative area (edge case)
_negative_area = st.floats(
    min_value=-10.0, max_value=-0.001, allow_nan=False, allow_infinity=False
)

# Greater than 1.0 (edge case)
_over_one_area = st.floats(
    min_value=1.001, max_value=10.0, allow_nan=False, allow_infinity=False
)


# ---------------------------------------------------------------------------
# Property 14: Texture Size Selection
# ---------------------------------------------------------------------------


class TestTextureSizeSelectionProperty:
    """Property 14: Texture Size Selection.

    **Validates: Requirements 11.4**
    """

    @given(area_pct=_valid_area_pct)
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_texture_size_selection_all_tiers(self, area_pct: float) -> None:
        """For any valid area_pct, the correct texture size tier is selected."""
        result = select_texture_size(area_pct)

        if area_pct < THRESHOLD_LOW:
            assert result == SMALL_SIZE, (
                f"area_pct={area_pct} (< {THRESHOLD_LOW}) should give {SMALL_SIZE}, "
                f"got {result}"
            )
        elif area_pct <= THRESHOLD_HIGH:
            assert result == MEDIUM_SIZE, (
                f"area_pct={area_pct} ([{THRESHOLD_LOW}, {THRESHOLD_HIGH}]) "
                f"should give {MEDIUM_SIZE}, got {result}"
            )
        else:
            assert result == LARGE_SIZE, (
                f"area_pct={area_pct} (> {THRESHOLD_HIGH}) should give {LARGE_SIZE}, "
                f"got {result}"
            )

    @given(area_pct=_small_area)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_small_area_gives_256(self, area_pct: float) -> None:
        """Objects with area < 2% always get 256×256 textures.

        **Validates: Requirements 11.4** (small tier)
        """
        result = select_texture_size(area_pct)
        assert result == SMALL_SIZE, (
            f"area_pct={area_pct} should give {SMALL_SIZE}, got {result}"
        )

    @given(area_pct=_medium_area)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_medium_area_gives_512(self, area_pct: float) -> None:
        """Objects with 2% ≤ area ≤ 10% always get 512×512 textures.

        **Validates: Requirements 11.4** (medium tier)
        """
        result = select_texture_size(area_pct)
        assert result == MEDIUM_SIZE, (
            f"area_pct={area_pct} should give {MEDIUM_SIZE}, got {result}"
        )

    @given(area_pct=_large_area)
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_large_area_gives_1024(self, area_pct: float) -> None:
        """Objects with area > 10% always get 1024×1024 textures.

        **Validates: Requirements 11.4** (large tier)
        """
        result = select_texture_size(area_pct)
        assert result == LARGE_SIZE, (
            f"area_pct={area_pct} should give {LARGE_SIZE}, got {result}"
        )

    @given(area_pct=_negative_area)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_negative_area_gives_smallest(self, area_pct: float) -> None:
        """Negative area values (edge case) fall into the smallest tier.

        Negative values are < 0.02, so the function returns 256×256.
        """
        result = select_texture_size(area_pct)
        assert result == SMALL_SIZE, (
            f"Negative area_pct={area_pct} should give {SMALL_SIZE}, got {result}"
        )

    @given(area_pct=_over_one_area)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_over_one_area_gives_largest(self, area_pct: float) -> None:
        """Area > 1.0 (edge case) falls into the largest tier.

        Values > 0.10 always produce 1024×1024.
        """
        result = select_texture_size(area_pct)
        assert result == LARGE_SIZE, (
            f"area_pct={area_pct} (> 1.0) should give {LARGE_SIZE}, got {result}"
        )

    def test_exact_boundary_low(self) -> None:
        """Exact boundary at 0.02 should return 512×512 (medium tier).

        The threshold is: area_pct < 0.02 → small, else check medium.
        So 0.02 exactly is medium.
        """
        result = select_texture_size(0.02)
        assert result == MEDIUM_SIZE

    def test_exact_boundary_high(self) -> None:
        """Exact boundary at 0.10 should return 512×512 (medium tier).

        The threshold is: area_pct <= 0.10 → medium.
        So 0.10 exactly is medium.
        """
        result = select_texture_size(0.10)
        assert result == MEDIUM_SIZE

    @given(area_pct=_valid_area_pct)
    @settings(
        max_examples=300,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_result_is_power_of_two(self, area_pct: float) -> None:
        """All returned texture dimensions are powers of two (WebGL compat).

        **Validates: Requirements 11.4** (WebGL compatibility)
        """
        w, h = select_texture_size(area_pct)
        assert w == h, f"Texture should be square, got {w}×{h}"
        assert w > 0 and (w & (w - 1)) == 0, (
            f"Texture dimension {w} is not a power of two"
        )
