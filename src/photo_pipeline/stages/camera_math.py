"""Camera geometry utilities for the Photo-to-Real-3D-World V14 pipeline.

Provides back-projection from pixel coordinates to 3D world space using
the pinhole camera model, and position clamping within room bounds.

Requirements: 4.1, 4.2, 4.4
"""
from __future__ import annotations


def back_project(
    u: float,
    v: float,
    d: float,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
) -> tuple[float, float, float]:
    """Back-project pixel (u, v) at depth d to camera-space 3D.

    Uses the pinhole camera model with right-handed convention:
    - x = (u - cx) * d / fx
    - y = -(v - cy) * d / fy
    - z = -d

    Parameters
    ----------
    u, v : Pixel coordinates (origin top-left, +v downward).
    d : Metric depth along the optical axis (positive, metres).
    fx, fy : Focal lengths in pixels.
    cx, cy : Principal point in pixels.
    """
    x = (u - cx) * d / fx
    y = -(v - cy) * d / fy
    z = -d
    return (x, y, z)


def clamp_to_bounds(
    position: tuple[float, float, float],
    bbox_min: tuple[float, float, float],
    bbox_max: tuple[float, float, float],
    margin: float = 0.05,
) -> tuple[float, float, float]:
    """Clamp position inside the axis-aligned bounding box with margin.

    Parameters
    ----------
    position : (x, y, z) to clamp.
    bbox_min : Lower corner of the bounding volume.
    bbox_max : Upper corner of the bounding volume.
    margin : Inward margin on all axes (default 0.05m).
    """
    px, py, pz = position
    bx_min, by_min, bz_min = bbox_min
    bx_max, by_max, bz_max = bbox_max

    cx = max(bx_min + margin, min(bx_max - margin, px))
    cy = max(by_min + margin, min(by_max - margin, py))
    cz = max(bz_min + margin, min(bz_max - margin, pz))
    return (cx, cy, cz)
