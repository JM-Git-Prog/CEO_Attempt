"""Scale Calibrator — converts pixel footprints to real-world meters.

This module computes real-world dimensions for segmented objects by
combining:

1. **Pixel footprint**: Object bounding box width and height in pixels.
2. **Metric depth**: Depth value at the object centroid from the MoGe-2
   depth map (meters).
3. **Camera FOV**: Vertical field of view (default 60°), used to derive
   focal length in pixels.

Algorithm (pinhole camera model):
    fov_v_rad = radians(fov_v_deg)
    fy = image_height / (2 * tan(fov_v_rad / 2))
    fx = fy  # square pixels assumed

    real_width  = (pixel_width  * depth_at_centroid) / fx
    real_height = (pixel_height * depth_at_centroid) / fy
    real_depth  = real_width * 0.6  # heuristic: depth ≈ 60% of width

Each axis is clamped to [0.01m, room_dimension_on_that_axis].

Confidence heuristic:
- High (> 0.7): depth in [0.5m, 10m] AND pixel footprint > 1% of image
- Medium (0.3-0.7): depth or footprint at boundary values
- Low (< 0.3): depth very small/large or footprint tiny

Pure computation functions are separated from the class interface for
independent testability.
"""

from __future__ import annotations

import logging
import math

import numpy as np

from src.photo_pipeline.models import ScaleResult, SegmentedObject

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Depth plausibility range (meters)
_DEPTH_PLAUSIBLE_MIN = 0.5
_DEPTH_PLAUSIBLE_MAX = 10.0

# Minimum pixel footprint as fraction of image area for high confidence
_FOOTPRINT_HIGH_THRESHOLD = 0.01  # 1% of image area

# Depth heuristic multiplier: real_depth ≈ 60% of real_width
_DEPTH_HEURISTIC_RATIO = 0.6

# Clamping bounds
_MIN_DIMENSION_M = 0.01


# ---------------------------------------------------------------------------
# Pure helper functions (testable without I/O)
# ---------------------------------------------------------------------------


def pixel_to_meters(
    pixel_size: float, depth_m: float, fov_deg: float, image_dim: int
) -> float:
    """Convert a pixel measurement to meters using pinhole camera model.

    Derives focal length from FOV and image dimension, then computes
    the real-world size corresponding to a pixel footprint at a given depth.

    Parameters
    ----------
    pixel_size : float
        Size in pixels along one axis (width or height of the object).
    depth_m : float
        Depth at the object centroid in meters (must be positive).
    fov_deg : float
        Field of view in degrees for the axis corresponding to image_dim
        (must be in (0, 180)).
    image_dim : int
        Image dimension in pixels along the same axis (width or height).

    Returns
    -------
    float
        Real-world size in meters along that axis.

    Raises
    ------
    ValueError
        If inputs are non-positive or FOV is out of valid range.
    """
    if pixel_size <= 0:
        raise ValueError(f"pixel_size must be positive, got {pixel_size}")
    if depth_m <= 0:
        raise ValueError(f"depth_m must be positive, got {depth_m}")
    if fov_deg <= 0 or fov_deg >= 180:
        raise ValueError(f"fov_deg must be in (0, 180), got {fov_deg}")
    if image_dim <= 0:
        raise ValueError(f"image_dim must be positive, got {image_dim}")

    fov_rad = math.radians(fov_deg)
    focal_length_px = image_dim / (2.0 * math.tan(fov_rad / 2.0))

    return (pixel_size * depth_m) / focal_length_px


