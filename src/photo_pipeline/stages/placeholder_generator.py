"""Placeholder primitive generator for the Photo-to-Real-3D-World V14 pipeline.

When both Hunyuan3D and Trellis2 fail for an object, this module produces a
colored primitive (box, cylinder, or sphere) as a stand-in.

Requirements: 1.5
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

log = logging.getLogger(__name__)

# Area threshold for sphere selection (in pixels)
SPHERE_AREA_THRESHOLD: int = 1000

# Aspect ratio thresholds
THIN_ASPECT: float = 0.5
TALL_ASPECT: float = 2.0
SQUARE_LOW: float = 0.8
SQUARE_HIGH: float = 1.2


def select_placeholder_type(width: int, height: int, area: int) -> str:
    """Pick a primitive type from image-space statistics of the object mask.

    Parameters
    ----------
    width, height
        Bounding-box dimensions of the object's 2D mask, in pixels.
    area
        Total mask area in pixels.

    Returns
    -------
    One of "sphere", "cylinder", or "box".
    """
    if area < SPHERE_AREA_THRESHOLD:
        return "sphere"

    if height == 0:
        aspect = 1.0
    else:
        aspect = width / height

    if aspect < THIN_ASPECT:
        return "cylinder"

    if aspect > TALL_ASPECT or (SQUARE_LOW <= aspect <= SQUARE_HIGH):
        return "box"

    return "box"


def _average_color(image_path: Path) -> np.ndarray:
    """Return the mean RGB colour of image_path as float array [R, G, B]."""
    with Image.open(str(image_path)) as img:
        rgb = img.convert("RGB")
        arr = np.asarray(rgb, dtype=np.float32)
        if arr.size == 0:
            return np.array([200.0, 200.0, 200.0], dtype=np.float32)
        avg = arr.reshape(-1, 3).mean(axis=0)
        return np.clip(avg, 0, 255)


def generate_placeholder(
    object_png: Path, dimensions_m: tuple[float, float, float]
) -> Path:
    """Generate a colored GLB primitive placeholder.

    Parameters
    ----------
    object_png
        Path to the segmented object RGBA image.
    dimensions_m
        (width, height, depth) in metres.

    Returns
    -------
    Path to the written .glb file.
    """
    with Image.open(str(object_png)) as img:
        width, height = img.size
        # Estimate mask area from alpha channel
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            rgba = img.convert("RGBA")
            alpha = np.asarray(rgba)[..., 3]
            area = int((alpha > 0).sum())
        else:
            area = width * height

    ptype = select_placeholder_type(width, height, area)
    color = _average_color(object_png)

    w, h, d = dimensions_m
    w = max(w, 1e-6)
    h = max(h, 1e-6)
    d = max(d, 1e-6)

    if ptype == "sphere":
        radius = max(w, h, d) / 2.0
        mesh = trimesh.creation.uv_sphere(radius=radius, count=[32, 16])
    elif ptype == "cylinder":
        radius = max(w, d) / 2.0
        mesh = trimesh.creation.cylinder(radius=radius, height=h, sections=48)
    else:
        mesh = trimesh.creation.box(extents=[w, h, d])

    # Apply average color as vertex colors
    rgba = np.append(color, 255.0).astype(np.uint8)
    vertex_colors = np.tile(rgba, (len(mesh.vertices), 1))
    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=vertex_colors)

    output_path = object_png.parent / (object_png.stem + "_placeholder.glb")
    mesh.export(str(output_path), file_type="glb")
    log.info("Generated %s placeholder → %s", ptype, output_path)
    return output_path
