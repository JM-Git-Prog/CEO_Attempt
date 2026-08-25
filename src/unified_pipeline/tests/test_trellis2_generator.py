"""Unit tests for UnifiedTrellis2Generator.

Tests the Trellis2 fallback mesh generator wrapper that adapts the V14
Trellis2Generator to the unified pipeline's ObjectCanon → MeshApproval
interface.

Requirements: 10.4
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh

from src.photo_pipeline.models_v14 import ObjectMeshResult
from src.unified_pipeline.mesh_generators import (
    MeshGenerationError,
    UnifiedTrellis2Generator,
)
from src.unified_pipeline.models import MeshApproval, ObjectCanon


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def object_png(tmp_path: Path) -> Path:
    """Create a dummy Object_Canon RGBA image."""
    from PIL import Image

    png_path = tmp_path / "chair.png"
    img = Image.new("RGBA", (256, 256), (100, 80, 60, 255))
    img.save(str(png_path))
    return png_path


@pytest.fixture
def object_canon(object_png: Path) -> ObjectCanon:
    """Create an ObjectCanon pointing to the test image."""
    return ObjectCanon(
        object_id="obj-chair-001",
        object_name="chair",
        image_path=str(object_png),
        mask_coverage=0.55,
        approved=True,
        provenance="raw_segmentation",
    )


@pytest.fixture
def valid_glb(tmp_path: Path) -> Path:
    """Create a valid GLB file with sufficient geometry and texture."""
    mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    # Subdivide to get enough faces/vertices
    for _ in range(3):
        mesh = mesh.subdivide()

    # Add a simple texture
    from PIL import Image

    tex_img = Image.new("RGBA", (64, 64), (128, 100, 80, 255))
    from trimesh.visual.material import PBRMaterial

    material = PBRMaterial(baseColorTexture=tex_img)
    mesh.visual = trimesh.visual.TextureVisuals(material=material)

    glb_path = tmp_path / "output" / "objects" / "obj-chair-001_trellis2.glb"
    glb_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(glb_path))
    return glb_path


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock ComfyUIClient."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests: Class Configuration
# ---------------------------------------------------------------------------


class TestUnifiedTrellis2GeneratorConfig:
    """Test the generator maintains fixed Trellis2 parameters."""

    def test_steps_fixed_at_18(self) -> None:
        """STEPS is fixed at 18 per Requirement 10.4."""
        assert UnifiedTrellis2Generator.STEPS == 18

    def test_target_triangles_fixed_at_12000(self) -> None:
        """TARGET_TRIANGLES is fixed at 12000 per Requirement 10.4."""
        assert UnifiedTrellis2Generator.TARGET_TRIANGLES == 12000

    def test_min_faces_threshold(self) -> None:
        """MIN_FACES is 100 per Requirement 10.6."""
        assert UnifiedTrellis2Generator.MIN_FACES == 100

    def test_min_vertices_threshold(self) -> None:
        """MIN_VERTICES is 50 per Requirement 10.6."""
        assert UnifiedTrellis2Generator.MIN_VERTICES == 50


# ---------------------------------------------------------------------------
# Tests: Successful Generation
# ---------------------------------------------------------------------------


class TestUnifiedTrellis2GeneratorSuccess:
    """Test successful Trellis2 mesh generation from ObjectCanon."""

    @pytest.mark.asyncio
    async def test_returns_mesh_approval(
        self, object_canon: ObjectCanon, valid_glb: Path, tmp_path: Path, mock_client: MagicMock
    ) -> None:
        """generate() returns a valid MeshApproval on success."""
        mock_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-chair-001",
            generation_method="trellis2",
            generation_time_s=12.5,
            face_count=1500,
            vertex_count=800,
            has_texture=True,
        )

        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path / "output")
        gen._inner = AsyncMock()
        gen._inner.generate = AsyncMock(return_value=mock_result)

        result = await gen.generate(object_canon)

        assert isinstance(result, MeshApproval)
        assert result.object_id == "obj-chair-001"
        assert result.generation_method == "trellis2"

    @pytest.mark.asyncio
    async def test_mesh_not_approved_by_default(
        self, object_canon: ObjectCanon, valid_glb: Path, tmp_path: Path, mock_client: MagicMock
    ) -> None:
        """Generated meshes await user shape approval (approved=False)."""
        mock_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-chair-001",
            generation_method="trellis2",
            generation_time_s=10.0,
            face_count=1500,
            vertex_count=800,
            has_texture=True,
        )

        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path / "output")
        gen._inner = AsyncMock()
        gen._inner.generate = AsyncMock(return_value=mock_result)

        result = await gen.generate(object_canon)

        assert result.approved is False
        assert result.is_placeholder is False

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_inner(
        self, object_canon: ObjectCanon, valid_glb: Path, tmp_path: Path, mock_client: MagicMock
    ) -> None:
        """Passes fixed steps=18, target_triangles=12000 to inner generator."""
        mock_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-chair-001",
            generation_method="trellis2",
            generation_time_s=10.0,
            face_count=1500,
            vertex_count=800,
            has_texture=True,
        )

        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path / "output")
        gen._inner = AsyncMock()
        gen._inner.generate = AsyncMock(return_value=mock_result)

        await gen.generate(object_canon)

        prepared_path = tmp_path / "output" / "prepared_inputs" / "obj-chair-001.png"
        assert prepared_path.is_file()
        gen._inner.generate.assert_called_once_with(
            object_png=prepared_path,
            mask_id="obj-chair-001",
            steps=18,
            target_triangles=12000,
        )


# ---------------------------------------------------------------------------
# Tests: Failure Handling
# ---------------------------------------------------------------------------


class TestUnifiedTrellis2GeneratorFailures:
    """Test failure modes that trigger the fallback chain."""

    @pytest.mark.asyncio
    async def test_missing_image_raises_error(
        self, tmp_path: Path, mock_client: MagicMock
    ) -> None:
        """Non-existent Object_Canon image raises MeshGenerationError."""
        canon = ObjectCanon(
            object_id="obj-ghost-001",
            object_name="ghost",
            image_path=str(tmp_path / "nonexistent.png"),
            mask_coverage=0.5,
            approved=True,
        )

        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path / "output")

        with pytest.raises(MeshGenerationError) as exc_info:
            await gen.generate(canon)

        assert exc_info.value.object_id == "obj-ghost-001"
        assert exc_info.value.method == "trellis2"
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_inner_returns_none_raises_error(
        self, object_canon: ObjectCanon, tmp_path: Path, mock_client: MagicMock
    ) -> None:
        """When inner generator returns None (ComfyUI failure), raises error."""
        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path / "output")
        gen._inner = AsyncMock()
        gen._inner.generate = AsyncMock(return_value=None)

        with pytest.raises(MeshGenerationError) as exc_info:
            await gen.generate(object_canon)

        assert exc_info.value.object_id == "obj-chair-001"
        assert exc_info.value.method == "trellis2"
        assert "failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_error_preserves_object_id(
        self, object_canon: ObjectCanon, tmp_path: Path, mock_client: MagicMock
    ) -> None:
        """MeshGenerationError always contains the object_id."""
        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path / "output")
        gen._inner = AsyncMock()
        gen._inner.generate = AsyncMock(return_value=None)

        with pytest.raises(MeshGenerationError) as exc_info:
            await gen.generate(object_canon)

        assert exc_info.value.object_id == object_canon.object_id


# ---------------------------------------------------------------------------
# Tests: Mesh Validation
# ---------------------------------------------------------------------------


class TestUnifiedTrellis2Validation:
    """Test mesh validation logic."""

    def test_validate_nonexistent_file(self, tmp_path: Path, mock_client: MagicMock) -> None:
        """Non-existent mesh file fails validation."""
        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path)
        error = gen._validate_mesh(tmp_path / "missing.glb")
        assert error is not None
        assert "does not exist" in error

    def test_validate_valid_mesh(self, valid_glb: Path, tmp_path: Path, mock_client: MagicMock) -> None:
        """Valid mesh with texture passes validation."""
        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path)
        error = gen._validate_mesh(valid_glb)
        assert error is None

    def test_validate_too_few_faces(self, tmp_path: Path, mock_client: MagicMock) -> None:
        """Mesh with fewer than 100 faces fails validation."""
        # Create a simple triangle mesh (2 faces from a plane)
        mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
        # A box has 12 faces — below 100

        from PIL import Image
        from trimesh.visual.material import PBRMaterial

        tex_img = Image.new("RGBA", (32, 32), (128, 128, 128, 255))
        material = PBRMaterial(baseColorTexture=tex_img)
        mesh.visual = trimesh.visual.TextureVisuals(material=material)

        glb_path = tmp_path / "small.glb"
        mesh.export(str(glb_path))

        gen = UnifiedTrellis2Generator(client=mock_client, output_dir=tmp_path)
        error = gen._validate_mesh(glb_path)
        assert error is not None
        assert "Insufficient faces" in error
