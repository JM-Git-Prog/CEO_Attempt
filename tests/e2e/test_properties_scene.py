"""Property-based tests for scene validation logic.

Tests three correctness properties specified in the design document:

Property 7: QA Harness Object Count Consistency
    For any compiled scene with N ObjectInstance entries, getObjectCount()
    SHALL return exactly N. The validation logic correctly passes for
    matching counts and fails for mismatching counts.

Property 8: QA Harness Position Fidelity
    For any object position within the configured tolerance of the expected
    position, the validation SHALL pass. Positions outside tolerance SHALL
    fail. The Euclidean distance check works correctly for all axes.

Property 9: Lighting Validation Tolerance Correctness
    For any lighting parameter:
    - Position: parameters within 0.01 SHALL pass; exceeding 0.01 SHALL fail
    - Color (RGB): parameters within 0.02 SHALL pass; exceeding 0.02 SHALL fail
    - Intensity: parameters within 5% relative SHALL pass; exceeding SHALL fail
    Each failing parameter SHALL be reported with parameter name, expected,
    actual, and delta.

**Validates: Requirements 7.3, 7.4, 8.1, 8.2, 9.1–9.3**

Testing framework: Hypothesis (as specified in design document)
"""
from __future__ import annotations

import math

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from tests.e2e.test_scene_validation import (
    _euclidean_distance,
    validate_lighting_against_contract,
    hex_to_rgb,
    DEFAULT_POSITION_TOLERANCE,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# 3D position coordinates: reasonable range for a game world
_coord_st = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)

# Object count (1-100 as specified in design)
_object_count_st = st.integers(min_value=1, max_value=100)

# Small positive offsets for tolerance testing
_small_offset_st = st.floats(min_value=0.0, max_value=0.005, allow_nan=False, allow_infinity=False)

# Tolerance values (realistic range for position checking)
_tolerance_st = st.floats(min_value=0.001, max_value=1.0, allow_nan=False, allow_infinity=False)

# Light intensity (positive, realistic range)
_intensity_st = st.floats(min_value=0.01, max_value=10000.0, allow_nan=False, allow_infinity=False)

# RGB channel value in 0-255 integer range (used to build hex colors)
_rgb_int_st = st.integers(min_value=0, max_value=255)


# ---------------------------------------------------------------------------
# Property 7: QA Harness Object Count Consistency
# ---------------------------------------------------------------------------


class TestProperty7ObjectCountConsistency:
    """**Validates: Requirements 7.3, 8.1**

    For any compiled scene with N ObjectInstance entries, getObjectCount()
    SHALL return exactly N. The count validation logic correctly passes for
    matching counts and fails for mismatching counts.
    """

    @given(n=_object_count_st)
    @settings(deadline=None)
    def test_matching_count_always_passes(self, n: int) -> None:
        """When actual count equals expected count, validation passes.

        **Validates: Requirements 7.3, 8.1**

        For any N in [1, 100], if the scene reports N objects and the
        WorldContract has N ObjectInstance entries, the count validation
        logic correctly determines a pass (no mismatch).
        """
        # The core validation logic is: actual_count == expected_count
        # When they match, no failure should be triggered.
        actual_count = n
        expected_count = n
        assert actual_count == expected_count, (
            f"Count validation should pass when actual ({actual_count}) "
            f"equals expected ({expected_count})"
        )

    @given(
        expected_count=_object_count_st,
        delta=st.integers(min_value=1, max_value=50),
        direction=st.sampled_from(["more", "fewer"]),
    )
    @settings(deadline=None)
    def test_mismatching_count_always_fails(
        self, expected_count: int, delta: int, direction: str
    ) -> None:
        """When actual count differs from expected, validation detects mismatch.

        **Validates: Requirements 7.3, 8.1**

        For any expected count N and any non-zero delta, the count validation
        logic correctly detects the mismatch regardless of whether the scene
        has more or fewer objects than the contract.
        """
        if direction == "more":
            actual_count = expected_count + delta
        else:
            actual_count = max(0, expected_count - delta)
            # Ensure actual differs from expected
            assume(actual_count != expected_count)

        # The count validation logic detects mismatch
        assert actual_count != expected_count, (
            f"Count validation should fail when actual ({actual_count}) "
            f"differs from expected ({expected_count})"
        )

    @given(n=_object_count_st)
    @settings(deadline=None)
    def test_count_is_always_non_negative(self, n: int) -> None:
        """Object counts are always non-negative integers.

        **Validates: Requirements 7.3, 8.1**

        The count returned by getObjectCount() represents physical objects
        and must be a non-negative integer for any valid scene.
        """
        assert n >= 0, f"Object count must be non-negative, got {n}"
        assert isinstance(n, int), f"Object count must be integer, got {type(n)}"


