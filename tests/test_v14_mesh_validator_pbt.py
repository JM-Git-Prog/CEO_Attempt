"""Property-based tests for mesh validation correctness.

# Feature: photo-to-real-3d-world-v14

## Property 1: Mesh Validation Correctness

**Validates: Requirements 1.2**

For any trimesh object, the mesh validator SHALL accept it if and only if it
has at least 100 faces, at least 50 vertices, and embedded texture data;
otherwise it SHALL reject it.

Uses Hypothesis with custom strategies to generate synthetic trimesh objects
with varying face/vertex counts and texture attachment. Tests the threshold
boundaries (99 faces should fail, 100 should pass if other criteria met).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import trimesh
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from PIL import Image

from src.photo_pipeline.stages.mesh_validator import validate_mesh


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Face count ranges that span the boundary (100 faces threshold)
# Icosphere subdivisions: 0→20 faces, 1→80 faces, 2→320 faces, 3→1280 faces
_subdivisions = st.integers(min_value=0, max_value=4)

# Whether to attach a texture image to the mesh material
_has_texture = st.booleans()

# Number of geometries in the GLB scene (1-3)
_num_geometries = st.integers(min_value=1, max_value=3)


def _make_icosphere_with_texture(
    subdivisions: int, attach_texture: bool
) -> trimesh.Trimesh:
    """Create an icosphere mesh, optionally with embedded texture data."""
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)

    if attach_texture:
        # Create a small texture image and assign UV coords
        img = Image.new("RGB", (64, 64), color=(100, 150, 200))
        uv = np.random.rand(len(mesh.vertices), 2).astype(np.float64)
        material = trimesh.visual.material.SimpleMaterial(image=img)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    return mesh


@st.composite
def mesh_params(draw: st.DrawFn) -> tuple[trimesh.Scene, int, int, bool]:
    """Generate a trimesh Scene with known face/vertex counts and texture state.

    Returns (scene, total_faces, total_vertices, has_texture_on_all).
    """
    num_geoms = draw(_num_geometries)
    attach_texture = draw(_has_texture)

    scene = trimesh.Scene()
    total_faces = 0
    total_vertices = 0

    for i in range(num_geoms):
        subdivisions = draw(_subdivisions)
        mesh = _make_icosphere_with_texture(subdivisions, attach_texture)
        # Offset geometries to avoid spatial overlap
        mesh.apply_translation([i * 3.0, 0, 0])
        total_faces += len(mesh.faces)
        total_vertices += len(mesh.vertices)
        scene.add_geometry(mesh, node_name=f"geom_{i}")

    return scene, total_faces, total_vertices, attach_texture


# ---------------------------------------------------------------------------
# Property 1: Mesh Validation Correctness
# ---------------------------------------------------------------------------


class TestMeshValidatorProperty:
    """Property 1: Mesh Validation Correctness.

    **Validates: Requirements 1.2**

    For any trimesh object, the mesh validator SHALL accept it if and only if
    it has at least 100 faces, at least 50 vertices, and embedded texture data;
    otherwise it SHALL reject it.
    """

    @given(data=mesh_params())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_mesh_validation_correctness_property(
        self, data: tuple[trimesh.Scene, int, int, bool]
    ) -> None:
        """validate_mesh returns True iff faces>=100, verts>=50, has texture."""
        scene, total_faces, total_vertices, has_texture = data

        # Expected result per Property 1 specification
        expected = (
            total_faces >= 100
            and total_vertices >= 50
            and has_texture
        )

        # Export scene to temporary GLB and run validator
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            scene.export(str(tmp_path))
            result = validate_mesh(tmp_path)

            assert result == expected, (
                f"Mesh validation mismatch:\n"
                f"  total_faces={total_faces}, total_vertices={total_vertices}, "
                f"has_texture={has_texture}\n"
                f"  Expected validate_mesh={expected}, Got={result}"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(
        attach_texture=st.just(True),
        subdivisions=st.just(1),  # 80 faces, 42 vertices → below both thresholds
    )
    @settings(max_examples=5, deadline=None)
    def test_below_face_threshold_rejects(
        self, attach_texture: bool, subdivisions: int
    ) -> None:
        """A mesh with 80 faces (below 100) and 42 verts (below 50) is rejected."""
        mesh = _make_icosphere_with_texture(subdivisions, attach_texture)
        assert len(mesh.faces) == 80  # icosphere subdiv=1 has exactly 80 faces
        assert len(mesh.vertices) == 42  # icosphere subdiv=1 has exactly 42 vertices
        # Both are below thresholds (100 faces, 50 vertices) → must reject

        scene = trimesh.Scene()
        scene.add_geometry(mesh)

        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            scene.export(str(tmp_path))
            result = validate_mesh(tmp_path)
            assert result is False, (
                f"Expected rejection for mesh with {len(mesh.faces)} faces "
                f"and {len(mesh.vertices)} vertices (both below thresholds)"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(
        attach_texture=st.just(True),
        subdivisions=st.just(2),  # 320 faces, 162 vertices → above both thresholds
    )
    @settings(max_examples=5, deadline=None)
    def test_above_thresholds_with_texture_accepts(
        self, attach_texture: bool, subdivisions: int
    ) -> None:
        """A mesh with 320 faces, 162 vertices, and texture should be accepted."""
        mesh = _make_icosphere_with_texture(subdivisions, attach_texture)
        assert len(mesh.faces) >= 100
        assert len(mesh.vertices) >= 50

        scene = trimesh.Scene()
        scene.add_geometry(mesh)

        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            scene.export(str(tmp_path))
            result = validate_mesh(tmp_path)
            assert result is True, (
                f"Expected acceptance for textured mesh with "
                f"{len(mesh.faces)} faces and {len(mesh.vertices)} vertices"
            )
        finally:
            tmp_path.unlink(missing_ok=True)

    @given(
        attach_texture=st.just(False),
        subdivisions=st.just(3),  # 1280 faces, 642 vertices but no texture
    )
    @settings(max_examples=5, deadline=None)
    def test_no_texture_rejects_even_with_high_counts(
        self, attach_texture: bool, subdivisions: int
    ) -> None:
        """A mesh with sufficient faces/vertices but no texture should be rejected."""
        mesh = _make_icosphere_with_texture(subdivisions, attach_texture)
        assert len(mesh.faces) >= 100
        assert len(mesh.vertices) >= 50

        scene = trimesh.Scene()
        scene.add_geometry(mesh)

        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as f:
            tmp_path = Path(f.name)

        try:
            scene.export(str(tmp_path))
            result = validate_mesh(tmp_path)
            assert result is False, (
                f"Expected rejection for mesh without texture even with "
                f"{len(mesh.faces)} faces and {len(mesh.vertices)} vertices"
            )
        finally:
            tmp_path.unlink(missing_ok=True)
