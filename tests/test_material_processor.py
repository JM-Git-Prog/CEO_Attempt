"""Unit tests for MaterialProcessor (task 12.1).

Tests the two-pass material quality system including:
- Pass 1 for neural meshes (accept native textures)
- Pass 1 for placeholder geometry (photo-project)
- Pass 2 PBR estimation from material type heuristic
- Texture size selection delegation
- Pass 2 priority queue ordering by area descending
- GLB update with embedded PBR buffer views

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 11.1, 11.2, 11.3
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.photo_pipeline.stages.material_processor import MaterialProcessor


@pytest.fixture
def processor() -> MaterialProcessor:
    """Create a MaterialProcessor instance for testing."""
    return MaterialProcessor()


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test artifacts."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_object_png(tmp_dir: Path) -> Path:
    """Create a sample RGBA object PNG for testing."""
    img = Image.new("RGBA", (128, 128), (200, 100, 50, 255))
    path = tmp_dir / "object_test.png"
    img.save(path)
    return path


@pytest.fixture
def sample_glb_neural(tmp_dir: Path) -> Path:
    """Create a minimal GLB file simulating a neural mesh output."""
    import trimesh

    # Create a simple box mesh with a texture
    mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    # Apply a simple color texture
    tex_img = Image.new("RGB", (64, 64), (150, 100, 200))
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=tex_img
    )
    uv = np.random.rand(len(mesh.vertices), 2).astype(np.float64)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    path = tmp_dir / "neural_mesh.glb"
    mesh.export(str(path), file_type="glb")
    return path


@pytest.fixture
def sample_glb_placeholder(tmp_dir: Path) -> Path:
    """Create a minimal GLB file simulating placeholder geometry."""
    import trimesh

    mesh = trimesh.creation.box(extents=[0.5, 0.5, 0.5])
    # No texture applied — simulates raw placeholder
    path = tmp_dir / "placeholder_mesh.glb"
    mesh.export(str(path), file_type="glb")
    return path


class TestPass1NeuralMesh:
    """Test Pass 1 behavior for Hunyuan3D/Trellis2 neural meshes."""

    def test_hunyuan3d_accepts_native_textures(
        self, processor: MaterialProcessor, sample_glb_neural: Path, sample_object_png: Path
    ):
        """Hunyuan3D mesh: Pass 1 should accept native textures, has_base_color=True."""
        result = processor.apply_pass1(
            glb_path=sample_glb_neural,
            object_png=sample_object_png,
            generation_method="hunyuan3d_v2.1",
            image_area_pct=0.05,
        )
        assert result.pass_number == 1
        assert result.has_base_color is True
        assert result.has_metallic_roughness is False
        assert result.has_normal_map is False
        assert result.object_id == "neural_mesh"

    def test_trellis2_accepts_native_textures(
        self, processor: MaterialProcessor, sample_glb_neural: Path, sample_object_png: Path
    ):
        """Trellis2 mesh: Pass 1 should accept native textures, has_base_color=True."""
        result = processor.apply_pass1(
            glb_path=sample_glb_neural,
            object_png=sample_object_png,
            generation_method="trellis2",
            image_area_pct=0.12,
        )
        assert result.pass_number == 1
        assert result.has_base_color is True
        assert result.texture_resolution == (1024, 1024)  # > 10%

    def test_missing_glb_returns_no_base_color(
        self, processor: MaterialProcessor, sample_object_png: Path, tmp_dir: Path
    ):
        """If GLB is missing, Pass 1 should return has_base_color=False."""
        missing_glb = tmp_dir / "nonexistent.glb"
        result = processor.apply_pass1(
            glb_path=missing_glb,
            object_png=sample_object_png,
            generation_method="hunyuan3d_v2.1",
            image_area_pct=0.05,
        )
        assert result.has_base_color is False


class TestPass1Placeholder:
    """Test Pass 1 photo-projection for placeholder geometry."""

    def test_placeholder_gets_photo_projected_texture(
        self, processor: MaterialProcessor, sample_glb_placeholder: Path, sample_object_png: Path
    ):
        """Placeholder mesh: Pass 1 should photo-project and embed texture."""
        result = processor.apply_pass1(
            glb_path=sample_glb_placeholder,
            object_png=sample_object_png,
            generation_method="placeholder",
            image_area_pct=0.03,
        )
        assert result.pass_number == 1
        assert result.has_base_color is True
        assert result.texture_resolution == (512, 512)  # 2-10% range

    def test_placeholder_glb_updated_with_texture(
        self, processor: MaterialProcessor, sample_glb_placeholder: Path, sample_object_png: Path
    ):
        """After Pass 1, placeholder GLB should contain embedded base color texture."""
        import trimesh

        processor.apply_pass1(
            glb_path=sample_glb_placeholder,
            object_png=sample_object_png,
            generation_method="placeholder",
            image_area_pct=0.05,
        )

        # Reload and check texture is embedded
        scene = trimesh.load(str(sample_glb_placeholder), force="scene")
        has_texture = False
        for geom in scene.geometry.values():
            if hasattr(geom, "visual") and hasattr(geom.visual, "material"):
                mat = geom.visual.material
                if hasattr(mat, "baseColorTexture") and mat.baseColorTexture is not None:
                    has_texture = True
                    break
        assert has_texture, "GLB should have embedded base color texture after Pass 1"


class TestPass2:
    """Test Pass 2 PBR estimation."""

    def test_pass2_metal_material(
        self, processor: MaterialProcessor, sample_glb_neural: Path, sample_object_png: Path
    ):
        """Pass 2 with metal material should produce high metallic, low roughness."""
        result = asyncio.run(
            processor.apply_pass2(
                glb_path=sample_glb_neural,
                object_png=sample_object_png,
                material_type="metal",
            )
        )
        assert result.pass_number == 2
        assert result.has_metallic_roughness is True
        assert result.has_normal_map is True

    def test_pass2_wood_material(
        self, processor: MaterialProcessor, sample_glb_neural: Path, sample_object_png: Path
    ):
        """Pass 2 with wood material should produce low metallic, high roughness."""
        result = asyncio.run(
            processor.apply_pass2(
                glb_path=sample_glb_neural,
                object_png=sample_object_png,
                material_type="wood",
            )
        )
        assert result.pass_number == 2
        assert result.has_metallic_roughness is True
        assert result.has_normal_map is True

    def test_pass2_unknown_material_uses_defaults(
        self, processor: MaterialProcessor, sample_glb_neural: Path, sample_object_png: Path
    ):
        """Pass 2 with unknown material should use default PBR values."""
        result = asyncio.run(
            processor.apply_pass2(
                glb_path=sample_glb_neural,
                object_png=sample_object_png,
                material_type="unknown_material",
            )
        )
        assert result.pass_number == 2
        assert result.has_metallic_roughness is True

    def test_pass2_failure_retains_pass1(
        self, processor: MaterialProcessor, sample_object_png: Path, tmp_dir: Path
    ):
        """If Pass 2 fails (e.g. corrupt GLB), result should gracefully degrade."""
        # Create a corrupt GLB (invalid binary)
        corrupt_glb = tmp_dir / "corrupt.glb"
        corrupt_glb.write_bytes(b"not a valid glb file")

        result = asyncio.run(
            processor.apply_pass2(
                glb_path=corrupt_glb,
                object_png=sample_object_png,
                material_type="metal",
            )
        )
        # Should indicate failure gracefully
        assert result.pass_number == 2
        assert result.has_metallic_roughness is False
        assert result.has_base_color is True  # retained from Pass 1


class TestTextureSizeSelection:
    """Test texture size selection delegation."""

    def test_small_object(self, processor: MaterialProcessor):
        """Objects < 2% area should get 256x256."""
        assert processor.select_texture_size(0.01) == (256, 256)
        assert processor.select_texture_size(0.0) == (256, 256)
        assert processor.select_texture_size(0.019) == (256, 256)

    def test_medium_object(self, processor: MaterialProcessor):
        """Objects 2-10% area should get 512x512."""
        assert processor.select_texture_size(0.02) == (512, 512)
        assert processor.select_texture_size(0.05) == (512, 512)
        assert processor.select_texture_size(0.10) == (512, 512)

    def test_large_object(self, processor: MaterialProcessor):
        """Objects > 10% area should get 1024x1024."""
        assert processor.select_texture_size(0.11) == (1024, 1024)
        assert processor.select_texture_size(0.5) == (1024, 1024)
        assert processor.select_texture_size(1.0) == (1024, 1024)


class TestPass2Queue:
    """Test Pass 2 priority queue ordering."""

    def test_sorted_by_area_descending(self, processor: MaterialProcessor):
        """Objects should be queued largest-area first for Pass 2."""
        objects = [("obj_a", 0.05), ("obj_b", 0.20), ("obj_c", 0.01), ("obj_d", 0.10)]
        queue = processor.get_pass2_queue(objects)
        assert queue == ["obj_b", "obj_d", "obj_a", "obj_c"]

    def test_empty_list(self, processor: MaterialProcessor):
        """Empty input returns empty queue."""
        assert processor.get_pass2_queue([]) == []

    def test_single_object(self, processor: MaterialProcessor):
        """Single object returns that object."""
        assert processor.get_pass2_queue([("only", 0.5)]) == ["only"]

    def test_equal_areas_preserves_order(self, processor: MaterialProcessor):
        """Equal areas: order among them is stable (Python sort is stable)."""
        objects = [("a", 0.10), ("b", 0.10), ("c", 0.10)]
        queue = processor.get_pass2_queue(objects)
        assert queue == ["a", "b", "c"]