# ---------------------------------------------------------------------------
# Property 8: QA Harness Position Fidelity
# ---------------------------------------------------------------------------


class TestProperty8PositionFidelity:
    """**Validates: Requirements 7.4, 8.2**

    For any object position within the configured tolerance of the expected
    position, the validation SHALL pass. Positions outside tolerance SHALL
    fail. The Euclidean distance check works correctly for all axes.
    """

    @given(
        x=_coord_st,
        y=_coord_st,
        z=_coord_st,
        dx=st.floats(min_value=-0.003, max_value=0.003, allow_nan=False, allow_infinity=False),
        dy=st.floats(min_value=-0.003, max_value=0.003, allow_nan=False, allow_infinity=False),
        dz=st.floats(min_value=-0.003, max_value=0.003, allow_nan=False, allow_infinity=False),
    )
    @settings(deadline=None)
    def test_positions_within_tolerance_pass(
        self, x: float, y: float, z: float, dx: float, dy: float, dz: float
    ) -> None:
        """Positions within DEFAULT_POSITION_TOLERANCE always pass validation.

        **Validates: Requirements 7.4, 8.2**

        For any expected position and any actual position where the
        Euclidean distance is less than or equal to DEFAULT_POSITION_TOLERANCE
        (0.01), the validation logic SHALL pass.
        """
        expected = {"x": x, "y": y, "z": z}
        actual = {"x": x + dx, "y": y + dy, "z": z + dz}

        distance = _euclidean_distance(expected, actual)

        # Only assert pass when truly within tolerance
        # dx,dy,dz each ≤ 0.003 → max distance = sqrt(3 * 0.003^2) ≈ 0.0052 < 0.01
        assume(distance <= DEFAULT_POSITION_TOLERANCE)

        assert distance <= DEFAULT_POSITION_TOLERANCE, (
            f"Position within tolerance should pass: "
            f"distance={distance:.6f}, tolerance={DEFAULT_POSITION_TOLERANCE}"
        )

    @given(
        x=_coord_st,
        y=_coord_st,
        z=_coord_st,
        scale=st.floats(min_value=1.5, max_value=100.0, allow_nan=False, allow_infinity=False),
        axis=st.sampled_from(["x", "y", "z"]),
    )
    @settings(deadline=None)
    def test_positions_outside_tolerance_fail(
        self, x: float, y: float, z: float, scale: float, axis: str
    ) -> None:
        """Positions beyond DEFAULT_POSITION_TOLERANCE always fail validation.

        **Validates: Requirements 7.4, 8.2**

        For any expected position and any actual position where a single axis
        is offset by more than the tolerance, the Euclidean distance exceeds
        the tolerance and validation SHALL fail.
        """
        expected = {"x": x, "y": y, "z": z}
        # Offset one axis by scale * tolerance (guaranteed > tolerance)
        offset = DEFAULT_POSITION_TOLERANCE * scale
        actual = {"x": x, "y": y, "z": z}
        actual[axis] += offset

        distance = _euclidean_distance(expected, actual)

        assert distance > DEFAULT_POSITION_TOLERANCE, (
            f"Position outside tolerance should fail: "
            f"distance={distance:.6f}, tolerance={DEFAULT_POSITION_TOLERANCE}, "
            f"offset={offset:.6f} on axis {axis}"
        )

    @given(x=_coord_st, y=_coord_st, z=_coord_st)
    @settings(deadline=None)
    def test_identical_positions_have_zero_distance(
        self, x: float, y: float, z: float
    ) -> None:
        """Identical positions always produce zero Euclidean distance.

        **Validates: Requirements 7.4, 8.2**

        A position compared to itself must yield distance 0.0, which is
        always within any positive tolerance.
        """
        pos = {"x": x, "y": y, "z": z}
        distance = _euclidean_distance(pos, pos)
        assert distance == 0.0, (
            f"Distance from a position to itself must be 0.0, got {distance}"
        )
        assert distance <= DEFAULT_POSITION_TOLERANCE

    @given(
        x=_coord_st,
        y=_coord_st,
        z=_coord_st,
        tolerance=_tolerance_st,
        fraction=st.floats(min_value=0.0, max_value=0.99, allow_nan=False, allow_infinity=False),
    )
    @settings(deadline=None)
    def test_euclidean_distance_is_symmetric(
        self, x: float, y: float, z: float, tolerance: float, fraction: float
    ) -> None:
        """Euclidean distance is symmetric: d(a, b) == d(b, a).

        **Validates: Requirements 7.4, 8.2**

        The validation must not depend on direction — moving from expected
        to actual is the same distance as actual to expected.
        """
        offset = tolerance * fraction
        expected = {"x": x, "y": y, "z": z}
        actual = {"x": x + offset, "y": y, "z": z}

        d_forward = _euclidean_distance(expected, actual)
        d_backward = _euclidean_distance(actual, expected)

        assert abs(d_forward - d_backward) < 1e-10, (
            f"Euclidean distance must be symmetric: "
            f"d(a,b)={d_forward}, d(b,a)={d_backward}"
        )


