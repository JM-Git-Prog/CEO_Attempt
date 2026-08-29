"""Capture Planner — deterministic camera trajectory from MetricPlan geometry.

Computes a set of cameras (hero + coverage + transition) with EXACT known
intrinsics and extrinsics derived from MetricPlan room dimensions and the
immutable CameraContract. There is no pose estimation anywhere — every camera
matrix is declared, not recovered.

This is the foundation module for the geometry-injected capture planning spec.
Downstream modules (depth_sequence_renderer, controlnet_conditioner,
depth_backprojector) consume the CaptureManifest produced here.

Authority note: CapturePlanner READS MetricPlan geometry to place cameras. It
never claims spatial authority — it specifies WHERE to point cameras, not what
the geometry IS. MetricPlan remains the sole spatial authority.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.unified_pipeline.models import CameraContract, MetricPlan


# ─── Constants ──────────────────────────────────────────────────────────────

WALL_CLEARANCE_M = 0.3
DEFAULT_EYE_HEIGHT_M = 1.62
SMALL_ROOM_THRESHOLD_M = 3.0


# ─── Data Models ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlannedCamera:
    """One camera in the planned trajectory with exact known transforms.

    All matrices are declared deterministically from MetricPlan + CameraContract.
    No field is estimated from image data.
    """

    position: tuple[float, float, float]
    target: tuple[float, float, float]
    up: tuple[float, float, float]
    extrinsic: tuple[tuple[float, ...], ...]  # 4x4 world-to-camera as nested tuples
    intrinsic: tuple[tuple[float, ...], ...]  # 3x3 camera matrix K as nested tuples
    camera_type: str  # "hero" | "coverage" | "transition"
    label: str
    vfov: float = 60.0
    raster_width: int = 1024
    raster_height: int = 768
    hash: str = ""

    def extrinsic_array(self) -> np.ndarray:
        """Return the 4x4 extrinsic as a float64 numpy array."""
        return np.array(self.extrinsic, dtype=np.float64)

    def intrinsic_array(self) -> np.ndarray:
        """Return the 3x3 intrinsic as a float64 numpy array."""
        return np.array(self.intrinsic, dtype=np.float64)

    def to_camera_contract(self) -> CameraContract:
        """Build a CameraContract matching this planned camera's framing.

        Enables reuse of render_controlled_depth and existing generation paths
        that consume a CameraContract.
        """
        return CameraContract(
            position=self.position,
            target=self.target,
            up=self.up,
            vfov=self.vfov,
            aspect=self.raster_width / self.raster_height,
            raster_width=self.raster_width,
            raster_height=self.raster_height,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": list(self.position),
            "target": list(self.target),
            "up": list(self.up),
            "extrinsic": [list(row) for row in self.extrinsic],
            "intrinsic": [list(row) for row in self.intrinsic],
            "camera_type": self.camera_type,
            "label": self.label,
            "vfov": self.vfov,
            "raster_width": self.raster_width,
            "raster_height": self.raster_height,
            "hash": self.hash,
        }


@dataclass
class CaptureManifest:
    """Complete camera trajectory with exact known transforms."""

    cameras: list[PlannedCamera] = field(default_factory=list)
    room_dimensions: tuple[float, float, float] = (4.0, 3.0, 2.7)
    plan_revision_hash: str = ""
    total_surface_coverage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cameras": [c.to_dict() for c in self.cameras],
            "room_dimensions": list(self.room_dimensions),
            "plan_revision_hash": self.plan_revision_hash,
            "total_surface_coverage": self.total_surface_coverage,
        }

    def hero(self) -> PlannedCamera | None:
        """Return the hero camera if present."""
        for cam in self.cameras:
            if cam.camera_type == "hero":
                return cam
        return self.cameras[0] if self.cameras else None


# ─── Linear Algebra Helpers ─────────────────────────────────────────────────


def _look_at_extrinsic(
    position: tuple[float, float, float],
    target: tuple[float, float, float],
    up: tuple[float, float, float],
) -> np.ndarray:
    """Compute a 4x4 world-to-camera extrinsic matrix via the look-at convention.

    Right-handed, X-right, Y-up, camera looks down -Z (OpenGL/CameraContract
    convention). The returned matrix maps world coordinates to camera coordinates:
        p_camera = R @ p_world + t   (stored as homogeneous 4x4).

    Args:
        position: Camera eye position in world space.
        target: Point the camera looks at.
        up: Up direction hint.

    Returns:
        4x4 float64 world-to-camera matrix.
    """
    eye = np.array(position, dtype=np.float64)
    center = np.array(target, dtype=np.float64)
    up_vec = np.array(up, dtype=np.float64)

    # Forward axis (camera looks toward target). Camera -Z points forward,
    # so the camera-space +Z basis vector points backward (eye - target).
    forward = center - eye
    fnorm = np.linalg.norm(forward)
    if fnorm < 1e-9:
        # Degenerate: target coincides with position; default to -Z look.
        forward = np.array([0.0, 0.0, -1.0], dtype=np.float64)
        fnorm = 1.0
    forward = forward / fnorm

    # Right axis = forward x up
    right = np.cross(forward, up_vec)
    rnorm = np.linalg.norm(right)
    if rnorm < 1e-9:
        # up parallel to forward; pick an alternate up
        alt_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        right = np.cross(forward, alt_up)
        rnorm = np.linalg.norm(right)
        if rnorm < 1e-9:
            right = np.array([1.0, 0.0, 0.0], dtype=np.float64)
            rnorm = 1.0
    right = right / rnorm

    # True up axis = right x forward
    true_up = np.cross(right, forward)

    # Camera basis rows: x=right, y=true_up, z=-forward (camera looks down -Z)
    rotation = np.stack([right, true_up, -forward], axis=0)  # 3x3 world->camera
    translation = -rotation @ eye

    extrinsic = np.eye(4, dtype=np.float64)
    extrinsic[:3, :3] = rotation
    extrinsic[:3, 3] = translation
    return extrinsic


def intrinsic_from_vfov(
    vfov_deg: float = 60.0, width: int = 1024, height: int = 768
) -> np.ndarray:
    """Compute a 3x3 pinhole intrinsic matrix from vertical FOV and raster size.

    Square pixels are assumed (fx == fy). Principal point at image center.

    For vfov=60, height=768: fy = 384 / tan(30 deg) ~= 665.1.

    Args:
        vfov_deg: Vertical field of view in degrees.
        width: Raster width in pixels.
        height: Raster height in pixels.

    Returns:
        3x3 float64 camera intrinsic matrix K.
    """
    vfov_rad = math.radians(vfov_deg)
    fy = (height / 2.0) / math.tan(vfov_rad / 2.0)
    fx = fy  # square pixels
    cx = width / 2.0
    cy = height / 2.0
    return np.array(
        [[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64
    )


def _matrix_to_tuples(m: np.ndarray) -> tuple[tuple[float, ...], ...]:
    """Convert a numpy matrix to nested tuples of floats for frozen storage."""
    return tuple(tuple(float(v) for v in row) for row in m)


def _camera_hash(
    position: tuple[float, float, float],
    target: tuple[float, float, float],
    intrinsic: np.ndarray,
) -> str:
    """Compute a stable SHA-256 hash binding a camera's framing + intrinsics."""
    payload = {
        "position": [round(v, 6) for v in position],
        "target": [round(v, 6) for v in target],
        "intrinsic": [[round(float(v), 6) for v in row] for row in intrinsic],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ─── Capture Planner ────────────────────────────────────────────────────────


class CapturePlanner:
    """Plans a deterministic camera trajectory from MetricPlan + CameraContract.

    Coordinate convention (matching the existing multi_view_generator and
    render_controlled_depth): room is centered at world origin on the XZ plane.
    Room spans x in [-width/2, width/2], z in [-depth/2, depth/2], y in
    [0, ceiling]. Cameras sit at eye height near the center looking outward.

    Requirements: 2.1-2.7
    """

    def __init__(
        self,
        metric_plan: MetricPlan | None = None,
        camera_contract: CameraContract | None = None,
    ) -> None:
        self._plan = metric_plan
        self._contract = camera_contract or CameraContract()

    # ── Public API ──────────────────────────────────────────────────────────

    def plan(self) -> CaptureManifest:
        """Produce a deterministic CaptureManifest.

        If no MetricPlan is available, falls back to the legacy 5 cardinal
        cameras (backward compatibility with _compute_cardinal_cameras).
        """
        if self._plan is None:
            return self._plan_fallback_cardinal()

        width, depth, ceiling = self._plan.room_dimensions
        cameras: list[PlannedCamera] = []

        hero = self._plan_hero()
        cameras.append(hero)

        coverage = self._plan_coverage(width, depth, ceiling)
        cameras.extend(coverage)

        transitions = self._plan_transitions(hero, coverage)
        cameras.extend(transitions)

        coverage_estimate = self._estimate_surface_coverage(cameras, width, depth)

        return CaptureManifest(
            cameras=cameras,
            room_dimensions=(width, depth, ceiling),
            plan_revision_hash=self._plan_hash(),
            total_surface_coverage=coverage_estimate,
        )

    # ── Camera planning ──────────────────────────────────────────────────────

    def _plan_hero(self) -> PlannedCamera:
        """Hero camera taken directly from the CameraContract framing."""
        c = self._contract
        return self._make_camera(
            position=c.position,
            target=c.target,
            up=c.up,
            camera_type="hero",
            label="hero",
            vfov=c.vfov,
            width=c.raster_width,
            height=c.raster_height,
        )

    def _plan_coverage(
        self, width: float, depth: float, ceiling: float
    ) -> list[PlannedCamera]:
        """One camera per wall, positioned at room center looking outward.

        Small rooms get fewer coverage views (walls are close and the hero
        already sees most surfaces).
        """
        eye_h = min(DEFAULT_EYE_HEIGHT_M, ceiling * 0.6)
        center = (0.0, eye_h, 0.0)
        look_h = eye_h * 0.9

        # Wall targets in room-centered coordinates.
        wall_targets = {
            "north": (0.0, look_h, depth / 2.0),
            "east": (width / 2.0, look_h, 0.0),
            "south": (0.0, look_h, -depth / 2.0),
            "west": (-width / 2.0, look_h, 0.0),
        }

        min_dim = min(width, depth)
        if min_dim < SMALL_ROOM_THRESHOLD_M:
            # Small room: hero + two orthogonal coverage views suffice.
            selected = ("north", "east")
        else:
            selected = ("north", "east", "south", "west")

        cameras: list[PlannedCamera] = []
        for wall in selected:
            target = wall_targets[wall]
            cameras.append(
                self._make_camera(
                    position=center,
                    target=target,
                    up=(0.0, 1.0, 0.0),
                    camera_type="coverage",
                    label=f"coverage_{wall}",
                )
            )
        return cameras

    def _plan_transitions(
        self, hero: PlannedCamera, coverage: list[PlannedCamera]
    ) -> list[PlannedCamera]:
        """Interpolate transition cameras between hero and first coverage view.

        These give a video generator continuity between key views. Kept minimal
        (one midpoint) to bound generation cost.
        """
        if not coverage:
            return []

        first = coverage[0]
        mid_pos = tuple(
            (h + c) / 2.0 for h, c in zip(hero.position, first.position)
        )
        mid_target = tuple(
            (h + c) / 2.0 for h, c in zip(hero.target, first.target)
        )
        return [
            self._make_camera(
                position=mid_pos,  # type: ignore[arg-type]
                target=mid_target,  # type: ignore[arg-type]
                up=(0.0, 1.0, 0.0),
                camera_type="transition",
                label="transition_hero_to_coverage0",
            )
        ]

    def _plan_fallback_cardinal(self) -> CaptureManifest:
        """Legacy 5 cardinal cameras for backward compatibility (no MetricPlan).

        Mirrors multi_view_generator._compute_cardinal_cameras: center of a
        default 4x4x2.7 room, eye height 1.62, looking at each cardinal wall.
        """
        width, depth, ceiling = 4.0, 4.0, 2.7
        eye_h = min(DEFAULT_EYE_HEIGHT_M, ceiling * 0.6)
        center = (0.0, eye_h, 0.0)
        look_h = eye_h * 0.9

        specs = [
            ((0.0, look_h, -depth / 2.0), "hero", "hero_south"),
            ((0.0, look_h, depth / 2.0), "coverage", "north"),
            ((width / 2.0, look_h, 0.0), "coverage", "east"),
            ((0.0, look_h, -depth / 2.0), "coverage", "south"),
            ((-width / 2.0, look_h, 0.0), "coverage", "west"),
        ]
        cameras = [
            self._make_camera(
                position=center,
                target=target,
                up=(0.0, 1.0, 0.0),
                camera_type=ctype,
                label=label,
            )
            for target, ctype, label in specs
        ]
        return CaptureManifest(
            cameras=cameras,
            room_dimensions=(width, depth, ceiling),
            plan_revision_hash="fallback_cardinal",
            total_surface_coverage=0.0,
        )

    # ── Construction helpers ─────────────────────────────────────────────────

    def _make_camera(
        self,
        position: tuple[float, float, float],
        target: tuple[float, float, float],
        up: tuple[float, float, float],
        camera_type: str,
        label: str,
        vfov: float | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> PlannedCamera:
        """Build a PlannedCamera with clamped position and exact K/R/t."""
        vfov = vfov if vfov is not None else self._contract.vfov
        width = width if width is not None else self._contract.raster_width
        height = height if height is not None else self._contract.raster_height

        clamped = self._clamp_inside_room(position)
        intrinsic = intrinsic_from_vfov(vfov, width, height)
        extrinsic = _look_at_extrinsic(clamped, target, up)
        cam_hash = _camera_hash(clamped, target, intrinsic)

        return PlannedCamera(
            position=clamped,
            target=target,
            up=up,
            extrinsic=_matrix_to_tuples(extrinsic),
            intrinsic=_matrix_to_tuples(intrinsic),
            camera_type=camera_type,
            label=label,
            vfov=vfov,
            raster_width=width,
            raster_height=height,
            hash=cam_hash,
        )

    def _clamp_inside_room(
        self, position: tuple[float, float, float]
    ) -> tuple[float, float, float]:
        """Clamp a camera position to stay >= WALL_CLEARANCE_M from every wall.

        Room is centered at origin: x in [-w/2, w/2], z in [-d/2, d/2],
        y in [0, ceiling].
        """
        if self._plan is None:
            width, depth, ceiling = 4.0, 4.0, 2.7
        else:
            width, depth, ceiling = self._plan.room_dimensions

        half_w = max(0.0, width / 2.0 - WALL_CLEARANCE_M)
        half_d = max(0.0, depth / 2.0 - WALL_CLEARANCE_M)
        y_min = WALL_CLEARANCE_M
        y_max = max(y_min, ceiling - WALL_CLEARANCE_M)

        x = float(np.clip(position[0], -half_w, half_w))
        y = float(np.clip(position[1], y_min, y_max))
        z = float(np.clip(position[2], -half_d, half_d))
        return (x, y, z)

    def _plan_hash(self) -> str:
        """Stable hash of the MetricPlan revision for provenance binding."""
        if self._plan is None:
            return "no_plan"
        canonical = json.dumps(
            self._plan.to_dict(), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    # ── Analysis ─────────────────────────────────────────────────────────────

    def _estimate_surface_coverage(
        self, cameras: list[PlannedCamera], width: float, depth: float
    ) -> float:
        """Rough estimate of the fraction of the 4 walls covered by some camera.

        A wall is "covered" if a camera's forward direction has a positive dot
        product with the wall's inward normal above a threshold.
        """
        wall_inward_normals = {
            "north": np.array([0.0, 0.0, -1.0]),  # +Z wall faces inward -Z
            "east": np.array([-1.0, 0.0, 0.0]),
            "south": np.array([0.0, 0.0, 1.0]),
            "west": np.array([1.0, 0.0, 0.0]),
        }
        covered: set[str] = set()
        for cam in cameras:
            fwd = np.array(cam.target) - np.array(cam.position)
            n = np.linalg.norm(fwd)
            if n < 1e-9:
                continue
            fwd = fwd / n
            for wall, inward in wall_inward_normals.items():
                # Camera looks toward a wall if forward opposes the inward normal
                if float(np.dot(fwd, -inward)) > 0.5:
                    covered.add(wall)
        return len(covered) / 4.0
