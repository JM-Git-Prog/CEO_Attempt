"""Unit tests for UnifiedHunyuan3DGenerator.

Tests the Hunyuan3D 2.1 mesh generator wrapper that adapts the V14
generator to the unified pipeline's ObjectCanon → MeshApproval interface.

Requirements: 10.3, 10.4, 10.6
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
import trimesh
from PIL import Image

from src.photo_pipeline.models_v14 import ObjectMeshResult
from src.unified_pipeline.mesh_generators import (
    MeshGenerationError,
    UnifiedHunyuan3DGenerator,
)
from src.unified_pipeline.models import MeshApproval, ObjectCanon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_valid_glb(path: Path, face_count: int = 200, with_texture: bool = True) -> Path:
    """Create a valid GLB file with specified face count and optional texture."""
    # Create a sphere with enough faces
    mesh = trimesh.creation.icosphere(subdivisions=3)  # ~1280 faces

    if with_texture:
        # Create a simple texture image and apply as material
        tex_image = Image.new("RGB", (64, 64), (128, 100, 80))
        from trimesh.visual.material import PBRMaterial

        material = PBRMaterial(baseColorTexture=tex_image)
        mesh.visual = trimesh.visual.TextureVisuals(material=material)

    mesh.export(str(path), file_type="glb")
    return path


def _create_ground_sheet_glb(path: Path) -> Path:
    """Create a GLB with a fused ground sheet pattern."""
    # Create a mesh with >30% vertices on a flat bottom plane
    sphere = trimesh.creation.icosphere(subdivisions=2)

    # Add a big flat plane at the bottom
    plane_verts = np.array([
        [-2, -1, -2], [2, -1, -2], [2, -1, 2], [-2, -1, 2],
        [-1.5, -1, -1.5], [1.5, -1, -1.5], [1.5, -1, 1.5], [-1.5, -1, 1.5],
        [-1, -1, -1], [1, -1, -1], [1, -1, 1], [-1, -1, 1],
    ], dtype=np.float64)
    # Replicate to ensure >30% of total vertices
    plane_verts_many = np.tile(plane_verts, (20, 1))
    # Slightly jitter to avoid exact duplicates but keep flat
    plane_verts_many += np.random.default_rng(42).uniform(-0.001, 0.001, plane_verts_many.shape)
    plane_verts_many[:, 1] = -1.0  # Keep Y exactly flat

    # Combine sphere verts with ground plane verts
    all_verts = np.vstack([sphere.vertices + [0, 0.5, 0], plane_verts_many])

    # Create faces for sphere part only (ground sheet detected from vertices)
    # Use existing sphere faces
    combined = trimesh.Trimesh(vertices=all_verts, faces=sphere.faces, process=False)

    # Apply texture
    tex_image = Image.new("RGB", (64, 64), (100, 100, 100))
    from trimesh.visual.material import PBRMaterial

    material = PBRMaterial(baseColorTexture=tex_image)
    combined.visual = trimesh.visual.TextureVisuals(material=material)
    combined.export(str(path), file_type="glb")
    return path


def _create_no_texture_glb(path: Path) -> Path:
    """Create a valid geometry GLB without embedded textures."""
    mesh = trimesh.creation.icosphere(subdivisions=3)
    # Only vertex colors, no texture
    colors = np.full((len(mesh.vertices), 4), [128, 100, 80, 255], dtype=np.uint8)
    mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=colors)
    mesh.export(str(path), file_type="glb")
    return path


def _create_low_poly_glb(path: Path) -> Path:
    """Create a GLB with too few faces."""
    # Simple box with 12 faces
    mesh = trimesh.creation.box(extents=[1, 1, 1])
    tex_image = Image.new("RGB", (64, 64), (128, 100, 80))
    from trimesh.visual.material import PBRMaterial

    material = PBRMaterial(baseColorTexture=tex_image)
    mesh.visual = trimesh.visual.TextureVisuals(material=material)
    mesh.export(str(path), file_type="glb")
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def object_png(tmp_path: Path) -> Path:
    """Create a dummy Object_Canon RGBA image."""
    png_path = tmp_path / "coffee_maker.png"
    img = Image.new("RGBA", (256, 256), (120, 80, 40, 255))
    img.save(str(png_path))
    return png_path


@pytest.fixture
def object_canon(object_png: Path) -> ObjectCanon:
    """Create an ObjectCanon pointing to the test image."""
    return ObjectCanon(
        object_id="obj-coffee-001",
        object_name="coffee_maker",
        image_path=str(object_png),
        mask_coverage=0.45,
        approved=True,
        provenance="raw_segmentation",
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mocked ComfyUIClient."""
    return MagicMock()


