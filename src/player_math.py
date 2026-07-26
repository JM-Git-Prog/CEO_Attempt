"""Pure-math utilities for player controller logic.

No BGE/bpy dependencies — fully testable outside the game engine.
Provides movement normalization, look-angle clamping, and spawn repositioning.
"""

from __future__ import annotations

import math


def normalize_movement(dx: float, dy: float, max_speed: float) -> tuple[float, float]:
    """Scale raw WASD input direction so the resulting vector magnitude ≤ max_speed.

    Parameters
    ----------
    dx : float
        Horizontal input (typically -1, 0, or +1 from A/D keys).
    dy : float
        Forward/backward input (typically -1, 0, or +1 from W/S keys).
    max_speed : float
        Configured maximum movement speed (m/s). Must be > 0.

    Returns
    -------
    tuple[float, float]
        Speed-scaled movement vector (vx, vy) where
        sqrt(vx² + vy²) ≤ max_speed.

    Validates: Requirements 4.2
    """
    if max_speed <= 0:
        return (0.0, 0.0)

    mag = math.sqrt(dx * dx + dy * dy)
    if mag == 0.0:
        return (0.0, 0.0)

    # Normalize direction then scale by max_speed
    scale = max_speed / mag
    return (dx * scale, dy * scale)


def clamp_vertical_angle(current_angle: float, delta: float) -> float:
    """Apply a look delta to the current vertical angle, clamped to ±85°.

    Parameters
    ----------
    current_angle : float
        Current vertical look angle in degrees.
    delta : float
        Change in vertical angle in degrees (positive = look up).

    Returns
    -------
    float
        New vertical angle clamped to [-85, +85].

    Validates: Requirements 4.3
    """
    new_angle = current_angle + delta
    return max(-85.0, min(85.0, new_angle))


def find_spawn_position(
    floor_center: tuple[float, float, float],
    ceiling_height: float,
    room_bounds: tuple[float, float, float, float],
    obstacles: list[tuple[float, float, float, float]],
    eye_height: float = 1.7,
) -> tuple[float, float, float]:
    """Find a valid spawn position using spiral search with fallback.

    Searches outward from floor_center in 0.5m increments (up to 8 attempts)
    for a position that doesn't intersect any obstacle AABB and is within
    room bounds. Falls back to ceiling_height - 0.5m (drop from above).

    Parameters
    ----------
    floor_center : tuple[float, float, float]
        (x, y, z) center of the floor.
    ceiling_height : float
        Height of the ceiling in world units.
    room_bounds : tuple[float, float, float, float]
        (min_x, min_y, max_x, max_y) axis-aligned room boundary on the
        horizontal plane.
    obstacles : list[tuple[float, float, float, float]]
        List of obstacle AABBs as (min_x, min_y, max_x, max_y) on the
        horizontal plane.
    eye_height : float
        Player eye height above floor (default 1.7m).

    Returns
    -------
    tuple[float, float, float]
        Valid spawn position (x, y, z).

    Validates: Requirements 4.7
    """
    step = 0.5  # 0.5m increments
    cx, cy, cz = floor_center
    min_x, min_y, max_x, max_y = room_bounds

    def _point_in_bounds(px: float, py: float) -> bool:
        return min_x <= px <= max_x and min_y <= py <= max_y

    def _point_obstructed(px: float, py: float) -> bool:
        for obs_min_x, obs_min_y, obs_max_x, obs_max_y in obstacles:
            if obs_min_x <= px <= obs_max_x and obs_min_y <= py <= obs_max_y:
                return True
        return False

    def _is_valid(px: float, py: float) -> bool:
        return _point_in_bounds(px, py) and not _point_obstructed(px, py)

    # Attempt 0: try the center itself
    if _is_valid(cx, cy):
        return (cx, cy, cz + eye_height)

    # Spiral search: 8 attempts outward in 0.5m increments
    # Use a simple spiral pattern: for each ring radius, try 4 cardinal
    # + 4 diagonal directions
    for attempt in range(1, 9):
        radius = attempt * step
        # Try 8 directions: N, NE, E, SE, S, SW, W, NW
        for angle_idx in range(8):
            angle = angle_idx * (math.pi / 4.0)
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            if _is_valid(px, py):
                return (px, py, cz + eye_height)

    # Fallback: drop from ceiling_height - 0.5m
    return (cx, cy, ceiling_height - 0.5)


def compute_door_step(
    current_angle: float,
    target_angle: float,
    speed_deg_s: float,
    frame_rate: float,
) -> float:
    """Compute the next angle after one frame of door animation.

    The step advances toward target without overshooting:
    step = min(|target - current|, speed_deg_s / frame_rate)

    Parameters
    ----------
    current_angle : float
        Current door rotation angle in degrees.
    target_angle : float
        Target door rotation angle in degrees.
    speed_deg_s : float
        Door rotation speed in degrees per second. Must be > 0.
    frame_rate : float
        Game frame rate (frames per second). Must be > 0.

    Returns
    -------
    float
        New angle after one frame step.

    Validates: Requirements 5.3
    """
    max_step = speed_deg_s / frame_rate
    difference = target_angle - current_angle
    # Clamp the step: advance by at most max_step in the correct direction,
    # but never overshoot the target.
    clamped = max(-max_step, min(max_step, difference))
    return current_angle + clamped
