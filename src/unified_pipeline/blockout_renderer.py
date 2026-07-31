"""Blockout renderer for the Unified World Pipeline.

Produces a flat-shaded 3D blockout PNG from a validated MetricPlan and
CameraContract. The blockout shows walls with cutouts for openings,
object placeholders at correct scale, and renders at the CameraContract's
raster dimensions (default 1024×768).

No GPU required — uses PIL software rendering with painter's algorithm.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from src.unified_pipeline.camera_contract import CameraContract as CameraContractImpl
from src.unified_pipeline.models import (
    BlockoutResult,
    CameraContract,
    MetricPlan,
)

# ─── Color palette for flat-shaded blockout ────────────────────────────────────

_COLORS = {
    "wall_front": "#4a5568",
    "wall_side": "#2d3748",
    "wall_top": "#718096",
    "floor": "#1a202c",
    "ceiling_edge": "#4a5568",
    "opening_door": "#2f855a",
    "opening_door_outline": "#68d391",
    "opening_window": "#2b6cb0",
    "opening_window_outline": "#63b3ed",
    "object_top": "#b0b0b0",
    "object_front": "#787878",
    "object_side": "#606060",
    "object_outline": "#e2e8f0",
    "edge": "#a0aec0",
    "label": "#f7fafc",
    "hud_bg": "#0a0e14dd",
    "hud_border": "#4a5568",
    "hud_text": "#e2e8f0",
    "camera_lock": "#a0aec0",
}


# ─── Mesh data types (lightweight 3D polygon representations) ──────────────────

# A "mesh" here is a list of Face dicts:
#   { "vertices": [(x,y,z), ...], "color": str, "outline": str }

Face = dict[str, Any]
Mesh3D = list[Face]


# ─── BlockoutRenderer Class ────────────────────────────────────────────────────


class BlockoutRenderer:
    """Renders a 3D blockout of a MetricPlan from a CameraContract viewpoint.

    The renderer produces a flat-shaded wireframe/polygon image showing:
    - Walls as extruded rectangles (floor to ceiling height)
    - Openings (doors/windows) as colored cutouts in wall geometry
    - Objects as colored boxes at placement positions with correct dimensions

    Output is a PIL Image at CameraContract raster dimensions (1024×768 default).
    Images are saved to output/blockouts/{session_id}/ directory.

    Requirements: 7.1, 7.2, 7.3
    """

    def __init__(self, output_base: Path | None = None) -> None:
        """Initialize renderer.

        Args:
            output_base: Base directory for output. Defaults to ./output/blockouts/.
        """
        self._output_base = output_base or Path("output/blockouts")

    def render(
        self,
        plan: MetricPlan,
        camera: CameraContract | CameraContractImpl,
        session_id: str = "default",
    ) -> BlockoutResult:
        """Render a 3D blockout of the MetricPlan from the CameraContract viewpoint.

        Produces a flat-shaded polygon image showing walls with openings,
        object placeholders at correct scale, and saves at CameraContract
        raster dimensions (1024×768).

        Args:
            plan: Validated MetricPlan with room_dimensions, walls, openings,
                  and object_placements.
            camera: Immutable CameraContract defining projection parameters.
            session_id: Session identifier for output directory naming.

        Returns:
            BlockoutResult with image_path, plan_revision, camera_hash, approved=False.
        """
        width = camera.raster_width
        height = camera.raster_height

        # Build projection function from CameraContract
        project = _build_projector(camera)

        # Render wall meshes
        wall_meshes = self._render_walls(plan)

        # Render opening meshes (colored quads that overlay walls)
        opening_meshes = self._render_openings(plan)

        # Render object placeholder meshes
        placeholder_meshes = self._render_placeholders(plan)

        # Project all meshes to a PIL Image
        image = self._project_to_image(
            wall_meshes + opening_meshes + placeholder_meshes,
            camera,
            project,
            plan,
        )

        # Save output
        output_dir = self._output_base / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        revision = plan.revisions[-1].revision if plan.revisions else 1
        output_path = output_dir / f"blockout_v{revision}.png"
        image.save(str(output_path), "PNG")

        # Compute camera hash
        camera_hash = ""
        if hasattr(camera, "compute_hash"):
            camera_hash = camera.compute_hash()
        elif hasattr(camera, "camera_hash"):
            camera_hash = camera.camera_hash

        return BlockoutResult(
            image_path=str(output_path),
            plan_revision=revision,
            camera_hash=camera_hash,
            approved=False,
            feedback="",
        )

    def _render_walls(self, plan: MetricPlan) -> Mesh3D:
        """Produce 3D wall meshes as line/polygon data for rendering.

        Walls are extruded rectangles from floor to ceiling height.
        The room is centered at origin with dimensions from plan.room_dimensions.

        Returns:
            List of Face dicts representing wall geometry.
        """
        rx, ry, rz = plan.room_dimensions
        hw, hd = rx / 2.0, rz / 2.0
        h = ry

        faces: Mesh3D = []

        # Floor quad
        floor_corners = [
            (-hw, 0.0, -hd),
            (hw, 0.0, -hd),
            (hw, 0.0, hd),
            (-hw, 0.0, hd),
        ]
        faces.append({
            "vertices": floor_corners,
            "color": _COLORS["floor"],
            "outline": _COLORS["edge"],
            "kind": "floor",
        })

        # Four walls as quads
        wall_definitions = [
            # North wall (far, +Z)
            {"vertices": [(-hw, 0.0, hd), (hw, 0.0, hd), (hw, h, hd), (-hw, h, hd)], "name": "north"},
            # South wall (near, -Z)
            {"vertices": [(hw, 0.0, -hd), (-hw, 0.0, -hd), (-hw, h, -hd), (hw, h, -hd)], "name": "south"},
            # East wall (+X)
            {"vertices": [(hw, 0.0, hd), (hw, 0.0, -hd), (hw, h, -hd), (hw, h, hd)], "name": "east"},
            # West wall (-X)
            {"vertices": [(-hw, 0.0, -hd), (-hw, 0.0, hd), (-hw, h, hd), (-hw, h, -hd)], "name": "west"},
        ]

        for wall_def in wall_definitions:
            faces.append({
                "vertices": wall_def["vertices"],
                "color": _COLORS["wall_front"],
                "outline": _COLORS["edge"],
                "kind": "wall",
                "wall_name": wall_def["name"],
            })

        # Ceiling edges (wireframe only)
        ceiling_edges = [
            [(-hw, h, -hd), (hw, h, -hd)],
            [(hw, h, -hd), (hw, h, hd)],
            [(hw, h, hd), (-hw, h, hd)],
            [(-hw, h, hd), (-hw, h, -hd)],
        ]
        for edge in ceiling_edges:
            faces.append({
                "vertices": edge,
                "color": _COLORS["ceiling_edge"],
                "outline": _COLORS["ceiling_edge"],
                "kind": "ceiling_edge",
            })

        return faces

    def _render_openings(self, plan: MetricPlan) -> Mesh3D:
        """Cut openings in wall geometry by rendering colored quads.

        Doors and windows are represented as colored overlays on wall faces,
        positioned according to the opening's wall reference and parameter.

        Returns:
            List of Face dicts representing opening geometry.
        """
        rx, ry, rz = plan.room_dimensions
        hw, hd = rx / 2.0, rz / 2.0

        faces: Mesh3D = []

        for opening in plan.openings:
            wall = opening.get("wall", "")
            kind = opening.get("kind", "door")
            width_m = opening.get("width", 0.9)
            height_m = opening.get("height", 2.1)
            sill = opening.get("sill_height", 0.0)
            offset = opening.get("offset", 0.0)
            position_param = opening.get("position", None)

            if position_param is not None:
                # Convert parameter (0..1) to offset from center
                if wall in ("north", "south"):
                    wall_length = rx
                else:
                    wall_length = rz
                offset = (position_param - 0.5) * wall_length

            half_w = width_m / 2.0
            low = sill
            high = sill + height_m

            # Build quad vertices based on wall
            if wall == "north":
                vertices = [
                    (offset - half_w, low, hd),
                    (offset + half_w, low, hd),
                    (offset + half_w, high, hd),
                    (offset - half_w, high, hd),
                ]
            elif wall == "south":
                vertices = [
                    (offset + half_w, low, -hd),
                    (offset - half_w, low, -hd),
                    (offset - half_w, high, -hd),
                    (offset + half_w, high, -hd),
                ]
            elif wall == "east":
                vertices = [
                    (hw, low, offset - half_w),
                    (hw, low, offset + half_w),
                    (hw, high, offset + half_w),
                    (hw, high, offset - half_w),
                ]
            elif wall == "west":
                vertices = [
                    (-hw, low, offset + half_w),
                    (-hw, low, offset - half_w),
                    (-hw, high, offset - half_w),
                    (-hw, high, offset + half_w),
                ]
            else:
                continue

            if kind == "window":
                fill = _COLORS["opening_window"]
                outline = _COLORS["opening_window_outline"]
            else:
                fill = _COLORS["opening_door"]
                outline = _COLORS["opening_door_outline"]

            faces.append({
                "vertices": vertices,
                "color": fill,
                "outline": outline,
                "kind": "opening",
                "opening_type": kind,
                "label": kind.upper(),
            })

        return faces

    def _render_placeholders(self, plan: MetricPlan) -> Mesh3D:
        """Render box/cylinder placeholders at object placement positions.

        Objects are represented as flat-shaded boxes positioned and rotated
        according to their placement data. Dimensions come from the plan's
        object_placements.

        Returns:
            List of Face dicts representing object placeholder geometry.
        """
        faces: Mesh3D = []

        for obj in plan.object_placements:
            pos = obj.get("position", [0.0, 0.0, 0.0])
            dims = obj.get("dimensions", [0.5, 0.5, 0.5])
            rotation_deg = obj.get("rotation", 0.0)
            name = obj.get("name", obj.get("id", "object"))

            cx, cy, cz = float(pos[0]), float(pos[1]), float(pos[2])
            w, h, d = float(dims[0]), float(dims[1]), float(dims[2])

            # Build box vertices with rotation around Y axis
            angle = math.radians(float(rotation_deg))
            cos_a, sin_a = math.cos(angle), math.sin(angle)

            local_corners = [
                (-w / 2, -d / 2),
                (w / 2, -d / 2),
                (w / 2, d / 2),
                (-w / 2, d / 2),
            ]

            # Base corners (bottom of object)
            base = [
                (cx + x * cos_a - z * sin_a, cy, cz + x * sin_a + z * cos_a)
                for x, z in local_corners
            ]
            # Top corners
            top = [(bx, cy + h, bz) for bx, _, bz in base]

            # Generate box faces
            box_faces = _make_box_faces(base, top, name)
            faces.extend(box_faces)

        return faces

    def _project_to_image(
        self,
        meshes: Mesh3D,
        camera: CameraContract | CameraContractImpl,
        project,
        plan: MetricPlan,
    ) -> Image.Image:
        """Project all meshes onto a 2D PIL Image at CameraContract raster dimensions.

        Uses painter's algorithm (back-to-front depth sorting) for correct
        occlusion without a Z-buffer.

        Args:
            meshes: Combined list of Face dicts from walls, openings, placeholders.
            camera: CameraContract for raster dimensions.
            project: Projection closure from _build_projector.
            plan: MetricPlan for HUD info.

        Returns:
            PIL Image at camera.raster_width × camera.raster_height.
        """
        width = camera.raster_width
        height = camera.raster_height
        cam_pos = np.array(camera.position, dtype=np.float64)

        canvas = Image.new("RGB", (width, height), "#0f1419")
        draw = ImageDraw.Draw(canvas)

        # Draw gradient background
        _draw_gradient(draw, width, height)

        # Separate ceiling edges (wireframe) from filled faces
        ceiling_edges = [f for f in meshes if f.get("kind") == "ceiling_edge"]
        filled_faces = [f for f in meshes if f.get("kind") != "ceiling_edge"]

        # Sort filled faces by depth (back-to-front via painter's algorithm)
        def _face_depth(face: Face) -> float:
            verts = face["vertices"]
            center = np.mean([np.array(v, dtype=np.float64) for v in verts], axis=0)
            return float(np.linalg.norm(center - cam_pos))

        filled_faces.sort(key=_face_depth, reverse=True)

        # Draw filled faces
        for face in filled_faces:
            vertices = face["vertices"]
            projected = [project(v) for v in vertices]
            if not all(projected):
                continue

            points = [(p[0], p[1]) for p in projected]
            color = face["color"]
            outline = face.get("outline", color)
            kind = face.get("kind", "")

            draw.polygon(points, fill=color, outline=outline)

            # Draw thicker outlines for openings
            if kind == "opening":
                for i in range(len(points)):
                    j = (i + 1) % len(points)
                    draw.line(
                        (points[i][0], points[i][1], points[j][0], points[j][1]),
                        fill=outline,
                        width=4,
                    )
                # Label the opening
                cx_s = sum(p[0] for p in points) / len(points)
                cy_s = sum(p[1] for p in points) / len(points)
                label = face.get("label", "")
                if label:
                    draw.text((cx_s - 20, cy_s - 6), label, fill=_COLORS["label"])

            # Label objects (top face)
            if kind == "object_top":
                label = face.get("label", "")
                if label:
                    draw.text(
                        (points[0][0] + 4, points[0][1] - 14),
                        label[:24],
                        fill=_COLORS["label"],
                    )

        # Draw ceiling edges
        for edge in ceiling_edges:
            verts = edge["vertices"]
            if len(verts) >= 2:
                a, b = project(verts[0]), project(verts[1])
                if a and b:
                    draw.line(
                        (a[0], a[1], b[0], b[1]),
                        fill=edge["color"],
                        width=2,
                    )

        # Draw HUD overlay
        _draw_hud(draw, plan, camera, width, height)

        return canvas


# ─── Public convenience function (backward compatibility) ──────────────────────


def render_blockout(
    plan: MetricPlan,
    camera: CameraContract | CameraContractImpl,
    output_path: Path,
) -> BlockoutResult:
    """Render a 3D blockout of the MetricPlan from the CameraContract viewpoint.

    Convenience function wrapping BlockoutRenderer for backward compatibility.

    Args:
        plan: Validated MetricPlan with room_dimensions, walls, openings,
              and object_placements.
        camera: Immutable CameraContract defining projection parameters.
        output_path: Filesystem path to write the output PNG.

    Returns:
        BlockoutResult with image_path, plan_revision, and camera_hash.
    """
    renderer = BlockoutRenderer(output_base=output_path.parent)
    # Use parent dir as base and set session_id to empty to write directly
    width = camera.raster_width
    height = camera.raster_height

    project = _build_projector(camera)

    wall_meshes = renderer._render_walls(plan)
    opening_meshes = renderer._render_openings(plan)
    placeholder_meshes = renderer._render_placeholders(plan)

    image = renderer._project_to_image(
        wall_meshes + opening_meshes + placeholder_meshes,
        camera,
        project,
        plan,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(output_path), "PNG")

    revision = plan.revisions[-1].revision if plan.revisions else 1

    camera_hash = ""
    if hasattr(camera, "compute_hash"):
        camera_hash = camera.compute_hash()
    elif hasattr(camera, "camera_hash"):
        camera_hash = camera.camera_hash

    return BlockoutResult(
        image_path=str(output_path),
        plan_revision=revision,
        camera_hash=camera_hash,
        approved=False,
        feedback="",
    )


# ─── Projection ───────────────────────────────────────────────────────────────


def _build_projector(camera: CameraContract | CameraContractImpl):
    """Build a projection closure from CameraContract fields.

    Returns a function (world_point) -> (screen_x, screen_y, depth) or None.
    """
    cam_pos = np.array(camera.position, dtype=np.float64)
    cam_target = np.array(camera.target, dtype=np.float64)
    cam_up = np.array(camera.up, dtype=np.float64)

    forward = cam_target - cam_pos
    forward_len = np.linalg.norm(forward)
    if forward_len < 1e-9:
        forward = np.array([0.0, 0.0, -1.0])
    else:
        forward = forward / forward_len

    right = np.cross(forward, cam_up)
    right_len = np.linalg.norm(right)
    if right_len < 1e-9:
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / right_len

    up = np.cross(right, forward)

    width = camera.raster_width
    height = camera.raster_height
    focal = (height / 2.0) / math.tan(math.radians(camera.vfov) / 2.0)
    near = camera.near

    def project(vertex: tuple[float, float, float]):
        """Project a 3D world point to 2D screen coordinates.

        Returns (screen_x, screen_y, depth) or None if behind camera.
        """
        relative = np.array(vertex, dtype=np.float64) - cam_pos
        depth = float(np.dot(relative, forward))
        if depth <= near:
            return None
        sx = width / 2.0 + float(np.dot(relative, right)) * focal / depth
        sy = height / 2.0 - float(np.dot(relative, up)) * focal / depth
        return (sx, sy, depth)

    return project


# ─── Background ────────────────────────────────────────────────────────────────


def _draw_gradient(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
    """Draw a subtle vertical gradient background."""
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(15 + t * 10)
        g = int(20 + t * 12)
        b = int(25 + t * 15)
        draw.line((0, y, width, y), fill=(r, g, b))


# ─── Box face generation ──────────────────────────────────────────────────────


def _make_box_faces(
    base: list[tuple[float, float, float]],
    top: list[tuple[float, float, float]],
    label: str = "",
) -> Mesh3D:
    """Generate box faces from base and top corner lists.

    Base indices: 0-3, Top indices: 4-7
    """
    faces: Mesh3D = []

    # Top face
    faces.append({
        "vertices": list(top),
        "color": _COLORS["object_top"],
        "outline": _COLORS["object_outline"],
        "kind": "object_top",
        "label": label,
    })

    # Front face (base[0], base[1], top[1], top[0])
    faces.append({
        "vertices": [base[0], base[1], top[1], top[0]],
        "color": _COLORS["object_front"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
    })

    # Right face (base[1], base[2], top[2], top[1])
    faces.append({
        "vertices": [base[1], base[2], top[2], top[1]],
        "color": _COLORS["object_side"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
    })

    # Back face (base[2], base[3], top[3], top[2])
    faces.append({
        "vertices": [base[2], base[3], top[3], top[2]],
        "color": _COLORS["object_front"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
    })

    # Left face (base[3], base[0], top[0], top[3])
    faces.append({
        "vertices": [base[3], base[0], top[0], top[3]],
        "color": _COLORS["object_side"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
    })

    return faces


# ─── HUD ───────────────────────────────────────────────────────────────────────


def _draw_hud(
    draw: ImageDraw.ImageDraw,
    plan: MetricPlan,
    camera: CameraContract | CameraContractImpl,
    width: int,
    height: int,
) -> None:
    """Draw overlay HUD with plan info and camera lock label."""
    rx, ry, rz = plan.room_dimensions
    revision = plan.revisions[-1].revision if plan.revisions else 1
    obj_count = len(plan.object_placements)
    opening_count = len(plan.openings)

    # Top-left info box
    info_text = (
        f"BLOCKOUT \u00b7 Rev {revision} \u00b7 "
        f"{rx:.1f}m \u00d7 {rz:.1f}m \u00d7 {ry:.1f}m \u00b7 "
        f"{obj_count} objects \u00b7 {opening_count} openings"
    )
    text_width = min(len(info_text) * 7 + 40, width - 36)
    draw.rectangle((18, 18, 18 + text_width, 58), fill=_COLORS["hud_bg"], outline=_COLORS["hud_border"])
    draw.text((32, 30), info_text, fill=_COLORS["hud_text"])

    # Bottom camera lock label
    camera_hash = ""
    if hasattr(camera, "compute_hash"):
        camera_hash = camera.compute_hash()
    elif hasattr(camera, "camera_hash"):
        camera_hash = camera.camera_hash

    lock_label = f"CAMERA LOCK \u00b7 vfov={camera.vfov:.0f}\u00b0 \u00b7 {camera.raster_width}\u00d7{camera.raster_height}"
    if camera_hash:
        lock_label += f" \u00b7 hash={camera_hash[:12]}\u2026"
    draw.text((20, height - 28), lock_label, fill=_COLORS["camera_lock"])
