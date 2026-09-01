"""Orthographic canon -> metric plan.

Why this exists
---------------
The eye-level canon cannot carry coordinates. Recovering them from a perspective
render (see v15_fable.reconcile) needs a pinhole ground-plane inversion with an
assumed eye height, an assumed focal length, a horizon test, and a failure mode
that silently drops any object whose base sits above the horizon:

    f = (W / 2) / tan(hfov / 2)
    Z = eye_height * f / (y_bottom - cy)
    X = (x_centre - cx) * Z / f

A true nadir orthographic render deletes all of it. Under orthographic
projection straight down, the mapping from pixels to metres is a SIMILARITY
transform: one uniform scale plus a translate. No focal length, no eye height,
no horizon, nothing to drop.

    x_m = (x_px - origin_x) * k
    y_m = (y_px - origin_y) * k

That is the constitutional rule for measured spatial data — one uniform scale,
never a per-axis min/max stretch, so noise stays noise-sized and geometry keeps
its shape.

What top-down can and cannot measure
------------------------------------
A plan view sees the floor. It gives x, y, footprint and yaw honestly. It cannot
see HEIGHT — every object is viewed along its height axis. Height therefore
comes from the furniture table in plan_generator, never from the image. Keeping
that boundary explicit is what stops a "measurement" from quietly becoming a
guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# A truly orthographic render of a rectangular room implies the SAME scale on
# both axes. If the two implied scales disagree by more than this fraction, the
# render carries perspective and its coordinates must not be trusted.
MAX_SCALE_RESIDUAL = 0.04

# Below this the aspect ratio is too close to square to infer yaw from it.
SQUARE_ASPECT_BAND = 0.15


@dataclass(frozen=True)
class OrthoScale:
    """The similarity transform taking floor pixels to room metres."""

    scale: float          # metres per pixel, ONE value for both axes
    origin_x: float       # pixel x of the room's west wall
    origin_y: float       # pixel y of the room's north wall
    residual: float       # |k_x - k_y| / k, the non-orthographality evidence
    trustworthy: bool     # residual within MAX_SCALE_RESIDUAL

    def to_metres(self, x_px: float, y_px: float) -> tuple[float, float]:
        return (
            (x_px - self.origin_x) * self.scale,
            (y_px - self.origin_y) * self.scale,
        )


def solve_scale(
    room_box_px: tuple[float, float, float, float],
    room_size_m: tuple[float, float],
) -> OrthoScale:
    """Derive the single uniform scale from the measured room outline.

    room_box_px is (x0, y0, x1, y1) of the floor outline in the ortho render.
    room_size_m is the room's (width, depth) in metres.

    The two axes each imply a scale. Under a true orthographic projection they
    agree; the disagreement is kept as drift evidence rather than averaged away
    silently, because a large residual means the render is not orthographic and
    the whole measurement should be rejected at QA.
    """
    x0, y0, x1, y1 = room_box_px
    width_px = float(x1 - x0)
    depth_px = float(y1 - y0)
    if width_px <= 0 or depth_px <= 0:
        raise ValueError("room outline has no area in the ortho render")

    width_m, depth_m = room_size_m
    scale_x = width_m / width_px
    scale_y = depth_m / depth_px

    # ONE scale for both axes — the similarity transform. Averaging the two is
    # the uniform choice; the residual records how far apart they were.
    scale = (scale_x + scale_y) / 2.0
    residual = abs(scale_x - scale_y) / scale if scale else float("inf")

    return OrthoScale(
        scale=scale,
        origin_x=float(x0),
        origin_y=float(y0),
        residual=residual,
        trustworthy=residual <= MAX_SCALE_RESIDUAL,
    )


def solve_scale_anchored(
    room_box_px: tuple[float, float, float, float],
    known_width_m: float,
) -> tuple[OrthoScale, tuple[float, float]]:
    """Scale from ONE known dimension; measure the other. Returns (scale, room_m).

    solve_scale asserts both room dimensions and treats their disagreement with
    the measured outline as evidence of non-orthographality. That conflates two
    questions, and the bench proved it: a render of aspect 0.881 declared as
    4.0x4.3 (0.930) was rejected at 5.4% residual, when nothing was actually
    wrong with the projection -- the generator simply chose its own proportion,
    which it is entitled to do because the Brief only ever fixes a MINIMUM
    footprint, never an exact one.

    So anchor the scale on the one dimension we genuinely constrain, and let
    the render tell us the other. Residual is zero by construction here, and
    checking orthographality becomes a separate question about whether the
    outline is a true rectangle -- not about whether it matched an assumption.
    """
    x0, y0, x1, y1 = room_box_px
    width_px = float(x1 - x0)
    depth_px = float(y1 - y0)
    if width_px <= 0 or depth_px <= 0:
        raise ValueError("room outline has no area in the ortho render")

    scale = known_width_m / width_px
    measured_depth_m = depth_px * scale

    ortho = OrthoScale(
        scale=scale,
        origin_x=float(x0),
        origin_y=float(y0),
        residual=0.0,
        trustworthy=True,
    )
    return ortho, (known_width_m, measured_depth_m)


def infer_rotation(
    measured_w: float,
    measured_d: float,
    catalogue_w: float,
    catalogue_d: float,
) -> int:
    """Infer yaw from how the measured footprint compares to the catalogue one.

    A rectangular object rotated 90 degrees presents its depth along x. Only two
    orientations are distinguishable from an axis-aligned bounding box, so this
    returns 0 or 90 and leaves finer yaw to the seating relationship, which
    knows which way a chair must face.
    """
    if catalogue_w <= 0 or catalogue_d <= 0 or measured_w <= 0 or measured_d <= 0:
        return 0
    catalogue_aspect = catalogue_w / catalogue_d
    if abs(catalogue_aspect - 1.0) <= SQUARE_ASPECT_BAND:
        return 0  # square footprint: rotation is unobservable from a bbox
    measured_aspect = measured_w / measured_d
    upright = abs(measured_aspect - catalogue_aspect)
    turned = abs(measured_aspect - (1.0 / catalogue_aspect))
    return 90 if turned < upright else 0


def placements_from_ortho(
    detections: Iterable[dict[str, Any]],
    ortho: OrthoScale,
    dimensions_for: Any,
    room_size_m: tuple[float, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn measured ortho bounding boxes into MetricPlan object placements.

    detections: dicts with 'id', 'name' and 'bbox' = (x0, y0, x1, y1) in pixels.
    dimensions_for: callable name -> (width, depth, height) in metres.

    Returns (placements, evidence). Height always comes from the catalogue: a
    plan view looks along the height axis and cannot measure it.
    """
    width_m, depth_m = room_size_m
    placements: list[dict[str, Any]] = []
    measured: list[dict[str, Any]] = []

    for detection in detections:
        bbox = detection.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = (float(value) for value in bbox)

        centre_x_m, centre_y_m = ortho.to_metres((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        footprint_w = (x1 - x0) * ortho.scale
        footprint_d = (y1 - y0) * ortho.scale

        name = str(detection.get("name", ""))
        catalogue_w, catalogue_d, catalogue_h = dimensions_for(name)
        rotation = infer_rotation(
            footprint_w, footprint_d, catalogue_w, catalogue_d
        )

        # Clamp inside the room so a ragged mask edge cannot push an object
        # through a wall. Clamping is recorded, never silent.
        clamped_x = min(max(centre_x_m, footprint_w / 2.0), width_m - footprint_w / 2.0)
        clamped_y = min(max(centre_y_m, footprint_d / 2.0), depth_m - footprint_d / 2.0)

        placements.append({
            "id": detection.get("id", name),
            "name": name,
            "x": clamped_x,
            "y": clamped_y,
            "rotation_deg": rotation,
            "width": footprint_w,
            "depth": footprint_d,
            # Height is NOT measurable from a plan view — catalogue only.
            "height": catalogue_h,
            "is_architectural": bool(detection.get("is_architectural", False)),
        })
        measured.append({
            "name": name,
            "measured_footprint_m": [round(footprint_w, 3), round(footprint_d, 3)],
            "catalogue_footprint_m": [catalogue_w, catalogue_d],
            "centre_m": [round(centre_x_m, 3), round(centre_y_m, 3)],
            "clamped": [
                round(clamped_x - centre_x_m, 3),
                round(clamped_y - centre_y_m, 3),
            ],
            "rotation_deg": rotation,
        })

    evidence = {
        "schema_version": "ortho-measurement/v1",
        "scale_m_per_px": ortho.scale,
        "scale_residual": round(ortho.residual, 5),
        "scale_trustworthy": ortho.trustworthy,
        "max_scale_residual": MAX_SCALE_RESIDUAL,
        "height_source": "furniture_catalogue_not_measurable_from_plan_view",
        "objects": measured,
    }
    return placements, evidence


# ─── Segmentation ─────────────────────────────────────────────────────────────
#
# The measurement render is deliberately engineered to be trivially separable:
# flat shadowless light, no occlusion, warm wood furniture on a neutral floor.
# A saturation threshold plus connected components finds every object in
# milliseconds with no model and no GPU.
#
# Measured live 2026-08-31 on a 1024x1024 nadir render of a table and two
# chairs: this found 3 of 3 objects. SAM3, prompted per object name, returned
# only ONE chair across four attempts (threshold 0.5 and 0.3, individual_masks
# both ways) even on a fully separated, unoccluded render. Cheapest rung wins
# the lane; step up only when this provably fails.

MIN_OBJECT_AREA_PX = 2000
WARM_SATURATION = 0.18


def detect_room_outline(
    rgb: Any,
    tolerance: float = 18.0,
) -> tuple[int, int, int, int]:
    """Find the room's pixel rectangle by separating it from the flat surround.

    The measurement render places the room on a uniform background, so the
    background colour can be sampled from the image border and everything
    unlike it is the room. Returns (x0, y0, x1, y1).

    This exists because the scale MUST come from a measured outline. Passing
    the image frame instead is what made the first end-to-end run report
    trustworthy=False: a square frame declared as a 4.0x4.3 room implies two
    different scales, and the residual check caught it.

    Raises ValueError when the room cannot be separated from the background,
    which is the correct outcome for a render with no visible surround --
    better a loud failure than a silently assumed frame.
    """
    import numpy as np
    from scipy import ndimage

    pixels = np.asarray(rgb).astype(float)
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        raise ValueError("detect_room_outline expects an (H, W, 3) RGB array")
    height, width = pixels.shape[:2]

    # Sample the border ring for the background colour.
    border = np.concatenate([
        pixels[0, :, :3], pixels[-1, :, :3],
        pixels[:, 0, :3], pixels[:, -1, :3],
    ])
    background = np.median(border, axis=0)

    distance = np.abs(pixels[:, :, :3] - background).max(axis=2)
    mask = distance > tolerance
    mask = ndimage.binary_closing(mask, np.ones((7, 7)))
    mask = ndimage.binary_opening(mask, np.ones((5, 5)))

    labelled, count = ndimage.label(mask)
    if count == 0:
        raise ValueError(
            "no room found: the render has no measurable surround, so its "
            "scale cannot be measured (do not assume the image frame)"
        )
    sizes = ndimage.sum(mask, labelled, range(1, count + 1))
    room_label = int(np.argmax(sizes)) + 1
    ys, xs = np.nonzero(labelled == room_label)

    coverage = len(xs) / float(height * width)
    if coverage > 0.985:
        raise ValueError(
            f"room fills {coverage:.1%} of the frame - no surround to measure "
            "against, so the outline would just be the frame"
        )

    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def segment_warm_objects(
    rgb: Any,
    min_area_px: int = MIN_OBJECT_AREA_PX,
    saturation: float = WARM_SATURATION,
) -> list[tuple[int, int, int, int]]:
    """Find furniture in a nadir render by colour saturation.

    rgb is an (H, W, 3) array. Returns pixel bounding boxes (x0, y0, x1, y1)
    ordered top to bottom, one per detected object.

    Works because the floor and walls are neutral (R about G about B, low
    saturation) while wood and fabric are warm. Requires numpy and scipy.
    """
    import numpy as np
    from scipy import ndimage

    pixels = np.asarray(rgb).astype(float)
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        raise ValueError("segment_warm_objects expects an (H, W, 3) RGB array")

    highest = pixels[:, :, :3].max(axis=2)
    lowest = pixels[:, :, :3].min(axis=2)
    saturation_map = np.where(highest > 0, (highest - lowest) / np.maximum(highest, 1), 0)

    mask = saturation_map > saturation
    # Opening removes speckle from wood grain and JPEG-style ringing without
    # eroding a real object enough to move its centroid.
    mask = ndimage.binary_opening(mask, np.ones((5, 5)))

    labelled, count = ndimage.label(mask)
    boxes: list[tuple[int, int, int, int]] = []
    for index in range(1, count + 1):
        ys, xs = np.nonzero(labelled == index)
        if len(xs) < min_area_px:
            continue
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())))

    boxes.sort(key=lambda box: (box[1], box[0]))
    return boxes


