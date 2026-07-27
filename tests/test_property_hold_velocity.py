"""Property-based tests for held object velocity direction (Property 10).

**Validates: Requirements 4.6**

Property 10: Held Object Velocity Direction
- For any grabbed object position P and camera state (C, F, D), velocity SHALL
  point from P toward (C + F * D) with magnitude proportional to distance.
"""

from __future__ import annotations

import math

from hypothesis import given, settings, assume, strategies as st

from src.upbge_runtime import compute_hold_velocity


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_coord = st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False)

_pos_3d = st.tuples(_coord, _coord, _coord)


@st.composite
def unit_vector_3d(draw):
    """Generate a 3D unit vector by drawing 3 floats and normalizing."""
    x = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    y = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    z = draw(st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    length = math.sqrt(x * x + y * y + z * z)
    assume(length > 1e-6)
    return (x / length, y / length, z / length)


_hold_distance = st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Property 10: Held Object Velocity Direction
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(
    obj_pos=_pos_3d,
    cam_pos=_pos_3d,
    cam_forward=unit_vector_3d(),
    hold_distance=_hold_distance,
)
def test_property_10_velocity_direction_matches_target(
    obj_pos: tuple, cam_pos: tuple, cam_forward: tuple, hold_distance: float
):
    """Property 10: Velocity direction points from obj_pos toward target.

    **Validates: Requirements 4.6**

    The velocity vector must be parallel to (target - obj_pos) and point
    in the same direction (positive dot product with displacement).
    """
    # Compute target = cam_pos + cam_forward * hold_distance
    target = (
        cam_pos[0] + cam_forward[0] * hold_distance,
        cam_pos[1] + cam_forward[1] * hold_distance,
        cam_pos[2] + cam_forward[2] * hold_distance,
    )

    # Displacement from obj_pos to target
    disp = (
        target[0] - obj_pos[0],
        target[1] - obj_pos[1],
        target[2] - obj_pos[2],
    )
    disp_mag = math.sqrt(disp[0] ** 2 + disp[1] ** 2 + disp[2] ** 2)

    # Skip degenerate case where obj is already at target
    assume(disp_mag > 1e-9)

    velocity = compute_hold_velocity(obj_pos, cam_pos, cam_forward, hold_distance)

    vel_mag = math.sqrt(velocity[0] ** 2 + velocity[1] ** 2 + velocity[2] ** 2)
    assume(vel_mag > 1e-9)

    # Normalize both vectors
    disp_norm = (disp[0] / disp_mag, disp[1] / disp_mag, disp[2] / disp_mag)
    vel_norm = (velocity[0] / vel_mag, velocity[1] / vel_mag, velocity[2] / vel_mag)

    # Dot product should be ~1.0 (same direction)
    dot = (
        disp_norm[0] * vel_norm[0]
        + disp_norm[1] * vel_norm[1]
        + disp_norm[2] * vel_norm[2]
    )

    assert dot > 0.999, (
        f"Velocity must point toward target. dot={dot}, "
        f"obj_pos={obj_pos}, target={target}, velocity={velocity}"
    )


@settings(max_examples=300, deadline=None)
@given(
    obj_pos=_pos_3d,
    cam_pos=_pos_3d,
    cam_forward=unit_vector_3d(),
    hold_distance=_hold_distance,
)
def test_property_10_velocity_magnitude_proportional_to_distance(
    obj_pos: tuple, cam_pos: tuple, cam_forward: tuple, hold_distance: float
):
    """Property 10: Velocity magnitude equals distance * 10.0.

    **Validates: Requirements 4.6**

    The magnitude of the velocity vector must be exactly the Euclidean
    distance from obj_pos to target multiplied by the constant factor 10.0.
    """
    # Compute target = cam_pos + cam_forward * hold_distance
    target = (
        cam_pos[0] + cam_forward[0] * hold_distance,
        cam_pos[1] + cam_forward[1] * hold_distance,
        cam_pos[2] + cam_forward[2] * hold_distance,
    )

    # Euclidean distance from obj_pos to target
    distance = math.sqrt(
        (target[0] - obj_pos[0]) ** 2
        + (target[1] - obj_pos[1]) ** 2
        + (target[2] - obj_pos[2]) ** 2
    )

    velocity = compute_hold_velocity(obj_pos, cam_pos, cam_forward, hold_distance)

    vel_mag = math.sqrt(velocity[0] ** 2 + velocity[1] ** 2 + velocity[2] ** 2)

    expected_mag = distance * 10.0

    # Allow small floating-point tolerance
    assert abs(vel_mag - expected_mag) < 1e-6, (
        f"Velocity magnitude must be distance * 10.0. "
        f"vel_mag={vel_mag}, expected={expected_mag}, distance={distance}"
    )


@settings(max_examples=300, deadline=None)
@given(
    cam_pos=_pos_3d,
    cam_forward=unit_vector_3d(),
    hold_distance=_hold_distance,
)
def test_property_10_at_target_produces_zero_velocity(
    cam_pos: tuple, cam_forward: tuple, hold_distance: float
):
    """Property 10: When obj_pos == target, velocity is (0, 0, 0).

    **Validates: Requirements 4.6**

    If the grabbed object is already at the target hold position,
    the applied velocity must be zero (no movement needed).
    """
    # obj_pos IS the target
    obj_pos = (
        cam_pos[0] + cam_forward[0] * hold_distance,
        cam_pos[1] + cam_forward[1] * hold_distance,
        cam_pos[2] + cam_forward[2] * hold_distance,
    )

    velocity = compute_hold_velocity(obj_pos, cam_pos, cam_forward, hold_distance)

    assert velocity[0] == 0.0, f"vx must be 0.0 at target, got {velocity[0]}"
    assert velocity[1] == 0.0, f"vy must be 0.0 at target, got {velocity[1]}"
    assert velocity[2] == 0.0, f"vz must be 0.0 at target, got {velocity[2]}"
