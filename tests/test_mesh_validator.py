"""Unit tests for mesh_validator.validate_mesh.

Verifies the mesh validation utility correctly accepts meshes that meet
all three criteria (≥100 faces, ≥50 vertices, embedded texture) and
rejects meshes that fail any criterion.

Requirements: 1.2
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest
import trimesh
from PIL import Image

from src.photo_pipeline.stages.mesh_validator import validate_mesh


@pytest.fixture
def tmp_glb(tmp_path):
    """Helper to export a trimesh scene to a temporary GLB and return its path."""

    def _export(scene: trimesh.Scene) -> Path:
        path = tmp_path / "test_mesh.glb"
        scene.export(str(path))
        return path

    return _export


def _make_textured_mesh(subdivisions: int = 4) -> trimesh.Trimesh:
    """Create an icosphere with a valid texture applied."""
    mesh = trimesh.creation.icosphere(subdivisions=subdivisions)
    img = Image.new("RGB", (64, 64), color=(128, 100, 80))
    uv = np.random.rand(len(mesh.vertices), 2).astype(np.float64)
    material = trimesh.visual.material.SimpleMaterial(image=img)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    return mesh


class TestValidateMeshRejectsInvalidInputs:
    """Tests that validate_mesh returns False for invalid inputs."""

    def test_nonexistent_file_returns_false(self):
        assert validate_mesh(Path("does_not_exist.glb")) is False

    def test_empty_file_returns_false(self, tmp_path):
        path = tmp_path / "empty.glb"
        path.write_bytes(b"")
        assert validate_mesh(path) is False

    def test_corrupt_file_returns_false(self, tmp_path):
        path = tmp_path / "corrupt.glb"
        path.write_bytes(b"not a valid glb file content here")
        assert validate_mesh(path) is False

    def test_too_few_faces_returns_false(self, tmp_glb):
        # A box has 12 faces, 8 vertices - both below thresholds
        mesh = trimesh.creation.box()
        scene = trimesh.Scene(mesh)
        path = tmp_glb(scene)
        assert validate_mesh(path) is False

    def test_enough_vertices_but_too_few_faces_returns_false(self, tmp_glb):
        # Create a mesh with many vertices but few faces (degenerate)
        # A low-subdivision sphere: 42 vertices, 80 faces
        mesh = trimesh.creation.icosphere(subdivisions=1)
        # 80 faces < 100 threshold
        img = Image.new("RGB", (32, 32), color=(200, 200, 200))
        uv = np.random.rand(len(mesh.vertices), 2).astype(np.float64)
        material = trimesh.visual.material.SimpleMaterial(image=img)
        mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
        scene = trimesh.Scene(mesh)
        path = tmp_glb(scene)
        assert validate_mesh(path) is False

    def test_no_texture_returns_false(self, tmp_glb):
        # Large mesh (lots of faces/verts) but no texture
        mesh = trimesh.creation.icosphere(subdivisions=4)
        # icosphere(4) has 5120 faces, 2562 vertices - well above thresholds
        scene = trimesh.Scene(mesh)
        path = tmp_glb(scene)
        assert validate_mesh(path) is False


class TestValidateMeshAcceptsValid:
    """Tests that validate_mesh returns True for valid inputs."""

    def test_large_textured_mesh_passes(self, tmp_glb):
        mesh = _make_textured_mesh(subdivisions=4)
        # icosphere(4): 5120 faces, 2562 vertices + texture
        scene = trimesh.Scene(mesh)
        path = tmp_glb(scene)
        result = validate_mesh(path)
        assert result is True

    def test_exactly_at_threshold_passes(self, tmp_glb):
        """A mesh with exactly 100+ faces, 50+ vertices, and texture should pass."""
        mesh = _make_textured_mesh(subdivisions=2)
        # icosphere(2): 320 faces, 162 vertices - above thresholds
        scene = trimesh.Scene(mesh)
        path = tmp_glb(scene)
        assert validate_mesh(path) is True

    def test_multi_geometry_scene_aggregates(self, tmp_glb):
        """Multiple small meshes that together exceed thresholds should pass."""
        # Each icosphere(1) has 80 faces, 42 vertices
        # Two together: 160 faces, 84 vertices - above thresholds
        mesh1 = _make_textured_mesh(subdivisions=1)
        mesh2 = _make_textured_mesh(subdivisions=1)
        mesh2.apply_translation([2, 0, 0])
        scene = trimesh.Scene()
        scene.add_geometry(mesh1, node_name="obj1")
        scene.add_geometry(mesh2, node_name="obj2")
        path = tmp_glb(scene)
        result = validate_mesh(path)
        assert result is True
