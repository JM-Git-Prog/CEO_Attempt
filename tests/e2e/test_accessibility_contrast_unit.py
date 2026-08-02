"""Unit tests for color contrast ratio computation.

Tests the compute_contrast_ratio helper and its constituent functions
(parse_rgb, relative_luminance, _linearize_channel) independently of
any browser/Playwright environment.

These validate Property 11: Contrast Ratio Enforcement from the design doc.

Requirements: 13.1, 13.2
"""
from __future__ import annotations

import pytest

from tests.e2e.test_accessibility import (
    WCAG_AA_CONTRAST_MINIMUM,
    _linearize_channel,
    compute_contrast_ratio,
    parse_rgb,
    relative_luminance,
)


# ---------------------------------------------------------------------------
# parse_rgb tests
# ---------------------------------------------------------------------------


class TestParseRGB:
    """Unit tests for CSS color string parsing."""

    def test_rgb_format(self) -> None:
        """Parse standard rgb(R, G, B) format."""
        assert parse_rgb("rgb(255, 255, 255)") == (255, 255, 255)
        assert parse_rgb("rgb(0, 0, 0)") == (0, 0, 0)
        assert parse_rgb("rgb(128, 64, 32)") == (128, 64, 32)

    def test_rgba_format(self) -> None:
        """Parse rgba(R, G, B, A) format — alpha is ignored."""
        assert parse_rgb("rgba(255, 255, 255, 1)") == (255, 255, 255)
        assert parse_rgb("rgba(0, 0, 0, 0.5)") == (0, 0, 0)
        assert parse_rgb("rgba(100, 200, 50, 0)") == (100, 200, 50)

    def test_hex_6_digit(self) -> None:
        """Parse #RRGGBB hex format."""
        assert parse_rgb("#ffffff") == (255, 255, 255)
        assert parse_rgb("#000000") == (0, 0, 0)
        assert parse_rgb("#FF8040") == (255, 128, 64)

    def test_hex_3_digit(self) -> None:
        """Parse #RGB shorthand hex format."""
        assert parse_rgb("#fff") == (255, 255, 255)
        assert parse_rgb("#000") == (0, 0, 0)
        assert parse_rgb("#f80") == (255, 136, 0)

    def test_whitespace_trimming(self) -> None:
        """Leading/trailing whitespace is stripped."""
        assert parse_rgb("  rgb(10, 20, 30)  ") == (10, 20, 30)
        assert parse_rgb(" #ff0000 ") == (255, 0, 0)

    def test_invalid_format_raises(self) -> None:
        """Unparseable formats raise ValueError."""
        with pytest.raises(ValueError):
            parse_rgb("hsl(0, 100%, 50%)")
        with pytest.raises(ValueError):
            parse_rgb("not-a-color")
        with pytest.raises(ValueError):
            parse_rgb("")


# ---------------------------------------------------------------------------
# _linearize_channel tests
# ---------------------------------------------------------------------------


class TestLinearizeChannel:
    """Unit tests for sRGB to linear conversion."""

    def test_zero(self) -> None:
        """sRGB 0 maps to linear 0."""
        assert _linearize_channel(0) == 0.0

    def test_max(self) -> None:
        """sRGB 255 maps to linear 1.0."""
        assert abs(_linearize_channel(255) - 1.0) < 1e-6

    def test_low_value_linear_region(self) -> None:
        """Low sRGB values (<=0.04045) use the linear formula."""
        # sRGB 10/255 = 0.0392 < 0.04045 → linear region
        result = _linearize_channel(10)
        expected = (10 / 255.0) / 12.92
        assert abs(result - expected) < 1e-10

    def test_high_value_gamma_region(self) -> None:
        """Higher sRGB values use the gamma formula."""
        # sRGB 128/255 = 0.502 > 0.04045 → gamma region
        result = _linearize_channel(128)
        srgb = 128 / 255.0
        expected = ((srgb + 0.055) / 1.055) ** 2.4
        assert abs(result - expected) < 1e-10

    def test_monotonically_increasing(self) -> None:
        """Linearized values should increase monotonically with input."""
        prev = -1.0
        for i in range(256):
            val = _linearize_channel(i)
            assert val >= prev
            prev = val


# ---------------------------------------------------------------------------
# relative_luminance tests
# ---------------------------------------------------------------------------


