"""Tests for DreamPreviewGenerator.

Tests the Dream Preview generation logic including:
- Successful single and multi-variant generation
- Timeout handling (15s target, 20s hard timeout)
- Provisional labeling (not spatial authority)
- User preference recording and retrieval
- ComfyUI failure handling (returns empty list)
- Session state management

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.unified_pipeline.dream_preview import (
    DreamPreviewGenerator,
    GENERATION_TIMEOUT_S,
    PROVISIONAL_LABEL,
)
from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)


@pytest.fixture
def mock_client():
    """Create a mock ComfyUI client with success-path defaults."""
    client = MagicMock(spec=ComfyUIClient)
    client.health_check = AsyncMock(return_value=True)
    client.submit_workflow = AsyncMock(return_value="prompt-123")
    client.wait_for_completion = AsyncMock(
        return_value={"outputs": {"7": {"images": [{"filename": "dream_preview.png"}]}}}
    )
    client.get_output_image = AsyncMock(
        return_value=Path("output/dream_previews/test-session/dream_preview_000.png")
    )
    return client


@pytest.fixture
def generator(mock_client, tmp_path):
    """Create a DreamPreviewGenerator with mocked client."""
    return DreamPreviewGenerator(
        comfyui_client=mock_client,
        output_dir=tmp_path / "dream_previews",
    )


class TestGenerate:
    """Tests for DreamPreviewGenerator.generate()."""

    @pytest.mark.asyncio
    async def test_single_variant_success(self, generator, mock_client):
        """Req 3.1: Generate a single Dream_Preview image successfully."""
        result = await generator.generate(
            prompt="warm kitchen, 1950s era, soft lighting",
            session_id="session-1",
            variant_count=1,
        )

        assert len(result) == 1
        assert "dream_preview" in result[0]
        mock_client.health_check.assert_awaited_once()
        mock_client.submit_workflow.assert_awaited_once()
        mock_client.wait_for_completion.assert_awaited_once()
        mock_client.get_output_image.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multiple_variants(self, generator, mock_client):
        """Req 3.5: Multiple Dream_Preview variants may be generated."""
        # Make get_output_image return different paths per call
        paths = [
            Path(f"output/dream_previews/s1/dream_preview_{i:03d}.png")
            for i in range(3)
        ]
        mock_client.get_output_image = AsyncMock(side_effect=paths)

        result = await generator.generate(
            prompt="cozy diner at night, neon lights",
            session_id="session-multi",
            variant_count=3,
        )

        assert len(result) == 3
        assert mock_client.submit_workflow.await_count == 3

    @pytest.mark.asyncio
    async def test_comfyui_unavailable_returns_empty(self, generator, mock_client):
        """Returns empty list when ComfyUI is not reachable."""
        mock_client.health_check = AsyncMock(return_value=False)

        result = await generator.generate(
            prompt="a dark alley",
            session_id="session-fail",
            variant_count=1,
        )

        assert result == []
        mock_client.submit_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_submission_error_returns_empty(self, generator, mock_client):
        """Gracefully handles ComfyUI submission failures."""
        mock_client.submit_workflow = AsyncMock(
            side_effect=ComfyUIError("Node not found")
        )

        result = await generator.generate(
            prompt="space station",
            session_id="session-err",
            variant_count=1,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty(self, generator, mock_client):
        """Req 3.1: Returns empty list on timeout (20s limit)."""
        mock_client.wait_for_completion = AsyncMock(
            side_effect=ComfyUITimeoutError("Timed out after 20s")
        )

        result = await generator.generate(
            prompt="detailed fantasy castle",
            session_id="session-timeout",
            variant_count=1,
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_partial_variants_on_failure(self, generator, mock_client):
        """Returns partial results when some variants fail."""
        # First succeeds, second fails
        mock_client.submit_workflow = AsyncMock(
            side_effect=[
                "prompt-1",
                ComfyUIError("VRAM OOM"),
            ]
        )

        result = await generator.generate(
            prompt="tropical beach",
            session_id="session-partial",
            variant_count=2,
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_variant_count_clamped_to_minimum_1(self, generator, mock_client):
        """variant_count < 1 is treated as 1."""
        result = await generator.generate(
            prompt="a room",
            session_id="session-clamp",
            variant_count=0,
        )

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_regeneration_resets_preference(self, generator, mock_client):
        """Req 3.4: Regeneration on steering feedback resets preference."""
        # First generation
        await generator.generate("room v1", session_id="s-regen", variant_count=1)
        generator.record_preference("s-regen", 0)

        # Second generation (user gave feedback)
        paths = [Path("output/dream_previews/s-regen/dream_preview_001.png")]
        mock_client.get_output_image = AsyncMock(side_effect=paths)

        await generator.generate("room v2 with warmer tones", session_id="s-regen", variant_count=1)

        # Preference should be reset
        session = generator._sessions["s-regen"]
        assert session["preferred_index"] is None

    @pytest.mark.asyncio
    async def test_session_state_accumulates_variants(self, generator, mock_client):
        """Multiple generate calls accumulate variants in session state."""
        await generator.generate("prompt 1", session_id="s-accum", variant_count=1)

        path2 = Path("output/dream_previews/s-accum/dream_preview_001.png")
        mock_client.get_output_image = AsyncMock(return_value=path2)

        await generator.generate("prompt 2", session_id="s-accum", variant_count=1)

        variants = generator.get_variants("s-accum")
        assert len(variants) == 2


class TestRecordPreference:
    """Tests for DreamPreviewGenerator.record_preference()."""

    @pytest.mark.asyncio
    async def test_record_valid_preference(self, generator, mock_client):
        """Req 3.6: Record which variant the user responded positively to."""
        paths = [
            Path(f"output/dream_previews/s-pref/dream_preview_{i:03d}.png")
            for i in range(3)
        ]
        mock_client.get_output_image = AsyncMock(side_effect=paths)

        await generator.generate("diner scene", session_id="s-pref", variant_count=3)
        generator.record_preference("s-pref", 1)

        assert generator._sessions["s-pref"]["preferred_index"] == 1

    def test_unknown_session_raises(self, generator):
        """Raises ValueError for unknown session."""
        with pytest.raises(ValueError, match="Unknown session"):
            generator.record_preference("nonexistent", 0)

    @pytest.mark.asyncio
    async def test_out_of_range_raises(self, generator, mock_client):
        """Raises ValueError for out-of-range variant_index."""
        await generator.generate("room", session_id="s-range", variant_count=1)

        with pytest.raises(ValueError, match="out of range"):
            generator.record_preference("s-range", 5)

    @pytest.mark.asyncio
    async def test_no_variants_raises(self, generator, mock_client):
        """Raises ValueError when no variants exist."""
        mock_client.health_check = AsyncMock(return_value=False)
        await generator.generate("room", session_id="s-empty", variant_count=1)

        with pytest.raises(ValueError, match="No variants available"):
            generator.record_preference("s-empty", 0)


class TestGetPreferred:
    """Tests for DreamPreviewGenerator.get_preferred()."""

    @pytest.mark.asyncio
    async def test_returns_preferred_variant(self, generator, mock_client):
        """Req 3.6: Returns the variant the user preferred."""
        paths = [
            Path(f"output/dream_previews/s-get/dream_preview_{i:03d}.png")
            for i in range(3)
        ]
        mock_client.get_output_image = AsyncMock(side_effect=paths)

        await generator.generate("scene", session_id="s-get", variant_count=3)
        generator.record_preference("s-get", 2)

        preferred = generator.get_preferred("s-get")
        assert "dream_preview_002" in preferred

    @pytest.mark.asyncio
    async def test_returns_first_when_no_preference(self, generator, mock_client):
        """Defaults to first variant when no preference recorded."""
        await generator.generate("scene", session_id="s-default", variant_count=1)

        preferred = generator.get_preferred("s-default")
        assert "dream_preview_000" in preferred

    def test_unknown_session_raises(self, generator):
        """Raises ValueError for unknown session."""
        with pytest.raises(ValueError, match="Unknown session"):
            generator.get_preferred("nonexistent")

    @pytest.mark.asyncio
    async def test_no_variants_raises(self, generator, mock_client):
        """Raises ValueError when no variants exist."""
        mock_client.health_check = AsyncMock(return_value=False)
        await generator.generate("room", session_id="s-novar", variant_count=1)

        with pytest.raises(ValueError, match="No variants available"):
            generator.get_preferred("s-novar")


class TestProvisionalLabel:
    """Tests for Req 3.3: Dream_Preview is NOT spatial authority."""

    def test_label_content(self, generator):
        """Label explicitly states provisional and not spatial authority."""
        label = generator.get_label()
        assert "PROVISIONAL" in label
        assert "not spatial authority" in label

    def test_label_matches_constant(self, generator):
        """Label matches the module-level constant."""
        assert generator.get_label() == PROVISIONAL_LABEL


class TestGetVariants:
    """Tests for DreamPreviewGenerator.get_variants()."""

    @pytest.mark.asyncio
    async def test_returns_all_variants(self, generator, mock_client):
        """Returns all generated variant paths."""
        paths = [
            Path(f"output/dream_previews/s-all/dream_preview_{i:03d}.png")
            for i in range(2)
        ]
        mock_client.get_output_image = AsyncMock(side_effect=paths)

        await generator.generate("scene", session_id="s-all", variant_count=2)

        variants = generator.get_variants("s-all")
        assert len(variants) == 2

    def test_unknown_session_returns_empty(self, generator):
        """Returns empty list for unknown session (no crash)."""
        assert generator.get_variants("unknown") == []
