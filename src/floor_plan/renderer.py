"""Render an authoritative plan as SVG and a camera-matched 3D blockout PNG."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.camera_contract import CameraContract, project_world_point
from src.floor_plan.models import FloorPlan, PlanItem

COLORS = {
    "furniture": "#d89552",
    "fixture": "#5fa7a1",
    "architectural": "#8d7cc2",
    "decor": "#6d83a8",
}


def render_floor_plan_svg(plan: FloorPlan, path: Path) -> Path:
    width, height, pad = 1000, 760, 86
    scale = min((width - 2 * pad) / plan.room.width, (height - 2 * pad) / plan.room.depth)
    ox, oy = width / 2, height / 2

    def point(x: float, z: float) -> tuple[float, float]:
        return ox + x * scale, oy - z * scale

    rw, rd = plan.room.width * scale, plan.room.depth * scale
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0b1017"/>',
        '<style>text{font-family:Segoe UI,Arial;fill:#dce5ef}.label{font-size:13px}.dim{font-size:15px;fill:#8e9aaa}.note{font-size:12px;fill:#697586}</style>',
        f'<rect x="{ox-rw/2:.1f}" y="{oy-rd/2:.1f}" width="{rw:.1f}" height="{rd:.1f}" fill="#111a24" stroke="#e7edf5" stroke-width="7"/>',
        f'<text x="{pad}" y="34" class="dim">{html.escape(plan.name)} · {plan.room.width:.1f}m × {plan.room.depth:.1f}m × {plan.room.height:.1f}m</text>',
        f'<text x="{ox:.1f}" y="{oy-rd/2-22:.1f}" text-anchor="middle" class="dim">NORTH · {plan.room.width:.1f}m</text>',
        f'<text x="{ox-rw/2-28:.1f}" y="{oy:.1f}" transform="rotate(-90 {ox-rw/2-28:.1f} {oy:.1f})" text-anchor="middle" class="dim">{plan.room.depth:.1f}m</text>',
    ]
    for item in plan.items:
        x, y = point(item.x, item.z)
        item_w, item_d = item.width * scale, item.depth * scale
        full_label = html.escape(item.name)
        dim_label = f"{item.width:.1f}×{item.depth:.1f}m"
        mount_badge = ""
        if item.mount == "ceiling":
            mount_badge = " ▼CEIL"
        elif item.mount == "wall":
            mount_badge = " ◧WALL"
        # Use full name + dimensions for clarity
        primary = html.escape(item.name[:20])
        secondary = f"{dim_label}{mount_badge}"
        is_small = min(item_w, item_d) < 50
        label_class = "label" if not is_small else "label"
        # Item rectangle with ID annotation
        parts.append(
            f'<g transform="translate({x:.1f} {y:.1f}) rotate({-item.rotation_deg:.1f})">'
            f'<title>{full_label} ({dim_label}, {item.category}, {item.mount})</title>'
            f'<rect x="{-item_w/2:.1f}" y="{-item_d/2:.1f}" width="{item_w:.1f}" height="{item_d:.1f}" rx="4" '
            f'fill="{COLORS[item.category]}" fill-opacity=".72" stroke="#f3f6fa" stroke-opacity=".65"/>'
        )
        if not is_small:
            parts.append(f'<text class="label" text-anchor="middle" dominant-baseline="middle" y="-6">{primary}</text>')
            parts.append(f'<text class="note" text-anchor="middle" dominant-baseline="middle" y="10">{html.escape(secondary)}</text>')
        else:
            parts.append(f'<text class="label" text-anchor="middle" dominant-baseline="middle" style="font-size:10px">{html.escape(item.id)}</text>')
        parts.append('</g>')
    for opening in plan.openings:
        color = "#66d6a6" if opening.kind == "door" else "#69b9ff"
        half = opening.width * scale / 2
        if opening.wall in {"north", "south"}:
            _, y = point(0, plan.room.depth / 2 if opening.wall == "north" else -plan.room.depth / 2)
            x, _ = point(opening.offset, 0)
            parts.append(f'<line x1="{x-half:.1f}" y1="{y:.1f}" x2="{x+half:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="10"/>')
        else:
            x, _ = point(plan.room.width / 2 if opening.wall == "east" else -plan.room.width / 2, 0)
            _, y = point(0, opening.offset)
            parts.append(f'<line x1="{x:.1f}" y1="{y-half:.1f}" x2="{x:.1f}" y2="{y+half:.1f}" stroke="{color}" stroke-width="10"/>')
    cx, cy = point(plan.camera.x, plan.camera.z)
    tx, ty = point(plan.camera.target_x, plan.camera.target_z)
    # Legend with colored swatches instead of unicode symbols
    item_count = len(plan.items)
    ceiling_count = sum(1 for i in plan.items if i.mount == "ceiling")
    floor_count = sum(1 for i in plan.items if i.mount == "floor")
    opening_count = len(plan.openings)
    legend_y = height - 70
    parts.extend([
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="#ffcb70" stroke-width="3" stroke-dasharray="8 6"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="#ffcb70"/><text x="{cx+16:.1f}" y="{cy-12:.1f}" class="label">CAM {plan.camera.fov_deg:.0f}deg</text>',
        # Legend row 1: item categories
        f'<rect x="86" y="{legend_y}" width="12" height="12" fill="{COLORS["furniture"]}" rx="2"/>',
        f'<text x="102" y="{legend_y+10}" class="note">furniture</text>',
        f'<rect x="170" y="{legend_y}" width="12" height="12" fill="{COLORS["fixture"]}" rx="2"/>',
        f'<text x="186" y="{legend_y+10}" class="note">fixture</text>',
        f'<rect x="240" y="{legend_y}" width="12" height="12" fill="{COLORS["architectural"]}" rx="2"/>',
        f'<text x="256" y="{legend_y+10}" class="note">architectural</text>',
        f'<rect x="340" y="{legend_y}" width="12" height="12" fill="{COLORS["decor"]}" rx="2"/>',
        f'<text x="356" y="{legend_y+10}" class="note">decor</text>',
        f'<rect x="410" y="{legend_y}" width="20" height="12" fill="#66d6a6" rx="2"/>',
        f'<text x="434" y="{legend_y+10}" class="note">door</text>',
        f'<rect x="475" y="{legend_y}" width="20" height="12" fill="#69b9ff" rx="2"/>',
        f'<text x="499" y="{legend_y+10}" class="note">window</text>',
        f'<circle cx="560" cy="{legend_y+6}" r="6" fill="#ffcb70"/>',
        f'<text x="570" y="{legend_y+10}" class="note">camera</text>',
        # Legend row 2: counts
        f'<text x="86" y="{legend_y+28}" class="note">{item_count} items ({floor_count} floor, {ceiling_count} ceiling) | {opening_count} openings | Room {plan.room.width:.1f} x {plan.room.depth:.1f} x {plan.room.height:.1f}m</text>',
        '</svg>',
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path


def render_blockout(
    plan: FloorPlan,
    path: Path,
    concept=None,
    *,
    camera_contract: CameraContract | None = None,
    blockout_detail: str = "primitive",
) -> Path:
    width = camera_contract.image_width if camera_contract else 1024
    height = camera_contract.image_height if camera_contract else 768
    canvas = Image.new("RGB", (width, height), "#111720")
    draw = ImageDraw.Draw(canvas)
    _draw_gradient(draw, width, height)
    camera = np.array([plan.camera.x, plan.camera.y, plan.camera.z], dtype=float)

    if camera_contract:
        def project(vertex: tuple[float, float, float]) -> tuple[float, float, float] | None:
            x, y, depth, _ = project_world_point(camera_contract, vertex)
            return None if depth < camera_contract.near else (x, y, depth)
    else:
        target = np.array([plan.camera.target_x, plan.camera.target_y, plan.camera.target_z], dtype=float)
        forward = target - camera
        forward /= max(np.linalg.norm(forward), 1e-6)
        right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
        right /= max(np.linalg.norm(right), 1e-6)
        up = np.cross(right, forward)
        focal = 512 / math.tan(math.radians(plan.camera.fov_deg) / 2)

        def project(vertex: tuple[float, float, float]) -> tuple[float, float, float] | None:
            relative = np.array(vertex) - camera
            depth = float(np.dot(relative, forward))
            if depth <= 0.08:
                return None
            return 512 + float(np.dot(relative, right)) * focal / depth, 384 - float(np.dot(relative, up)) * focal / depth, depth

    _draw_room(draw, plan, project, concept)
    items = sorted(plan.items, key=lambda item: -_distance(item, camera))
    draw_fn = _draw_item_articulated if blockout_detail == "articulated" else _draw_item
    for item in items:
        draw_fn(draw, item, project, concept)
    draw.rectangle((18, 18, min(520, width - 18), 62), fill="#080c12dd", outline="#3d4858")
    draw.text((32, 30), f"APPROVED BLOCKOUT · {plan.name}", fill="#e8edf4")
    # Burn object count summary into the blockout so FLUX can read it
    from collections import Counter
    import re as _re
    base_names = Counter(
        _re.sub(r'\s*\d+$', '', item.name).strip() for item in plan.items
    )
    count_text = " | ".join(f"{count}x {name}" for name, count in base_names.items())
    draw.rectangle((18, height - 60, min(width - 18, 18 + len(count_text) * 7 + 20), height - 18), fill="#080c12dd", outline="#3d4858")
    draw.text((28, height - 52), f"EXACT CONTENTS: {count_text}", fill="#e8edf4")
    draw.text((28, height - 34), "NO EXTRA OBJECTS. Match counts precisely.", fill="#ffcb70")
    lock_label = "Geometry and camera are locked; canon generation may change only appearance and lighting."
    if camera_contract:
        lock_label = f"CAMERA LOCK {camera_contract.contract_id} · Blockout, Canon, and World share this frame."
    draw.text((20, height - 80), lock_label, fill="#9ea9b7")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "PNG")
    return path


def _draw_gradient(draw: ImageDraw.ImageDraw, width: int = 1024, height: int = 768) -> None:
    for y in range(height):
        value = int(13 + y * 15 / height)
        draw.line((0, y, width, y), fill=(value, value + 5, value + 12))


def _draw_room(draw: ImageDraw.ImageDraw, plan: FloorPlan, project, concept=None) -> None:
    w, d, h = plan.room.width / 2, plan.room.depth / 2, plan.room.height
    floor = [project((-w, 0, -d)), project((w, 0, -d)), project((w, 0, d)), project((-w, 0, d))]
    concept_text = " " if concept is None else f"{concept.architecture_notes} {concept.image_prompt}".lower()
    if "checkerboard" in concept_text:
        tile = 0.5
        x_steps, z_steps = math.ceil(plan.room.width / tile), math.ceil(plan.room.depth / tile)
        for x_index in range(x_steps):
            for z_index in range(z_steps):
                x0, x1 = -w + x_index * tile, min(w, -w + (x_index + 1) * tile)
                z0, z1 = -d + z_index * tile, min(d, -d + (z_index + 1) * tile)
                corners = [project((x0, 0, z0)), project((x1, 0, z0)), project((x1, 0, z1)), project((x0, 0, z1))]
                if all(corners):
                    color = "#ded8c8" if (x_index + z_index) % 2 else "#1b1d20"
                    draw.polygon([(point[0], point[1]) for point in corners], fill=color, outline="#555b62")
    elif all(floor):
        draw.polygon([(p[0], p[1]) for p in floor], fill="#343b43", outline="#8d98a6")
    if all(floor):
        draw.line([(point[0], point[1]) for point in floor] + [(floor[0][0], floor[0][1])], fill="#8d98a6", width=3)
    edges = [
        ((-w, 0, -d), (-w, h, -d)), ((w, 0, -d), (w, h, -d)),
        ((-w, 0, d), (-w, h, d)), ((w, 0, d), (w, h, d)),
        ((-w, h, -d), (w, h, -d)), ((w, h, -d), (w, h, d)),
        ((w, h, d), (-w, h, d)), ((-w, h, d), (-w, h, -d)),
    ]
    for start, end in edges:
        a, b = project(start), project(end)
        if a and b:
            draw.line((a[0], a[1], b[0], b[1]), fill="#778493", width=3)
    for opening in plan.openings:
        low, high = opening.sill_height, opening.sill_height + opening.height
        half = opening.width / 2
        if opening.wall == "north":
            vertices = [(opening.offset-half, low, d), (opening.offset+half, low, d), (opening.offset+half, high, d), (opening.offset-half, high, d)]
        elif opening.wall == "south":
            vertices = [(opening.offset+half, low, -d), (opening.offset-half, low, -d), (opening.offset-half, high, -d), (opening.offset+half, high, -d)]
        elif opening.wall == "east":
            vertices = [(w, low, opening.offset-half), (w, low, opening.offset+half), (w, high, opening.offset+half), (w, high, opening.offset-half)]
        else:
            vertices = [(-w, low, opening.offset+half), (-w, low, opening.offset-half), (-w, high, opening.offset-half), (-w, high, opening.offset+half)]
        projected = [project(vertex) for vertex in vertices]
        if all(projected):
            points = [(point[0], point[1]) for point in projected]
            fill = "#183a4d" if opening.kind == "window" else "#244236"
            outline = "#69b9ff" if opening.kind == "window" else "#66d6a6"
            draw.polygon(points, fill=fill, outline=outline)
            draw.line(points + [points[0]], fill=outline, width=5)
            label = "WINDOW" if opening.kind == "window" else "DOOR"
            anchor_x = sum(point[0] for point in points) / 4
            anchor_y = sum(point[1] for point in points) / 4
            draw.text((anchor_x - 24, anchor_y - 7), label, fill="#eef7ff")


def _distance(item: PlanItem, camera: np.ndarray) -> float:
    return float(np.linalg.norm(np.array([item.x, item.elevation + item.height / 2, item.z]) - camera))


def _draw_item(draw: ImageDraw.ImageDraw, item: PlanItem, project, concept=None) -> None:
    angle = math.radians(item.rotation_deg)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    local = [(-item.width/2, -item.depth/2), (item.width/2, -item.depth/2), (item.width/2, item.depth/2), (-item.width/2, item.depth/2)]
    base = [(item.x + x*cos_a - z*sin_a, item.elevation, item.z + x*sin_a + z*cos_a) for x, z in local]
    top = [(x, item.elevation + item.height, z) for x, _, z in base]
    vertices = base + top
    projected = [project(vertex) for vertex in vertices]
    if not all(projected):
        return
    faces = [
        ([4, 5, 6, 7], "#b0b0b0"), ([0, 1, 5, 4], "#787878"),
        ([1, 2, 6, 5], "#8a8a8a"), ([2, 3, 7, 6], "#686868"),
        ([3, 0, 4, 7], "#808080"),
    ]
    ranked = []
    for indices, color in faces:
        depth = sum(projected[index][2] for index in indices) / len(indices)
        ranked.append((depth, indices, color))
    for _, indices, color in sorted(ranked, reverse=True):
        points = [(projected[index][0], projected[index][1]) for index in indices]
        draw.polygon(points, fill=color, outline="#f0d1a4")
    anchor = projected[4]
    draw.text((anchor[0] + 4, anchor[1] - 14), item.name[:24], fill="#f2f4f7")


def _floor_label(item: PlanItem) -> str:
    text = f"{item.id} {item.name}".lower()
    suffix = re.search(r"(\d+)$", item.id)
    number = suffix.group(1) if suffix else ""
    if "stool" in text:
        return f"S{number}" if number else "STOOL"
    if "pendant" in text or "light" in text:
        return f"P{number}" if number else "LIGHT"
    if "counter" in text:
        return f"COUNTER · {item.width:.1f}m"
    label = item.name.upper()
    return label if len(label) <= 18 else f"{label[:17]}…"


# ---------------------------------------------------------------------------
# Articulated blockout: sub-part decomposition for denser geometry signal
# ---------------------------------------------------------------------------

# Neutral grayscale palette for blockout — communicates shape without imposing color.
# FLUX should interpret geometry from the blockout and materials from the text prompt.
# Different luminance values distinguish parts without color bias.
_PALETTE = {
    "chrome": "#b8b8b8",
    "chrome_highlight": "#d8d8d8",
    "mint_green": "#909090",
    "red_vinyl": "#686868",
    "formica_top": "#c8c8c8",
    "counter_body": "#585858",
    "stool_base": "#707070",
    "stool_stem": "#989898",
    "pendant_canopy": "#a0a0a0",
    "pendant_shade": "#c0c0c0",
    "pendant_glow": "#e8e8e8",
    "door_frame": "#484848",
    "door_panel": "#606060",
    "generic_furniture": "#787878",
    "generic_fixture": "#8a8a8a",
    "generic_top": "#b0b0b0",
    "generic_side": "#686868",
}


def _box_vertices(
    cx: float, cy: float, cz: float,
    w: float, h: float, d: float,
    angle_rad: float = 0.0,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Return (base_corners, top_corners) for an axis-aligned box rotated around Y."""
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    local = [(-w/2, -d/2), (w/2, -d/2), (w/2, d/2), (-w/2, d/2)]
    base = [(cx + x*cos_a - z*sin_a, cy, cz + x*sin_a + z*cos_a) for x, z in local]
    top = [(bx, cy + h, bz) for bx, _, bz in base]
    return base, top