# ─── The injected canon prompt ────────────────────────────────────────────────

_ORTHO_NEGATIVE = (
    "perspective, isometric, angled view, tilted camera, three-quarter view, "
    "roof, ceiling, people, text, labels, dimension lines, north arrow, "
    "watermark, signature, clutter, extra furniture, duplicated objects"
)


def ortho_canon_prompt(
    objects: list[tuple[str, int]],
    room_size_m: tuple[float, float],
    palette: str = "neutral",
    floor: str = "concrete",
) -> tuple[str, str]:
    """Build the nadir-orthographic canon prompt and its negative.

    Everything the measurement needs is INJECTED, never hoped for: the
    projection, the room dimensions, the exact object counts, the axis
    alignment, and the flat lighting that keeps shadows out of the masks.
    """
    width_m, depth_m = room_size_m
    inventory = ", ".join(
        f"exactly {count} {name}" + ("s" if count != 1 else "")
        for name, count in objects
    )
    positive = (
        "Top-down orthographic floor plan view, straight down nadir projection, "
        f"of a single empty room measuring {width_m:.1f} by {depth_m:.1f} metres. "
        "No roof, no ceiling. Walls drawn as thin outlines aligned parallel to "
        "the image edges, room corners square to the frame. "
        f"NON-NEGOTIABLE VISIBLE INVENTORY: {inventory}, and nothing else. "
        "Every object fully visible, spatially separate, non-overlapping, "
        "correctly counted, and resting on the floor. "
        f"{floor} floor, {palette} palette. "
        "Completely uniform diffuse studio lighting, no cast shadows, no "
        "vignette, no depth of field. Photorealistic materials, sharp focus, "
        "high resolution. Solid neutral white background outside the room outline."
    )
    return positive, _ORTHO_NEGATIVE
