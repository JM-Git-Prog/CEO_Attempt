"""Unit tests for material_utils.py — texture size selection and PBR clamping.

Requirements: 11.4, 5.3
"""

import pytest

from src.photo_pipeline.stages.material_utils import clamp_pbr_values, select_texture_size


# ---------------------------------------------------------------------------
# select_texture_size tests
# ---------------------------------------------------------------------------


class TestSelectTextureSize:
    """Tests for the three-tier texture size selection."""

    def test_small_object_below_threshold(self) -> None:
        """Objects < 2% image area get 256×256."""
        assert select_texture_size(0.01) == (256, 256)

    def test_very_small_object(self) -> None:
        """Tiny objects still get 256×256."""
        assert select_texture_size(0.001) == (256, 256)

    def test_zero_area(self) -> None:
        """Zero area gets smallest texture."""
        assert select_texture_size(0.0) == (256, 256)

    def test_medium_object_at_lower_boundary(self) -> None:
        """Exactly 2% gets 512×512 (inclusive lower bound)."""
        assert select_texture_size(0.02) == (512, 512)

    def test_medium_object_mid_range(self) -> None:
        """5% gets 512×512."""
        assert select_texture_size(0.05) == (512, 512)

    def test_medium_object_at_upper_boundary(self) -> None:
        """Exactly 10% gets 512×512 (inclusive upper bound)."""
        assert select_texture_size(0.10) == (512, 512)

    def test_large_object_above_threshold(self) -> None:
        """Objects > 10% get 1024×1024."""
        assert select_texture_size(0.15) == (1024, 1024)

    def test_very_large_object(self) -> None:
        """Full image area gets 1024×1024."""
        assert select_texture_size(1.0) == (1024, 1024)

    def test_just_below_lower_boundary(self) -> None:
        """Just under 2% stays in the small tier."""
        assert select_texture_size(0.0199) == (256, 256)

    def test_just_above_upper_boundary(self) -> None:
        """Just above 10% enters the large tier."""
        assert select_texture_size(0.1001) == (1024, 1024)


# ---------------------------------------------------------------------------
# clamp_pbr_values tests
# ---------------------------------------------------------------------------


class TestClampPbrValues:
    """Tests for PBR value clamping to [0.0, 1.0]."""

    def test_values_in_range_unchanged(self) -> None:
        """Values already in [0.0, 1.0] pass through unchanged."""
        assert clamp_pbr_values(0.5, 0.7) == (0.5, 0.7)

    def test_zero_values(self) -> None:
        """Zero is a valid minimum."""
        assert clamp_pbr_values(0.0, 0.0) == (0.0, 0.0)

    def test_one_values(self) -> None:
        """One is a valid maximum."""
        assert clamp_pbr_values(1.0, 1.0) == (1.0, 1.0)

    def test_negative_metallic_clamped(self) -> None:
        """Negative metallic clamps to 0.0."""
        m, r = clamp_pbr_values(-0.5, 0.5)
        assert m == 0.0
        assert r == 0.5

    def test_negative_roughness_clamped(self) -> None:
        """Negative roughness clamps to 0.0."""
        m, r = clamp_pbr_values(0.5, -0.3)
        assert m == 0.5
        assert r == 0.0

    def test_over_one_metallic_clamped(self) -> None:
        """Metallic > 1.0 clamps to 1.0."""
        m, r = clamp_pbr_values(1.5, 0.5)
        assert m == 1.0
        assert r == 0.5

    def test_over_one_roughness_clamped(self) -> None:
        """Roughness > 1.0 clamps to 1.0."""
        m, r = clamp_pbr_values(0.5, 2.0)
        assert m == 0.5
        assert r == 1.0

    def test_both_negative_clamped(self) -> None:
        """Both negative clamp to 0.0."""
        assert clamp_pbr_values(-1.0, -2.0) == (0.0, 0.0)

    def test_both_over_one_clamped(self) -> None:
        """Both over 1.0 clamp to 1.0."""
        assert clamp_pbr_values(5.0, 10.0) == (1.0, 1.0)

    def test_extreme_values(self) -> None:
        """Extreme negative and positive values clamp correctly."""
        assert clamp_pbr_values(-1000.0, 1000.0) == (0.0, 1.0)
