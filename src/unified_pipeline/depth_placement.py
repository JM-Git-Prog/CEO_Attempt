"""Depth/geometry-driven object placement for the V2.0 pipeline.

Replaces the fragile name-matching placement (catalog name -> MetricPlan
object_placement by SequenceMatcher, defaulting to the origin on a miss, which
piled every object at (0,0,0) and produced an empty walkable world).

New approach — place each object by BACK-PROJECTING its detection through the
known camera, using the room box as the spatial prior:

  1. Take the object's bbox in its best view + that view's camera (K, R|t) from
     the capture manifest.
  2. Cast a ray from the camera through the bbox BOTTOM-CENTER pixel (where the
     object meets the floor).
  3. Intersect that ray with the floor plane y=0 -> the object's ground (x, z).
  4. Elevation y comes from the object footprint / size class (objects rest on
     the floor unless clearly wall-mounted).
  5. Clamp inside the room bounds.

This uses only artifacts already on disk (capture_manifest.json intrinsics/
extrinsics + catalog bbox) and needs NO metric depth — the Depth Anything V2
map is relative, so we rely on the known room geometry (floor plane + bounds)
as the "physical feasibility" prior rather than trusting DA2's scale. Aligns
with the project's inject-don't-extract principle: the camera geometry already
determines where a floor-resting object sits.

Coordinate convention (matches v2_assembler / capture_manifest):
  room centered at origin, floor at y=0,
  x in [-width/2, +width/2], z in [-depth/2, +depth/2], up = +y.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

logger = logging.getLogger("live_trace")

# Categories that hang on a wall rather than rest on the floor. For these we
# still ground the ray but lift elevation to a plausible wall height.
_WALL_CATEGORIES = {
    "window_wall_treatments",
    "decor_accessories",  # paintings/mirrors/clocks often wall-mounted
}
_CEILING_CATEGORIES = {"lighting_fixtures"}  # pendants/chandeliers hang high


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    z: float
    method: str  # "floor_ray" | "wall_ray" | "ceiling_ray" | "fallback_grid"
    confidence: float


def _mat_vec3(m: Sequence[Sequence[float]], v: Sequence[float]) -> tuple[float, float, float]:
    """Multiply a 3x3 (or upper-left of 4x4) matrix by a 3-vector."""
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def _invert_extrinsic(ext: Sequence[Sequence[float]]) -> tuple[list[list[float]], tuple[float, float, float]]:
    """Given a world->camera 4x4 [R|t], return (R^T, camera_center_world).

    camera_center_world = -R^T t. R^T maps camera-space dirs to world-space.
    """
    R = [[ext[i][j] for j in range(3)] for i in range(3)]
    t = (ext[0][3], ext[1][3], ext[2][3])
    Rt = [[R[j][i] for j in range(3)] for i in range(3)]  # transpose
    neg_Rt_t = _mat_vec3(Rt, t)
    cam_center = (-neg_Rt_t[0], -neg_Rt_t[1], -neg_Rt_t[2])
    return Rt, cam_center


def _ray_through_pixel(
    camera: dict[str, Any], u: float, v: float
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return (origin_world, dir_world) for the ray through pixel (u, v).

    Uses the pinhole intrinsic (fx, fy, cx, cy) and the world->camera extrinsic.
    Camera looks down +z in its own frame here (OpenCV-style: x right, y down,
    z forward), consistent with the manifest's intrinsic (cx,cy at raster center)
    and extrinsic produced by the CapturePlanner.
    """
    K = camera["intrinsic"]
    fx, fy = K[0][0], K[1][1]
    cx, cy = K[0][2], K[1][2]

    # Pixel -> normalized camera-space direction (z forward).
    dir_cam = ((u - cx) / fx, (v - cy) / fy, 1.0)

    ext = camera["extrinsic"]
    Rt, cam_center = _invert_extrinsic(ext)
    dir_world = _mat_vec3(Rt, dir_cam)

    # The manifest extrinsic convention requires negating the transformed
    # direction so the center-pixel ray matches (target - position) for every
    # camera. Verified across all 6 manifest cameras (hero + N/E/S/W + transition).
    dir_world = (-dir_world[0], -dir_world[1], -dir_world[2])

    # Normalize.
    n = (dir_world[0] ** 2 + dir_world[1] ** 2 + dir_world[2] ** 2) ** 0.5 or 1.0
    dir_world = (dir_world[0] / n, dir_world[1] / n, dir_world[2] / n)
    return cam_center, dir_world


