"""Mesh validation utility for V14 pipeline.

Validates that a GLB mesh meets minimum quality thresholds:
- At least 100 faces (triangles)
- At least 50 vertices
- Embedded texture data (material with texture/image)

Requirements: 1.2
"""

from __future__ import annotations

from pathlib import Path

import trimesh


# Minimum thresholds from V14PipelineConfig defaults
MIN_FACES = 100
MIN_VERTICES = 50


def validate_mesh(mesh_path: Path) -> bool:
    """Validate a GLB mesh meets V14 quality thresholds.

    Checks:
    - At least 100 faces (triangles)
    - At least 50 vertices
    - Embedded texture data (material with a texture image)

    Parameters
    ----------
    mesh_path : Path
        Path to the GLB file to validate.

    Returns
    -------
    bool
        True if ALL checks pass, False otherwise.
    """
    try:
        scene = trimesh.load(str(mesh_path), force="scene", process=False)

        if not isinstance(scene, trimesh.Scene):
            return False

        # Aggregate geometry stats across all meshes in the scene
        total_faces = 0
        total_vertices = 0

        geometries = list(scene.geometry.values())
        if not geometries:
            return False

        for geom in geometries:
            if isinstance(geom, trimesh.Trimesh):
                total_faces += len(geom.faces)
                total_vertices += len(geom.vertices)

        # Check minimum face count
        if total_faces < MIN_FACES:
            return False

        # Check minimum vertex count
        if total_vertices < MIN_VERTICES:
            return False

        # Check for embedded texture data
        if not _has_embedded_texture(scene):
            return False

        return True

    except Exception:
        return False


def _has_embedded_texture(scene: trimesh.Scene) -> bool:
    """Check if the scene has any embedded texture data.

    Looks for materials with texture images in any geometry within the scene.

    Parameters
    ----------
    scene : trimesh.Scene
        The loaded trimesh scene to inspect.

    Returns
    -------
    bool
        True if at least one geometry has a material with embedded texture data.
    """
    for geom in scene.geometry.values():
        if not isinstance(geom, trimesh.Trimesh):
            continue

        visual = geom.visual

        # Check TextureVisuals (most common for GLB with textures)
        if hasattr(visual, "material") and visual.material is not None:
            material = visual.material

            # PBR material with texture images
            if hasattr(material, "baseColorTexture") and material.baseColorTexture is not None:
                return True

            # SimpleMaterial or PBRMaterial with an image attribute
            if hasattr(material, "image") and material.image is not None:
                return True

        # Check if visual kind is 'texture' with a valid image
        if hasattr(visual, "kind") and visual.kind == "texture":
            if hasattr(visual, "material") and visual.material is not None:
                mat = visual.material
                if hasattr(mat, "image") and mat.image is not None:
                    return True
                if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                    return True

    return False
