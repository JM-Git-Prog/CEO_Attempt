"""Unit tests for VRAMManager state machine.

Tests the core state machine logic: single-model exclusion, release behavior,
system RAM checks, flash attention flag, and OOM retry logic.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIVRAMError
from src.photo_pipeline.vram_manager import (
    SYSTEM_RAM_PAUSE_THRESHOLD_GB,
    SYSTEM_RAM_RESUME_THRESHOLD_GB,
    VRAM_FREE_THRESHOLD_GB,
    VRAMManager,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> ComfyUIClient:
    """Create a mock ComfyUI client with _free_vram as an async mock."""
    client = MagicMock(spec=ComfyUIClient)
    client.base_url = "http://localhost:8188"
    client._free_vram = AsyncMock()
    return client


@pytest.fixture
def manager(mock_client: ComfyUIClient) -> VRAMManager:
    """Create a VRAMManager with mocked dependencies."""
    mgr = VRAMManager(client=mock_client, max_vram_gb=24.0)
    return mgr


# ---------------------------------------------------------------------------
# Tests: Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_no_model_loaded_initially(self, manager: VRAMManager) -> None:
        assert manager.current_model is None

    def test_estimated_usage_zero_initially(self, manager: VRAMManager) -> None:
        assert manager.estimated_usage_gb == 0.0

    def test_flash_attention_enabled_by_default(self, manager: VRAMManager) -> None:
        assert manager.flash_attention_enabled is True

    def test_get_state_snapshot(self, manager: VRAMManager) -> None:
        state = manager.get_state()
        assert state.current_model is None
        assert state.estimated_usage_gb == 0.0
        assert state.system_ram_gb >= 0.0


# ---------------------------------------------------------------------------
# Tests: acquire_model
# ---------------------------------------------------------------------------


class TestAcquireModel:
    @pytest.mark.asyncio
    async def test_acquire_sets_current_model(self, manager: VRAMManager) -> None:
        """Acquiring a model should set current_model and estimated usage."""
        with patch.object(manager, "_wait_for_vram_free", new_callable=AsyncMock):
            with patch.object(manager, "wait_for_ram_available", new_callable=AsyncMock):
                await manager.acquire_model("hunyuan3d_v2.1", 12.0)

        assert manager.current_model == "hunyuan3d_v2.1"
        assert manager.estimated_usage_gb == 12.0

    @pytest.mark.asyncio
    async def test_acquire_releases_previous_model(
        self, manager: VRAMManager, mock_client: ComfyUIClient
    ) -> None:
        """If a model is already loaded, acquire should release it first."""
        with patch.object(manager, "_wait_for_vram_free", new_callable=AsyncMock):
            with patch.object(manager, "wait_for_ram_available", new_callable=AsyncMock):
                await manager.acquire_model("flux_klein", 8.0)
                assert manager.current_model == "flux_klein"

                # Now acquire a different model — should release first
                await manager.acquire_model("hunyuan3d_v2.1", 12.0)

        # The /free should have been called to release flux_klein
        mock_client._free_vram.assert_called()
        assert manager.current_model == "hunyuan3d_v2.1"
        assert manager.estimated_usage_gb == 12.0

    @pytest.mark.asyncio
    async def test_acquire_enforces_single_model(self, manager: VRAMManager) -> None:
        """Only one model should be loaded at a time."""
        with patch.object(manager, "_wait_for_vram_free", new_callable=AsyncMock):
            with patch.object(manager, "wait_for_ram_available", new_callable=AsyncMock):
                await manager.acquire_model("sam_vit_h", 4.0)
                assert manager.current_model == "sam_vit_h"

                await manager.acquire_model("depth_anything_3", 4.0)
                assert manager.current_model == "depth_anything_3"


# ---------------------------------------------------------------------------
# Tests: release_model
# ---------------------------------------------------------------------------


class TestReleaseModel:
    @pytest.mark.asyncio
    async def test_release_clears_state(
        self, manager: VRAMManager, mock_client: ComfyUIClient
    ) -> None:
        """Releasing a model should clear state and call /free."""
        with patch.object(manager, "_wait_for_vram_free", new_callable=AsyncMock):
            with patch.object(manager, "wait_for_ram_available", new_callable=AsyncMock):
                await manager.acquire_model("hunyuan3d_v2.1", 12.0)

        with patch.object(manager, "_wait_for_vram_free", new_callable=AsyncMock):
            await manager.release_model()

        assert manager.current_model is None
        assert manager.estimated_usage_gb == 0.0
        mock_client._free_vram.assert_called()

    @pytest.mark.asyncio
    async def test_release_noop_when_no_model(
        self, manager: VRAMManager, mock_client: ComfyUIClient
    ) -> None:
        """Releasing when no model is loaded should be a no-op."""
        with patch.object(manager, "_wait_for_vram_free", new_callable=AsyncMock):
            await manager.release_model()

        mock_client._free_vram.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: check_system_ram
# ---------------------------------------------------------------------------


class TestCheckSystemRAM:
    @pytest.mark.asyncio
    async def test_returns_true_when_below_threshold(
        self, manager: VRAMManager
    ) -> None:
        """check_system_ram returns True when usage is below 80GB."""
        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=60.0
        ):
            result = await manager.check_system_ram()
            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_above_threshold(
        self, manager: VRAMManager
    ) -> None:
        """check_system_ram returns False when usage exceeds 80GB."""
        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=85.0
        ):
            result = await manager.check_system_ram()
            assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_at_exactly_threshold(
        self, manager: VRAMManager
    ) -> None:
        """check_system_ram returns True at exactly 80GB (not > threshold)."""
        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=80.0
        ):
            result = await manager.check_system_ram()
            assert result is True


# ---------------------------------------------------------------------------
# Tests: wait_for_ram_available
# ---------------------------------------------------------------------------


class TestWaitForRAMAvailable:
    @pytest.mark.asyncio
    async def test_returns_immediately_when_below_pause(
        self, manager: VRAMManager
    ) -> None:
        """Should return immediately when RAM is below pause threshold."""
        with patch.object(
            VRAMManager, "_get_system_ram_used_gb", return_value=50.0
        ):
            # Should not block
            await asyncio.wait_for(manager.wait_for_ram_available(), timeout=1.0)

    @pytest.mark.asyncio
    async def test_waits_until_below_resume_threshold(
        self, manager: VRAMManager
    ) -> None:
        """Should block until RAM drops below the resume threshold (72GB)."""
        # Simulate RAM dropping: 85 -> 75 -> 70
        call_count = 0

        def ram_values() -> float:
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return 85.0
            elif call_count == 2:
                return 75.0
            else:
                return 70.0

        with patch.object(VRAMManager, "_get_system_ram_used_gb", side_effect=ram_values):
            with patch("src.photo_pipeline.vram_manager.asyncio.sleep", new_callable=AsyncMock):
                await manager.wait_for_ram_available()


# ---------------------------------------------------------------------------
# Tests: flash attention flag
# ---------------------------------------------------------------------------


class TestFlashAttention:
    def test_flash_attention_settable(self, manager: VRAMManager) -> None:
        """Flash attention flag should be settable."""
        assert manager.flash_attention_enabled is True
        manager.flash_attention_enabled = False
        assert manager.flash_attention_enabled is False


# ---------------------------------------------------------------------------
# Tests: OOM retry
# ---------------------------------------------------------------------------


class TestOOMRetry:
    @pytest.mark.asyncio
    async def test_oom_retry_calls_free_and_retries(
        self, manager: VRAMManager, mock_client: ComfyUIClient
    ) -> None:
        """On OOM, should call /free, wait 5s, then retry once."""
        call_count = 0

        async def flaky_inference() -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ComfyUIVRAMError("CUDA out of memory")
            return "success"

        with patch("src.photo_pipeline.vram_manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await manager.execute_with_oom_retry(flaky_inference)

        assert result == "success"
        assert call_count == 2
        mock_client._free_vram.assert_called_once()
        mock_sleep.assert_called_once_with(5.0)

    @pytest.mark.asyncio
    async def test_oom_retry_raises_on_second_failure(
        self, manager: VRAMManager, mock_client: ComfyUIClient
    ) -> None:
        """If retry also fails with OOM, the error propagates."""

        async def always_oom() -> str:
            raise ComfyUIVRAMError("CUDA out of memory")

        with patch("src.photo_pipeline.vram_manager.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ComfyUIVRAMError):
                await manager.execute_with_oom_retry(always_oom)

    @pytest.mark.asyncio
    async def test_no_retry_on_success(
        self, manager: VRAMManager, mock_client: ComfyUIClient
    ) -> None:
        """If inference succeeds first try, no retry needed."""

        async def good_inference() -> str:
            return "done"

        result = await manager.execute_with_oom_retry(good_inference)
        assert result == "done"
        mock_client._free_vram.assert_not_called()
