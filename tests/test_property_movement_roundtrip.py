"""Property-based tests for movement round-trip (Property 6).

**Validates: Requirements 2.9**

Property 6: Movement Round-Trip
- For any valid move_speed and unit direction, N frames forward + N frames
  reverse → final position within 0.01 units of start (no collision/gravity).
"""

from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import compute_movement_vector


# ---------------------------------------------------------------------------
# Valid direction key combinations that produce non-zero movement.
# Excludes: all-off, contradictory-only (W+S with no A/D, A+D with no W/S).
# ---------------------------------------------------------------------------

VALID_FORWARD_KEYS = [
    {"w": True, "s": False, "a": False, "d": False},   # forward
    {"w": False, "s": True, "a": False, "d": False},   # backward
    {"w": False, "s": False, "a": True, "d": False},   # left
    {"w": False, "s": False, "a": False, "d": True},   # right
    {"w": True, "s": False, "a": True, "d": False},    # forward-left
    {"w": True, "s": False, "a": False, "d": True},    # forward-right
    {"w": False, "s": True, "a": True, "d": False},    # backward-left
    {"w": False, "s": True, "a": False, "d": True},    # backward-right
]


def _reverse_keys(forward: dict) -> dict:
    """Compute the opposite direction keys: W↔S, A↔D."""
    return {
        "w": forward.get("s", False),
        "s": forward.get("w", False),
        "a": forward.get("d", False),
        "d": forward.get("a", False),
    }


# ---------------------------------------------------------------------------
# Property 6: Movement Round-Trip
# ---------------------------------------------------------------------------


@settings(max_examples=300, deadline=None)
@given(
    speed=st.floats(min_value=0.1, max_value=20.0, allow_nan=False, allow_infinity=False),
    n_frames=st.integers(min_value=1, max_value=600),
    direction=st.sampled_from(VALID_FORWARD_KEYS),
)
def test_property_6_movement_round_trip(
    speed: float, n_frames: int, direction: dict
):
    """N frames forward + N frames reverse → position within 0.01 of start.

    **Validates: Requirements 2.9**

    Without collision or gravity, moving in one direction for N frames
    then in the exact opposite direction for N frames should cancel out,
    returning the position to within floating-point tolerance of the origin.
    """
    # Accumulate position going forward
    pos_x, pos_y, pos_z = 0.0, 0.0, 0.0

    for _ in range(n_frames):
        dx, dy, dz = compute_movement_vector(direction, speed)
        pos_x += dx
        pos_y += dy
        pos_z += dz

    # Accumulate position going in reverse
    reverse = _reverse_keys(direction)
    for _ in range(n_frames):
        dx, dy, dz = compute_movement_vector(reverse, speed)
        pos_x += dx
        pos_y += dy
        pos_z += dz

    # Final position should be within 0.01 of origin
    distance = math.sqrt(pos_x * pos_x + pos_y * pos_y + pos_z * pos_z)
    assert distance < 0.01, (
        f"Round-trip failed: final position ({pos_x:.6f}, {pos_y:.6f}, {pos_z:.6f}), "
        f"distance={distance:.6f} (speed={speed}, n_frames={n_frames}, "
        f"direction={direction})"
    )
