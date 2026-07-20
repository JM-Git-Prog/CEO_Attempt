"""Render an authoritative plan as SVG and a camera-matched 3D blockout PNG."""

from __future__ import annotations

import html
import math
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

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
        label = html.escape(_floor_label(item))
        full_label = html.escape(item.name)
        label_class = "label tiny" if min(item_w, item_d) < 58 else "label"
        parts.append(
            f'<g transform="translate({x:.1f} {y:.1f}) rotate({-item.rotation_deg:.1f})">'
            f'<title>{full_label}</title>'
            f'<rect x="{-item_w/2:.1f}" y="{-item_d/2:.1f}" width="{item_w:.1f}" height="{item_d:.1f}" rx="4" '
            f'fill="{COLORS[item.category]}" fill-opacity=".72" stroke="#f3f6fa" stroke-opacity=".65"/>'
            f'<text class="{label_class}" text-anchor="middle" dominant-baseline="middle">{label}</text></g>'
        )
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
    parts.extend([
        f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="#ffcb70" stroke-width="3" stroke-dasharray="8 6"/>',
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="11" fill="#ffcb70"/><text x="{cx+16:.1f}" y="{cy-12:.1f}" class="label">CANON CAMERA</text>',
        '<text x="86" y="730" class="note">AMBER furniture · TEAL fixed fixtures · GREEN doors · BLUE windows · dashed line canon view</text>',
        '</svg>',
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts), encoding="utf-8")
    return path


def render_blockout(plan: FloorPlan, path: Path, concept=None) -> Path:
    canvas = Image.new("RGB", (1024, 768), "#111720")
    draw = ImageDraw.Draw(canvas)
    _draw_gradient(draw)
    camera = np.array([plan.camera.x, plan.camera.y, plan.camera.z], dtype=float)
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
    for item in items:
        _draw_item(draw, item, project)
    draw.rectangle((18, 18, 520, 62), fill="#080c12dd", outline="#3d4858")
    draw.text((32, 30), f"APPROVED BLOCKOUT · {plan.name}", fill="#e8edf4")
    draw.text((20, 730), "Geometry and camera are locked; canon generation may change only appearance and lighting.", fill="#9ea9b7")
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, "PNG")
    return path


def _draw_gradient(draw: ImageDraw.ImageDraw) -> None:
    for y in range(768):
        value = int(13 + y * 15 / 768)
        draw.line((0, y, 1024, y), fill=(value, value + 5, value + 12))


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


def _draw_item(draw: ImageDraw.ImageDraw, item: PlanItem, project) -> None:
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
        ([4, 5, 6, 7], "#dba25f"), ([0, 1, 5, 4], "#8b6846"),
        ([1, 2, 6, 5], "#a77b4d"), ([2, 3, 7, 6], "#765b42"),
        ([3, 0, 4, 7], "#947052"),
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
