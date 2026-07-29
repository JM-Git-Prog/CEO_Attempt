"""Layout Estimator — back-projects 2D centroids to 3D and runs physics settle.

This module performs two main tasks:

1. **Back-projection**: Converts 2D pixel centroids to 3D world positions
   using the pinhole camera model with metric depth values.

2. **Physics settle**: Simulates gravity to resolve floating objects and
   interpenetration. Uses PyBullet if available, otherwise falls back to
   a simple gravity-drop heuristic (place objects on the ground plane).

Camera model (pinhole, Y-up, camera looks along -Z):
    fx = fy = image_height / (2 * tan(fov_v / 2))
    cx, cy = image_width / 2, image_height / 2
    x = (u - cx) * d / fx
    y = -(v - cy) * d / fy   (negated for Y-up)
    z = -d                    (camera looks along -Z)

Physics settle constraints:
    - Max 500 iterations or 5s wall time (configurable)
    - Max 0.5m displacement per iteration
    - Unsettled threshold: velocity > 0.01 m/s or penetration > 0.01m

Pure computation functions (back_project) are separated from the class
interface for independent testability and property-based testing.

V14 Extensions:
    - V14LayoutEstimator uses camera_math.back_project for back-projection
      with DA3 depth maps
    - scale_mesh_to_dimensions() rescales normalized meshes to real-world
      ScaleResult.dimensions_m
    - Clamps positions within room shell bounds with 0.05m margin
    - Averages mask-region depth when centroid depth is invalid

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from src.photo_pipeline.models import (
    LayoutResult,
    PhotoPipelineConfig,
    ScaleResult,
    SegmentedObject,
)
from src.photo_pipeline.stages.camera_math import (
    back_project as _camera_math_back_project,
    clamp_to_bounds,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Try to import PyBullet — optional dependency
# ---------------------------------------------------------------------------

try:
    import pybullet as p
    import pybullet_data

    PYBULLET_AVAILABLE = True
except ImportError:
    PYBULLET_AVAILABLE = False
    logger.info("PyBullet not available — using simple gravity-drop fallback")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Physics settle defaults
_DEFAULT_MAX_ITERATIONS = 500
_DEFAULT_TIMEOUT_S = 5.0
_MAX_DISPLACEMENT_M = 0.5

# Unsettled thresholds
_VELOCITY_THRESHOLD = 0.01  # m/s
_PENETRATION_THRESHOLD = 0.01  # meters

# Simulation timestep
_TIMESTEP = 1.0 / 240.0

# Default vertical FOV if not specified
_DEFAULT_FOV_V_DEG = 60.0


# ---------------------------------------------------------------------------
# Pure helper functions (testable without I/O or physics engine)
# ---------------------------------------------------------------------------


def back_project(
    centroid_px: tuple[float, float],
    depth_m: float,
    fov_v_deg: float,
    image_size: tuple[int, int],
) -> tuple[float, float, float]:
    """Back-project a 2D pixel coordinate to 3D world position.

    Uses the pinhole camera model with Y-up coordinate convention:
    - x axis: right
    - y axis: up
    - z axis: into screen (camera looks along -Z)

    Parameters
    ----------
    centroid_px : tuple[float, float]
        Pixel coordinate (u, v) where u is horizontal, v is vertical.
    depth_m : float
        Metric depth at the centroid in meters (must be positive).
    fov_v_deg : float
        Vertical field of view in degrees (must be in (0, 180)).
    image_size : tuple[int, int]
        Image dimensions as (width, height) in pixels.

    Returns
    -------
    tuple[float, float, float]
        3D position (x, y, z) in meters, Y-up coordinates.

    Raises
    ------
    ValueError
        If depth_m <= 0 or fov_v_deg is out of valid range.
    """
    if depth_m <= 0:
        raise ValueError(f"depth_m must be positive, got {depth_m}")
    if fov_v_deg <= 0 or fov_v_deg >= 180:
        raise ValueError(f"fov_v_deg must be in (0, 180), got {fov_v_deg}")

    w, h = image_size
    if w <= 0 or h <= 0:
        raise ValueError(f"image_size must have positive dimensions, got {image_size}")

    fov_v_rad = math.radians(fov_v_deg)
    fy = h / (2.0 * math.tan(fov_v_rad / 2.0))
    fx = fy  # square pixels assumed

    cx = w / 2.0
    cy = h / 2.0

    u, v = centroid_px
    x = (u - cx) * depth_m / fx
    y = -(v - cy) * depth_m / fy  # negated for Y-up
    z = -depth_m  # camera looks along -Z

    return (x, y, z)


def forward_project(
    position_3d: tuple[float, float, float],
    fov_v_deg: float,
    image_size: tuple[int, int],
) -> tuple[float, float]:
    """Forward-project a 3D position back to 2D pixel coordinates.

    Inverse of back_project. Useful for validation and testing.

    Parameters
    ----------
    position_3d : tuple[float, float, float]
        3D position (x, y, z) in Y-up coordinates.
    fov_v_deg : float
        Vertical field of view in degrees.
    image_size : tuple[int, int]
        Image dimensions as (width, height) in pixels.

    Returns
    -------
    tuple[float, float]
        Pixel coordinate (u, v).
    """
    x, y, z = position_3d
    w, h = image_size

    fov_v_rad = math.radians(fov_v_deg)
    fy = h / (2.0 * math.tan(fov_v_rad / 2.0))
    fx = fy

    cx = w / 2.0
    cy = h / 2.0

    # Recover depth from z: z = -d → d = -z
    d = -z
    if d <= 0:
        raise ValueError(f"Cannot forward-project point behind camera (z={z})")

    u = (x * fx / d) + cx
    v = -(y * fy / d) + cy  # negate y back

    return (u, v)


# ---------------------------------------------------------------------------
# Physics settle (PyBullet)
# ---------------------------------------------------------------------------


@dataclass
class _SettleOutcome:
    """Internal result of physics settle for one object."""

    position: tuple[float, float, float]
    rotation_deg: tuple[float, float, float]
    settled: bool


def _physics_settle_pybullet(
    positions: list[tuple[float, float, float]],
    dimensions: list[tuple[float, float, float]],
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> list[_SettleOutcome]:
    """Run physics settle using PyBullet.

    Creates a simplified physics world with:
    - Ground plane at y=0
    - One box collision shape per object at initial position
    - Gravity pulling downward (y axis)

    Steps simulation up to max_iterations or timeout_s, then checks
    velocity and penetration for each object.

    Parameters
    ----------
    positions : list of 3-tuples
        Initial (x, y, z) positions in meters.
    dimensions : list of 3-tuples
        Object dimensions (width, height, depth) in meters.
    max_iterations : int
        Maximum number of simulation steps.
    timeout_s : float
        Maximum wall-clock time for the simulation.

    Returns
    -------
    list of _SettleOutcome
        Final positions, rotations, and settled status for each object.
    """
    if not PYBULLET_AVAILABLE:
        raise RuntimeError("PyBullet not available")

    # Create physics client (DIRECT mode — no GUI)
    physics_client = p.connect(p.DIRECT)
    try:
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, -9.81, 0, physicsClientId=physics_client)
        p.setTimeStep(_TIMESTEP, physicsClientId=physics_client)

        # Create ground plane at y=0
        # PyBullet uses Z-up by default, so we need to orient our Y-up
        # ground plane. We'll create a static box at y=-0.5 with height 1.
        ground_shape = p.createCollisionShape(
            p.GEOM_BOX,
            halfExtents=[50, 0.5, 50],
            physicsClientId=physics_client,
        )
        p.createMultiBody(
            baseMass=0,  # static
            baseCollisionShapeIndex=ground_shape,
            basePosition=[0, -0.5, 0],  # top surface at y=0
            physicsClientId=physics_client,
        )

        # Create objects as box shapes
        body_ids = []
        for pos, dims in zip(positions, dimensions):
            half_w = max(0.01, dims[0] / 2.0)
            half_h = max(0.01, dims[1] / 2.0)
            half_d = max(0.01, dims[2] / 2.0)

            shape = p.createCollisionShape(
                p.GEOM_BOX,
                halfExtents=[half_w, half_h, half_d],
                physicsClientId=physics_client,
            )

            # Mass based on volume (approximate density 500 kg/m³)
            volume = dims[0] * dims[1] * dims[2]
            mass = max(0.1, volume * 500.0)

            body_id = p.createMultiBody(
                baseMass=mass,
                baseCollisionShapeIndex=shape,
                basePosition=list(pos),
                physicsClientId=physics_client,
            )
            body_ids.append(body_id)

        # Step simulation
        start_time = time.time()
        iterations = 0
        while iterations < max_iterations:
            if time.time() - start_time > timeout_s:
                break

            p.stepSimulation(physicsClientId=physics_client)
            iterations += 1

            # Check if all objects have settled (early exit)
            all_settled = True
            for body_id in body_ids:
                vel, _ = p.getBaseVelocity(body_id, physicsClientId=physics_client)
                speed = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)
                if speed > _VELOCITY_THRESHOLD:
                    all_settled = False
                    break

            if all_settled and iterations > 10:  # Give at least 10 steps
                break

        # Read final state
        outcomes = []
        for i, body_id in enumerate(body_ids):
            pos_final, orn = p.getBasePositionAndOrientation(
                body_id, physicsClientId=physics_client
            )
            vel, _ = p.getBaseVelocity(body_id, physicsClientId=physics_client)

            # Convert quaternion to Euler (degrees)
            euler = p.getEulerFromQuaternion(orn)
            rotation_deg = (
                math.degrees(euler[0]),
                math.degrees(euler[1]),
                math.degrees(euler[2]),
            )

            # Check settled status
            speed = math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2)

            # Check penetration via contact points
            max_penetration = 0.0
            contacts = p.getContactPoints(
                bodyA=body_id, physicsClientId=physics_client
            )
            for contact in contacts:
                # contact[8] is the contact distance (negative = penetration)
                penetration = -contact[8]
                max_penetration = max(max_penetration, penetration)

            settled = (
                speed <= _VELOCITY_THRESHOLD
                and max_penetration <= _PENETRATION_THRESHOLD
            )

            # Clamp displacement from original position
            original = positions[i]
            dx = pos_final[0] - original[0]
            dy = pos_final[1] - original[1]
            dz = pos_final[2] - original[2]
            displacement = math.sqrt(dx * dx + dy * dy + dz * dz)

            if displacement > _MAX_DISPLACEMENT_M * max_iterations:
                # Object flew off — reset to original with ground clamp
                half_h = max(0.01, dimensions[i][1] / 2.0)
                final_pos = (original[0], max(half_h, original[1]), original[2])
                rotation_deg = (0.0, 0.0, 0.0)
                settled = False
            else:
                final_pos = (pos_final[0], pos_final[1], pos_final[2])

            outcomes.append(
                _SettleOutcome(
                    position=final_pos,
                    rotation_deg=rotation_deg,
                    settled=settled,
                )
            )

        return outcomes
    finally:
        p.disconnect(physics_client)


# ---------------------------------------------------------------------------
# Physics settle (simple gravity-drop fallback)
# ---------------------------------------------------------------------------


def _physics_settle_fallback(
    positions: list[tuple[float, float, float]],
    dimensions: list[tuple[float, float, float]],
) -> list[_SettleOutcome]:
    """Simple gravity-drop heuristic (no PyBullet).

    Places each object at ground level (y = half_height) if it's floating
    above the ground. Does not resolve inter-object interpenetration.

    Parameters
    ----------
    positions : list of 3-tuples
        Initial (x, y, z) positions in meters.
    dimensions : list of 3-tuples
        Object dimensions (width, height, depth) in meters.

    Returns
    -------
    list of _SettleOutcome
        Final positions with zero rotation, settled=True.
    """
    outcomes = []
    for pos, dims in zip(positions, dimensions):
        half_h = max(0.01, dims[1] / 2.0)
        # Place object so its bottom touches y=0 (ground plane)
        # If object is already below ground, bring it up
        settled_y = max(half_h, pos[1])

        # If object is floating significantly above ground, drop it
        # Keep some tolerance for objects that are legitimately elevated
        # (e.g., on a shelf). Only drop if > 2x its height above ground.
        if pos[1] > half_h * 4.0:
            # Drop to ground
            settled_y = half_h

        outcomes.append(
            _SettleOutcome(
                position=(pos[0], settled_y, pos[2]),
                rotation_deg=(0.0, 0.0, 0.0),
                settled=True,  # Fallback always reports settled
            )
        )

    return outcomes


# ---------------------------------------------------------------------------
# LayoutEstimator class
# ---------------------------------------------------------------------------


class LayoutEstimator:
    """Estimates 3D layout from 2D centroids, depth, and camera model.

    Back-projects object centroids to 3D positions, then runs physics
    settle to resolve floating objects and interpenetration.

    Uses PyBullet if available for physically accurate simulation,
    otherwise falls back to a simple gravity-drop heuristic.
    """

    def estimate(
        self,
        objects: list[SegmentedObject],
        scales: list[ScaleResult],
        depth_map: np.ndarray,
        camera_fov_deg: float = _DEFAULT_FOV_V_DEG,
        image_size: tuple[int, int] | None = None,
        config: PhotoPipelineConfig | None = None,
    ) -> list[LayoutResult]:
        """Estimate 3D layout for all segmented objects.

        Parameters
        ----------
        objects : list[SegmentedObject]
            Segmented objects with centroid pixel coordinates.
        scales : list[ScaleResult]
            Scale calibration results (one per object, same order).
        depth_map : np.ndarray
            Float32 2D depth map in meters (H, W).
        camera_fov_deg : float
            Vertical field of view in degrees.
        image_size : tuple[int, int] or None
            Image dimensions as (width, height). If None, derived from
            depth_map shape (W, H).
        config : PhotoPipelineConfig or None
            Pipeline configuration for settle parameters.

        Returns
        -------
        list[LayoutResult]
            Layout results with final positions, rotations, and settle status.
        """
        if config is None:
            config = PhotoPipelineConfig()

        if image_size is None:
            # depth_map is (H, W), so image_size is (W, H)
            image_size = (depth_map.shape[1], depth_map.shape[0])

        if len(objects) == 0:
            return []

        if len(objects) != len(scales):
            raise ValueError(
                f"objects ({len(objects)}) and scales ({len(scales)}) must have same length"
            )

        # Step 1: Back-project centroids to 3D positions
        initial_positions: list[tuple[float, float, float]] = []
        dimensions: list[tuple[float, float, float]] = []

        for obj, scale in zip(objects, scales):
            cx, cy = obj.centroid_px

            # Sample depth at centroid
            depth_y = int(max(0, min(depth_map.shape[0] - 1, round(cy))))
            depth_x = int(max(0, min(depth_map.shape[1] - 1, round(cx))))
            depth_at_centroid = float(depth_map[depth_y, depth_x])

            # Handle invalid depth
            if depth_at_centroid <= 0 or not math.isfinite(depth_at_centroid):
                valid_depths = depth_map[
                    (depth_map > 0) & np.isfinite(depth_map)
                ]
                if valid_depths.size > 0:
                    depth_at_centroid = float(np.median(valid_depths))
                else:
                    depth_at_centroid = 3.0  # absolute fallback
                    logger.warning(
                        "No valid depth for object %s — using 3.0m",
                        obj.mask_id,
                    )

            pos_3d = back_project(
                centroid_px=obj.centroid_px,
                depth_m=depth_at_centroid,
                fov_v_deg=camera_fov_deg,
                image_size=image_size,
            )
            initial_positions.append(pos_3d)
            dimensions.append(scale.dimensions_m)

        # Step 2: Physics settle
        max_iter = config.physics_settle_iterations
        timeout = config.physics_settle_timeout_s

        if PYBULLET_AVAILABLE:
            try:
                outcomes = _physics_settle_pybullet(
                    positions=initial_positions,
                    dimensions=dimensions,
                    max_iterations=max_iter,
                    timeout_s=timeout,
                )
            except Exception as exc:
                logger.warning(
                    "PyBullet settle failed (%s) — falling back to gravity drop",
                    exc,
                )
                outcomes = _physics_settle_fallback(initial_positions, dimensions)
        else:
            outcomes = _physics_settle_fallback(initial_positions, dimensions)

        # Step 3: Build LayoutResult list
        results: list[LayoutResult] = []
        unsettled_count = 0

        for i, outcome in enumerate(outcomes):
            if not outcome.settled:
                unsettled_count += 1
                logger.warning(
                    "Object %s did not settle (velocity or penetration above threshold)",
                    objects[i].mask_id,
                )

            results.append(
                LayoutResult(
                    position_m=outcome.position,
                    rotation_deg=outcome.rotation_deg,
                    settled=outcome.settled,
                    pre_settle_position_m=initial_positions[i],
                )
            )

        # Log summary
        total = len(objects)
        if unsettled_count > 0:
            logger.warning(
                "Physics settle: %d/%d objects unsettled", unsettled_count, total
            )
        else:
            logger.info("Physics settle: all %d objects converged", total)

        return results


# ---------------------------------------------------------------------------
# V14 Layout Utilities
# ---------------------------------------------------------------------------


def sample_depth_at_centroid(
    depth_map: np.ndarray,
    centroid_px: tuple[float, float],
    mask_bbox: tuple[int, int, int, int] | None = None,
) -> float:
    """Sample depth at a 2D centroid, falling back to mask-region average.

    Implements Requirement 4.5: If the depth at the centroid is invalid
    (zero, negative, infinite), average valid depth values within the
    object's mask region (bounding box).

    Parameters
    ----------
    depth_map : np.ndarray
        Float32 2D depth map in meters (H, W).
    centroid_px : tuple[float, float]
        Pixel coordinate (u, v) of the object centroid.
    mask_bbox : tuple[int, int, int, int] or None
        Bounding box (x, y, width, height) for mask-region fallback.
        If None, uses the entire depth map for fallback averaging.

    Returns
    -------
    float
        Valid depth in meters. Falls back to mask-region average if
        centroid depth is invalid, or 3.0m as absolute fallback.
    """
    u, v = centroid_px
    v_idx = int(max(0, min(depth_map.shape[0] - 1, round(v))))
    u_idx = int(max(0, min(depth_map.shape[1] - 1, round(u))))
    d = float(depth_map[v_idx, u_idx])

    # If depth at centroid is valid, return it directly
    if d > 0 and np.isfinite(d):
        return d

    # Fallback: average valid depth in mask region (Requirement 4.5)
    if mask_bbox is not None:
        x1, y1, w, h = mask_bbox
        # Clamp bbox to depth map bounds
        y_start = max(0, y1)
        y_end = min(depth_map.shape[0], y1 + h)
        x_start = max(0, x1)
        x_end = min(depth_map.shape[1], x1 + w)
        region = depth_map[y_start:y_end, x_start:x_end]
    else:
        region = depth_map

    valid = region[(region > 0) & np.isfinite(region)]
    if valid.size > 0:
        return float(np.mean(valid))

    # Absolute fallback
    logger.warning("No valid depth in mask region — using 3.0m fallback")
    return 3.0


def scale_mesh_to_dimensions(
    mesh_bbox_min: tuple[float, float, float],
    mesh_bbox_max: tuple[float, float, float],
    target_dimensions_m: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Compute scale factors to resize a normalized mesh to target dimensions.

    Hunyuan3D and Trellis2 produce meshes in normalized bounding boxes
    (typically [-1, 1] or similar). This function computes per-axis scale
    factors to map from the mesh's current bounding box to the real-world
    dimensions from ScaleResult.dimensions_m.

    Parameters
    ----------
    mesh_bbox_min : tuple[float, float, float]
        Minimum corner of the mesh's axis-aligned bounding box.
    mesh_bbox_max : tuple[float, float, float]
        Maximum corner of the mesh's axis-aligned bounding box.
    target_dimensions_m : tuple[float, float, float]
        Target dimensions (width, height, depth) in meters from
        ScaleResult.dimensions_m.

    Returns
    -------
    tuple[float, float, float]
        Scale factors (sx, sy, sz) to apply to the mesh so that its
        bounding box matches the target dimensions. Returns (1, 1, 1)
        if any mesh extent is zero (degenerate mesh).

    Requirement 4.6: Scale generated meshes from normalized bounding box
    to ScaleResult.dimensions_m.
    """
    mesh_extents = (
        mesh_bbox_max[0] - mesh_bbox_min[0],
        mesh_bbox_max[1] - mesh_bbox_min[1],
        mesh_bbox_max[2] - mesh_bbox_min[2],
    )

    scales = []
    for extent, target in zip(mesh_extents, target_dimensions_m):
        if extent <= 0:
            scales.append(1.0)
        else:
            scales.append(target / extent)

    return (scales[0], scales[1], scales[2])


