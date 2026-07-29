"""Camera math utilities for back-projection and position clamping.

Provides pure functions for converting 2D pixel coordinates to 3D world
positions via the pinhole camera model, and for clamping 3D positions
within room bounding volumes.

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
    """Back-project a 2D pixel coordinate to a 3D world position.

    Uses the pinhole camera model with the convention that the camera
    looks along -Z in a right-handed coordinate system (Y-up).

    Args:
        u: Pixel x-coordinate (column).
        v: Pixel y-coordinate (row).
        d: Metric depth at (u, v) in meters (positive).
        fx: Focal length in pixels (horizontal).
        fy: Focal length in pixels (vertical).
        cx: Principal point x (image center x).
        cy: Principal point y (image center y).

    Returns:
        A tuple (x, y, z) representing the 3D world position in meters.
        x = (u - cx) * d / fx
        y = -(v - cy) * d / fy   (negated: image Y is inverted)
        z = -d                    (camera looks along -Z)
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
    """Clamp a 3D position to within a bounding volume with margin.

    Ensures the returned position lies within
    [bbox_min + margin, bbox_max - margin] on each axis.

    Args:
        position: The (x, y, z) position to clamp.
        bbox_min: Minimum corner of the bounding box (x, y, z).
        bbox_max: Maximum corner of the bounding box (x, y, z).
        margin: Inward margin in meters on each axis (default 0.05m).

    Returns:
        A tuple (x, y, z) guaranteed to be inside the bounded volume
        minus the margin on all sides.
    """
    return tuple(
        max(lo + margin, min(hi - margin, p))
        for p, lo, hi in zip(position, bbox_min, bbox_max)
    )  # type: ignore[return-value]
