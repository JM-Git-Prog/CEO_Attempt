"""Unit tests for SemanticLabeler with Ollama integration and heuristic fallback.

Tests the fallback_label heuristic rules, JSON parsing, response validation,
and the async label method with mocked Ollama responses.

Requirements: 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.photo_pipeline.models_v14 import (
    VALID_CATEGORIES,
    VALID_MATERIALS,
    SemanticLabel,
)
from src.photo_pipeline.stages.semantic_labeler import SemanticLabeler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def labeler() -> SemanticLabeler:
    """Create a SemanticLabeler instance with default settings."""
    return SemanticLabeler()


# ---------------------------------------------------------------------------
# Heuristic fallback tests
# ---------------------------------------------------------------------------


class TestFallbackLabel:
    """Tests for the fallback_label heuristic method."""

    def test_large_rectangular_produces_furniture(self, labeler: SemanticLabeler) -> None:
        """Large area + rectangular aspect → props/wood/furniture."""
        # area > 50000, 0.5 < aspect (300/200=1.5) < 2.0
        result = labeler.fallback_label(width=300, height=200, area_px=60000)
        assert result.category == "props"
        assert result.primary_material == "wood"
        assert result.semantic_label == "furniture item"
        assert result.is_architectural is False

    def test_small_uniform_produces_decorative(self, labeler: SemanticLabeler) -> None:
        """Small area (< 5000) → set-dressing/ceramic/decorative."""
        result = labeler.fallback_label(width=50, height=50, area_px=2500)
        assert result.category == "set-dressing"
        assert result.primary_material == "ceramic"
        assert result.semantic_label == "small decorative object"
        assert result.is_architectural is False

    def test_tall_narrow_produces_architectural(self, labeler: SemanticLabeler) -> None:
        """Tall + narrow (aspect < 0.5) → architecture/wood/structural."""
        # aspect = 30/200 = 0.15 < 0.5
        result = labeler.fallback_label(width=30, height=200, area_px=6000)
        assert result.category == "architecture"
        assert result.primary_material == "wood"
        assert result.semantic_label == "structural element"
        assert result.is_architectural is True

    def test_default_produces_unidentified(self, labeler: SemanticLabeler) -> None:
        """Medium area, non-rectangular, non-tall → default props/plastic."""
        # area=10000 (not <5000, not >50000), aspect=100/50=2.0 (not <0.5)
        # aspect 2.0 is not strictly < 2.0, so large+rect won't match
        result = labeler.fallback_label(width=100, height=50, area_px=10000)
        assert result.category == "props"
        assert result.primary_material == "plastic"
        assert result.semantic_label == "unidentified object"
        assert result.is_architectural is False

    def test_fallback_always_produces_valid_category(self, labeler: SemanticLabeler) -> None:
        """All fallback results have valid category and material."""
        test_cases = [
            (300, 200, 60000),  # large rectangular
            (50, 50, 2500),    # small uniform
            (30, 200, 6000),   # tall narrow
            (100, 50, 10000),  # default
            (1, 1, 1),         # edge: tiny
            (10000, 10000, 100000000),  # edge: huge
        ]
        for w, h, a in test_cases:
            result = labeler.fallback_label(width=w, height=h, area_px=a)
            assert result.category in VALID_CATEGORIES
            assert result.primary_material in VALID_MATERIALS

    def test_fallback_zero_height_uses_default_aspect(self, labeler: SemanticLabeler) -> None:
        """Zero height should not crash (aspect defaults to 1.0)."""
        result = labeler.fallback_label(width=100, height=0, area_px=10000)
        # aspect = 1.0 (guarded), area 10000 not in any special branch
        assert result.category in VALID_CATEGORIES
        assert result.primary_material in VALID_MATERIALS


# ---------------------------------------------------------------------------
# JSON parsing tests
# ---------------------------------------------------------------------------


class TestParseJsonResponse:
    """Tests for _parse_json_response static method."""

    def test_direct_json(self) -> None:
        """Direct JSON object parses correctly."""
        content = json.dumps({"semantic_label": "chair", "category": "props"})
        result = SemanticLabeler._parse_json_response(content)
        assert result == {"semantic_label": "chair", "category": "props"}

    def test_markdown_wrapped_json(self) -> None:
        """JSON wrapped in markdown code blocks parses correctly."""
        content = '```json\n{"semantic_label": "table"}\n```'
        result = SemanticLabeler._parse_json_response(content)
        assert result == {"semantic_label": "table"}

    def test_json_with_preamble(self) -> None:
        """JSON preceded by text can still be found."""
        content = 'Here is the result:\n{"semantic_label": "lamp", "category": "props"}'
        result = SemanticLabeler._parse_json_response(content)
        assert result is not None
        assert result["semantic_label"] == "lamp"

    def test_invalid_content_returns_none(self) -> None:
        """Non-JSON content returns None."""
        result = SemanticLabeler._parse_json_response("This is not JSON at all")
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        """Empty string returns None."""
        result = SemanticLabeler._parse_json_response("")
        assert result is None


# ---------------------------------------------------------------------------
# Response validation tests
# ---------------------------------------------------------------------------


class TestValidateResponse:
    """Tests for _validate_response static method."""

    def test_valid_complete_response(self) -> None:
        """Complete valid response produces a SemanticLabel."""
        parsed = {
            "semantic_label": "wooden dining chair",
            "primary_material": "wood",
            "category": "props",
            "estimated_era": "mid-century modern",
            "condition": "worn",
            "is_architectural": False,
        }
        result = SemanticLabeler._validate_response(parsed)
        assert result is not None
        assert result.semantic_label == "wooden dining chair"
        assert result.primary_material == "wood"
        assert result.category == "props"
        assert result.estimated_era == "mid-century modern"
        assert result.condition == "worn"
        assert result.is_architectural is False

    def test_missing_field_returns_none(self) -> None:
        """Missing required field returns None."""
        parsed = {
            "semantic_label": "chair",
            "primary_material": "wood",
            # missing category, estimated_era, condition, is_architectural
        }
        result = SemanticLabeler._validate_response(parsed)
        assert result is None

    def test_invalid_material_returns_none(self) -> None:
        """Invalid material value returns None."""
        parsed = {
            "semantic_label": "chair",
            "primary_material": "titanium",  # not valid
            "category": "props",
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": False,
        }
        result = SemanticLabeler._validate_response(parsed)
        assert result is None

    def test_invalid_category_returns_none(self) -> None:
        """Invalid category value returns None."""
        parsed = {
            "semantic_label": "chair",
            "primary_material": "wood",
            "category": "vehicles",  # not valid
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": False,
        }
        result = SemanticLabeler._validate_response(parsed)
        assert result is None

    def test_string_is_architectural_coercion(self) -> None:
        """String 'true'/'false' for is_architectural gets coerced."""
        parsed = {
            "semantic_label": "door frame",
            "primary_material": "wood",
            "category": "architecture",
            "estimated_era": "victorian",
            "condition": "worn",
            "is_architectural": "true",
        }
        result = SemanticLabeler._validate_response(parsed)
        assert result is not None
        assert result.is_architectural is True

    def test_empty_semantic_label_returns_none(self) -> None:
        """Empty semantic_label string returns None."""
        parsed = {
            "semantic_label": "",
            "primary_material": "wood",
            "category": "props",
            "estimated_era": "modern",
            "condition": "new",
            "is_architectural": False,
        }
        result = SemanticLabeler._validate_response(parsed)
        assert result is None


# ---------------------------------------------------------------------------
# Async label method tests (mocked Ollama)
# ---------------------------------------------------------------------------


class TestLabelAsync:
    """Tests for the async label method with mocked HTTP calls."""

    @pytest.mark.asyncio
    async def test_successful_ollama_call(self, labeler: SemanticLabeler, tmp_path: Path) -> None:
        """Successful Ollama call returns parsed SemanticLabel."""
        # Create a minimal valid PNG file (8-byte signature + IHDR chunk)
        png_data = self._make_minimal_png(200, 150)
        png_path = tmp_path / "object.png"
        png_path.write_bytes(png_data)

        # Mock the httpx response
        ollama_response = {
            "message": {
                "content": json.dumps({
                    "semantic_label": "wooden dining table",
                    "primary_material": "wood",
                    "category": "props",
                    "estimated_era": "mid-century modern",
                    "condition": "worn",
                    "is_architectural": False,
                })
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = ollama_response
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await labeler.label(png_path)

        assert result.semantic_label == "wooden dining table"
        assert result.primary_material == "wood"
        assert result.category == "props"

    @pytest.mark.asyncio
    async def test_timeout_falls_back(self, labeler: SemanticLabeler, tmp_path: Path) -> None:
        """Timeout from Ollama triggers heuristic fallback."""
        import httpx as httpx_module

        png_data = self._make_minimal_png(300, 200)
        png_path = tmp_path / "object.png"
        png_path.write_bytes(png_data)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx_module.TimeoutException("timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await labeler.label(png_path, timeout_s=10.0)

        # Should get a valid fallback label
        assert result.category in VALID_CATEGORIES
        assert result.primary_material in VALID_MATERIALS

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self, labeler: SemanticLabeler, tmp_path: Path) -> None:
        """Unparseable JSON response triggers fallback."""
        png_data = self._make_minimal_png(100, 100)
        png_path = tmp_path / "object.png"
        png_path.write_bytes(png_data)

        ollama_response = {
            "message": {
                "content": "I cannot analyze this image properly."
            }
        }

        mock_response = MagicMock()
        mock_response.json.return_value = ollama_response
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await labeler.label(png_path)

        assert result.category in VALID_CATEGORIES
        assert result.primary_material in VALID_MATERIALS

    @staticmethod
    def _make_minimal_png(width: int, height: int) -> bytes:
        """Create a minimal valid PNG file with given dimensions.

        Creates just enough structure for the PNG header reader to work:
        8-byte signature + 4-byte length + 4-byte type + 4-byte width + 4-byte height.
        """
        # PNG signature
        signature = b"\x89PNG\r\n\x1a\n"
        # IHDR chunk: length (13 bytes), type, width, height, rest of IHDR
        chunk_length = (13).to_bytes(4, "big")
        chunk_type = b"IHDR"
        w_bytes = width.to_bytes(4, "big")
        h_bytes = height.to_bytes(4, "big")
        # bit depth, color type, compression, filter, interlace
        ihdr_rest = b"\x08\x06\x00\x00\x00"
        # CRC (dummy, not validated by our reader)
        crc = b"\x00\x00\x00\x00"

        return signature + chunk_length + chunk_type + w_bytes + h_bytes + ihdr_rest + crc
