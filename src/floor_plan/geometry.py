"""Authoritative rotation-aware geometry operations for floor-plan validation."""

from __future__ import annotations

import math
from typing import Protocol


class SpatialVolume(Protocol):
    x: float
    z: float
    width: float
    depth: float
    height: float
    elevation: float
    rotation_deg: float


def vertical_intersects(left: SpatialVolume, right: SpatialVolume, tolerance: float = 0.03) -> bool:
    """Return whether two occupied vertical intervals overlap beyond tolerance."""
    return (
        left.elevation < right.elevation + right.height - tolerance
        and right.elevation < left.elevation + left.height - tolerance
    )


def footprint_axes(volume: SpatialVolume) -> tuple[tuple[float, float], tuple[float, float]]:
    angle = math.radians(volume.rotation_deg)
    return ((math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle)))


def footprint_corners(volume: SpatialVolume, padding: float = 0.0) -> list[tuple[float, float]]:
    """Return the four world-space corners of an oriented rectangular footprint."""
    axis_x, axis_z = footprint_axes(volume)
    half_w = volume.width / 2 + padding
    half_d = volume.depth / 2 + padding
    return [
        (
            volume.x + sx * half_w * axis_x[0] + sz * half_d * axis_z[0],
            volume.z + sx * half_w * axis_x[1] + sz * half_d * axis_z[1],
        )
        for sx, sz in ((-1, -1), (-1, 1), (1, 1), (1, -1))
    ]


def _projection(corners: list[tuple[float, float]], axis: tuple[float, float]) -> tuple[float, float]:
    values = [x * axis[0] + z * axis[1] for x, z in corners]
    return min(values), max(values)


def footprints_intersect(
    left: SpatialVolume,
    right: SpatialVolume,
    *,
    left_padding: float = 0.0,
    right_padding: float = 0.0,
    tolerance: float = 0.03,
) -> bool:
    """Apply SAT to occupied oriented footprints and their vertical intervals."""
    if not vertical_intersects(left, right, tolerance):
        return False
    left_corners = footprint_corners(left, left_padding)
    right_corners = footprint_corners(right, right_padding)
    for axis in (*footprint_axes(left), *footprint_axes(right)):
        left_min, left_max = _projection(left_corners, axis)
        right_min, right_max = _projection(right_corners, axis)
        if left_max <= right_min + tolerance or right_max <= left_min + tolerance:
            return False
    return True


def footprint_overlap_depth(
    left: SpatialVolume,
    right: SpatialVolume,
    *,
    left_padding: float = 0.0,
    right_padding: float = 0.0,
) -> float:
    """Return the minimum penetration depth (meters) between two footprints.

    Returns 0.0 if the footprints do not overlap. A positive value indicates
    the smallest translation along any separating axis that would separate
    the two footprints.
    """
    if not vertical_intersects(left, right, tolerance=0.0):
        return 0.0
    left_corners = footprint_corners(left, left_padding)
    right_corners = footprint_corners(right, right_padding)
    min_penetration = float("inf")
    for axis in (*footprint_axes(left), *footprint_axes(right)):
        left_min, left_max = _projection(left_corners, axis)
        right_min, right_max = _projection(right_corners, axis)
        # Overlap on this axis
        overlap = min(left_max - right_min, right_max - left_min)
        if overlap <= 0.0:
            return 0.0  # Separated on this axis — no intersection
        min_penetration = min(min_penetration, overlap)
    return min_penetration if min_penetration != float("inf") else 0.0


def inside_room(volume: SpatialVolume, width: float, depth: float, margin: float = 0.03) -> bool:
    half_w, half_d = width / 2, depth / 2
    return all(
        -half_w + margin <= x <= half_w - margin
        and -half_d + margin <= z <= half_d - margin
        for x, z in footprint_corners(volume)
    )


def fit_center_inside(
    volume: SpatialVolume, width: float, depth: float, margin: float = 0.03
) -> tuple[float, float] | None:
    """Return the nearest center that keeps the rotated footprint in the room."""
    relative = footprint_corners(
        type("Centered", (), {
            "x": 0.0, "z": 0.0, "width": volume.width, "depth": volume.depth,
            "height": volume.height, "elevation": volume.elevation,
            "rotation_deg": volume.rotation_deg,
        })()
    )
    min_x = min(point[0] for point in relative)
    max_x = max(point[0] for point in relative)
    min_z = min(point[1] for point in relative)
    max_z = max(point[1] for point in relative)
    low_x, high_x = -width / 2 + margin - min_x, width / 2 - margin - max_x
    low_z, high_z = -depth / 2 + margin - min_z, depth / 2 - margin - max_z
    if low_x > high_x or low_z > high_z:
        return None
    return (
        max(low_x, min(high_x, volume.x)),
        max(low_z, min(high_z, volume.z)),
    )