@pytest.fixture
def valid_glb(tmp_path: Path) -> Path:
    """Create a valid textured GLB for testing."""
    return _create_valid_glb(tmp_path / "test_mesh.glb")


# ---------------------------------------------------------------------------
# Tests: Class Configuration
# ---------------------------------------------------------------------------


class TestUnifiedHunyuan3DConfiguration:
    """Test that the generator maintains required parameters."""

    def test_steps_is_50(self) -> None:
        """Requirement 10.3: KSampler steps=50."""
        assert UnifiedHunyuan3DGenerator.STEPS == 50

    def test_cfg_is_7(self) -> None:
        """Requirement 10.3: cfg=7.0."""
        assert UnifiedHunyuan3DGenerator.CFG == 7.0

    def test_octree_resolution_is_384(self) -> None:
        """Requirement 10.3: octree_resolution=384."""
        assert UnifiedHunyuan3DGenerator.OCTREE_RESOLUTION == 384

    def test_stall_timeout_is_180(self) -> None:
        """Requirement 10.4: 180s stall timeout."""
        assert UnifiedHunyuan3DGenerator.STALL_TIMEOUT_S == 180

    def test_min_faces_is_100(self) -> None:
        """Requirement 10.6: ≥100 faces."""
        assert UnifiedHunyuan3DGenerator.MIN_FACES == 100

    def test_min_vertices_is_50(self) -> None:
        """Requirement 10.6: ≥50 vertices."""
        assert UnifiedHunyuan3DGenerator.MIN_VERTICES == 50


# ---------------------------------------------------------------------------
# Tests: Successful Generation
# ---------------------------------------------------------------------------


