"""Render deterministic neutral four-view geometry previews from generated GLBs.

This software projection is diagnostic evidence only. It does not apply or
claim durable materials and performs no approval or lane selection.
"""
from pathlib import Path
import math
import numpy as np
import trimesh
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
OBJECTS = OUT / "objects"
SIZE = 512
ANGLES = (("front", 0), ("right", 90), ("rear", 180), ("left", 270))


def render(vertices: np.ndarray, degrees: float) -> Image.Image:
    angle = math.radians(degrees)
    rotation = np.array([
        [math.cos(angle), 0.0, math.sin(angle)],
        [0.0, 1.0, 0.0],
        [-math.sin(angle), 0.0, math.cos(angle)],
    ])
    points = vertices @ rotation.T
    xy = points[:, :2]
    depth = points[:, 2]
    span = np.maximum(np.ptp(xy, axis=0), 1e-9)
    scale = 0.82 * SIZE / max(span)
    pixels = np.rint((xy - (xy.min(axis=0) + xy.max(axis=0)) / 2) * scale + SIZE / 2).astype(int)
    pixels[:, 1] = SIZE - 1 - pixels[:, 1]
    valid = np.all((pixels >= 2) & (pixels < SIZE - 2), axis=1)
    pixels = pixels[valid]
    depth = depth[valid]
    order = np.argsort(depth)
    pixels = pixels[order]
    depth = depth[order]
    dmin, dmax = float(depth.min()), float(depth.max())
    shade = (95 + 145 * (depth - dmin) / max(dmax - dmin, 1e-9)).astype(np.uint8)
    image = np.full((SIZE, SIZE, 3), 224, dtype=np.uint8)
    for (x, y), value in zip(pixels, shade):
        image[y - 1:y + 2, x - 1:x + 2] = (value, value, value)
    return Image.fromarray(image)


for mesh_path in sorted(OBJECTS.glob("*.glb")):
    scene = trimesh.load(mesh_path, force="scene", process=False)
    vertices = np.vstack([geometry.vertices for geometry in scene.geometry.values()])
    vertices = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    if len(vertices) > 80000:
        indices = np.linspace(0, len(vertices) - 1, 80000, dtype=int)
        vertices = vertices[indices]
    sheet = Image.new("RGB", (SIZE * 2, SIZE * 2 + 56), (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 18), f"{mesh_path.name} — geometry only; no durable material", fill=(255, 255, 255))
    for index, (label, degrees) in enumerate(ANGLES):
        panel = render(vertices, degrees)
        x = (index % 2) * SIZE
        y = (index // 2) * SIZE + 56
        sheet.paste(panel, (x, y))
        ImageDraw.Draw(sheet).text((x + 12, y + 12), label, fill=(20, 20, 20))
    sheet.save(OUT / f"{mesh_path.stem}-four-view.png", optimize=True)
