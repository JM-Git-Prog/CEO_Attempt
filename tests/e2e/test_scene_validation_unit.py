"""Unit tests for scene validation lighting logic.

Tests the validate_lighting_against_contract helper and hex_to_rgb conversion
without requiring a live browser or Playwright.

Requirements: 9.1, 9.2, 9.3
"""
from __future__ import annotations

import pytest

from tests.e2e.test_scene_validation import (
    LightingMismatch,
    format_lighting_mismatches,
    hex_to_rgb,
    validate_lighting_against_contract,
)


def _make_light(
    light_type="point", x=1.0, y=2.0, z=3.0, color="#ffffff", intensity=1.0,
):
    return {"light_type": light_type, "position": {"x": x, "y": y, "z": z}, "color": color, "intensity": intensity}


def _make_actual_light(
    light_type="point", x=1.0, y=2.0, z=3.0, color="#ffffff", intensity=1.0,
):
    return {"type": light_type, "position": {"x": x, "y": y, "z": z}, "color": color, "intensity": intensity}


class TestHexToRgb:
    def test_white(self):
        assert hex_to_rgb("#ffffff") == pytest.approx((1.0, 1.0, 1.0))

    def test_black(self):
        assert hex_to_rgb("#000000") == pytest.approx((0.0, 0.0, 0.0))

    def test_red(self):
        assert hex_to_rgb("#ff0000") == pytest.approx((1.0, 0.0, 0.0))

    def test_case_insensitive(self):
        assert hex_to_rgb("#FF8800") == hex_to_rgb("#ff8800")

    def test_without_hash(self):
        assert hex_to_rgb("ff8800") == pytest.approx((1.0, 136 / 255, 0.0))


class TestLightingValidationExactMatch:
    def test_single_matching_light(self):
        expected = [_make_light()]
        actual = [_make_actual_light()]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_multiple_matching_lights(self):
        expected = [
            _make_light("point", 1.0, 2.0, 3.0, "#ff0000", 0.8),
            _make_light("directional", 0.0, 5.0, 0.0, "#00ff00", 1.5),
        ]
        actual = [
            _make_actual_light("point", 1.0, 2.0, 3.0, "#ff0000", 0.8),
            _make_actual_light("directional", 0.0, 5.0, 0.0, "#00ff00", 1.5),
        ]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_empty_lights(self):
        mismatches = validate_lighting_against_contract([], [])
        assert mismatches == []


class TestLightingValidationWithinTolerance:
    def test_position_within_tolerance(self):
        expected = [_make_light(x=1.0, y=2.0, z=3.0)]
        actual = [_make_actual_light(x=1.005, y=1.995, z=3.009)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_position_at_exact_tolerance_boundary(self):
        expected = [_make_light(x=1.0)]
        actual = [_make_actual_light(x=1.01)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_color_within_tolerance(self):
        expected = [_make_light(color="#ff0000")]
        actual = [_make_actual_light(color="#fc0000")]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_intensity_within_5_percent(self):
        expected = [_make_light(intensity=1.0)]
        actual = [_make_actual_light(intensity=1.04)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_intensity_at_exactly_5_percent(self):
        expected = [_make_light(intensity=1.0)]
        actual = [_make_actual_light(intensity=1.05)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []


class TestLightingValidationExceedsTolerance:
    def test_type_mismatch(self):
        expected = [_make_light(light_type="point")]
        actual = [_make_actual_light(light_type="directional")]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert len(mismatches) == 1
        assert mismatches[0].parameter == "type"
        assert mismatches[0].expected == "point"
        assert mismatches[0].actual == "directional"

    def test_position_exceeds_tolerance(self):
        expected = [_make_light(x=1.0, y=2.0, z=3.0)]
        actual = [_make_actual_light(x=1.02, y=2.0, z=3.0)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert len(mismatches) == 1
        assert mismatches[0].parameter == "position.x"
        assert mismatches[0].expected == 1.0
        assert mismatches[0].actual == 1.02
        assert mismatches[0].delta == pytest.approx(0.02)

    def test_color_exceeds_tolerance(self):
        expected = [_make_light(color="#ff0000")]
        actual = [_make_actual_light(color="#f00000")]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert len(mismatches) == 1
        assert mismatches[0].parameter == "color.r"
        assert mismatches[0].delta > 0.02

    def test_intensity_exceeds_5_percent(self):
        expected = [_make_light(intensity=1.0)]
        actual = [_make_actual_light(intensity=1.06)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert len(mismatches) == 1
        assert mismatches[0].parameter == "intensity"
        assert mismatches[0].expected == 1.0
        assert mismatches[0].actual == 1.06
        assert mismatches[0].delta == pytest.approx(0.06)

    def test_multiple_position_axes_exceed(self):
        expected = [_make_light(x=0.0, y=0.0, z=0.0)]
        actual = [_make_actual_light(x=0.05, y=0.05, z=0.05)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert len(mismatches) == 3
        params = {m.parameter for m in mismatches}
        assert params == {"position.x", "position.y", "position.z"}


class TestLightingValidationEdgeCases:
    def test_zero_intensity_expected(self):
        expected = [_make_light(intensity=0.0)]
        actual = [_make_actual_light(intensity=0.0)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_zero_intensity_with_nonzero_actual(self):
        expected = [_make_light(intensity=0.0)]
        actual = [_make_actual_light(intensity=0.01)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert len(mismatches) == 1
        assert mismatches[0].parameter == "intensity"

    def test_very_high_intensity(self):
        expected = [_make_light(intensity=100.0)]
        actual = [_make_actual_light(intensity=104.0)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_negative_position(self):
        expected = [_make_light(x=-5.0, y=-10.0, z=-1.0)]
        actual = [_make_actual_light(x=-5.005, y=-10.005, z=-1.005)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == []

    def test_custom_tolerances(self):
        expected = [_make_light(x=1.0, intensity=1.0)]
        actual = [_make_actual_light(x=1.05, intensity=1.2)]
        mismatches = validate_lighting_against_contract(
            actual, expected, position_tolerance=0.1, intensity_tolerance_pct=0.25,
        )
        assert mismatches == []


class TestLightingMismatchReporting:
    def test_mismatch_contains_light_index(self):
        expected = [_make_light(), _make_light(light_type="directional")]
        actual = [_make_actual_light(), _make_actual_light(light_type="point")]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches[0].light_index == 1

    def test_mismatch_contains_expected_and_actual(self):
        expected = [_make_light(intensity=2.0)]
        actual = [_make_actual_light(intensity=3.0)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches[0].expected == 2.0
        assert mismatches[0].actual == 3.0

    def test_mismatch_contains_delta(self):
        expected = [_make_light(x=1.0)]
        actual = [_make_actual_light(x=1.5)]
        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches[0].delta == pytest.approx(0.5)

    def test_format_mismatches_includes_all_info(self):
        mismatches = [
            LightingMismatch(light_index=0, parameter="position.x", expected=1.0, actual=1.5, delta=0.5),
            LightingMismatch(light_index=1, parameter="type", expected="point", actual="spot", delta="type mismatch: 'point' != 'spot'"),
        ]
        report = format_lighting_mismatches(mismatches)
        assert "2 mismatch(es)" in report
        assert "Light[0] position.x" in report
        assert "expected=1.0" in report
        assert "actual=1.5" in report
        assert "delta=0.5" in report
        assert "Light[1] type" in report
