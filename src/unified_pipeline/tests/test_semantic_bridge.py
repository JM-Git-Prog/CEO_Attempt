"""Tests for the unified semantic labeler adapter.

Validates that UnifiedSemanticLabeler correctly delegates to the
existing V14 semantic_labeler.py for Ollama vision analysis and
falls back to heuristic labeling on failure.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.photo_pipeline.models_v14 import SemanticLabel
from src.unified_pipeline.models import ObjectCanon
from src.unified_pipeline.semantic_bridge import (
    UnifiedSemanticLabeler,
    _validate_label_response,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def labeler() -> UnifiedSemanticLabeler:
    """Create an UnifiedSemanticLabeler instance."""
    return UnifiedSemanticLabeler()


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
def valid_semantic_label() -> SemanticLabel:
    """A valid SemanticLabel returned by the V14 labeler."""
    return SemanticLabel(
        semantic_label="stainless steel coffee maker",
        primary_material="metal",
        category="props",
        estimated_era="contemporary",
        condition="new",
        is_architectural=False,
    )


# ---------------------------------------------------------------------------
# Response Validation (Req 13.5)
# ---------------------------------------------------------------------------


class TestValidateLabelResponse:
    """Test label response validation logic."""

    def test_valid_response_passes(self) -> None:
        """A complete valid response passes validation."""
        response = {
            "semantic_label": "wooden dining chair",
            "primary_material": "wood",
            "category": "props",
            "estimated_era": "mid-century modern",
            "condition": "worn",
            "is_architectural": False,
        }
        assert _validate_label_response(response) is True

    def test_missing_field_fails(self) -> None:
        """Missing a required field fails validation."""
        response = {
            "semantic_label": "chair",
            "primary_material": "wood",
            "category": "props",
            # missing estimated_era, condition, is_architectural
        }
        assert _validate_label_response(response) is False

    def test_empty_semantic_label_fails(self) -> None:
        """Empty semantic_label fails validation."""
        response = {
            "semantic_label": "",
            "primary_material": "wood",
            "category": "props",
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": False,
        }
        assert _validate_label_response(response) is False

    def test_invalid_category_fails(self) -> None:
        """Category not in taxonomy fails validation."""
        response = {
            "semantic_label": "table",
            "primary_material": "wood",
            "category": "furniture",  # invalid
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": False,
        }
        assert _validate_label_response(response) is False

    def test_invalid_material_fails(self) -> None:
        """Material not in valid set fails validation."""
        response = {
            "semantic_label": "table",
            "primary_material": "stone",  # invalid
            "category": "props",
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": False,
        }
        assert _validate_label_response(response) is False

    def test_invalid_condition_fails(self) -> None:
        """Condition not in valid set fails validation."""
        response = {
            "semantic_label": "table",
            "primary_material": "wood",
            "category": "props",
            "estimated_era": "modern",
            "condition": "pristine",  # invalid
            "is_architectural": False,
        }
        assert _validate_label_response(response) is False

    def test_non_bool_is_architectural_fails(self) -> None:
        """is_architectural must be a bool."""
        response = {
            "semantic_label": "wall",
            "primary_material": "wood",
            "category": "architecture",
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": "yes",  # invalid — must be bool
        }
        assert _validate_label_response(response) is False

    def test_all_valid_categories_pass(self) -> None:
        """All five taxonomy categories pass validation."""
        for category in ("props", "architecture", "foliage", "hard-surface", "set-dressing"):
            response = {
                "semantic_label": "item",
                "primary_material": "wood",
                "category": category,
                "estimated_era": "modern",
                "condition": "new",
                "is_architectural": False,
            }
            assert _validate_label_response(response) is True

    def test_all_valid_materials_pass(self) -> None:
        """All six valid materials pass validation."""
        for material in ("wood", "metal", "glass", "fabric", "ceramic", "plastic"):
            response = {
                "semantic_label": "item",
                "primary_material": material,
                "category": "props",
                "estimated_era": "modern",
                "condition": "new",
                "is_architectural": False,
            }
            assert _validate_label_response(response) is True


# ---------------------------------------------------------------------------
# Label — Successful Ollama Path (Req 13.1, 13.2)
# ---------------------------------------------------------------------------


class TestLabelSuccess:
    """Test successful Ollama-based labeling."""

    @pytest.mark.asyncio
    async def test_label_returns_dict_from_ollama(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
        valid_semantic_label: SemanticLabel,
    ) -> None:
        """Successful Ollama labeling returns a dict with all required fields."""
        labeler._labeler.label = AsyncMock(return_value=valid_semantic_label)

        result = await labeler.label(sample_object_canon)

        assert result["semantic_label"] == "stainless steel coffee maker"
        assert result["primary_material"] == "metal"
        assert result["category"] == "props"
        assert result["estimated_era"] == "contemporary"
        assert result["condition"] == "new"
        assert result["is_architectural"] is False

    @pytest.mark.asyncio
    async def test_label_delegates_image_path(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
        valid_semantic_label: SemanticLabel,
    ) -> None:
        """Label passes the ObjectCanon's image_path to the underlying labeler."""
        labeler._labeler.label = AsyncMock(return_value=valid_semantic_label)

        await labeler.label(sample_object_canon)

        call_args = labeler._labeler.label.call_args
        assert call_args[0][0] == Path("test_data/coffee_maker.png")

    @pytest.mark.asyncio
    async def test_label_uses_10s_timeout(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
        valid_semantic_label: SemanticLabel,
    ) -> None:
        """Label uses 10-second timeout per Req 13.2."""
        labeler._labeler.label = AsyncMock(return_value=valid_semantic_label)

        await labeler.label(sample_object_canon)

        call_kwargs = labeler._labeler.label.call_args[1]
        assert call_kwargs["timeout_s"] == 10.0

    @pytest.mark.asyncio
    async def test_result_has_all_required_fields(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
        valid_semantic_label: SemanticLabel,
    ) -> None:
        """Result dict contains exactly the required fields."""
        labeler._labeler.label = AsyncMock(return_value=valid_semantic_label)

        result = await labeler.label(sample_object_canon)

        expected_keys = {
            "semantic_label",
            "primary_material",
            "category",
            "estimated_era",
            "condition",
            "is_architectural",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Label — Fallback on Failure (Req 13.3)
# ---------------------------------------------------------------------------


class TestLabelFallback:
    """Test heuristic fallback when Ollama fails."""

    @pytest.mark.asyncio
    async def test_ollama_exception_triggers_fallback(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Ollama exceptions trigger heuristic fallback."""
        labeler._labeler.label = AsyncMock(
            side_effect=RuntimeError("Ollama unavailable")
        )
        # Mock _read_png_dimensions since test image doesn't exist
        with patch.object(
            type(labeler._labeler),
            "_read_png_dimensions",
            staticmethod(lambda p: (200, 200)),
        ):
            result = await labeler.label(sample_object_canon)

        # Fallback still produces a valid response
        assert _validate_label_response(result) is True

    @pytest.mark.asyncio
    async def test_fallback_produces_valid_dict(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Fallback response has all required fields with valid values."""
        labeler._labeler.label = AsyncMock(
            side_effect=TimeoutError("Ollama timeout")
        )
        with patch.object(
            type(labeler._labeler),
            "_read_png_dimensions",
            staticmethod(lambda p: (300, 300)),
        ):
            result = await labeler.label(sample_object_canon)

        assert result["semantic_label"] != ""
        assert result["primary_material"] in (
            "wood", "metal", "glass", "fabric", "ceramic", "plastic"
        )
        assert result["category"] in (
            "props", "architecture", "foliage", "hard-surface", "set-dressing"
        )
        assert result["estimated_era"] != ""
        assert result["condition"] in ("new", "worn", "broken")
        assert isinstance(result["is_architectural"], bool)

    @pytest.mark.asyncio
    async def test_fallback_when_image_unreadable(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
    ) -> None:
        """Fallback still works when image file cannot be read."""
        labeler._labeler.label = AsyncMock(
            side_effect=OSError("file not found")
        )
        with patch.object(
            type(labeler._labeler),
            "_read_png_dimensions",
            staticmethod(MagicMock(side_effect=FileNotFoundError)),
        ):
            result = await labeler.label(sample_object_canon)

        # Should still return a valid response using defaults
        assert _validate_label_response(result) is True

    @pytest.mark.asyncio
    async def test_large_image_gets_furniture_label(
        self,
        labeler: UnifiedSemanticLabeler,
    ) -> None:
        """Large object (>50000 area, rectangular) gets 'furniture item' fallback."""
        canon = ObjectCanon(
            object_id="big-table",
            object_name="table",
            image_path="test_data/table.png",
            mask_coverage=1.0,  # 100% coverage
            approved=True,
        )
        labeler._labeler.label = AsyncMock(
            side_effect=RuntimeError("Ollama down")
        )
        # 300x300 image with 100% mask = 90000 area, aspect = 1.0
        with patch.object(
            type(labeler._labeler),
            "_read_png_dimensions",
            staticmethod(lambda p: (300, 300)),
        ):
            result = await labeler.label(canon)

        assert result["semantic_label"] == "furniture item"
        assert result["primary_material"] == "wood"
        assert result["category"] == "props"

    @pytest.mark.asyncio
    async def test_small_image_gets_decorative_label(
        self,
        labeler: UnifiedSemanticLabeler,
    ) -> None:
        """Small object (<5000 area) gets 'small decorative object' fallback."""
        canon = ObjectCanon(
            object_id="tiny-vase",
            object_name="vase",
            image_path="test_data/vase.png",
            mask_coverage=0.01,
            approved=True,
        )
        labeler._labeler.label = AsyncMock(
            side_effect=RuntimeError("Ollama down")
        )
        # 50x50 image with 1% mask coverage = 25 area
        with patch.object(
            type(labeler._labeler),
            "_read_png_dimensions",
            staticmethod(lambda p: (50, 50)),
        ):
            result = await labeler.label(canon)

        assert result["semantic_label"] == "small decorative object"
        assert result["primary_material"] == "ceramic"
        assert result["category"] == "set-dressing"

    @pytest.mark.asyncio
    async def test_tall_narrow_image_gets_architectural_label(
        self,
        labeler: UnifiedSemanticLabeler,
    ) -> None:
        """Tall+narrow object (aspect < 0.5) gets architectural fallback."""
        canon = ObjectCanon(
            object_id="column-001",
            object_name="column",
            image_path="test_data/column.png",
            mask_coverage=0.5,
            approved=True,
        )
        labeler._labeler.label = AsyncMock(
            side_effect=RuntimeError("Ollama down")
        )
        # 100x400 image = aspect 0.25, area = 100*400*0.5 = 20000
        with patch.object(
            type(labeler._labeler),
            "_read_png_dimensions",
            staticmethod(lambda p: (100, 400)),
        ):
            result = await labeler.label(canon)

        assert result["semantic_label"] == "structural element"
        assert result["is_architectural"] is True
        assert result["category"] == "architecture"


# ---------------------------------------------------------------------------
# Adapter Interface (Req 13.4 — determines warehouse, physics, filename)
# ---------------------------------------------------------------------------


class TestAdapterInterface:
    """Test the adapter provides the interface needed by downstream consumers."""

    @pytest.mark.asyncio
    async def test_result_usable_for_warehouse_category(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
        valid_semantic_label: SemanticLabel,
    ) -> None:
        """Result 'category' field maps to warehouse directory (Req 13.4)."""
        labeler._labeler.label = AsyncMock(return_value=valid_semantic_label)

        result = await labeler.label(sample_object_canon)

        # Category should map to a warehouse subdirectory
        warehouse_dirs = {
            "props": "assets/props/",
            "architecture": "assets/architecture/",
            "foliage": "assets/foliage/",
            "hard-surface": "assets/hard-surface/",
            "set-dressing": "assets/set-dressing/",
        }
        assert result["category"] in warehouse_dirs

    @pytest.mark.asyncio
    async def test_result_usable_for_physics_density(
        self,
        labeler: UnifiedSemanticLabeler,
        sample_object_canon: ObjectCanon,
        valid_semantic_label: SemanticLabel,
    ) -> None:
        """Result 'primary_material' maps to density for physics (Req 13.4)."""
        labeler._labeler.label = AsyncMock(return_value=valid_semantic_label)

        result = await labeler.label(sample_object_canon)

        # Material maps to density kg/m³ (from physics classifier)
        density_table = {
            "wood": 600,
            "metal": 7800,
            "glass": 2500,
            "fabric": 200,
            "ceramic": 2300,
            "plastic": 950,
        }
        assert result["primary_material"] in density_table

    def test_constructor_accepts_custom_url(self) -> None:
        """Constructor accepts a custom Ollama URL."""
        labeler = UnifiedSemanticLabeler(ollama_url="http://custom:9999")
        assert labeler._labeler._ollama_url == "http://custom:9999"