def _draw_box(
    draw: ImageDraw.ImageDraw,
    project,
    base: list[tuple[float, float, float]],
    top: list[tuple[float, float, float]],
    top_color: str,
    front_color: str,
    side_color: str,
    outline_color: str = "#f0d1a4",
) -> None:
    """Draw a projected box with distinct colors per face orientation."""
    vertices = base + top  # 0-3 base, 4-7 top
    projected = [project(v) for v in vertices]
    if not all(projected):
        return
    faces = [
        ([4, 5, 6, 7], top_color),    # top face
        ([0, 1, 5, 4], front_color),   # front
        ([1, 2, 6, 5], side_color),    # right side
        ([2, 3, 7, 6], front_color),   # back (same as front for symmetry)
        ([3, 0, 4, 7], side_color),    # left side
    ]
    ranked = []
    for indices, color in faces:
        depth = sum(projected[i][2] for i in indices) / len(indices)
        ranked.append((depth, indices, color))
    for _, indices, color in sorted(ranked, reverse=True):
        points = [(projected[i][0], projected[i][1]) for i in indices]
        draw.polygon(points, fill=color, outline=outline_color)


def _draw_cylinder_top(
    draw: ImageDraw.ImageDraw,
    project,
    cx: float, cy: float, cz: float,
    radius: float, height: float,
    body_color: str, top_color: str,
    segments: int = 12,
) -> None:
    """Approximate a cylinder with a polygon body and distinct top disc."""
    angles = [2 * math.pi * i / segments for i in range(segments)]
    base_ring = [(cx + radius * math.cos(a), cy, cz + radius * math.sin(a)) for a in angles]
    top_ring = [(cx + radius * math.cos(a), cy + height, cz + radius * math.sin(a)) for a in angles]
    base_proj = [project(v) for v in base_ring]
    top_proj = [project(v) for v in top_ring]
    if not all(base_proj) or not all(top_proj):
        return
    # Draw body quads (back to front)
    quads = []
    for i in range(segments):
        j = (i + 1) % segments
        quad_proj = [base_proj[i], base_proj[j], top_proj[j], top_proj[i]]
        depth = sum(p[2] for p in quad_proj) / 4
        quads.append((depth, quad_proj, body_color))
    # Top disc
    top_depth = sum(p[2] for p in top_proj) / len(top_proj)
    quads.append((top_depth - 0.001, top_proj, top_color))  # slight bias to draw on top
    for _, pts, color in sorted(quads, reverse=True):
        points = [(p[0], p[1]) for p in pts]
        draw.polygon(points, fill=color, outline="#d0c8bc")


