"""Property-based tests for mesh validation correctness.

# Feature: photo-to-real-3d-world-v14

## Property 1: Mesh Validation Correctness

**Validates: Requirements 1.2**

For any trimesh object, the mesh validator SHALL accept it if and only if it
has at least 100 faces, at least 50 vertices, and embedded texture data;
otherwise it SHALL reject it.

Uses Hypothesis with custom strategies to generate trimesh scenes with varying:
- Icosphere subdivisions (0-5) giving different face/vertex counts
- Whether a texture image is attached to the material
- Single vs multiple geometries in a scene

For each generated scene:
- If total_faces >= 100 AND total_vertices >= 50 AND has_texture → validate_mesh returns True
- Otherwise → validate_mesh returns False
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st
from PIL import Image

from src.photo_pipeline.stages.mesh_validator import validate_mesh


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Icosphere subdivisions: 0 gives 20 faces/12 verts, 1 gives 80/42,
# 2 gives 320/162, 3 gives 1280/642, 4 gives 5120/2562, 5 gives 20480/10242
_subdivisions = st.integers(min_value=0, max_value=5)

# Whether to attach a texture to the mesh
_has_texture = st.booleans()

# Number of geometries in the scene (1-3)
_num_geometries = st.integers(min_value=1, max_value=3)


def _create_mesh_with_optional_texture(
    subdivisions: int, attach_texture: bool
) -> trimesh.Trimesh:
    """Create an icosphere mesh, optionally with a texture applied."""
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)

    if attach_texture:
        img = Image.new("RGB", (64, 64), color=(128, 100, 80))
        uv = np.random.rand(len(mesh.vertices), 2).astype(np.float64)
        material = trimesh.visual.material.SimpleMaterial(image=img)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    return mesh


@st.composite
def mesh_scenes(draw: st.DrawFn) -> tuple[trimesh.Scene, int, int, bool]:
    """Generate a trimesh scene with known face/vertex counts and texture state.

    Returns (scene, total_faces, total_vertices, has_texture).
    """
    num_geoms = draw(_num_geometries)
    attach_texture = draw(_has_texture)

    scene = trimesh.Scene()
    total_faces = 0
    total_vertices = 0

    for i in range(num_geoms):
        subdivisions = draw(_subdivisions)
        mesh = _create_mesh_with_optional_texture(subdivisions, attach_texture)
        # Offset each geometry to avoid overlap
        mesh.apply_translation([i * 2.0, 0, 0])
        total_faces += len(mesh.faces)
        total_vertices += len(mesh.vertices)
        scene.add_geometry(mesh, node_name=f"obj_{i}")

    return scene, total_faces, total_vertices, attach_texture


# ---------------------------------------------------------------------------
# Property 1: Mesh Validation Correctness
# ---------------------------------------------------------------------------


class TestMeshValidationCorrectnessProperty:
    """Property 1: Mesh Validation Correctness.

    **Validates: Requirements 1.2**

    For any trimesh object, the mesh validator SHALL accept it if and only if
    it has at least 100 faces, at least 50 vertices, and embedded texture data;
    otherwise it SHALL reject it.
    """

    @given(data=mesh_scenes())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_mesh_validation_correctness(
        self, data: tuple[trimesh.Scene, int, int, bool]
    ) -> None:
        """validate_mesh accepts iff faces>=100, vertices>=50, and has texture."""
        scene, total_faces, total_vertices, has_texture = data

        # Expected outcome based on the property specification
        expected = (
            total_faces >= 100
            and total_vertices >= 50
            and has_texture
        )

        # Export scene to a temporary GLB file
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            scene.export(str(tmp_path))
            result = validate_mesh(tmp_path)

            assert result == expected, (
                f"Mesh validation mismatch:\n"
                f"  faces={total_faces}, vertices={total_vertices}, "
                f"has_texture={has_texture}\n"
                f"  Expected: {expected}, Got: {result}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)