class TestRelativeLuminance:
    """Unit tests for WCAG relative luminance computation."""

    def test_black(self) -> None:
        """Black has luminance 0."""
        assert relative_luminance(0, 0, 0) == 0.0

    def test_white(self) -> None:
        """White has luminance 1.0."""
        assert abs(relative_luminance(255, 255, 255) - 1.0) < 1e-6

    def test_pure_red(self) -> None:
        """Pure red luminance uses the 0.2126 coefficient."""
        result = relative_luminance(255, 0, 0)
        expected = 0.2126 * 1.0  # R=1.0 linearized, G=0, B=0
        assert abs(result - expected) < 1e-6

    def test_pure_green(self) -> None:
        """Pure green luminance uses the 0.7152 coefficient."""
        result = relative_luminance(0, 255, 0)
        expected = 0.7152 * 1.0
        assert abs(result - expected) < 1e-6

    def test_pure_blue(self) -> None:
        """Pure blue luminance uses the 0.0722 coefficient."""
        result = relative_luminance(0, 0, 255)
        expected = 0.0722 * 1.0
        assert abs(result - expected) < 1e-6

    def test_mid_gray(self) -> None:
        """Mid-gray (128, 128, 128) has luminance ~0.216."""
        result = relative_luminance(128, 128, 128)
        # All channels equal → luminance = linearize(128)
        lin = _linearize_channel(128)
        expected = (0.2126 + 0.7152 + 0.0722) * lin  # == lin
        assert abs(result - expected) < 1e-6


# ---------------------------------------------------------------------------
# compute_contrast_ratio tests
# ---------------------------------------------------------------------------


class TestComputeContrastRatio:
    """Unit tests for the full contrast ratio computation."""

    def test_black_on_white(self) -> None:
        """Black text on white background gives maximum contrast 21:1."""
        ratio = compute_contrast_ratio("rgb(0, 0, 0)", "rgb(255, 255, 255)")
        assert abs(ratio - 21.0) < 0.01

    def test_white_on_black(self) -> None:
        """White text on black background also gives 21:1 (order independent)."""
        ratio = compute_contrast_ratio("rgb(255, 255, 255)", "rgb(0, 0, 0)")
        assert abs(ratio - 21.0) < 0.01

    def test_same_color(self) -> None:
        """Same foreground and background gives ratio of 1:1."""
        ratio = compute_contrast_ratio("rgb(128, 128, 128)", "rgb(128, 128, 128)")
        assert abs(ratio - 1.0) < 0.01

    def test_wcag_aa_passing(self) -> None:
        """Dark gray on white passes WCAG AA (>= 4.5:1)."""
        # rgb(89, 89, 89) on white gives approximately 5.92:1
        ratio = compute_contrast_ratio("rgb(89, 89, 89)", "rgb(255, 255, 255)")
        assert ratio >= WCAG_AA_CONTRAST_MINIMUM

    def test_wcag_aa_failing(self) -> None:
        """Light gray on white fails WCAG AA (< 4.5:1)."""
        # rgb(180, 180, 180) on white gives approximately 2.14:1
        ratio = compute_contrast_ratio("rgb(180, 180, 180)", "rgb(255, 255, 255)")
        assert ratio < WCAG_AA_CONTRAST_MINIMUM

    def test_hex_input(self) -> None:
        """Accepts hex color format for both arguments."""
        ratio = compute_contrast_ratio("#000000", "#ffffff")
        assert abs(ratio - 21.0) < 0.01

    def test_mixed_formats(self) -> None:
        """Accepts mixed rgb and hex formats."""
        ratio = compute_contrast_ratio("rgb(0, 0, 0)", "#ffffff")
        assert abs(ratio - 21.0) < 0.01

    def test_rgba_input(self) -> None:
        """Accepts rgba format (alpha is ignored for contrast)."""
        ratio = compute_contrast_ratio("rgba(0, 0, 0, 1)", "rgba(255, 255, 255, 0.8)")
        assert abs(ratio - 21.0) < 0.01

    def test_ratio_always_gte_one(self) -> None:
        """Contrast ratio is always >= 1.0 regardless of color order."""
        ratio = compute_contrast_ratio("rgb(50, 50, 50)", "rgb(200, 200, 200)")
        assert ratio >= 1.0

    def test_invalid_color_raises(self) -> None:
        """Invalid color strings propagate ValueError."""
        with pytest.raises(ValueError):
            compute_contrast_ratio("not-a-color", "rgb(255, 255, 255)")
        with pytest.raises(ValueError):
            compute_contrast_ratio("rgb(0, 0, 0)", "invalid")

    def test_known_contrast_value(self) -> None:
        """Verify a known contrast ratio value for a specific color pair.

        Using the WCAG contrast calculator:
        - fg: #767676 (118, 118, 118) on white → ratio ~4.54:1
          (the minimum gray that passes WCAG AA on white)
        """
        ratio = compute_contrast_ratio("#767676", "#ffffff")
        # Should be approximately 4.54:1 (the well-known boundary gray)
        assert 4.4 <= ratio <= 4.7