class TestUnifiedHunyuan3DSuccess:
    """Test successful mesh generation via the inner generator."""

    @pytest.mark.asyncio
    async def test_returns_mesh_approval(
        self, object_canon: ObjectCanon, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """generate() returns a MeshApproval on success."""
        inner_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=45.0,
            face_count=1280,
            vertex_count=642,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            result = await gen.generate(object_canon)

        assert isinstance(result, MeshApproval)

    @pytest.mark.asyncio
    async def test_object_id_preserved(
        self, object_canon: ObjectCanon, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """Object ID from ObjectCanon is carried through to MeshApproval."""
        inner_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=50.0,
            face_count=1280,
            vertex_count=642,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            result = await gen.generate(object_canon)

        assert result.object_id == "obj-coffee-001"

    @pytest.mark.asyncio
    async def test_generation_method_is_hunyuan3d(
        self, object_canon: ObjectCanon, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """generation_method is set to 'hunyuan3d_v2.1'."""
        inner_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=60.0,
            face_count=1280,
            vertex_count=642,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            result = await gen.generate(object_canon)

        assert result.generation_method == "hunyuan3d_v2.1"

    @pytest.mark.asyncio
    async def test_not_placeholder(
        self, object_canon: ObjectCanon, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """Result is not marked as placeholder."""
        inner_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=45.0,
            face_count=1280,
            vertex_count=642,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            result = await gen.generate(object_canon)

        assert result.is_placeholder is False

    @pytest.mark.asyncio
    async def test_not_auto_approved(
        self, object_canon: ObjectCanon, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """Result awaits user approval gate (approved=False initially)."""
        inner_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=45.0,
            face_count=1280,
            vertex_count=642,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            result = await gen.generate(object_canon)

        assert result.approved is False

    @pytest.mark.asyncio
    async def test_passes_correct_params_to_inner(
        self, object_canon: ObjectCanon, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """Inner generator is called with the correct fixed parameters."""
        inner_result = ObjectMeshResult(
            mesh_path=valid_glb,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=45.0,
            face_count=1280,
            vertex_count=642,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result) as mock_gen:
            await gen.generate(object_canon)

        mock_gen.assert_called_once()
        call_kwargs = mock_gen.call_args[1]
        assert call_kwargs["steps"] == 50
        assert call_kwargs["cfg"] == 7.0
        assert call_kwargs["octree_resolution"] == 384
        assert call_kwargs["stall_timeout_s"] == 180


# ---------------------------------------------------------------------------
# Tests: Failure → MeshGenerationError
# ---------------------------------------------------------------------------


class TestUnifiedHunyuan3DFailure:
    """Test that failures raise MeshGenerationError for the fallback chain."""

    @pytest.mark.asyncio
    async def test_missing_image_raises(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Non-existent image_path raises MeshGenerationError immediately."""
        canon = ObjectCanon(
            object_id="obj-ghost-001",
            object_name="ghost",
            image_path=str(tmp_path / "nonexistent.png"),
            mask_coverage=0.0,
            approved=True,
        )
        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)

        with pytest.raises(MeshGenerationError) as exc_info:
            await gen.generate(canon)

        assert exc_info.value.object_id == "obj-ghost-001"
        assert exc_info.value.method == "hunyuan3d_v2.1"

    @pytest.mark.asyncio
    async def test_inner_returns_none_raises(
        self, object_canon: ObjectCanon, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """When inner generator returns None (timeout/VRAM), raises MeshGenerationError."""
        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=None):
            with pytest.raises(MeshGenerationError) as exc_info:
                await gen.generate(object_canon)

        assert "failed" in str(exc_info.value).lower()
        assert exc_info.value.object_id == "obj-coffee-001"

    @pytest.mark.asyncio
    async def test_error_contains_method(
        self, object_canon: ObjectCanon, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """MeshGenerationError includes the method name for diagnostics."""
        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=None):
            with pytest.raises(MeshGenerationError) as exc_info:
                await gen.generate(object_canon)

        assert exc_info.value.method == "hunyuan3d_v2.1"


# ---------------------------------------------------------------------------
# Tests: Mesh Validation
# ---------------------------------------------------------------------------


class TestUnifiedHunyuan3DValidation:
    """Test mesh validation rules (Req 10.6)."""

    @pytest.mark.asyncio
    async def test_no_texture_fails_validation(
        self, object_canon: ObjectCanon, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Mesh without embedded texture fails validation."""
        no_tex_path = _create_no_texture_glb(tmp_path / "no_tex.glb")

        inner_result = ObjectMeshResult(
            mesh_path=no_tex_path,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=50.0,
            face_count=1280,
            vertex_count=642,
            has_texture=False,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            with pytest.raises(MeshGenerationError) as exc_info:
                await gen.generate(object_canon)

        assert "texture" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_low_poly_fails_validation(
        self, object_canon: ObjectCanon, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Mesh with <100 faces fails validation."""
        low_poly_path = _create_low_poly_glb(tmp_path / "low_poly.glb")

        inner_result = ObjectMeshResult(
            mesh_path=low_poly_path,
            mask_id="obj-coffee-001",
            generation_method="hunyuan3d_v2.1",
            generation_time_s=50.0,
            face_count=12,
            vertex_count=8,
            has_texture=True,
        )

        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)

        with patch.object(gen._inner, "generate", new_callable=AsyncMock, return_value=inner_result):
            with pytest.raises(MeshGenerationError) as exc_info:
                await gen.generate(object_canon)

        assert "faces" in str(exc_info.value).lower() or "vertices" in str(exc_info.value).lower()

    def test_validate_mesh_passes_valid_glb(
        self, mock_client: MagicMock, valid_glb: Path
    ) -> None:
        """_validate_mesh returns None for a valid textured mesh."""
        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=valid_glb.parent)
        result = gen._validate_mesh(valid_glb)
        assert result is None

    def test_validate_mesh_rejects_missing_file(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """_validate_mesh returns error string for missing file."""
        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)
        result = gen._validate_mesh(tmp_path / "does_not_exist.glb")
        assert result is not None
        assert "not exist" in result.lower() or "does not exist" in result.lower()

    def test_detect_ground_sheet_clean_mesh(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """A normal sphere has no ground sheet."""
        mesh = trimesh.creation.icosphere(subdivisions=3)
        gen = UnifiedHunyuan3DGenerator(client=mock_client, output_dir=tmp_path)
        assert gen._detect_ground_sheet([mesh]) is False


# ---------------------------------------------------------------------------
# Tests: MeshGenerationError class
# ---------------------------------------------------------------------------


class TestMeshGenerationError:
    """Test the custom exception class."""

    def test_stores_object_id(self) -> None:
        err = MeshGenerationError("failed", object_id="obj-123", method="hunyuan3d_v2.1")
        assert err.object_id == "obj-123"

    def test_stores_method(self) -> None:
        err = MeshGenerationError("failed", object_id="obj-123", method="hunyuan3d_v2.1")
        assert err.method == "hunyuan3d_v2.1"

    def test_message(self) -> None:
        err = MeshGenerationError("something went wrong")
        assert str(err) == "something went wrong"

    def test_defaults(self) -> None:
        err = MeshGenerationError("oops")
        assert err.object_id == ""
        assert err.method == ""
