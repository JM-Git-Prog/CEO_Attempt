"""Blockout renderer for the Unified World Pipeline.

Produces a flat-shaded 3D blockout PNG from a validated MetricPlan and
CameraContract. The blockout shows walls with cutouts for openings,
object placeholders at correct scale, and renders at the CameraContract's
raster dimensions (default 1024×768).

No GPU required — uses PIL software rendering with painter's algorithm.

Requirements: 7.1, 7.2, 7.3
"""

from __future__ import annotations

import hashlib
import json
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


_ENTITY_COLORS = (
    "#f6ad55",
    "#68d391",
    "#63b3ed",
    "#fc8181",
    "#b794f4",
    "#f6e05e",
    "#4fd1c5",
)


def _entity_color(index: int) -> str:
    return _ENTITY_COLORS[index % len(_ENTITY_COLORS)]


# ─── Mesh data types (lightweight 3D polygon representations) ──────────────────

# A "mesh" here is a list of Face dicts:
#   { "vertices": [(x,y,z), ...], "color": str, "outline": str }

Face = dict[str, Any]
Mesh3D = list[Face]


def _render_dimensions(plan: MetricPlan) -> tuple[float, float, float]:
    """Return width/depth/height across retained and canonical Plan layouts.

    Canonical generated Plans store ``(width, depth, height)`` and carry wall
    heights. Retained early blockout fixtures store ``(width, height, depth)``
    without wall-height fields; preserving that interpretation keeps released
    renderer behavior stable while the candidate adapter uses the canonical one.
    """
    first, second, third = (float(value) for value in plan.room_dimensions)
    if any("height" in wall for wall in plan.walls):
        return first, second, third
    return first, third, second


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
        meshes = wall_meshes + opening_meshes + placeholder_meshes
        visibility = _build_visibility_report(
            plan, camera, project, opening_meshes, placeholder_meshes
        )

        # Project all meshes to a PIL Image
        image = self._project_to_image(
            meshes,
            camera,
            project,
            plan,
            visibility,
        )

        # Save output
        output_dir = self._output_base / session_id
        output_dir.mkdir(parents=True, exist_ok=True)
        revision = plan.revisions[-1].revision if plan.revisions else 1
        output_path = output_dir / f"blockout_v{revision}.png"
        image.save(str(output_path), "PNG")
        _write_visibility_report(output_path, visibility)

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
        room_width, room_depth, room_height = _render_dimensions(plan)
        hw, hd = room_width / 2.0, room_depth / 2.0
        h = room_height

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
        room_width, room_depth, _room_height = _render_dimensions(plan)
        hw, hd = room_width / 2.0, room_depth / 2.0

        faces: Mesh3D = []

        for index, opening in enumerate(plan.openings):
            wall = opening.get("wall", "")
            kind = opening.get("kind", opening.get("type", "door"))
            width_m = opening.get("width", 0.9)
            height_m = opening.get("height", 2.1)
            sill = opening.get("sill_height", 0.0)
            offset = opening.get("offset", 0.0)
            position_param = opening.get("position", opening.get("parameter"))

            if position_param is not None:
                # Convert parameter (0..1) to offset from center
                if wall in ("north", "south"):
                    wall_length = room_width
                else:
                    wall_length = room_depth
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
                "element_id": f"opening:{index}",
                "display_label": f"{wall} {kind}",
                "element_color": _entity_color(index),
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

        room_width, room_depth, _room_height = _render_dimensions(plan)
        for index, obj in enumerate(plan.object_placements):
            if "position" in obj:
                pos = obj.get("position", [0.0, 0.0, 0.0])
                cx, cy, cz = float(pos[0]), float(pos[1]), float(pos[2])
            else:
                # Generator placements use a south-west floor origin while
                # blockout geometry uses a room-centered X/Z frame.
                cx = float(obj.get("x", room_width / 2.0)) - room_width / 2.0
                cy = float(obj.get("elevation", 0.0))
                cz = float(obj.get("y", room_depth / 2.0)) - room_depth / 2.0

            if "dimensions" in obj:
                dims = obj.get("dimensions", [0.5, 0.5, 0.5])
                w, h, d = float(dims[0]), float(dims[1]), float(dims[2])
            else:
                w = float(obj.get("width", 0.5))
                h = float(obj.get("height", 0.8))
                d = float(obj.get("depth", 0.5))
            rotation_deg = obj.get("rotation", obj.get("rotation_deg", 0.0))
            name = obj.get("name", obj.get("id", "object"))
            element_id = str(obj.get("id", f"object:{index}"))
            display_label = str(name)
            if display_label == "two chairs":
                chair_number = sum(
                    1
                    for prior in plan.object_placements[: index + 1]
                    if prior.get("name") == "two chairs"
                )
                display_label = f"chair {chair_number}"

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
            box_faces = _make_box_faces(
                base,
                top,
                display_label,
                element_id=element_id,
                element_color=_entity_color(index + len(plan.openings)),
            )
            faces.extend(box_faces)

        return faces

    def _project_to_image(
        self,
        meshes: Mesh3D,
        camera: CameraContract | CameraContractImpl,
        project,
        plan: MetricPlan,
        visibility: dict[str, Any],
    ) -> Image.Image:
        """Project a diagrammatic, same-camera blockout with explicit callouts."""
        width = camera.raster_width
        height = camera.raster_height
        cam_pos = np.array(camera.position, dtype=np.float64)

        canvas = Image.new("RGB", (width, height), "#0f1419")
        draw = ImageDraw.Draw(canvas)
        _draw_gradient(draw, width, height)

        ceiling_edges = [f for f in meshes if f.get("kind") == "ceiling_edge"]
        filled_faces = [f for f in meshes if f.get("kind") != "ceiling_edge"]

        def _face_depth(face: Face) -> float:
            center = np.mean(
                [np.array(v, dtype=np.float64) for v in face["vertices"]], axis=0
            )
            return float(np.linalg.norm(center - cam_pos))

        # Draw the room as a coherent wireframe shell. Opaque near-wall fills
        # caused revision 1 to erase valid Plan-owned instances and openings.
        for face in [f for f in filled_faces if f.get("kind") in {"floor", "wall"}]:
            projected = [project(vertex) for vertex in face["vertices"]]
            if not all(projected):
                continue
            points = [(point[0], point[1]) for point in projected]
            if face.get("kind") == "floor":
                draw.polygon(points, fill=face["color"], outline=face["outline"])
            else:
                draw.line(points + [points[0]], fill=face["outline"], width=3)

        entity_faces = [
            face for face in filled_faces
            if face.get("kind") not in {"floor", "wall"}
        ]
        entity_faces.sort(key=_face_depth, reverse=True)
        for face in entity_faces:
            projected = [project(vertex) for vertex in face["vertices"]]
            if not all(projected):
                continue
            points = [(point[0], point[1]) for point in projected]
            color = face.get("element_color", face["color"])
            kind = face.get("kind", "")
            if kind == "opening":
                fill = "#0f1419"
            elif kind == "object_top":
                fill = color
            else:
                fill = None
            draw.polygon(points, fill=fill, outline=color)
            line_width = 5 if kind == "opening" else 2
            draw.line(points + [points[0]], fill=color, width=line_width)

        for edge in ceiling_edges:
            verts = edge["vertices"]
            if len(verts) >= 2:
                a, b = project(verts[0]), project(verts[1])
                if a and b:
                    draw.line((a[0], a[1], b[0], b[1]), fill=edge["color"], width=2)

        _draw_callouts(draw, visibility)
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

    visibility = _build_visibility_report(
        plan, camera, project, opening_meshes, placeholder_meshes
    )
    image = renderer._project_to_image(
        wall_meshes + opening_meshes + placeholder_meshes,
        camera,
        project,
        plan,
        visibility,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(str(output_path), "PNG")
    _write_visibility_report(output_path, visibility)

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


def blockout_visibility_path(image_path: Path) -> Path:
    """Return the deterministic projection metadata sidecar for a blockout."""
    return image_path.with_name(f"{image_path.stem}_visibility.json")


def load_blockout_visibility(image_path: Path) -> dict[str, Any]:
    """Load and verify a blockout visibility sidecar."""
    path = blockout_visibility_path(image_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    stored = str(report.pop("report_sha256", ""))
    computed = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    if stored != computed:
        raise ValueError("blockout visibility report hash mismatch")
    report["report_sha256"] = stored
    return report


def _write_visibility_report(image_path: Path, report: dict[str, Any]) -> Path:
    path = blockout_visibility_path(image_path)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _rectangles_overlap(a: list[int], b: list[int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _assign_callout_rects(
    elements: dict[str, dict[str, Any]], width: int, height: int
) -> None:
    """Place side-sorted callouts so leader lines stay short and unambiguous."""
    label_width = min(180, max(96, width // 5))
    label_height = 28
    top_limit = 74
    bottom_limit = height - label_height - 38
    sides = {
        "left": [item for item in elements.values() if item["projected_center_px"][0] < width / 2],
        "right": [item for item in elements.values() if item["projected_center_px"][0] >= width / 2],
    }
    for side, values in sides.items():
        values.sort(key=lambda item: (item["projected_center_px"][1], item["element_id"]))
        placed_tops: list[int] = []
        previous_bottom = top_limit - 12
        for item in values:
            desired = int(item["projected_center_px"][1] - label_height / 2)
            top = max(top_limit, desired, previous_bottom + 12)
            placed_tops.append(top)
            previous_bottom = top + label_height
        overflow = max(0, previous_bottom - bottom_limit - label_height)
        if overflow:
            placed_tops = [max(top_limit, top - overflow) for top in placed_tops]
        x1 = 16 if side == "left" else width - label_width - 16
        for item, top in zip(values, placed_tops):
            item["label_bbox_px"] = [x1, top, x1 + label_width, top + label_height]
            item["label_readable"] = width >= 800 and label_width >= 160


def _build_visibility_report(
    plan: MetricPlan,
    camera: CameraContract | CameraContractImpl,
    project,
    opening_meshes: Mesh3D,
    placeholder_meshes: Mesh3D,
) -> dict[str, Any]:
    """Build deterministic geometry/projection evidence for every Plan element."""
    width = int(camera.raster_width)
    height = int(camera.raster_height)
    grouped: dict[str, list[Face]] = {}
    order: list[str] = []
    for face in opening_meshes + placeholder_meshes:
        element_id = str(face.get("element_id", ""))
        if not element_id:
            continue
        if element_id not in grouped:
            grouped[element_id] = []
            order.append(element_id)
        grouped[element_id].append(face)

    elements: dict[str, dict[str, Any]] = {}
    minimum_area = max(25.0, width * height * 0.00008)
    margin = max(4.0, min(width, height) * 0.008)
    for index, element_id in enumerate(order):
        faces = grouped[element_id]
        vertices = sorted({
            tuple(float(component) for component in vertex)
            for face in faces
            for vertex in face["vertices"]
        })
        projected = [project(vertex) for vertex in vertices]
        behind_camera = any(point is None for point in projected)
        valid_points = [point for point in projected if point is not None]
        if valid_points:
            xs = [float(point[0]) for point in valid_points]
            ys = [float(point[1]) for point in valid_points]
            depths = [float(point[2]) for point in valid_points]
            bbox = [min(xs), min(ys), max(xs), max(ys)]
            area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
            center = [(bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0]
            in_frame = (
                bbox[0] >= margin
                and bbox[1] >= margin
                and bbox[2] <= width - margin
                and bbox[3] <= height - margin
            )
            depth_valid = min(depths) > float(camera.near) and max(depths) < float(camera.far)
        else:
            bbox = [0.0, 0.0, 0.0, 0.0]
            area = 0.0
            center = [0.0, 0.0]
            in_frame = False
            depth_valid = False
        label_rect = [0, 0, 0, 0]
        display_label = str(faces[0].get("display_label", element_id))
        elements[element_id] = {
            "element_id": element_id,
            "kind": "opening" if element_id.startswith("opening:") else "instance",
            "label": display_label,
            "color": str(faces[0].get("element_color", _COLORS["label"])),
            "projected_bbox_px": [round(value, 3) for value in bbox],
            "projected_center_px": [round(value, 3) for value in center],
            "projected_area_px": round(area, 3),
            "all_vertices_projected": not behind_camera,
            "behind_camera": behind_camera,
            "depth_valid": depth_valid,
            "in_frame": in_frame,
            "clipped": not in_frame,
            "minimum_area_px": round(minimum_area, 3),
            "label_bbox_px": label_rect,
            "label_readable": False,
            "geometry_visible": (
                not behind_camera and depth_valid and in_frame and area >= minimum_area
            ),
            "geometry_distinct": True,
        }

    _assign_callout_rects(elements, width, height)

    minimum_separation = max(8.0, min(width, height) * 0.015)
    ids = list(elements)
    for index, first_id in enumerate(ids):
        first = elements[first_id]
        for second_id in ids[index + 1:]:
            second = elements[second_id]
            dx = first["projected_center_px"][0] - second["projected_center_px"][0]
            dy = first["projected_center_px"][1] - second["projected_center_px"][1]
            if math.hypot(dx, dy) < minimum_separation:
                first["geometry_distinct"] = False
                second["geometry_distinct"] = False

    labels = [elements[element_id]["label_bbox_px"] for element_id in ids]
    labels_non_overlapping = all(
        not _rectangles_overlap(first, second)
        for index, first in enumerate(labels)
        for second in labels[index + 1:]
    )
    all_required_visible = bool(elements) and all(
        value["geometry_visible"] and value["geometry_distinct"]
        for value in elements.values()
    )
    plan_payload = json.dumps(
        plan.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    report: dict[str, Any] = {
        "schema_version": "blockout-projection-visibility/v1",
        "plan_revision": plan.revisions[-1].revision if plan.revisions else 0,
        "metric_plan_sha256": hashlib.sha256(plan_payload).hexdigest(),
        "camera_sha256": camera.compute_hash() if hasattr(camera, "compute_hash") else camera.camera_hash,
        "raster": [width, height],
        "projection": "perspective",
        "diagrammatic_wireframe_shell": True,
        "opening_rendering": "dark_aperture_with_colored_frame",
        "callout_routing": "side_sorted_short_leaders",
        "required_element_count": len(plan.openings) + len(plan.object_placements),
        "element_count": len(elements),
        "elements": elements,
        "labels_non_overlapping": labels_non_overlapping,
        "all_labels_readable": all(value["label_readable"] for value in elements.values()),
        "all_required_visible": all_required_visible,
        "fully_green": (
            len(elements) == len(plan.openings) + len(plan.object_placements)
            and all_required_visible
            and labels_non_overlapping
            and all(value["label_readable"] for value in elements.values())
        ),
    }
    report["report_sha256"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return report


def _draw_callouts(draw: ImageDraw.ImageDraw, visibility: dict[str, Any]) -> None:
    for element in visibility["elements"].values():
        x1, y1, x2, y2 = element["label_bbox_px"]
        cx, cy = element["projected_center_px"]
        color = element["color"]
        anchor_x = x2 if x1 < visibility["raster"][0] / 2 else x1
        anchor_y = (y1 + y2) / 2
        draw.line((cx, cy, anchor_x, anchor_y), fill=color, width=2)
        draw.rectangle((x1, y1, x2, y2), fill="#111827", outline=color, width=2)
        draw.text((x1 + 6, y1 + 7), element["label"][:24], fill=_COLORS["label"])


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
    *,
    element_id: str = "",
    element_color: str = _COLORS["object_top"],
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
        "display_label": label,
        "element_id": element_id,
        "element_color": element_color,
    })

    # Front face (base[0], base[1], top[1], top[0])
    faces.append({
        "vertices": [base[0], base[1], top[1], top[0]],
        "color": _COLORS["object_front"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
        "display_label": label,
        "element_id": element_id,
        "element_color": element_color,
    })

    # Right face (base[1], base[2], top[2], top[1])
    faces.append({
        "vertices": [base[1], base[2], top[2], top[1]],
        "color": _COLORS["object_side"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
        "display_label": label,
        "element_id": element_id,
        "element_color": element_color,
    })

    # Back face (base[2], base[3], top[3], top[2])
    faces.append({
        "vertices": [base[2], base[3], top[3], top[2]],
        "color": _COLORS["object_front"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
        "display_label": label,
        "element_id": element_id,
        "element_color": element_color,
    })

    # Left face (base[3], base[0], top[0], top[3])
    faces.append({
        "vertices": [base[3], base[0], top[0], top[3]],
        "color": _COLORS["object_side"],
        "outline": _COLORS["object_outline"],
        "kind": "object_face",
        "display_label": label,
        "element_id": element_id,
        "element_color": element_color,
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
    room_width, room_depth, room_height = _render_dimensions(plan)
    revision = plan.revisions[-1].revision if plan.revisions else 1
    obj_count = len(plan.object_placements)
    opening_count = len(plan.openings)

    # Top-left info box
    info_text = (
        f"BLOCKOUT \u00b7 Rev {revision} \u00b7 "
        f"{room_width:.1f}m \u00d7 {room_depth:.1f}m \u00d7 {room_height:.1f}m \u00b7 "
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
