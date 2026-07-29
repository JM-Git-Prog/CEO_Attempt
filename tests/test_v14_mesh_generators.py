"""Unit tests for Hunyuan3DV2Generator and Trellis2Generator with mocked ComfyUI.

Tests workflow parameter passing, validation, timeout/fallback triggers,
and metadata recording for both mesh generators.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.6
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
    ComfyUIVRAMError,
)
from src.photo_pipeline.models_v14 import ObjectMeshResult
from src.photo_pipeline.stages.hunyuan3d_v2_generator import (
    Hunyuan3DV2Generator,
    _build_hunyuan3d_v2_workflow,
)
from src.photo_pipeline.stages.trellis2_generator import (
    Trellis2Generator,
    _build_trellis2_workflow,
)


# ---------------------------------------------------------------------------
# Helpers — create minimal valid GLB files using trimesh
# ---------------------------------------------------------------------------


def _create_valid_glb(path: Path) -> Path:
    """Create a minimal valid textured GLB (icosphere with >100 faces, >50 verts).

    Uses a textured icosphere with sufficient subdivisions to pass validation.
    """
    # Create an icosphere with enough subdivisions for >100 faces, >50 vertices
    mesh = trimesh.creation.icosphere(subdivisions=3)
    # Should have 320 faces and 162 vertices at subdivision 3

    # Apply a texture (small 4x4 image) to satisfy the texture check
    texture_image = np.random.randint(0, 255, (4, 4, 3), dtype=np.uint8)
    from PIL import Image

    img = Image.fromarray(texture_image)
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=img,
        metallicFactor=0.0,
        roughnessFactor=0.8,
    )

    # Create UV coordinates for the mesh
    uv = np.random.rand(len(mesh.vertices), 2).astype(np.float32)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    # Export as GLB
    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(path), file_type="glb")
    return path


def _create_invalid_glb_few_faces(path: Path) -> Path:
    """Create a GLB with too few faces (below 100 threshold)."""
    # Icosphere with subdivision 1 = 20 faces, 12 vertices — too few
    mesh = trimesh.creation.icosphere(subdivisions=1)

    texture_image = np.random.randint(0, 255, (4, 4, 3), dtype=np.uint8)
    from PIL import Image

    img = Image.fromarray(texture_image)
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=img,
    )
    uv = np.random.rand(len(mesh.vertices), 2).astype(np.float32)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(path), file_type="glb")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock ComfyUIClient with async methods."""
    client = AsyncMock(spec=ComfyUIClient)
    client.submit_workflow = AsyncMock(return_value="prompt-123")
    client.wait_for_completion = AsyncMock(return_value={"outputs": {}})
    client.get_output_mesh = AsyncMock()
    return client


@pytest.fixture
def object_png(tmp_path: Path) -> Path:
    """Create a dummy Object_PNG file for testing."""
    png_path = tmp_path / "object_01.png"
    # Create a minimal valid PNG
    from PIL import Image

    img = Image.new("RGBA", (256, 256), (128, 64, 32, 255))
    img.save(str(png_path))
    return png_path


# ===========================================================================
# Hunyuan3DV2Generator Tests
# ===========================================================================


class TestHunyuan3DV2WorkflowParams:
    """Verify workflow parameters are correctly built for Hunyuan3D 2.1."""

    def test_default_workflow_params(self) -> None:
        """Default workflow uses steps=50, cfg=7.0, octree_resolution=384."""
        workflow = _build_hunyuan3d_v2_workflow("test/image.png")

        # KSampler node (6) should have correct params
        ksampler = workflow["6"]["inputs"]
        assert ksampler["steps"] == 50
        assert ksampler["cfg"] == 7.0

        # VAEDecodeHunyuan3D node (7) should have octree_resolution
        vae_decode = workflow["7"]["inputs"]
        assert vae_decode["octree_resolution"] == 384

    def test_custom_workflow_params(self) -> None:
        """Custom parameters are passed through to the workflow."""
        workflow = _build_hunyuan3d_v2_workflow(
            "test/image.png",
            steps=30,
            cfg=5.5,
            octree_resolution=256,
            seed=99,
        )

        ksampler = workflow["6"]["inputs"]
        assert ksampler["steps"] == 30
        assert ksampler["cfg"] == 5.5
        assert ksampler["seed"] == 99

        vae_decode = workflow["7"]["inputs"]
        assert vae_decode["octree_resolution"] == 256

    def test_workflow_image_path(self) -> None:
        """Image path is set in the LoadImage node."""
        workflow = _build_hunyuan3d_v2_workflow("C:/path/to/object.png")
        assert workflow["1"]["inputs"]["image"] == "C:/path/to/object.png"

    def test_workflow_node_chain(self) -> None:
        """Verify the full node chain is present with correct class_types."""
        workflow = _build_hunyuan3d_v2_workflow("img.png")
        expected_nodes = {
            "1": "LoadImage",
            "2": "ImageOnlyCheckpointLoader",
            "3": "ModelSamplingAuraFlow",
            "4": "CLIPVisionEncode",
            "5": "Hunyuan3Dv2Conditioning",
            "6": "KSampler",
            "7": "VAEDecodeHunyuan3D",
            "8": "VoxelToMesh",
            "9": "SaveGLB",
        }
        for node_id, class_type in expected_nodes.items():
            assert workflow[node_id]["class_type"] == class_type


