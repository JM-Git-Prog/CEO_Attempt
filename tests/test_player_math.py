"""Tests for src/player_math.py — pure math utilities for the player controller.

Covers:
- Movement speed normalization (Req 4.2)
- Vertical look angle clamping (Req 4.3)
- Spawn repositioning with spiral search (Req 4.7)
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.player_math import clamp_vertical_angle, find_spawn_position, normalize_movement


# ---------------------------------------------------------------------------
# Unit tests: normalize_movement
# ---------------------------------------------------------------------------


class TestNormalizeMovement:
    """Unit tests for normalize_movement (Req 4.2)."""

    def test_no_input_returns_zero(self):
        assert normalize_movement(0.0, 0.0, 5.0) == (0.0, 0.0)

    def test_single_axis_forward(self):
        vx, vy = normalize_movement(0.0, 1.0, 4.0)
        assert vx == pytest.approx(0.0)
        assert vy == pytest.approx(4.0)

    def test_single_axis_backward(self):
        vx, vy = normalize_movement(0.0, -1.0, 4.0)
        assert vx == pytest.approx(0.0)
        assert vy == pytest.approx(-4.0)

    def test_single_axis_right(self):
        vx, vy = normalize_movement(1.0, 0.0, 4.0)
        assert vx == pytest.approx(4.0)
        assert vy == pytest.approx(0.0)

    def test_diagonal_magnitude_equals_max_speed(self):
        """Diagonal input (two keys) must produce magnitude ≤ max_speed."""
        vx, vy = normalize_movement(1.0, 1.0, 4.0)
        mag = math.sqrt(vx**2 + vy**2)
        assert mag == pytest.approx(4.0)

    def test_diagonal_negative(self):
        vx, vy = normalize_movement(-1.0, -1.0, 6.0)
        mag = math.sqrt(vx**2 + vy**2)
        assert mag == pytest.approx(6.0)

    def test_zero_max_speed_returns_zero(self):
        assert normalize_movement(1.0, 1.0, 0.0) == (0.0, 0.0)

    def test_negative_max_speed_returns_zero(self):
        assert normalize_movement(1.0, 0.0, -2.0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# Unit tests: clamp_vertical_angle
# ---------------------------------------------------------------------------


class TestClampVerticalAngle:
    """Unit tests for clamp_vertical_angle (Req 4.3)."""

    def test_no_delta(self):
        assert clamp_vertical_angle(0.0, 0.0) == 0.0

    def test_within_bounds(self):
        assert clamp_vertical_angle(10.0, 5.0) == 15.0

    def test_clamp_to_positive_85(self):
        assert clamp_vertical_angle(80.0, 10.0) == 85.0

    def test_clamp_to_negative_85(self):
        assert clamp_vertical_angle(-80.0, -10.0) == -85.0

    def test_extreme_positive_delta(self):
        assert clamp_vertical_angle(0.0, 1000.0) == 85.0

    def test_extreme_negative_delta(self):
        assert clamp_vertical_angle(0.0, -1000.0) == -85.0

    def test_already_at_limit_positive(self):
        assert clamp_vertical_angle(85.0, 5.0) == 85.0

    def test_already_at_limit_negative(self):
        assert clamp_vertical_angle(-85.0, -5.0) == -85.0

    def test_negative_current_positive_delta(self):
        assert clamp_vertical_angle(-40.0, 20.0) == -20.0


# ---------------------------------------------------------------------------
# Unit tests: find_spawn_position
# ---------------------------------------------------------------------------


class TestFindSpawnPosition:
    """Unit tests for find_spawn_position (Req 4.7)."""

    def test_center_unobstructed(self):
        """When center is free, spawn there at eye_height."""
        pos = find_spawn_position(
            floor_center=(5.0, 5.0, 0.0),
            ceiling_height=3.0,
            room_bounds=(0.0, 0.0, 10.0, 10.0),
            obstacles=[],
            eye_height=1.7,
        )
        assert pos == (5.0, 5.0, 1.7)

    def test_center_obstructed_finds_nearby(self):
        """When center is blocked by a small obstacle, spiral finds adjacent point."""
        # Small obstacle: only covers the exact center point, not the 0.5m ring
        pos = find_spawn_position(
            floor_center=(5.0, 5.0, 0.0),
            ceiling_height=3.0,
            room_bounds=(0.0, 0.0, 10.0, 10.0),
            obstacles=[(4.9, 4.9, 5.1, 5.1)],  # tiny obstacle at center
            eye_height=1.7,
        )
        # Should find something at the first ring (0.5m radius)
        dx = pos[0] - 5.0
        dy = pos[1] - 5.0
        dist = math.sqrt(dx**2 + dy**2)
        assert dist == pytest.approx(0.5, abs=0.01)
        assert pos[2] == pytest.approx(1.7)

    def test_all_obstructed_falls_back_to_ceiling(self):
        """When all spiral attempts fail, fall back to ceiling - 0.5m."""
        # Create a massive obstacle covering the entire room
        pos = find_spawn_position(
            floor_center=(5.0, 5.0, 0.0),
            ceiling_height=3.0,
            room_bounds=(0.0, 0.0, 10.0, 10.0),
            obstacles=[(0.0, 0.0, 10.0, 10.0)],  # blocks everything
            eye_height=1.7,
        )
        assert pos == (5.0, 5.0, 2.5)  # ceiling_height - 0.5

    def test_center_outside_bounds(self):
        """When floor_center is itself outside room_bounds, spiral outward."""
        pos = find_spawn_position(
            floor_center=(0.0, 0.0, 0.0),
            ceiling_height=4.0,
            room_bounds=(1.0, 1.0, 5.0, 5.0),
            obstacles=[],
            eye_height=1.7,
        )
        # Center (0,0) is outside bounds (1,1,5,5), but spiral should find
        # a valid point within bounds
        min_x, min_y, max_x, max_y = 1.0, 1.0, 5.0, 5.0
        assert min_x <= pos[0] <= max_x
        assert min_y <= pos[1] <= max_y
        assert pos[2] == pytest.approx(1.7)

    def test_custom_eye_height(self):
        pos = find_spawn_position(
            floor_center=(3.0, 3.0, 1.0),
            ceiling_height=5.0,
            room_bounds=(0.0, 0.0, 6.0, 6.0),
            obstacles=[],
            eye_height=2.0,
        )
        assert pos == (3.0, 3.0, 3.0)  # floor_z + eye_height = 1.0 + 2.0

    def test_spiral_step_is_half_meter(self):
        """Verify spiral increments by 0.5m per ring."""
        # Obstruct center and first ring at 0.5m.
        # At ring 1 (0.5m), cardinal point E is (5.5, 5.0) — inside the obstacle.
        # Diagonal NE at 0.5m is (5.354, 5.354) — also inside.
        # At ring 2 (1.0m), cardinal E is (6.0, 5.0) — still inside AABB boundary.
        # Use an obstacle that covers up to 0.6m in each direction to block ring 1
        # but leave ring 2 (1.0m) free.
        pos = find_spawn_position(
            floor_center=(5.0, 5.0, 0.0),
            ceiling_height=3.0,
            room_bounds=(0.0, 0.0, 10.0, 10.0),
            obstacles=[(4.4, 4.4, 5.6, 5.6)],  # blocks center + ring-1 cardinals
            eye_height=1.7,
        )
        dx = pos[0] - 5.0
        dy = pos[1] - 5.0
        dist = math.sqrt(dx**2 + dy**2)
        # Must be at 1.0m ring (attempt 2) since 0.5m points are obstructed
        assert dist == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Property-based tests
# ---------------------------------------------------------------------------


class TestNormalizeMovementProperty:
    """Property tests for normalize_movement (Req 4.2).

    **Validates: Requirements 4.2**
    """

    @given(
        dx=st.sampled_from([-1.0, 0.0, 1.0]),
        dy=st.sampled_from([-1.0, 0.0, 1.0]),
        max_speed=st.floats(min_value=0.01, max_value=100.0),
    )
    def test_magnitude_never_exceeds_max_speed(self, dx: float, dy: float, max_speed: float):
        """For any WASD input, resulting magnitude ≤ max_speed."""
        vx, vy = normalize_movement(dx, dy, max_speed)
        mag = math.sqrt(vx**2 + vy**2)
        assert mag <= max_speed + 1e-9  # tolerance for floating point

    @given(
        dx=st.sampled_from([-1.0, 0.0, 1.0]),
        dy=st.sampled_from([-1.0, 0.0, 1.0]),
        max_speed=st.floats(min_value=0.01, max_value=100.0),
    )
    def test_nonzero_input_uses_full_speed(self, dx: float, dy: float, max_speed: float):
        """When at least one key is pressed, magnitude equals max_speed."""
        if dx == 0.0 and dy == 0.0:
            return  # skip no-input case
        vx, vy = normalize_movement(dx, dy, max_speed)
        mag = math.sqrt(vx**2 + vy**2)
        assert mag == pytest.approx(max_speed, rel=1e-7)


class TestClampVerticalAngleProperty:
    """Property tests for clamp_vertical_angle (Req 4.3).

    **Validates: Requirements 4.3**
    """

    @given(
        current=st.floats(min_value=-180.0, max_value=180.0),
        delta=st.floats(min_value=-500.0, max_value=500.0),
    )
    def test_result_always_within_bounds(self, current: float, delta: float):
        """For any current angle and delta, result stays in [-85, 85]."""
        result = clamp_vertical_angle(current, delta)
        assert -85.0 <= result <= 85.0

    @given(
        initial_angle=st.floats(min_value=-85.0, max_value=85.0),
        deltas=st.lists(
            st.floats(min_value=-500.0, max_value=500.0),
            min_size=1,
            max_size=50,
        ),
    )
    @settings(max_examples=200)
    def test_sequence_always_within_bounds(self, initial_angle: float, deltas: list[float]):
        """For any sequence of mouse Y-axis movements, vertical angle stays within [-85, 85].

        Property 5: Vertical Look Angle Clamping
        **Validates: Requirements 4.3**
        """
        angle = initial_angle
        for delta in deltas:
            angle = clamp_vertical_angle(angle, delta)
            assert -85.0 <= angle <= 85.0


class TestFindSpawnPositionProperty:
    """Property tests for find_spawn_position (Req 4.7).

    **Validates: Requirements 4.7**
    """

    @given(
        cx=st.floats(min_value=-10.0, max_value=10.0),
        cy=st.floats(min_value=-10.0, max_value=10.0),
        ceiling_h=st.floats(min_value=2.5, max_value=20.0),
    )
    @settings(max_examples=50)
    def test_fallback_uses_ceiling_minus_half(self, cx: float, cy: float, ceiling_h: float):
        """When all positions obstructed, falls back to ceiling_height - 0.5."""
        # Block the entire room with one obstacle
        bounds = (cx - 20.0, cy - 20.0, cx + 20.0, cy + 20.0)
        obstacles = [(cx - 20.0, cy - 20.0, cx + 20.0, cy + 20.0)]
        pos = find_spawn_position(
            floor_center=(cx, cy, 0.0),
            ceiling_height=ceiling_h,
            room_bounds=bounds,
            obstacles=obstacles,
            eye_height=1.7,
        )
        assert pos[0] == pytest.approx(cx)
        assert pos[1] == pytest.approx(cy)
        assert pos[2] == pytest.approx(ceiling_h - 0.5)
