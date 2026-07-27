"""Property-based tests for mouse look delta with pitch clamping (Property 3).

**Validates: Requirements 2.3**

Property 3: Mouse Look Delta with Pitch Clamping
- For any mouse position delta (dx, dy) and current camera pitch, resulting
  pitch SHALL be clamped to [-1.5, 1.5] radians, yaw change SHALL be
  proportional to dx * look_speed * 100.0.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import compute_look_delta


# ---------------------------------------------------------------------------
# Property 3: Mouse Look Delta with Pitch Clamping
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    mouse_dx=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    mouse_dy=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    current_pitch=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    look_speed=st.floats(min_value=0.0001, max_value=0.02, allow_nan=False, allow_infinity=False),
)
def test_property_3_yaw_proportional_to_dx(
    mouse_dx: float, mouse_dy: float, current_pitch: float, look_speed: float
):
    """Yaw change SHALL be exactly -mouse_dx * look_speed * 100.0.

    **Validates: Requirements 2.3**

    Yaw is unclamped and directly proportional to horizontal mouse delta.
    """
    yaw_change, _new_pitch = compute_look_delta(mouse_dx, mouse_dy, current_pitch, look_speed)
    expected_yaw = -mouse_dx * look_speed * 100.0
    assert yaw_change == expected_yaw, (
        f"Yaw mismatch: got {yaw_change}, expected {expected_yaw} "
        f"(dx={mouse_dx}, speed={look_speed})"
    )


@settings(max_examples=500, deadline=None)
@given(
    mouse_dx=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    mouse_dy=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    current_pitch=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    look_speed=st.floats(min_value=0.0001, max_value=0.02, allow_nan=False, allow_infinity=False),
)
def test_property_3_pitch_clamped_within_bounds(
    mouse_dx: float, mouse_dy: float, current_pitch: float, look_speed: float
):
    """Resulting pitch SHALL always be clamped to [-1.5, 1.5] radians.

    **Validates: Requirements 2.3**

    Regardless of current pitch or mouse delta, the output pitch never
    exceeds the clamp bounds.
    """
    _yaw_change, new_pitch = compute_look_delta(mouse_dx, mouse_dy, current_pitch, look_speed)
    assert -1.5 <= new_pitch <= 1.5, (
        f"Pitch out of bounds: {new_pitch} "
        f"(current_pitch={current_pitch}, dy={mouse_dy}, speed={look_speed})"
    )


@settings(max_examples=500, deadline=None)
@given(
    mouse_dx=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    current_pitch=st.floats(min_value=-1.5, max_value=1.5, allow_nan=False, allow_infinity=False),
    look_speed=st.floats(min_value=0.0001, max_value=0.02, allow_nan=False, allow_infinity=False),
)
def test_property_3_zero_dy_preserves_pitch(
    mouse_dx: float, current_pitch: float, look_speed: float
):
    """When mouse_dy == 0 and current_pitch is within bounds, pitch is unchanged.

    **Validates: Requirements 2.3**

    No vertical mouse movement means no pitch change when already in bounds.
    """
    _yaw_change, new_pitch = compute_look_delta(mouse_dx, 0.0, current_pitch, look_speed)
    assert new_pitch == current_pitch, (
        f"Pitch changed with zero dy: got {new_pitch}, expected {current_pitch}"
    )


@settings(max_examples=500, deadline=None)
@given(
    mouse_dx=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    mouse_dy=st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
    current_pitch=st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False),
    look_speed=st.floats(min_value=0.0001, max_value=0.02, allow_nan=False, allow_infinity=False),
    scale=st.floats(min_value=0.1, max_value=10.0, allow_nan=False, allow_infinity=False),
)
def test_property_3_yaw_linear_in_dx(
    mouse_dx: float, mouse_dy: float, current_pitch: float, look_speed: float, scale: float
):
    """Yaw is linear: scaling dx by k scales yaw by k.

    **Validates: Requirements 2.3**

    Demonstrates the proportional (linear) relationship between dx and yaw.
    """
    yaw_1, _ = compute_look_delta(mouse_dx, mouse_dy, current_pitch, look_speed)
    scaled_dx = mouse_dx * scale
    # Only test if scaled dx is within a reasonable range
    if abs(scaled_dx) <= 0.5:
        yaw_scaled, _ = compute_look_delta(scaled_dx, mouse_dy, current_pitch, look_speed)
        expected_scaled_yaw = yaw_1 * scale
        # Use relative tolerance for floating point
        if abs(expected_scaled_yaw) > 1e-10:
            assert abs(yaw_scaled - expected_scaled_yaw) / abs(expected_scaled_yaw) < 1e-9, (
                f"Yaw not linear: yaw({scaled_dx})={yaw_scaled}, "
                f"expected {expected_scaled_yaw} = {yaw_1} * {scale}"
            )
        else:
            assert abs(yaw_scaled - expected_scaled_yaw) < 1e-15, (
                f"Yaw not linear near zero: yaw({scaled_dx})={yaw_scaled}, "
                f"expected {expected_scaled_yaw}"
            )
