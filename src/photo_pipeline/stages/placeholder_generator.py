"""Placeholder geometry generation for the V14 fallback path.

When both Hunyuan3D 2.1 and Trellis2 fail for an object, this module produces
a simple colored primitive (sphere, cylinder, or box) based on the object's
bounding box aspect ratio and pixel area.

Requirements: 1.5
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image


def select_placeholder_type(width: int, height: int, area: int) -> str:
    """Select placeholder geometry type based on bounding box and pixel area.

    Decision rules (evaluated in order):
    - area < 1000px → "sphere" (small objects)
    - aspect_ratio (width/height) < 0.5 → "cylinder" (tall narrow)
    - aspect_ratio > 2.0 → "box" (wide)
    - aspect_ratio in [0.8, 1.2] → "box" (roughly square)
    - otherwise → "box" (default)

    Parameters
    ----------
    width : int
        Bounding box width in pixels.
    height : int
        Bounding box height in pixels.
    area : int
        Object mask area in pixels.

    Returns
    -------
    str
        One of "sphere", "cylinder", or "box".
    """
    if area < 1000:
        return "sphere"

    aspect_ratio = width / height
    if aspect_ratio < 0.5:
        return "cylinder"
    if aspect_ratio > 2.0:
        return "box"
    if 0.8 <= aspect_ratio <= 1.2:
        return "box"

    return "box"


def generate_placeholder(
    object_png: Path,
    dimensions_m: tuple[float, float, float],
) -> Path:
    """Generate a colored GLB placeholder primitive.

    Reads the average color from the object PNG (ignoring transparent pixels),
    creates a trimesh primitive scaled to the given dimensions, applies the
    average color as a simple material, and exports as a GLB file.

    Parameters
    ----------
    object_png : Path
        Path to the RGBA object PNG image.
    dimensions_m : tuple[float, float, float]
        Target dimensions (width, height, depth) in meters.

    Returns
    -------
    Path
        Path to the exported GLB file.
    """
    # Read average color from object PNG, ignoring transparent pixels
    avg_color = _compute_average_color(object_png)

    # Determine placeholder type from image dimensions
    img = Image.open(object_png)
    img_width, img_height = img.size

    # Compute area from non-transparent pixels
    if img.mode == "RGBA":
        alpha = np.array(img)[:, :, 3]
        area = int(np.sum(alpha > 0))
    else:
        area = img_width * img_height

    placeholder_type = select_placeholder_type(img_width, img_height, area)

    # Create primitive mesh
    mesh = _create_primitive(placeholder_type, dimensions_m)

    # Apply average color as face color material
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh,
        face_colors=np.tile(avg_color, (len(mesh.faces), 1)),
    )

    # Export as GLB to temp file
    output_path = Path(tempfile.mktemp(suffix=".glb"))
    mesh.export(str(output_path), file_type="glb")

    return output_path


def _compute_average_color(object_png: Path) -> np.ndarray:
    """Compute the average RGB color from non-transparent pixels.

    Parameters
    ----------
    object_png : Path
        Path to the RGBA object PNG.

    Returns
    -------
    np.ndarray
        RGBA color array with shape (4,), values in [0, 255].
    """
    img = Image.open(object_png).convert("RGBA")
    pixels = np.array(img)

    # Mask for non-transparent pixels (alpha > 0)
    alpha_mask = pixels[:, :, 3] > 0

    if not np.any(alpha_mask):
        # All transparent — fallback to mid-gray
        return np.array([128, 128, 128, 255], dtype=np.uint8)

    # Average RGB of visible pixels
    visible_pixels = pixels[alpha_mask][:, :3]
    avg_rgb = np.mean(visible_pixels, axis=0).astype(np.uint8)

    return np.array([avg_rgb[0], avg_rgb[1], avg_rgb[2], 255], dtype=np.uint8)


def _create_primitive(
    primitive_type: str,
    dimensions_m: tuple[float, float, float],
) -> trimesh.Trimesh:
    """Create a trimesh primitive scaled to the given dimensions.

    Parameters
    ----------
    primitive_type : str
        One of "sphere", "cylinder", or "box".
    dimensions_m : tuple[float, float, float]
        Target dimensions (width, height, depth) in meters.

    Returns
    -------
    trimesh.Trimesh
        The created and scaled mesh primitive.
    """
    width, height, depth = dimensions_m

    if primitive_type == "sphere":
        # Sphere with radius = half of the largest dimension
        radius = max(width, height, depth) / 2.0
        mesh = trimesh.creation.icosphere(subdivisions=2, radius=radius)

    elif primitive_type == "cylinder":
        # Cylinder: height along Y, radius from width/depth
        radius = max(width, depth) / 2.0
        mesh = trimesh.creation.cylinder(radius=radius, height=height)

    else:  # "box"
        mesh = trimesh.creation.box(extents=(width, height, depth))

    return mesh