def _decompose_counter(item: PlanItem) -> list[dict]:
    """Decompose a counter into top slab, chrome trim, front panel, and body."""
    angle = math.radians(item.rotation_deg)
    trim_h = 0.03
    top_h = 0.05
    body_h = item.height - top_h - trim_h
    return [
        # Main body (dark base)
        {"cx": item.x, "cy": item.elevation, "cz": item.z,
         "w": item.width, "h": body_h, "d": item.depth,
         "angle": angle, "top": _PALETTE["counter_body"], "front": _PALETTE["mint_green"], "side": _PALETTE["counter_body"]},
        # Chrome trim strip at top of body
        {"cx": item.x, "cy": item.elevation + body_h, "cz": item.z,
         "w": item.width + 0.02, "h": trim_h, "d": item.depth + 0.02,
         "angle": angle, "top": _PALETTE["chrome_highlight"], "front": _PALETTE["chrome"], "side": _PALETTE["chrome"]},
        # Formica counter top slab
        {"cx": item.x, "cy": item.elevation + body_h + trim_h, "cz": item.z,
         "w": item.width, "h": top_h, "d": item.depth,
         "angle": angle, "top": _PALETTE["formica_top"], "front": _PALETTE["formica_top"], "side": _PALETTE["chrome"]},
    ]