class TestHunyuan3DV2GeneratorSuccess:
    """Test successful Hunyuan3D 2.1 generation flow."""

    @pytest.mark.asyncio
    async def test_successful_generation(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Successful generation returns ObjectMeshResult with correct fields."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        # Create a valid GLB that the mock will "return"
        glb_path = output_dir / "objects" / "obj_01_hunyuan3d.glb"
        _create_valid_glb(glb_path)

        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is not None
        assert isinstance(result, ObjectMeshResult)
        assert result.mesh_path == glb_path
        assert result.mask_id == "obj_01"
        assert result.generation_method == "hunyuan3d_v2.1"
        assert result.generation_time_s > 0
        assert result.face_count >= 100
        assert result.vertex_count >= 50
        assert result.has_texture is True

    @pytest.mark.asyncio
    async def test_submit_workflow_called_with_correct_params(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Verify submit_workflow is called with a workflow containing the image path."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_01_hunyuan3d.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        await generator.generate(object_png, mask_id="obj_01")

        # submit_workflow should have been called
        mock_client.submit_workflow.assert_called_once()
        call_args = mock_client.submit_workflow.call_args
        workflow = call_args[0][0]  # First positional arg

        # The image path in the workflow should use forward slashes
        image_in_workflow = workflow["1"]["inputs"]["image"]
        assert "/" in image_in_workflow or "\\" not in image_in_workflow


class TestHunyuan3DV2GeneratorErrors:
    """Test Hunyuan3D 2.1 error handling — all return None for fallback."""

    @pytest.mark.asyncio
    async def test_timeout_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """asyncio.TimeoutError → returns None (triggers Trellis2 fallback)."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        # Simulate timeout on wait_for_completion
        mock_client.wait_for_completion.side_effect = asyncio.TimeoutError()

        result = await generator.generate(
            object_png, mask_id="obj_01", stall_timeout_s=1
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_comfyui_error_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """ComfyUIError → returns None."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        mock_client.submit_workflow.side_effect = ComfyUIError("Node failed")

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is None

    @pytest.mark.asyncio
    async def test_comfyui_timeout_error_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """ComfyUITimeoutError → returns None."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        mock_client.wait_for_completion.side_effect = ComfyUITimeoutError(
            "Timed out after 180s"
        )

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is None

    @pytest.mark.asyncio
    async def test_comfyui_vram_error_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """ComfyUIVRAMError → returns None."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        mock_client.submit_workflow.side_effect = ComfyUIVRAMError("CUDA OOM")

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_mesh_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Mesh with too few faces fails validation → returns None."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        # Create an invalid GLB (too few faces)
        glb_path = output_dir / "objects" / "obj_01_hunyuan3d.glb"
        _create_invalid_glb_few_faces(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is None


class TestHunyuan3DV2GeneratorMetadata:
    """Test metadata recording in ObjectMeshResult."""

    @pytest.mark.asyncio
    async def test_generation_time_recorded(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """generation_time_s reflects actual elapsed time."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_01_hunyuan3d.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is not None
        assert result.generation_time_s >= 0.0

    @pytest.mark.asyncio
    async def test_face_and_vertex_counts(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Face and vertex counts are extracted from the generated mesh."""
        output_dir = tmp_path / "output"
        generator = Hunyuan3DV2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_01_hunyuan3d.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_01")

        assert result is not None
        # Icosphere subdiv 3 = 1280 faces, 642 vertices
        assert result.face_count == 1280
        assert result.vertex_count == 642


# ===========================================================================
# Trellis2Generator Tests
# ===========================================================================


class TestTrellis2WorkflowParams:
    """Verify workflow parameters are correctly built for Trellis2."""

    def test_default_workflow_params(self) -> None:
        """Default workflow uses steps=18, target_triangles=12000."""
        workflow = _build_trellis2_workflow("test/image.png")

        # Trellis2MeshWithVoxelGenerator node (4) should have steps
        voxel_gen = workflow["4"]["inputs"]
        assert voxel_gen["steps"] == 18

        # Trellis2SimplifyMesh node (5) should have triangles
        simplify = workflow["5"]["inputs"]
        assert simplify["triangles"] == 12000

    def test_custom_workflow_params(self) -> None:
        """Custom parameters are passed through to the workflow."""
        workflow = _build_trellis2_workflow(
            "test/image.png",
            steps=25,
            target_triangles=8000,
            seed=77,
        )

        voxel_gen = workflow["4"]["inputs"]
        assert voxel_gen["steps"] == 25
        assert voxel_gen["seed"] == 77

        simplify = workflow["5"]["inputs"]
        assert simplify["triangles"] == 8000

    def test_workflow_image_path(self) -> None:
        """Image path is set in the LoadImage node."""
        workflow = _build_trellis2_workflow("C:/path/to/object.png")
        assert workflow["1"]["inputs"]["image"] == "C:/path/to/object.png"

    def test_workflow_node_chain(self) -> None:
        """Verify the full Trellis2 node chain with correct class_types."""
        workflow = _build_trellis2_workflow("img.png")
        expected_nodes = {
            "1": "LoadImage",
            "2": "Trellis2LoadModel",
            "3": "Trellis2PreProcessImage",
            "4": "Trellis2MeshWithVoxelGenerator",
            "5": "Trellis2SimplifyMesh",
            "6": "Trellis2ExportMesh",
        }
        for node_id, class_type in expected_nodes.items():
            assert workflow[node_id]["class_type"] == class_type

    def test_export_format_is_glb(self) -> None:
        """Trellis2ExportMesh node specifies GLB format."""
        workflow = _build_trellis2_workflow("img.png")
        export_node = workflow["6"]["inputs"]
        assert export_node["format"] == "GLB"


class TestTrellis2GeneratorSuccess:
    """Test successful Trellis2 generation flow."""

    @pytest.mark.asyncio
    async def test_successful_generation(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Successful generation returns ObjectMeshResult with generation_method='trellis2'."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_02_trellis2.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is not None
        assert isinstance(result, ObjectMeshResult)
        assert result.mesh_path == glb_path
        assert result.mask_id == "obj_02"
        assert result.generation_method == "trellis2"
        assert result.generation_time_s > 0
        assert result.face_count >= 100
        assert result.vertex_count >= 50
        assert result.has_texture is True

    @pytest.mark.asyncio
    async def test_submit_workflow_called(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Verify submit_workflow is called with the Trellis2 workflow."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_02_trellis2.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        await generator.generate(object_png, mask_id="obj_02")

        mock_client.submit_workflow.assert_called_once()
        call_args = mock_client.submit_workflow.call_args
        workflow = call_args[0][0]

        # Verify Trellis2-specific nodes
        assert workflow["2"]["class_type"] == "Trellis2LoadModel"
        assert workflow["4"]["class_type"] == "Trellis2MeshWithVoxelGenerator"


class TestTrellis2GeneratorErrors:
    """Test Trellis2 error handling — all return None for placeholder fallback."""

    @pytest.mark.asyncio
    async def test_comfyui_error_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """ComfyUIError → returns None."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        mock_client.submit_workflow.side_effect = ComfyUIError("Execution failed")

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is None

    @pytest.mark.asyncio
    async def test_comfyui_timeout_error_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """ComfyUITimeoutError → returns None."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        mock_client.wait_for_completion.side_effect = ComfyUITimeoutError(
            "Trellis2 timed out"
        )

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is None

    @pytest.mark.asyncio
    async def test_comfyui_vram_error_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """ComfyUIVRAMError → returns None."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        mock_client.submit_workflow.side_effect = ComfyUIVRAMError("CUDA OOM")

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_mesh_returns_none(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Mesh failing validation → returns None for placeholder fallback."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_02_trellis2.glb"
        _create_invalid_glb_few_faces(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is None


class TestTrellis2GeneratorMetadata:
    """Test metadata recording for Trellis2."""

    @pytest.mark.asyncio
    async def test_generation_time_recorded(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """generation_time_s is recorded."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_02_trellis2.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is not None
        assert result.generation_time_s >= 0.0

    @pytest.mark.asyncio
    async def test_face_and_vertex_counts(
        self, mock_client: AsyncMock, object_png: Path, tmp_path: Path
    ) -> None:
        """Face and vertex counts extracted from generated mesh."""
        output_dir = tmp_path / "output"
        generator = Trellis2Generator(client=mock_client, output_dir=output_dir)

        glb_path = output_dir / "objects" / "obj_02_trellis2.glb"
        _create_valid_glb(glb_path)
        mock_client.get_output_mesh.return_value = glb_path

        result = await generator.generate(object_png, mask_id="obj_02")

        assert result is not None
        # Icosphere subdiv 3 = 1280 faces, 642 vertices
        assert result.face_count == 1280
        assert result.vertex_count == 642