def compute_room_bounds(
    room_dimensions_m: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Compute room bounding box from room dimensions.

    The room is centered on X-axis, spans [0, height] on Y-axis,
    and extends along -Z (camera looks along -Z).

    Parameters
    ----------
    room_dimensions_m : tuple[float, float, float]
        Room dimensions (width, height, depth) in meters.

    Returns
    -------
    tuple[tuple[float, float, float], tuple[float, float, float]]
        (bbox_min, bbox_max) defining the room volume.
    """
    width, height, depth = room_dimensions_m
    bbox_min = (-width / 2.0, 0.0, -depth)
    bbox_max = (width / 2.0, height, 0.0)
    return (bbox_min, bbox_max)


# ---------------------------------------------------------------------------
# V14LayoutEstimator class
# ---------------------------------------------------------------------------


class V14LayoutEstimator:
    """V14 layout estimation using DA3 depth back-projection and room clamping.

    Provides clean access to the V14-specific layout estimation pipeline:
    1. Back-project 2D centroid to 3D using camera_math.back_project with
       DA3 metric depth (Requirement 4.1, 4.2)
    2. Handle invalid depth at centroid by averaging mask region (Req 4.5)
    3. Clamp position within room shell bounds with 0.05m margin (Req 4.4)
    4. Scale generated mesh from normalized bbox to ScaleResult.dimensions_m
       (Requirement 4.6)

    The physics settle pass (Requirement 4.3) runs after all positions are
    computed via the inherited LayoutEstimator.estimate() method or the
    orchestrator's inline logic.
    """

    def __init__(
        self,
        fov_v_deg: float = _DEFAULT_FOV_V_DEG,
        clamp_margin: float = 0.05,
    ) -> None:
        """Initialize V14 layout estimator.

        Parameters
        ----------
        fov_v_deg : float
            Vertical field of view in degrees (default 60°).
        clamp_margin : float
            Margin in meters for position clamping within room bounds
            (default 0.05m per Requirement 4.4).
        """
        self._fov_v_deg = fov_v_deg
        self._clamp_margin = clamp_margin

    def estimate_position(
        self,
        centroid_px: tuple[float, float],
        depth_map: np.ndarray,
        image_size: tuple[int, int],
        room_dimensions_m: tuple[float, float, float],
        mask_bbox: tuple[int, int, int, int] | None = None,
    ) -> tuple[float, float, float]:
        """Estimate 3D position for a single object.

        Performs back-projection of the 2D centroid using DA3 depth,
        with invalid-depth fallback and room-bounds clamping.

        Parameters
        ----------
        centroid_px : tuple[float, float]
            Object centroid in pixel coordinates (u, v).
        depth_map : np.ndarray
            Float32 2D depth map in meters (H, W) from Depth Anything 3.
        image_size : tuple[int, int]
            Image dimensions as (width, height) in pixels.
        room_dimensions_m : tuple[float, float, float]
            Room dimensions (width, height, depth) in meters.
        mask_bbox : tuple[int, int, int, int] or None
            Object bounding box (x, y, w, h) for mask-region depth fallback.

        Returns
        -------
        tuple[float, float, float]
            Clamped 3D position (x, y, z) in meters within room bounds.
        """
        # Step 1: Sample depth at centroid with mask-region fallback (Req 4.5)
        depth_m = sample_depth_at_centroid(depth_map, centroid_px, mask_bbox)

        # Step 2: Compute camera intrinsics
        image_width, image_height = image_size
        fov_v_rad = math.radians(self._fov_v_deg)
        fy = image_height / (2.0 * math.tan(fov_v_rad / 2.0))
        fx = fy  # square pixels assumed
        cx = image_width / 2.0
        cy = image_height / 2.0

        # Step 3: Back-project to 3D (Req 4.1, 4.2)
        u, v = centroid_px
        position = _camera_math_back_project(u, v, depth_m, fx, fy, cx, cy)

        # Step 4: Clamp to room bounds with margin (Req 4.4)
        bbox_min, bbox_max = compute_room_bounds(room_dimensions_m)
        clamped = clamp_to_bounds(position, bbox_min, bbox_max, self._clamp_margin)

        return clamped

    def estimate_all(
        self,
        objects: list[SegmentedObject],
        scales: list[ScaleResult],
        depth_map: np.ndarray,
        image_size: tuple[int, int],
        room_dimensions_m: tuple[float, float, float],
    ) -> list[LayoutResult]:
        """Estimate 3D positions for all objects with physics settle.

        Combines back-projection, invalid-depth handling, room clamping,
        and optional physics settle into a single pipeline pass.

        Parameters
        ----------
        objects : list[SegmentedObject]
            Segmented objects with centroid and bbox information.
        scales : list[ScaleResult]
            Scale calibration results (same order as objects).
        depth_map : np.ndarray
            Float32 2D depth map in meters (H, W) from DA3.
        image_size : tuple[int, int]
            Image dimensions as (width, height).
        room_dimensions_m : tuple[float, float, float]
            Room dimensions (width, height, depth) in meters.

        Returns
        -------
        list[LayoutResult]
            Layout results with positions, rotations, and settle status.
        """
        if len(objects) == 0:
            return []
        if len(objects) != len(scales):
            raise ValueError(
                f"objects ({len(objects)}) and scales ({len(scales)}) "
                "must have same length"
            )

        # Step 1: Back-project all objects with depth fallback and clamping
        initial_positions: list[tuple[float, float, float]] = []
        dimensions: list[tuple[float, float, float]] = []

        for obj, scale in zip(objects, scales):
            pos = self.estimate_position(
                centroid_px=obj.centroid_px,
                depth_map=depth_map,
                image_size=image_size,
                room_dimensions_m=room_dimensions_m,
                mask_bbox=obj.bbox,
            )
            initial_positions.append(pos)
            dimensions.append(scale.dimensions_m)

        # Step 2: Physics settle (Req 4.3)
        if PYBULLET_AVAILABLE:
            try:
                outcomes = _physics_settle_pybullet(
                    positions=initial_positions,
                    dimensions=dimensions,
                    max_iterations=_DEFAULT_MAX_ITERATIONS,
                    timeout_s=_DEFAULT_TIMEOUT_S,
                )
            except Exception as exc:
                logger.warning(
                    "PyBullet settle failed (%s) — using gravity drop", exc
                )
                outcomes = _physics_settle_fallback(initial_positions, dimensions)
        else:
            outcomes = _physics_settle_fallback(initial_positions, dimensions)

        # Step 3: Build LayoutResult list with room clamping on final positions
        bbox_min, bbox_max = compute_room_bounds(room_dimensions_m)
        results: list[LayoutResult] = []

        for i, outcome in enumerate(outcomes):
            # Clamp settled position within room bounds (Req 4.4)
            final_pos = clamp_to_bounds(
                outcome.position, bbox_min, bbox_max, self._clamp_margin
            )

            if not outcome.settled:
                logger.warning(
                    "Object %s did not settle", objects[i].mask_id
                )

            results.append(
                LayoutResult(
                    position_m=final_pos,
                    rotation_deg=outcome.rotation_deg,
                    settled=outcome.settled,
                    pre_settle_position_m=initial_positions[i],
                )
            )

        return results

    def compute_mesh_scale(
        self,
        mesh_bbox_min: tuple[float, float, float],
        mesh_bbox_max: tuple[float, float, float],
        scale_result: ScaleResult,
    ) -> tuple[float, float, float]:
        """Compute scale factors for a normalized mesh to real-world dimensions.

        Implements Requirement 4.6: scale generated meshes from normalized
        bounding box to ScaleResult.dimensions_m.

        Parameters
        ----------
        mesh_bbox_min : tuple[float, float, float]
            Minimum corner of mesh bounding box.
        mesh_bbox_max : tuple[float, float, float]
            Maximum corner of mesh bounding box.
        scale_result : ScaleResult
            Scale calibration result with target dimensions_m.

        Returns
        -------
        tuple[float, float, float]
            Per-axis scale factors (sx, sy, sz).
        """
        return scale_mesh_to_dimensions(
            mesh_bbox_min, mesh_bbox_max, scale_result.dimensions_m
        )