def _decompose_stool(item: PlanItem) -> list[dict]:
    """Decompose a stool into base disc, chrome stem, and red cushion."""
    return [
        {"type": "cylinder", "cx": item.x, "cy": item.elevation, "cz": item.z,
         "radius": min(item.width, item.depth) / 2 * 0.75, "height": 0.04,
         "body": _PALETTE["stool_base"], "top": _PALETTE["chrome"]},
        {"type": "cylinder", "cx": item.x, "cy": item.elevation + 0.04, "cz": item.z,
         "radius": 0.025, "height": item.height - 0.14,
         "body": _PALETTE["stool_stem"], "top": _PALETTE["chrome_highlight"]},
        {"type": "cylinder", "cx": item.x, "cy": item.elevation + item.height - 0.10, "cz": item.z,
         "radius": min(item.width, item.depth) / 2, "height": 0.10,
         "body": _PALETTE["red_vinyl"], "top": _PALETTE["red_vinyl"]},
    ]


def _decompose_pendant(item: PlanItem) -> list[dict]:
    """Decompose a pendant light into canopy disc, cable, shade cone, and glow."""
    shade_h = item.height * 0.5
    cable_h = item.height * 0.35
    canopy_h = item.height * 0.08
    glow_h = item.height * 0.07
    base_y = item.elevation
    return [
        # Canopy (ceiling mount)
        {"type": "cylinder", "cx": item.x, "cy": base_y + cable_h + shade_h + glow_h, "cz": item.z,
         "radius": item.width / 2 * 0.4, "height": canopy_h,
         "body": _PALETTE["pendant_canopy"], "top": _PALETTE["chrome"]},
        # Cable/stem
        {"type": "cylinder", "cx": item.x, "cy": base_y + shade_h + glow_h, "cz": item.z,
         "radius": 0.012, "height": cable_h,
         "body": _PALETTE["chrome"], "top": _PALETTE["chrome"]},
        # Shade (widest part)
        {"type": "cylinder", "cx": item.x, "cy": base_y + glow_h, "cz": item.z,
         "radius": item.width / 2, "height": shade_h,
         "body": _PALETTE["pendant_shade"], "top": _PALETTE["chrome_highlight"]},
        # Glow aperture (warm emissive at bottom)
        {"type": "cylinder", "cx": item.x, "cy": base_y, "cz": item.z,
         "radius": item.width / 2 * 0.7, "height": glow_h,
         "body": _PALETTE["pendant_glow"], "top": _PALETTE["pendant_glow"]},
    ]