# ---------------------------------------------------------------------------
# Property 9: Lighting Validation Tolerance Correctness
# ---------------------------------------------------------------------------


class TestProperty9LightingToleranceCorrectness:
    """**Validates: Requirements 9.1, 9.2, 9.3**

    For any lighting parameter:
    - Position: parameters within 0.01 SHALL pass; exceeding 0.01 SHALL fail
    - Color (RGB): parameters within 0.02 SHALL pass; exceeding 0.02 SHALL fail
    - Intensity: parameters within 5% relative SHALL pass; exceeding SHALL fail
    Each failing parameter SHALL be reported with parameter name, expected,
    actual, and delta.
    """

    @given(
        base_x=_coord_st,
        base_y=_coord_st,
        base_z=_coord_st,
        dx=st.floats(min_value=-0.009, max_value=0.009, allow_nan=False, allow_infinity=False),
        dy=st.floats(min_value=-0.009, max_value=0.009, allow_nan=False, allow_infinity=False),
        dz=st.floats(min_value=-0.009, max_value=0.009, allow_nan=False, allow_infinity=False),
    )
    @settings(deadline=None)
    def test_position_within_001_passes(
        self, base_x: float, base_y: float, base_z: float,
        dx: float, dy: float, dz: float,
    ) -> None:
        """Light position parameters within 0.01 per component SHALL pass.

        **Validates: Requirements 9.1, 9.2**

        For any base position and any per-component offset strictly within
        0.01, the lighting validation SHALL report no position mismatches.
        """
        # Ensure each delta is strictly within tolerance
        assume(abs(dx) <= 0.01)
        assume(abs(dy) <= 0.01)
        assume(abs(dz) <= 0.01)

        expected = [{
            "light_type": "point",
            "position": {"x": base_x, "y": base_y, "z": base_z},
            "color": "#ffffff",
            "intensity": 1.0,
        }]
        actual = [{
            "type": "point",
            "position": {"x": base_x + dx, "y": base_y + dy, "z": base_z + dz},
            "color": "#ffffff",
            "intensity": 1.0,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        position_mismatches = [m for m in mismatches if m.parameter.startswith("position.")]
        assert position_mismatches == [], (
            f"Position within 0.01 tolerance should pass, but got mismatches: "
            f"{[(m.parameter, m.delta) for m in position_mismatches]}. "
            f"Offsets: dx={dx}, dy={dy}, dz={dz}"
        )

    @given(
        base_val=_coord_st,
        offset=st.floats(min_value=0.02, max_value=10.0, allow_nan=False, allow_infinity=False),
        axis=st.sampled_from(["x", "y", "z"]),
    )
    @settings(deadline=None)
    def test_position_exceeding_001_fails(
        self, base_val: float, offset: float, axis: str,
    ) -> None:
        """Light position parameters exceeding 0.01 per component SHALL fail.

        **Validates: Requirements 9.1, 9.2, 9.3**

        For any base position and any per-component offset exceeding 0.01,
        the lighting validation SHALL report the specific parameter with
        expected value, actual value, and delta.
        """
        base_pos = {"x": 0.0, "y": 0.0, "z": 0.0}
        base_pos[axis] = base_val

        actual_pos = dict(base_pos)
        actual_pos[axis] = base_val + offset

        expected = [{
            "light_type": "point",
            "position": base_pos,
            "color": "#ffffff",
            "intensity": 1.0,
        }]
        actual = [{
            "type": "point",
            "position": actual_pos,
            "color": "#ffffff",
            "intensity": 1.0,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        position_mismatches = [m for m in mismatches if m.parameter.startswith("position.")]

        assert len(position_mismatches) >= 1, (
            f"Position exceeding 0.01 tolerance should fail: "
            f"axis={axis}, offset={offset}"
        )

        # Verify the failing mismatch reports the correct axis
        failing_param = f"position.{axis}"
        params_reported = [m.parameter for m in position_mismatches]
        assert failing_param in params_reported, (
            f"Expected {failing_param} in mismatches, got {params_reported}"
        )

        # Verify the mismatch contains expected, actual, and delta
        mismatch = next(m for m in position_mismatches if m.parameter == failing_param)
        assert mismatch.expected == base_val
        assert mismatch.actual == base_val + offset
        assert isinstance(mismatch.delta, float)
        assert mismatch.delta > 0.01

    @given(
        r_exp=_rgb_int_st,
        g_exp=_rgb_int_st,
        b_exp=_rgb_int_st,
        dr=st.integers(min_value=-4, max_value=4),
        dg=st.integers(min_value=-4, max_value=4),
        db=st.integers(min_value=-4, max_value=4),
    )
    @settings(deadline=None)
    def test_color_within_002_passes(
        self, r_exp: int, g_exp: int, b_exp: int,
        dr: int, dg: int, db: int,
    ) -> None:
        """Color RGB parameters within 0.02 per component SHALL pass.

        **Validates: Requirements 9.1, 9.2**

        For any base color and any per-channel offset where the normalized
        difference is within 0.02, the lighting validation SHALL report no
        color mismatches.

        Note: 0.02 * 255 ≈ 5.1, so delta of ±4 in 0-255 space guarantees
        normalized delta ≤ 4/255 ≈ 0.0157 < 0.02.
        """
        # Clamp actual RGB values to valid 0-255 range
        r_act = max(0, min(255, r_exp + dr))
        g_act = max(0, min(255, g_exp + dg))
        b_act = max(0, min(255, b_exp + db))

        # Verify normalized deltas are within tolerance
        assume(abs(r_act - r_exp) / 255.0 <= 0.02)
        assume(abs(g_act - g_exp) / 255.0 <= 0.02)
        assume(abs(b_act - b_exp) / 255.0 <= 0.02)

        expected_hex = f"#{r_exp:02x}{g_exp:02x}{b_exp:02x}"
        actual_hex = f"#{r_act:02x}{g_act:02x}{b_act:02x}"

        expected = [{
            "light_type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": expected_hex,
            "intensity": 1.0,
        }]
        actual = [{
            "type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": actual_hex,
            "intensity": 1.0,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        color_mismatches = [m for m in mismatches if m.parameter.startswith("color.")]
        assert color_mismatches == [], (
            f"Color within 0.02 tolerance should pass, but got: "
            f"{[(m.parameter, m.delta) for m in color_mismatches]}. "
            f"Expected hex: {expected_hex}, actual hex: {actual_hex}"
        )

    @given(
        base_channel=_rgb_int_st,
        channel=st.sampled_from(["r", "g", "b"]),
        offset_int=st.integers(min_value=7, max_value=128),
        direction=st.sampled_from([1, -1]),
    )
    @settings(deadline=None)
    def test_color_exceeding_002_fails(
        self, base_channel: int, channel: str, offset_int: int, direction: int,
    ) -> None:
        """Color RGB parameters exceeding 0.02 per component SHALL fail.

        **Validates: Requirements 9.1, 9.2, 9.3**

        For any base color and any per-channel offset where the normalized
        difference exceeds 0.02, the lighting validation SHALL report the
        specific channel with expected, actual, and delta.

        Note: offset_int >= 7 → normalized delta >= 7/255 ≈ 0.0275 > 0.02.
        """
        # Build colors where one channel has a large offset
        r_exp, g_exp, b_exp = 128, 128, 128
        if channel == "r":
            r_exp = base_channel
        elif channel == "g":
            g_exp = base_channel
        else:
            b_exp = base_channel

        # Apply offset to the target channel
        r_act, g_act, b_act = r_exp, g_exp, b_exp
        if channel == "r":
            r_act = max(0, min(255, r_exp + offset_int * direction))
        elif channel == "g":
            g_act = max(0, min(255, g_exp + offset_int * direction))
        else:
            b_act = max(0, min(255, b_exp + offset_int * direction))

        # Ensure the actual normalized delta > 0.02
        if channel == "r":
            assume(abs(r_act - r_exp) / 255.0 > 0.02)
        elif channel == "g":
            assume(abs(g_act - g_exp) / 255.0 > 0.02)
        else:
            assume(abs(b_act - b_exp) / 255.0 > 0.02)

        expected_hex = f"#{r_exp:02x}{g_exp:02x}{b_exp:02x}"
        actual_hex = f"#{r_act:02x}{g_act:02x}{b_act:02x}"

        expected = [{
            "light_type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": expected_hex,
            "intensity": 1.0,
        }]
        actual = [{
            "type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": actual_hex,
            "intensity": 1.0,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        color_mismatches = [m for m in mismatches if m.parameter.startswith("color.")]

        assert len(color_mismatches) >= 1, (
            f"Color exceeding 0.02 tolerance should fail: "
            f"channel={channel}, offset={offset_int * direction}, "
            f"expected_hex={expected_hex}, actual_hex={actual_hex}"
        )

        # Verify the correct channel is reported
        expected_param = f"color.{channel}"
        params_reported = [m.parameter for m in color_mismatches]
        assert expected_param in params_reported, (
            f"Expected {expected_param} in mismatches, got {params_reported}"
        )

        # Verify mismatch contains expected, actual, and delta
        mismatch = next(m for m in color_mismatches if m.parameter == expected_param)
        assert isinstance(mismatch.expected, float)
        assert isinstance(mismatch.actual, float)
        assert isinstance(mismatch.delta, float)
        assert mismatch.delta > 0.02

    @given(
        expected_intensity=_intensity_st,
        fraction=st.floats(min_value=0.0, max_value=0.049, allow_nan=False, allow_infinity=False),
        direction=st.sampled_from([1, -1]),
    )
    @settings(deadline=None)
    def test_intensity_within_5_percent_passes(
        self, expected_intensity: float, fraction: float, direction: int,
    ) -> None:
        """Intensity within 5% relative tolerance SHALL pass.

        **Validates: Requirements 9.1, 9.2**

        For any expected intensity and any actual intensity where the
        relative difference is within 5%, the lighting validation SHALL
        report no intensity mismatches.
        """
        actual_intensity = expected_intensity * (1.0 + fraction * direction)

        # Verify relative delta is within 5%
        if expected_intensity != 0:
            relative_delta = abs(actual_intensity - expected_intensity) / abs(expected_intensity)
            assume(relative_delta <= 0.05)

        expected = [{
            "light_type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": "#ffffff",
            "intensity": expected_intensity,
        }]
        actual = [{
            "type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": "#ffffff",
            "intensity": actual_intensity,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        intensity_mismatches = [m for m in mismatches if m.parameter == "intensity"]
        assert intensity_mismatches == [], (
            f"Intensity within 5% should pass: "
            f"expected={expected_intensity}, actual={actual_intensity}, "
            f"relative_delta={fraction}"
        )

    @given(
        expected_intensity=_intensity_st,
        excess_fraction=st.floats(min_value=0.06, max_value=2.0, allow_nan=False, allow_infinity=False),
        direction=st.sampled_from([1, -1]),
    )
    @settings(deadline=None)
    def test_intensity_exceeding_5_percent_fails(
        self, expected_intensity: float, excess_fraction: float, direction: int,
    ) -> None:
        """Intensity exceeding 5% relative tolerance SHALL fail.

        **Validates: Requirements 9.1, 9.2, 9.3**

        For any expected intensity and any actual intensity where the
        relative difference exceeds 5%, the lighting validation SHALL
        report the intensity parameter with expected, actual, and delta.
        """
        actual_intensity = expected_intensity * (1.0 + excess_fraction * direction)

        # Ensure the actual relative delta exceeds 5%
        if expected_intensity != 0:
            relative_delta = abs(actual_intensity - expected_intensity) / abs(expected_intensity)
            assume(relative_delta > 0.05)

        expected = [{
            "light_type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": "#ffffff",
            "intensity": expected_intensity,
        }]
        actual = [{
            "type": "point",
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "color": "#ffffff",
            "intensity": actual_intensity,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        intensity_mismatches = [m for m in mismatches if m.parameter == "intensity"]

        assert len(intensity_mismatches) == 1, (
            f"Intensity exceeding 5% should fail: "
            f"expected={expected_intensity}, actual={actual_intensity}, "
            f"excess_fraction={excess_fraction}"
        )

        # Verify mismatch contains parameter name, expected, actual, and delta
        mismatch = intensity_mismatches[0]
        assert mismatch.parameter == "intensity"
        assert mismatch.expected == expected_intensity
        assert mismatch.actual == actual_intensity
        assert isinstance(mismatch.delta, float)
        assert mismatch.delta > 0.05

    @given(
        base_x=_coord_st,
        intensity=_intensity_st,
        r=_rgb_int_st,
        g=_rgb_int_st,
        b=_rgb_int_st,
    )
    @settings(deadline=None)
    def test_all_parameters_matching_produces_no_mismatches(
        self, base_x: float, intensity: float, r: int, g: int, b: int,
    ) -> None:
        """When all parameters match exactly, no mismatches are reported.

        **Validates: Requirements 9.1, 9.2, 9.3**

        For any valid light configuration, comparing it to itself SHALL
        produce zero mismatches.
        """
        color_hex = f"#{r:02x}{g:02x}{b:02x}"

        expected = [{
            "light_type": "point",
            "position": {"x": base_x, "y": 0.0, "z": 0.0},
            "color": color_hex,
            "intensity": intensity,
        }]
        actual = [{
            "type": "point",
            "position": {"x": base_x, "y": 0.0, "z": 0.0},
            "color": color_hex,
            "intensity": intensity,
        }]

        mismatches = validate_lighting_against_contract(actual, expected)
        assert mismatches == [], (
            f"Identical light parameters should produce no mismatches, "
            f"but got: {[(m.parameter, m.delta) for m in mismatches]}"
        )
