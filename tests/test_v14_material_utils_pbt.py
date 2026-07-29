"""Property-based tests for Texture Size Selection (material_utils).

# Feature: photo-to-real-3d-world-v14

## Property 14: Texture Size Selection

**Validates: Requirements 11.4**

For any object screen-space area percentage, texture dimensions SHALL be
256×256 for area < 2%, 512×512 for 2% ≤ area ≤ 10%, and 1024×1024 for
area > 10%.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.photo_pipeline.stages.material_utils import select_texture_size


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Area percentage in [0.0, 1.0) as specified in the implementation guidance
area_pct_strategy = st.floats(
    min_value=0.0, max_value=1.0, exclude_max=True,
    allow_nan=False, allow_infinity=False,
)

# Tier-specific strategies for focused testing
small_area = st.floats(
    min_value=0.0, max_value=0.02, exclude_max=True,
    allow_nan=False, allow_infinity=False,
)

medium_area = st.floats(
    min_value=0.02, max_value=0.10,
    allow_nan=False, allow_infinity=False,
)

large_area = st.floats(
    min_value=0.10, max_value=1.0, exclude_min=True, exclude_max=True,
    allow_nan=False, allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Property 14: Texture Size Selection
# ---------------------------------------------------------------------------


class TestTextureSizeSelection:
    """Property 14: Texture Size Selection.

    **Validates: Requirements 11.4**
    """

    @given(area_pct=small_area)
    @settings(max_examples=50, deadline=None)
    def test_small_area_returns_256(self, area_pct: float) -> None:
        """area_pct < 0.02 → (256, 256).

        **Validates: Requirements 11.4**
        """
        result = select_texture_size(area_pct)
        assert result == (256, 256), (
            f"Expected (256, 256) for area_pct={area_pct}, got {result}"
        )

    @given(area_pct=medium_area)
    @settings(max_examples=50, deadline=None)
    def test_medium_area_returns_512(self, area_pct: float) -> None:
        """0.02 <= area_pct <= 0.10 → (512, 512).

        **Validates: Requirements 11.4**
        """
        result = select_texture_size(area_pct)
        assert result == (512, 512), (
            f"Expected (512, 512) for area_pct={area_pct}, got {result}"
        )

    @given(area_pct=large_area)
    @settings(max_examples=50, deadline=None)
    def test_large_area_returns_1024(self, area_pct: float) -> None:
        """area_pct > 0.10 → (1024, 1024).

        **Validates: Requirements 11.4**
        """
        result = select_texture_size(area_pct)
        assert result == (1024, 1024), (
            f"Expected (1024, 1024) for area_pct={area_pct}, got {result}"
        )
