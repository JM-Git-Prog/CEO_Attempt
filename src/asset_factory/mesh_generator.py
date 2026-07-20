"""
Asset Factory - Generates 3D meshes for scene objects using trimesh.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from src.models import SceneGraph, SceneObject


def generate_all_meshes(scene: SceneGraph, output_dir: Path) -> dict[str, Path]:
    """Generate meshes for all objects in the scene graph."""
    meshes_dir = output_dir / "meshes"
    meshes_dir.mkdir(parents=True, exist_ok=True)

    mesh_paths: dict[str, Path] = {}

    for obj in scene.objects:
        mesh = _generate_object_mesh(obj)
        path = meshes_dir / f"{obj.id}.glb"
        mesh.export(str(path))
        mesh_paths[obj.id] = path

    for door in scene.doors:
        mesh = trimesh.creation.box(extents=[door.width, door.height, 0.04])
        mesh.visual = trimesh.visual.ColorVisuals(
            mesh=mesh, face_colors=np.tile([100, 80, 60, 255], (len(mesh.faces), 1))
        )
        path = meshes_dir / f"{door.id}.glb"
        mesh.export(str(path))
        mesh_paths[door.id] = path

    return mesh_paths


def _generate_object_mesh(obj: SceneObject) -> trimesh.Trimesh:
    """Generate a mesh based on the object's shape and dimensions."""
    shape = obj.primitive_shape or "box"
    dx, dy, dz = obj.dimensions.x, obj.dimensions.y, obj.dimensions.z

    if shape == "cylinder" and "stool" in obj.id:
        mesh = _generate_stool_mesh(min(dx, dz) / 2, dy)
    elif shape == "box":
        mesh = trimesh.creation.box(extents=[dx, dy, dz])
    elif shape == "cylinder":
        mesh = trimesh.creation.cylinder(radius=min(dx, dz) / 2, height=dy)
    elif shape == "sphere":
        mesh = trimesh.creation.icosphere(radius=max(dx, dy, dz) / 2)
    else:
        mesh = trimesh.creation.box(extents=[dx, dy, dz])

    color = _hex_to_rgba(obj.material.base_color)
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh=mesh, face_colors=np.tile(color, (len(mesh.faces), 1))
    )
    return mesh


def _generate_stool_mesh(seat_radius: float, height: float) -> trimesh.Trimesh:
    """Generate a diner stool: base disc + stem + seat cushion."""
    # Base
    base = trimesh.creation.cylinder(radius=seat_radius * 0.8, height=0.03)
    base.apply_translation([0, 0.015, 0])
    base.visual = trimesh.visual.ColorVisuals(
        mesh=base, face_colors=np.tile([180, 180, 180, 255], (len(base.faces), 1))
    )
    # Stem
    stem = trimesh.creation.cylinder(radius=0.025, height=height - 0.1)
    stem.apply_translation([0, (height - 0.1) / 2 + 0.03, 0])
    stem.visual = trimesh.visual.ColorVisuals(
        mesh=stem, face_colors=np.tile([190, 190, 190, 255], (len(stem.faces), 1))
    )
    # Seat
    seat = trimesh.creation.cylinder(radius=seat_radius, height=0.07)
    seat.apply_translation([0, height - 0.035, 0])
    seat.visual = trimesh.visual.ColorVisuals(
        mesh=seat, face_colors=np.tile([192, 57, 43, 255], (len(seat.faces), 1))
    )
    return trimesh.util.concatenate([base, stem, seat])


def _hex_to_rgba(hex_color: str) -> list[int]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return [int(hex_color[i:i+2], 16) for i in (0, 2, 4)] + [255]
    return [128, 128, 128, 255]