def _draw_item_articulated(draw: ImageDraw.ImageDraw, item: PlanItem, project, concept=None) -> None:
    """Draw an item decomposed into palette-mapped sub-parts for richer geometry signal."""
    text = f"{item.id} {item.name}".lower()

    if "counter" in text:
        for part in _decompose_counter(item):
            base, top = _box_vertices(part["cx"], part["cy"], part["cz"],
                                      part["w"], part["h"], part["d"], part["angle"])
            _draw_box(draw, project, base, top, part["top"], part["front"], part["side"])
    elif "stool" in text:
        for part in _decompose_stool(item):
            _draw_cylinder_top(draw, project, part["cx"], part["cy"], part["cz"],
                               part["radius"], part["height"], part["body"], part["top"])
    elif "pendant" in text or "light" in text:
        for part in _decompose_pendant(item):
            _draw_cylinder_top(draw, project, part["cx"], part["cy"], part["cz"],
                               part["radius"], part["height"], part["body"], part["top"])
    else:
        # Generic furniture: use original primitive renderer as fallback
        _draw_item(draw, item, project, concept)


def _floor_label(item: PlanItem) -> str:
    text = f"{item.id} {item.name}".lower()
    suffix = re.search(r"(\d+)$", item.id)
    number = suffix.group(1) if suffix else ""
    if "stool" in text:
        return f"S{number}" if number else "STOOL"
    if "pendant" in text or "light" in text:
        return f"P{number}" if number else "LIGHT"
    if "counter" in text:
        return f"COUNTER · {item.width:.1f}m"
    label = item.name.upper()
    return label if len(label) <= 18 else f"{label[:17]}…"
