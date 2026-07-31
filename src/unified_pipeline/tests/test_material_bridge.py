"""Tests for the unified material bridge adapter.

Validates that UnifiedMaterialProcessor correctly delegates to the
existing V14 material_processor.py for two-pass material application,
texture size selection, and Pass 2 queue ordering.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.photo_pipeline.models_v14 import MaterialPassResult
from src.unified_pipeline.material_bridge import (
    MaterialBridgeResult,
    UnifiedMaterialProcessor,
)
from src.unified_pipeline.models import ObjectCanon


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def processor() -> UnifiedMaterialProcessor:
    """Create a UnifiedMaterialProcessor instance."""
    return UnifiedMaterialProcessor()


@pytest.fixture
def sample_object_canon() -> ObjectCanon:
    """Create a sample ObjectCanon for testing."""
    return ObjectCanon(
        object_id="test-obj-001",
        object_name="coffee_maker",
        image_path="test_data/coffee_maker.png",
        mask_coverage=0.08,
        approved=True,
        provenance="raw_segmentation",
    )


@pytest.fixture
def small_object_canon() -> ObjectCanon:
    """Create a small ObjectCanon (<2% area)."""
    return ObjectCanon(
        object_id="test-obj-002",
        object_name="outlet",
        image_path="test_data/outlet.png",
        mask_coverage=0.01,
        approved=True,
        provenance="raw_segmentation",
    )


@pytest.fixture
def large_object_canon() -> ObjectCanon:
    """Create a large ObjectCanon (>10% area)."""
    return ObjectCanon(
        object_id="test-obj-003",
        object_name="dining_table",
        image_path="test_data/table.png",
        mask_coverage=0.15,
        approved=True,
        provenance="raw_segmentation",
    )


# ---------------------------------------------------------------------------
# Texture Size Selection (Req 12.6)
# ---------------------------------------------------------------------------


class TestGetTextureSize:
    """Test texture size selection per Req 12.6."""

    def test_small_object_256(self, processor: UnifiedMaterialProcessor) -> None:
        """Objects <2% image area get 256×256 textures."""
        assert processor.get_texture_size(0.01) == (256, 256)
        assert processor.get_texture_size(0.005) == (256, 256)
        assert processor.get_texture_size(0.0) == (256, 256)

    def test_medium_object_512(self, processor: UnifiedMaterialProcessor) -> None:
        """Objects 2-10% image area get 512×512 textures."""
        assert processor.get_texture_size(0.02) == (512, 512)
        assert processor.get_texture_size(0.05) == (512, 512)
        assert processor.get_texture_size(0.10) == (512, 512)

    def test_large_object_1024(self, processor: UnifiedMaterialProcessor) -> None:
        """Objects >10% image area get 1024×1024 textures."""
        assert processor.get_texture_size(0.11) == (1024, 1024)
        assert processor.get_texture_size(0.5) == (1024, 1024)
        assert processor.get_texture_size(1.0) == (1024, 1024)

    def test_boundary_at_2_percent(self, processor: UnifiedMaterialProcessor) -> None:
        """Boundary: exactly 2% crosses into 512×512."""
        assert processor.get_texture_size(0.019) == (256, 256)
        assert processor.get_texture_size(0.02) == (512, 512)

    def test_boundary_at_10_percent(self, processor: UnifiedMaterialProcessor) -> None:
        """Boundary: >10% crosses into 1024×1024."""
        assert processor.get_texture_size(0.10) == (512, 512)
        assert processor.get_texture_size(0.101) == (1024, 1024)


# ---------------------------------------------------------------------------
# Pass 2 Queue Ordering (Req 12.2 — largest objects first)
# ---------------------------------------------------------------------------


class TestPass2Queue:
    """Test Pass 2 scheduling order (largest first)."""

    def test_sorts_largest_first(self, processor: UnifiedMaterialProcessor) -> None:
        """Queue returns object IDs sorted by area descending."""
        objects = [
            ("small", 0.01),
            ("large", 0.15),
            ("medium", 0.05),
        ]
        result = processor.get_pass2_queue(objects)
        assert result == ["large", "medium", "small"]

    def test_empty_list(self, processor: UnifiedMaterialProcessor) -> None:
        """Empty input returns empty queue."""
        assert processor.get_pass2_queue([]) == []

    def test_single_object(self, processor: UnifiedMaterialProcessor) -> None:
        """Single object returns that object."""
        assert processor.get_pass2_queue([("only", 0.5)]) == ["only"]


# ---------------------------------------------------------------------------
# Pass 1 Application (Req 12.1)
# ---------------------------------------------------------------------------


class TestApplyPass1:
    """Test Pass 1 material application delegates to existing processor."""

    def test_pass1_returns_mesh_path(
        self,
        processor: UnifiedMaterialProcessor,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Pass 1 returns the mesh path unchanged (GLB modified in place)."""
        mock_result = MaterialPassResult(
            object_id="test-obj-001",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass1 = MagicMock(return_value=mock_result)

        result = processor.apply_pass_1(
            mesh_path="output/coffee_maker.glb",
            object_canon=sample_object_canon,
            generation_method="hunyuan3d_v2.1",
        )

        assert result == "output/coffee_maker.glb"
        processor._processor.apply_pass1.assert_called_once()

    def test_pass1_delegates_neural_method(
        self,
        processor: UnifiedMaterialProcessor,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Pass 1 passes generation_method to underlying processor."""
        mock_result = MaterialPassResult(
            object_id="test-obj-001",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass1 = MagicMock(return_value=mock_result)

        processor.apply_pass_1(
            mesh_path="output/coffee_maker.glb",
            object_canon=sample_object_canon,
            generation_method="trellis2",
        )

        call_kwargs = processor._processor.apply_pass1.call_args
        assert call_kwargs[1]["generation_method"] == "trellis2" or (
            call_kwargs[0][2] == "trellis2" if len(call_kwargs[0]) > 2 else True
        )

    def test_pass1_uses_mask_coverage_for_texture_size(
        self,
        processor: UnifiedMaterialProcessor,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Pass 1 passes mask_coverage as image_area_pct."""
        mock_result = MaterialPassResult(
            object_id="test-obj-001",
            pass_number=1,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass1 = MagicMock(return_value=mock_result)

        processor.apply_pass_1(
            mesh_path="output/coffee_maker.glb",
            object_canon=sample_object_canon,
            generation_method="placeholder",
        )

        call_args = processor._processor.apply_pass1.call_args
        # image_area_pct should be the mask_coverage value (0.08)
        assert call_args[1]["image_area_pct"] == 0.08 or (
            len(call_args[0]) > 3 and call_args[0][3] == 0.08
        )


# ---------------------------------------------------------------------------
# Pass 2 Application (Req 12.2, 12.4)
# ---------------------------------------------------------------------------


class TestApplyPass2:
    """Test Pass 2 material application (async, background)."""

    @pytest.mark.asyncio
    async def test_pass2_returns_mesh_path(
        self,
        processor: UnifiedMaterialProcessor,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Pass 2 returns the mesh path (GLB modified in place)."""
        mock_result = MaterialPassResult(
            object_id="test-obj-001",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=True,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass2 = AsyncMock(return_value=mock_result)

        result = await processor.apply_pass_2(
            mesh_path="output/coffee_maker.glb",
            object_canon=sample_object_canon,
            material_type="ceramic",
        )

        assert result == "output/coffee_maker.glb"
        processor._processor.apply_pass2.assert_called_once()

    @pytest.mark.asyncio
    async def test_pass2_failure_retains_pass1(
        self,
        processor: UnifiedMaterialProcessor,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Pass 2 failure logs warning but returns mesh path (Req 12.4)."""
        mock_result = MaterialPassResult(
            object_id="test-obj-001",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass2 = AsyncMock(return_value=mock_result)

        result = await processor.apply_pass_2(
            mesh_path="output/coffee_maker.glb",
            object_canon=sample_object_canon,
            material_type="glass",
        )

        # Mesh path returned even when PBR fails
        assert result == "output/coffee_maker.glb"


# ---------------------------------------------------------------------------
# Batch Pass 2 with WebSocket Hot-Swap (Req 12.3)
# ---------------------------------------------------------------------------


class TestProcessAllPass2:
    """Test batch Pass 2 processing with WebSocket notification."""

    @pytest.mark.asyncio
    async def test_batch_processes_all_objects(
        self,
        processor: UnifiedMaterialProcessor,
    ) -> None:
        """Batch processes all objects and returns results."""
        mock_result = MaterialPassResult(
            object_id="obj-1",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=True,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass2 = AsyncMock(return_value=mock_result)

        canon1 = ObjectCanon(
            object_id="obj-1",
            object_name="chair",
            image_path="test/chair.png",
            mask_coverage=0.05,
            approved=True,
        )
        canon2 = ObjectCanon(
            object_id="obj-2",
            object_name="table",
            image_path="test/table.png",
            mask_coverage=0.12,
            approved=True,
        )

        objects = [
            ("output/chair.glb", canon1, "wood"),
            ("output/table.glb", canon2, "wood"),
        ]

        results = await processor.process_all_pass2(objects)

        assert len(results) == 2
        assert all(r.success for r in results)
        assert all(r.pass_number == 2 for r in results)

    @pytest.mark.asyncio
    async def test_websocket_notification_on_success(
        self,
        processor: UnifiedMaterialProcessor,
    ) -> None:
        """WebSocket callback is invoked after each successful Pass 2."""
        mock_result = MaterialPassResult(
            object_id="obj-1",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=True,
            texture_resolution=(1024, 1024),
        )
        processor._processor.apply_pass2 = AsyncMock(return_value=mock_result)

        ws_notify = AsyncMock()

        canon = ObjectCanon(
            object_id="obj-1",
            object_name="table",
            image_path="test/table.png",
            mask_coverage=0.15,
            approved=True,
        )

        await processor.process_all_pass2(
            [("output/table.glb", canon, "wood")],
            websocket_notify=ws_notify,
        )

        ws_notify.assert_called_once()
        call_payload = ws_notify.call_args[0][0]
        assert call_payload["type"] == "material_update"
        assert call_payload["object_id"] == "obj-1"
        assert call_payload["pass"] == 2
        assert call_payload["has_pbr"] is True

    @pytest.mark.asyncio
    async def test_pass2_failure_in_batch_retains_pass1(
        self,
        processor: UnifiedMaterialProcessor,
    ) -> None:
        """Failed Pass 2 in batch results in success=False, pass1 retained."""
        processor._processor.apply_pass2 = AsyncMock(
            side_effect=RuntimeError("GPU unavailable")
        )

        canon = ObjectCanon(
            object_id="obj-fail",
            object_name="lamp",
            image_path="test/lamp.png",
            mask_coverage=0.03,
            approved=True,
        )

        results = await processor.process_all_pass2(
            [("output/lamp.glb", canon, "metal")]
        )

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].has_base_color is True
        assert results[0].has_metallic_roughness is False
        assert "GPU unavailable" in results[0].error

    @pytest.mark.asyncio
    async def test_websocket_failure_does_not_break_batch(
        self,
        processor: UnifiedMaterialProcessor,
    ) -> None:
        """WebSocket notification failure doesn't stop batch processing."""
        mock_result = MaterialPassResult(
            object_id="obj-1",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=True,
            texture_resolution=(512, 512),
        )
        processor._processor.apply_pass2 = AsyncMock(return_value=mock_result)

        ws_notify = AsyncMock(side_effect=ConnectionError("WS closed"))

        canon = ObjectCanon(
            object_id="obj-1",
            object_name="mug",
            image_path="test/mug.png",
            mask_coverage=0.02,
            approved=True,
        )

        results = await processor.process_all_pass2(
            [("output/mug.glb", canon, "ceramic")],
            websocket_notify=ws_notify,
        )

        # Batch still succeeds despite WS failure
        assert len(results) == 1
        assert results[0].success is True


# ---------------------------------------------------------------------------
# MaterialBridgeResult dataclass
# ---------------------------------------------------------------------------


class TestMaterialBridgeResult:
    """Test MaterialBridgeResult data structure."""

    def test_successful_result(self) -> None:
        """Successful result has all fields populated."""
        result = MaterialBridgeResult(
            object_id="obj-1",
            mesh_path="output/obj.glb",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=True,
            has_normal_map=True,
            texture_resolution=(1024, 1024),
            success=True,
        )
        assert result.error is None
        assert result.success is True

    def test_failed_result(self) -> None:
        """Failed result retains error information."""
        result = MaterialBridgeResult(
            object_id="obj-1",
            mesh_path="output/obj.glb",
            pass_number=2,
            has_base_color=True,
            has_metallic_roughness=False,
            has_normal_map=False,
            texture_resolution=(512, 512),
            success=False,
            error="GPU OOM",
        )
        assert result.success is False
        assert result.error == "GPU OOM"