def clamp_dimensions(
    dims: tuple[float, float, float],
    room_dims: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Clamp each dimension axis to [0.01m, 0.5 * room_dimension_on_that_axis].

    Objects larger than half the room in any dimension are almost certainly
    depth-estimation artifacts. Clamping to 50% prevents room-filling boxes
    while still allowing large furniture (e.g., a king bed in a 4m-wide room).

    Parameters
    ----------
    dims : tuple[float, float, float]
        Raw computed dimensions (width, height, depth) in meters.
    room_dims : tuple[float, float, float]
        Room dimensions (width, height, depth) in meters used as upper bounds.

    Returns
    -------
    tuple[float, float, float]
        Clamped dimensions where each axis is in [0.01, 0.5 * room_dim_axis].
    """
    clamped = []
    for dim, room_dim in zip(dims, room_dims):
        upper = max(_MIN_DIMENSION_M, room_dim * 0.5)
        clamped_val = max(_MIN_DIMENSION_M, min(dim, upper))
        clamped.append(clamped_val)
    return (clamped[0], clamped[1], clamped[2])


def compute_confidence(
    depth_m: float,
    pixel_footprint: float,
    image_area: float,
) -> float:
    """Compute confidence score for the scale calibration.

    Confidence is based on two factors:
    - Depth plausibility: values in [0.5m, 10m] are most reliable
    - Pixel footprint: objects covering > 1% of image area are well-resolved

    Scoring:
    - Both plausible → confidence 0.8-1.0
    - One marginal → confidence 0.3-0.7
    - Both poor → confidence < 0.3

    Parameters
    ----------
    depth_m : float
        Depth value at object centroid in meters.
    pixel_footprint : float
        Object bounding box area in pixels (width * height).
    image_area : float
        Total image area in pixels.

    Returns
    -------
    float
        Confidence score in [0.0, 1.0].
    """
    # Depth factor
    if _DEPTH_PLAUSIBLE_MIN <= depth_m <= _DEPTH_PLAUSIBLE_MAX:
        depth_score = 1.0
    elif depth_m > 0:
        # Gradual falloff outside plausible range
        if depth_m < _DEPTH_PLAUSIBLE_MIN:
            # Very close: 0.01m → 0.1, 0.5m → 1.0
            depth_score = max(0.1, depth_m / _DEPTH_PLAUSIBLE_MIN)
        else:
            # Very far: 10m → 1.0, 30m → 0.1
            depth_score = max(0.1, _DEPTH_PLAUSIBLE_MAX / depth_m)
    else:
        depth_score = 0.0

    # Footprint factor
    if image_area <= 0:
        footprint_score = 0.0
    else:
        footprint_ratio = pixel_footprint / image_area
        if footprint_ratio >= _FOOTPRINT_HIGH_THRESHOLD:
            footprint_score = 1.0
        else:
            # Linear ramp: 0% → 0.1, 1% → 1.0
            footprint_score = max(0.1, footprint_ratio / _FOOTPRINT_HIGH_THRESHOLD)

    # Combined confidence: geometric mean biased toward the weaker signal
    confidence = (depth_score * footprint_score) ** 0.5

    return max(0.0, min(1.0, confidence))


# ---------------------------------------------------------------------------
# ScaleCalibrator class
# ---------------------------------------------------------------------------


class ScaleCalibrator:
    """Converts pixel measurements to real-world meters.

    Uses the pinhole camera model with metric depth to compute object
    dimensions, then clamps results to physically plausible bounds
    defined by the room dimensions.

    Produces a ScaleResult with dimensions, scale_factor, and confidence.
    Confidence below 0.3 is flagged for downstream consumers (manifest).
    """

    def calibrate(
        self,
        obj: SegmentedObject,
        depth_map: np.ndarray,
        camera_fov_deg: float,
        image_size: tuple[int, int],
        room_dimensions_m: tuple[float, float, float],
    ) -> ScaleResult:
        """Compute real-world dimensions from pixel footprint, depth, and FOV.

        Parameters
        ----------
        obj : SegmentedObject
            Object with bounding box and centroid information.
        depth_map : np.ndarray
            Float32 2D array of depth values in meters (H, W).
        camera_fov_deg : float
            Vertical field of view in degrees (default 60°).
        image_size : tuple[int, int]
            Image dimensions as (width, height) in pixels.
        room_dimensions_m : tuple[float, float, float]
            Room dimensions (width, height, depth) in meters for clamping.

        Returns
        -------
        ScaleResult
            Calibrated dimensions, scale factor, and confidence.
        """
        image_width, image_height = image_size
        _, _, bbox_w, bbox_h = obj.bbox
        cx, cy = obj.centroid_px

        # Sample depth at centroid (clamp pixel coords to valid range)
        depth_y = int(max(0, min(depth_map.shape[0] - 1, round(cy))))
        depth_x = int(max(0, min(depth_map.shape[1] - 1, round(cx))))
        depth_at_centroid = float(depth_map[depth_y, depth_x])

        # Handle invalid depth: use median of valid depths as fallback
        if depth_at_centroid <= 0 or not math.isfinite(depth_at_centroid):
            valid_depths = depth_map[(depth_map > 0) & np.isfinite(depth_map)]
            if valid_depths.size > 0:
                depth_at_centroid = float(np.median(valid_depths))
            else:
                # Absolute fallback: assume 3m depth
                depth_at_centroid = 3.0
                logger.warning(
                    "No valid depth values for object %s — using 3.0m fallback",
                    obj.mask_id,
                )

        # Compute real-world dimensions via pinhole model
        # Vertical FOV → fy; assume square pixels → fx = fy
        real_height = pixel_to_meters(
            float(bbox_h), depth_at_centroid, camera_fov_deg, image_height
        )
        real_width = pixel_to_meters(
            float(bbox_w), depth_at_centroid, camera_fov_deg, image_height
        )
        # Heuristic: depth ≈ 60% of width
        real_depth = real_width * _DEPTH_HEURISTIC_RATIO

        # Clamp to room dimensions
        raw_dims = (real_width, real_height, real_depth)
        clamped_dims = clamp_dimensions(raw_dims, room_dimensions_m)

        # Compute scale factor (ratio of clamped to raw average dimension)
        raw_avg = (raw_dims[0] + raw_dims[1] + raw_dims[2]) / 3.0
        clamped_avg = (clamped_dims[0] + clamped_dims[1] + clamped_dims[2]) / 3.0
        scale_factor = clamped_avg / raw_avg if raw_avg > 0 else 1.0

        # Compute confidence
        pixel_footprint = float(bbox_w * bbox_h)
        image_area = float(image_width * image_height)
        confidence = compute_confidence(depth_at_centroid, pixel_footprint, image_area)

        if confidence < 0.3:
            logger.warning(
                "Low scale confidence (%.2f) for object %s — flagged in manifest",
                confidence,
                obj.mask_id,
            )

        return ScaleResult(
            dimensions_m=clamped_dims,
            scale_factor=scale_factor,
            confidence=confidence,
        )
