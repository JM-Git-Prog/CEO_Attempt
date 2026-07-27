"""Property-based tests for movement direction relative to orientation (Property 2).

**Validates: Requirements 2.2, 2.7**

Property 2: Movement Direction Relative to Orientation
- For any keyboard state (W/A/S/D combination) and player orientation, the
  computed movement vector SHALL have correct direction relative to local frame,
  and magnitude = move_speed / 60.0 when keys pressed, or zero otherwise.
"""

from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st
from hypothesis.strategies import composite

from src.upbge_runtime import compute_movement_vector


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@composite
def wasd_keys(draw):
    """Generate all 16 possible WASD key combinations."""
    w = draw(st.booleans())
    a = draw(st.booleans())
    s = draw(st.booleans())
    d = draw(st.booleans())
    return {"w": w, "a": a, "s": s, "d": d}


SPEED_STRATEGY = st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property 2: Movement Direction Relative to Orientation
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(keys=wasd_keys(), speed=SPEED_STRATEGY)
def test_property_2_magnitude_and_zero(keys: dict, speed: float):
    """Property 2: Movement magnitude equals speed/60 when keys pressed, zero otherwise.

    **Validates: Requirements 2.2, 2.7**

    For any WASD key combination and valid speed, the computed movement vector
    has magnitude == speed / 60.0 when any movement key is pressed, or is exactly
    (0, 0, 0) when no keys are pressed.
    """
    result = compute_movement_vector(keys, speed)
    x, y, z = result

    any_key_pressed = keys["w"] or keys["a"] or keys["s"] or keys["d"]

    # Opposing keys cancel out — check if net input is zero
    dx = 0.0
    dy = 0.0
    if keys["w"]:
        dy += 1.0
    if keys["s"]:
        dy -= 1.0
    if keys["a"]:
        dx -= 1.0
    if keys["d"]:
        dx += 1.0
    net_input_zero = (dx == 0.0 and dy == 0.0)

    if not any_key_pressed or net_input_zero:
        # No keys pressed or opposing keys cancel → zero vector
        assert result == (0.0, 0.0, 0.0), (
            f"Expected zero vector when no net input, got {result}"
        )
    else:
        # Keys pressed with net direction → magnitude should be speed / 60.0
        magnitude = math.sqrt(x * x + y * y)
        expected_magnitude = speed / 60.0
        assert abs(magnitude - expected_magnitude) < 1e-10, (
            f"Expected magnitude {expected_magnitude}, got {magnitude} "
            f"(diff={abs(magnitude - expected_magnitude)})"
        )


@settings(max_examples=500, deadline=None)
@given(keys=wasd_keys(), speed=SPEED_STRATEGY)
def test_property_2_z_always_zero(keys: dict, speed: float):
    """Property 2: Z component is always zero.

    **Validates: Requirements 2.2, 2.7**

    For any WASD key combination and speed, the z component of the movement
    vector is always exactly 0.0 (movement is in the XY plane).
    """
    result = compute_movement_vector(keys, speed)
    assert result[2] == 0.0, f"Z component should be 0.0, got {result[2]}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_w_only(speed: float):
    """Property 2: W alone produces positive Y, zero X.

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": True, "a": False, "s": False, "d": False}
    x, y, z = compute_movement_vector(keys, speed)
    assert y > 0, f"W alone: expected y > 0, got y={y}"
    assert abs(x) < 1e-10, f"W alone: expected x == 0, got x={x}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_s_only(speed: float):
    """Property 2: S alone produces negative Y, zero X.

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": False, "a": False, "s": True, "d": False}
    x, y, z = compute_movement_vector(keys, speed)
    assert y < 0, f"S alone: expected y < 0, got y={y}"
    assert abs(x) < 1e-10, f"S alone: expected x == 0, got x={x}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_a_only(speed: float):
    """Property 2: A alone produces negative X, zero Y.

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": False, "a": True, "s": False, "d": False}
    x, y, z = compute_movement_vector(keys, speed)
    assert x < 0, f"A alone: expected x < 0, got x={x}"
    assert abs(y) < 1e-10, f"A alone: expected y == 0, got y={y}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_d_only(speed: float):
    """Property 2: D alone produces positive X, zero Y.

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": False, "a": False, "s": False, "d": True}
    x, y, z = compute_movement_vector(keys, speed)
    assert x > 0, f"D alone: expected x > 0, got x={x}"
    assert abs(y) < 1e-10, f"D alone: expected y == 0, got y={y}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_w_d_diagonal(speed: float):
    """Property 2: W+D produces positive X and positive Y (normalized diagonal).

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": True, "a": False, "s": False, "d": True}
    x, y, z = compute_movement_vector(keys, speed)
    assert x > 0, f"W+D: expected x > 0, got x={x}"
    assert y > 0, f"W+D: expected y > 0, got y={y}"
    # Diagonal should be normalized: x == y for 45 degree movement
    assert abs(x - y) < 1e-10, f"W+D diagonal: expected x == y, got x={x}, y={y}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_w_a_diagonal(speed: float):
    """Property 2: W+A produces negative X and positive Y (normalized diagonal).

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": True, "a": True, "s": False, "d": False}
    x, y, z = compute_movement_vector(keys, speed)
    assert x < 0, f"W+A: expected x < 0, got x={x}"
    assert y > 0, f"W+A: expected y > 0, got y={y}"
    # Diagonal: |x| == y
    assert abs(abs(x) - y) < 1e-10, f"W+A diagonal: expected |x| == y, got x={x}, y={y}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_s_d_diagonal(speed: float):
    """Property 2: S+D produces positive X and negative Y (normalized diagonal).

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": False, "a": False, "s": True, "d": True}
    x, y, z = compute_movement_vector(keys, speed)
    assert x > 0, f"S+D: expected x > 0, got x={x}"
    assert y < 0, f"S+D: expected y < 0, got y={y}"
    # Diagonal: x == |y|
    assert abs(x - abs(y)) < 1e-10, f"S+D diagonal: expected x == |y|, got x={x}, y={y}"


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_direction_s_a_diagonal(speed: float):
    """Property 2: S+A produces negative X and negative Y (normalized diagonal).

    **Validates: Requirements 2.2, 2.7**
    """
    keys = {"w": False, "a": True, "s": True, "d": False}
    x, y, z = compute_movement_vector(keys, speed)
    assert x < 0, f"S+A: expected x < 0, got x={x}"
    assert y < 0, f"S+A: expected y < 0, got y={y}"
    # Diagonal: |x| == |y|
    assert abs(abs(x) - abs(y)) < 1e-10, (
        f"S+A diagonal: expected |x| == |y|, got x={x}, y={y}"
    )


@settings(max_examples=500, deadline=None)
@given(speed=SPEED_STRATEGY)
def test_property_2_opposing_keys_cancel(speed: float):
    """Property 2: W+S or A+D opposing keys cancel to zero.

    **Validates: Requirements 2.2, 2.7**
    """
    # W+S cancels Y
    keys_ws = {"w": True, "a": False, "s": True, "d": False}
    assert compute_movement_vector(keys_ws, speed) == (0.0, 0.0, 0.0), (
        "W+S should cancel to zero"
    )

    # A+D cancels X
    keys_ad = {"w": False, "a": True, "s": False, "d": True}
    assert compute_movement_vector(keys_ad, speed) == (0.0, 0.0, 0.0), (
        "A+D should cancel to zero"
    )

    # All four keys cancel everything
    keys_all = {"w": True, "a": True, "s": True, "d": True}
    assert compute_movement_vector(keys_all, speed) == (0.0, 0.0, 0.0), (
        "All keys should cancel to zero"
    )
