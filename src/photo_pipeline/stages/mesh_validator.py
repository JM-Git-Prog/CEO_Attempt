"""Mesh validation utility for the Photo-to-Real-3D-World V14 pipeline.

Validates that a generated GLB mesh meets minimum quality thresholds
before acceptance into the pipeline.

Requirements: 1.2
"""
from __future__ import annotations

import logging
from pathlib import Path

import trimesh

log = logging.getLogger(__name__)

MIN_FACES: int = 100
MIN_VERTICES: int = 50


def _has_texture(mesh: trimesh.Trimesh) -> bool:
    """Return True when mesh carries at least one valid texture image.

    After GLB load with trimesh, textures appear on the material object
    as SimpleMaterial.image or PBRMaterial.baseColorTexture.
    """
    visual = mesh.visual
    if isinstance(visual, trimesh.visual.TextureVisuals):
        material = getattr(visual, "material", None)
        if material is not None:
            # SimpleMaterial stores texture in .image
            img = getattr(material, "image", None)
            if img is not None:
                return True
            # PBR materials store in baseColorTexture
            base_tex = getattr(material, "baseColorTexture", None)
            if base_tex is not None:
                return True
    return False


def validate_mesh(mesh_path: Path) -> bool:
    """Validate that mesh_path points to a usable textured mesh.

    Checks:
    - File loads without error
    - Contains at least 100 faces
    - Contains at least 50 vertices
    - Has embedded texture data
    """
    if not mesh_path.exists():
        log.warning("Mesh file does not exist: %s", mesh_path)
        return False

    try:
        loaded = trimesh.load(str(mesh_path), process=False)
    except Exception as exc:
        log.warning("Failed to load mesh %s: %s", mesh_path, exc)
        return False

    # Handle scene (multi-geometry GLB) vs single mesh
    if isinstance(loaded, trimesh.Scene):
        meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
        if not meshes:
            log.warning("Scene %s contains no mesh geometry", mesh_path)
            return False
        total_faces = sum(len(m.faces) for m in meshes)
        total_verts = sum(len(m.vertices) for m in meshes)
        has_tex = any(_has_texture(m) for m in meshes)
    elif isinstance(loaded, trimesh.Trimesh):
        total_faces = len(loaded.faces)
        total_verts = len(loaded.vertices)
        has_tex = _has_texture(loaded)
    else:
        log.warning(
            "Loaded object is not a Trimesh or Scene: %s (got %s)",
            mesh_path,
            type(loaded),
        )
        return False

    if total_faces < MIN_FACES:
        log.warning(
            "Mesh %s has only %d faces (need %d)",
            mesh_path,
            total_faces,
            MIN_FACES,
        )
        return False

    if total_verts < MIN_VERTICES:
        log.warning(
            "Mesh %s has only %d vertices (need %d)",
            mesh_path,
            total_verts,
            MIN_VERTICES,
        )
        return False

    if not has_tex:
        log.warning("Mesh %s has no texture", mesh_path)
        return False

    return True
