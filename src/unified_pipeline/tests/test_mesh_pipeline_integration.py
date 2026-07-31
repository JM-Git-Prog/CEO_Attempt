"""Integration tests for the mesh generation pipeline.

Tests the fallback chain (Hunyuan3D → Trellis2 → placeholder),
VRAM ordering, and the approval gate interaction.

Requirements: 10.3, 10.4, 10.5, 10.6
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Any

import pytest

from src.unified_pipeline.mesh_generators import (
    UnifiedHunyuan3DGenerator,
    UnifiedTrellis2Generator,
    UnifiedPlaceholderGenerator,
    MeshGenerationError,
)
from src.unified_pipeline.mesh_approval import MeshApprovalGate
from src.unified_pipeline.models import ObjectCanon, MeshApproval
from src.unified_pipeline.tests.test_hunyuan3d_generator import _create_valid_glb


# ─── Helpers ───────────────────────────────────────────────────────────────────


@dataclass
class FakeGenerationResult:
    """Fake result object mimicking what the inner generators return."""

    mesh_path: Path
    face_count: int
    vertex_count: int


class FakeVRAMManager:
    """Mock VRAM manager tracking model load/unload order."""

    def __init__(self) -> None:
        self.load_order: list[str] = []
        self.currently_loaded: str | None = None

    def load_model(self, model_name: str) -> None:
        self.load_order.append(model_name)
        self.currently_loaded = model_name

    def unload_model(self) -> None:
        self.currently_loaded = None


async def run_fallback_chain(
    object_canon: ObjectCanon,
    hunyuan_gen: UnifiedHunyuan3DGenerator,
    trellis_gen: UnifiedTrellis2Generator,
    placeholder_gen: UnifiedPlaceholderGenerator,
    vram_manager: FakeVRAMManager | None = None,
) -> MeshApproval:
    """Execute the mesh generation fallback chain.

    Order: Hunyuan3D → Trellis2 → Placeholder.
    Each failure triggers the next in the chain.
    VRAM manager is notified of model loads if provided.
    """
    # Try Hunyuan3D first (Req 10.3)
    try:
        if vram_manager:
            vram_manager.load_model("hunyuan3d_v2.1")
        result = await hunyuan_gen.generate(object_canon)
        if vram_manager:
            vram_manager.unload_model()
        return result
    except MeshGenerationError:
        if vram_manager:
            vram_manager.unload_model()

    # Fallback to Trellis2 (Req 10.4)
    try:
        if vram_manager:
            vram_manager.load_model("trellis2")
        result = await trellis_gen.generate(object_canon)
        if vram_manager:
            vram_manager.unload_model()
        return result
    except MeshGenerationError:
        if vram_manager:
            vram_manager.unload_model()

    # Final fallback: placeholder (Req 10.5)
    if vram_manager:
        vram_manager.load_model("placeholder")
    result = placeholder_gen.generate(object_canon)
    if vram_manager:
        vram_manager.unload_model()
    return result


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def object_png(tmp_path: Path) -> Path:
    """Create a dummy Object_Canon RGBA image for testing."""
    from PIL import Image

    png_path = tmp_path / "test_object.png"
    img = Image.new("RGBA", (256, 256), (120, 80, 40, 255))
    img.save(str(png_path))
    return png_path


@pytest.fixture
def object_canon(object_png: Path) -> ObjectCanon:
    """ObjectCanon fixture with a valid test image."""
    return ObjectCanon(
        object_id="obj-table-001",
        object_name="table",
        image_path=str(object_png),
        mask_coverage=0.5,
        approved=True,
        provenance="raw_segmentation",
    )


@pytest.fixture
def mock_comfyui_client() -> MagicMock:
    """Mock ComfyUI client."""
    return MagicMock()


@pytest.fixture
def hunyuan_gen(mock_comfyui_client: MagicMock, tmp_path: Path):
    """UnifiedHunyuan3DGenerator with mocked inner generator."""
    with patch(
        "src.unified_pipeline.mesh_generators.Hunyuan3DV2Generator"
    ) as MockInner:
        mock_inner = MockInner.return_value
        gen = UnifiedHunyuan3DGenerator(
            client=mock_comfyui_client, output_dir=tmp_path / "hunyuan"
        )
        gen._inner = mock_inner
        yield gen


@pytest.fixture
def trellis_gen(mock_comfyui_client: MagicMock, tmp_path: Path):
    """UnifiedTrellis2Generator with mocked inner generator."""
    with patch(
        "src.unified_pipeline.mesh_generators.Trellis2Generator"
    ) as MockInner:
        mock_inner = MockInner.return_value
        gen = UnifiedTrellis2Generator(
            client=mock_comfyui_client, output_dir=tmp_path / "trellis"
        )
        gen._inner = mock_inner
        yield gen


@pytest.fixture
def placeholder_gen(tmp_path: Path) -> UnifiedPlaceholderGenerator:
    """UnifiedPlaceholderGenerator with output directory."""
    return UnifiedPlaceholderGenerator(output_dir=tmp_path / "placeholder")


# ─── Test 1: Successful Hunyuan3D → approval gate → materials ─────────────────


class TestHunyuan3DSuccessPath:
    """Req 10.3: Hunyuan3D succeeds → mesh goes to approval gate."""

    @pytest.mark.asyncio
    async def test_hunyuan_success_produces_unapproved_mesh(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon, tmp_path
    ):
        """Hunyuan3D success returns MeshApproval awaiting gate."""
        # Create a fake GLB with valid mesh data
        mesh_path = tmp_path / "hunyuan" / "table.glb"
        mesh_path.parent.mkdir(parents=True, exist_ok=True)
        _create_valid_glb(mesh_path)

        hunyuan_gen._inner.generate = AsyncMock(
            return_value=FakeGenerationResult(
                mesh_path=mesh_path, face_count=5000, vertex_count=2500
            )
        )
        # Patch validation to pass
        hunyuan_gen._validate_mesh = MagicMock(return_value=None)

        result = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        assert result.generation_method == "hunyuan3d_v2.1"
        assert result.approved is False  # Awaiting approval gate
        assert result.is_placeholder is False
        assert result.object_id == "obj-table-001"


    @pytest.mark.asyncio
    async def test_hunyuan_success_then_approval_gate_approves(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon, tmp_path
    ):
        """Approved Hunyuan3D mesh proceeds to materials (Req 11.4)."""
        mesh_path = tmp_path / "hunyuan" / "table.glb"
        mesh_path.parent.mkdir(parents=True, exist_ok=True)
        _create_valid_glb(mesh_path)

        hunyuan_gen._inner.generate = AsyncMock(
            return_value=FakeGenerationResult(
                mesh_path=mesh_path, face_count=5000, vertex_count=2500
            )
        )
        hunyuan_gen._validate_mesh = MagicMock(return_value=None)

        mesh = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        # Pass through approval gate
        gate = MeshApprovalGate()
        gate.present_for_approval(mesh)
        approved = gate.approve(mesh)

        assert approved.approved is True
        assert approved.generation_method == "hunyuan3d_v2.1"
        assert gate.is_approved


# ─── Test 2: Hunyuan3D fails → Trellis2 fallback ─────────────────────────────


class TestHunyuan3DFailsTrellis2Succeeds:
    """Req 10.4: Hunyuan3D fails → Trellis2 picks up."""

    @pytest.mark.asyncio
    async def test_hunyuan_fails_trellis2_succeeds(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon, tmp_path
    ):
        """When Hunyuan3D raises MeshGenerationError, Trellis2 takes over."""
        # Hunyuan3D fails
        hunyuan_gen._inner.generate = AsyncMock(return_value=None)

        # Trellis2 succeeds
        mesh_path = tmp_path / "trellis" / "table.glb"
        mesh_path.parent.mkdir(parents=True, exist_ok=True)
        _create_valid_glb(mesh_path)

        trellis_gen._inner.generate = AsyncMock(
            return_value=FakeGenerationResult(
                mesh_path=mesh_path, face_count=3000, vertex_count=1500
            )
        )
        trellis_gen._validate_mesh = MagicMock(return_value=None)

        result = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        assert result.generation_method == "trellis2"
        assert result.approved is False
        assert result.is_placeholder is False
        assert result.face_count == 3000


    @pytest.mark.asyncio
    async def test_trellis2_fallback_then_approval_gate(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon, tmp_path
    ):
        """Trellis2 fallback mesh still requires approval gate."""
        hunyuan_gen._inner.generate = AsyncMock(return_value=None)

        mesh_path = tmp_path / "trellis" / "table.glb"
        mesh_path.parent.mkdir(parents=True, exist_ok=True)
        _create_valid_glb(mesh_path)

        trellis_gen._inner.generate = AsyncMock(
            return_value=FakeGenerationResult(
                mesh_path=mesh_path, face_count=3000, vertex_count=1500
            )
        )
        trellis_gen._validate_mesh = MagicMock(return_value=None)

        mesh = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        gate = MeshApprovalGate()
        assert gate.should_skip(mesh) is False
        gate.present_for_approval(mesh)
        approved = gate.approve(mesh)

        assert approved.approved is True
        assert approved.generation_method == "trellis2"


# ─── Test 3: Both fail → placeholder auto-approved ────────────────────────────


class TestBothFailPlaceholderFallback:
    """Req 10.5: Both Hunyuan3D and Trellis2 fail → placeholder."""

    @pytest.mark.asyncio
    async def test_both_fail_placeholder_generated(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon
    ):
        """Both generators fail → placeholder is produced."""
        hunyuan_gen._inner.generate = AsyncMock(return_value=None)
        trellis_gen._inner.generate = AsyncMock(return_value=None)

        result = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        assert result.generation_method == "placeholder"
        assert result.is_placeholder is True


    @pytest.mark.asyncio
    async def test_placeholder_auto_approved(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon
    ):
        """Req 11.5: Placeholder auto-approves (skip gate)."""
        hunyuan_gen._inner.generate = AsyncMock(return_value=None)
        trellis_gen._inner.generate = AsyncMock(return_value=None)

        result = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        assert result.approved is True
        assert result.is_placeholder is True

        # Gate should recognize it as skippable
        gate = MeshApprovalGate()
        assert gate.should_skip(result) is True


# ─── Test 4: Fallback chain respects order ────────────────────────────────────


class TestFallbackChainOrder:
    """The chain MUST try Hunyuan3D first, then Trellis2, then placeholder."""

    @pytest.mark.asyncio
    async def test_order_hunyuan_first(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon, tmp_path
    ):
        """When Hunyuan3D succeeds, Trellis2 and placeholder are NOT called."""
        mesh_path = tmp_path / "hunyuan" / "table.glb"
        mesh_path.parent.mkdir(parents=True, exist_ok=True)
        _create_valid_glb(mesh_path)

        hunyuan_gen._inner.generate = AsyncMock(
            return_value=FakeGenerationResult(
                mesh_path=mesh_path, face_count=5000, vertex_count=2500
            )
        )
        hunyuan_gen._validate_mesh = MagicMock(return_value=None)
        trellis_gen._inner.generate = AsyncMock()

        result = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        assert result.generation_method == "hunyuan3d_v2.1"
        trellis_gen._inner.generate.assert_not_called()


    @pytest.mark.asyncio
    async def test_order_trellis_before_placeholder(
        self, hunyuan_gen, trellis_gen, placeholder_gen, object_canon, tmp_path
    ):
        """When Hunyuan3D fails but Trellis2 succeeds, placeholder not used."""
        hunyuan_gen._inner.generate = AsyncMock(return_value=None)

        mesh_path = tmp_path / "trellis" / "table.glb"
        mesh_path.parent.mkdir(parents=True, exist_ok=True)
        _create_valid_glb(mesh_path)

        trellis_gen._inner.generate = AsyncMock(
            return_value=FakeGenerationResult(
                mesh_path=mesh_path, face_count=3000, vertex_count=1500
            )
        )
        trellis_gen._validate_mesh = MagicMock(return_value=None)

        result = await run_fallback_chain(
            object_canon, hunyuan_gen, trellis_gen, placeholder_gen
        )

        assert result.generation_method == "trellis2"
        assert result.is_placeholder is False


# ─── Test 5: Placeholder auto-approves (skip gate) ────────────────────────────


class TestPlaceholderAutoApproval:
    """Req 11.5: MeshApprovalGate auto-approves placeholders."""

    def test_should_skip_returns_true_for_placeholder(self):
        """should_skip() is True for placeholder meshes."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="obj-001",
            mesh_path="/assets/placeholder.glb",
            generation_method="placeholder",
            face_count=12,
            vertex_count=8,
            approved=True,
            is_placeholder=True,
        )
        assert gate.should_skip(mesh) is True

    def test_present_placeholder_auto_approves_without_preview(self):
        """Placeholders are auto-approved; no turntable preview."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="obj-001",
            mesh_path="/assets/placeholder.glb",
            generation_method="placeholder",
            face_count=12,
            vertex_count=8,
            is_placeholder=True,
        )
        preview = gate.present_for_approval(mesh)

        assert preview is None
        assert gate.is_approved
        assert gate.history[0]["decision"] == "auto_approved"