def _intersect_plane_y(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    plane_y: float,
) -> tuple[float, float, float] | None:
    """Intersect a ray with the horizontal plane y = plane_y. None if parallel
    or the hit is behind the camera."""
    oy, dy = origin[1], direction[1]
    if abs(dy) < 1e-6:
        return None
    tprm = (plane_y - oy) / dy
    if tprm <= 0:
        return None
    return (
        origin[0] + tprm * direction[0],
        plane_y,
        origin[2] + tprm * direction[2],
    )


def place_objects(
    catalog_entries: Sequence[Any],
    capture_manifest: dict[str, Any] | None,
    room_dims: Sequence[float],
) -> dict[str, Placement]:
    """Compute a world placement for every catalog entry, keyed by entry uuid.

    Args:
        catalog_entries: objects with .uuid, .bbox_in_best_view, .best_view_index,
            .category, .size_estimate (CatalogEntry or equivalent dicts).
        capture_manifest: dict with "cameras" list (K/R/t per view). If None or
            missing a camera, that object falls back to a non-overlapping grid.
        room_dims: (width, depth, ceiling).

    Returns:
        {uuid: Placement}.
    """
    width, depth, ceiling = (
        float(room_dims[0]), float(room_dims[1]), float(room_dims[2])
    )
    cameras = (capture_manifest or {}).get("cameras", []) if capture_manifest else []

    def _get(entry: Any, key: str, default: Any = None) -> Any:
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    half_w, half_d = width / 2.0, depth / 2.0
    margin = 0.35  # keep objects off the walls
    placements: dict[str, Placement] = {}
    fallback_index = 0

    for entry in catalog_entries:
        uuid_ = _get(entry, "uuid", "")
        bbox = _get(entry, "bbox_in_best_view") or []
        view_idx = _get(entry, "best_view_index", 0) or 0
        category = (_get(entry, "category", "") or "").lower()
        size_est = (_get(entry, "size_estimate", "medium") or "medium").lower()

        camera = cameras[view_idx] if 0 <= view_idx < len(cameras) else None
        placement: Placement | None = None

        if camera is not None and len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            u_center = (x1 + x2) / 2.0
            v_bottom = float(max(y1, y2))  # object meets floor at its bottom edge
            origin, direction = _ray_through_pixel(camera, u_center, v_bottom)
            hit = _intersect_plane_y(origin, direction, 0.0)
            if hit is not None:
                gx = max(-half_w + margin, min(half_w - margin, hit[0]))
                gz = max(-half_d + margin, min(half_d - margin, hit[2]))
                if category in _CEILING_CATEGORIES:
                    y = ceiling - 0.35
                    method = "ceiling_ray"
                elif category in _WALL_CATEGORIES:
                    y = min(1.5, ceiling * 0.55)
                    method = "wall_ray"
                else:
                    y = 0.0
                    method = "floor_ray"
                # Confidence: interior hits are trustworthy; clamped hits less so.
                clamped = (gx != hit[0]) or (gz != hit[2])
                placement = Placement(
                    x=round(gx, 3), y=round(y, 3), z=round(gz, 3),
                    method=method, confidence=0.5 if clamped else 0.85,
                )

        if placement is None:
            # Deterministic non-overlapping grid fallback (never origin-pile).
            cols = 4
            row = fallback_index // cols
            col = fallback_index % cols
            gx = -half_w + margin + (col + 0.5) * (width - 2 * margin) / cols
            gz = -half_d + margin + (row + 0.5) * 0.9
            gz = max(-half_d + margin, min(half_d - margin, gz))
            placement = Placement(
                x=round(gx, 3), y=0.0, z=round(gz, 3),
                method="fallback_grid", confidence=0.2,
            )
            fallback_index += 1

        placements[uuid_] = placement

    return placements
