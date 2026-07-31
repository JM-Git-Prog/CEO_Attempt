"""Tests for the unified VRAM bridge adapter.

Verifies the adapter interface, exclusion rules, stage ordering,
OOM recovery flow, and system RAM checks.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIVRAMError
from src.unified_pipeline.vram_bridge import (
    OOMFallbackResult,
    PipelineStage,
    STAGE_ORDER,
    UnifiedVRAMManager,
    VRAMBridgeState,
    VRAMExclusionError,
    VRAMStageOrderError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> ComfyUIClient:
    """Create a mock ComfyUI client."""
    client = MagicMock(spec=ComfyUIClient)
    client.base_url = "http://localhost:8188"
    client._free_vram = AsyncMock()
    return client


@pytest.fixture
def vram_manager(mock_client: ComfyUIClient) -> UnifiedVRAMManager:
    """Create a UnifiedVRAMManager with mocked client."""
    with patch("src.unified_pipeline.vram_bridge.VRAMManager") as MockVRAM:
        instance = MockVRAM.return_value
        instance.flash_attention_enabled = True
        instance.acquire_model = AsyncMock()
        instance.release_model = AsyncMock()
        instance.hard_release = AsyncMock()
        instance.check_system_ram = AsyncMock(return_value=True)
        instance.wait_for_ram_available = AsyncMock()
        instance.execute_with_oom_retry = AsyncMock(return_value="test_result")
        instance._wait_for_vram_free = AsyncMock()
        instance.get_state = MagicMock(
            return_value=MagicMock(
                estimated_usage_gb=0.0,
                system_ram_gb=32.0,
            )
        )

        manager = UnifiedVRAMManager(mock_client)
        # Replace the internal _manager with our mock instance
        manager._manager = instance
        return manager


# ---------------------------------------------------------------------------
# Test: Basic interface
# ---------------------------------------------------------------------------


class TestBasicInterface:
    """Test the basic acquire/release interface."""

    @pytest.mark.asyncio
    async def test_acquire_via_context_manager(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Context manager acquires and releases VRAM."""
        async with vram_manager.acquire_vram(PipelineStage.SAM):
            assert vram_manager.current_stage == PipelineStage.SAM

        # After context exit, stage should be None (released)
        assert vram_manager.current_stage is None

    @pytest.mark.asyncio
    async def test_acquire_explicit(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Explicit acquire/release works correctly."""
        await vram_manager.acquire_vram_explicit(PipelineStage.FLUX)
        assert vram_manager.current_stage == PipelineStage.FLUX

        await vram_manager.release_vram()
        assert vram_manager.current_stage is None

    @pytest.mark.asyncio
    async def test_release_when_idle_is_noop(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Releasing when nothing is held does nothing."""
        await vram_manager.release_vram()
        assert vram_manager.current_stage is None

    @pytest.mark.asyncio
    async def test_wait_for_free(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """wait_for_free delegates to underlying VRAM manager."""
        await vram_manager.wait_for_free(threshold_gb=4.0)
        vram_manager._manager._wait_for_vram_free.assert_called_once()

    def test_get_state_snapshot(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """get_state returns a VRAMBridgeState."""
        state = vram_manager.get_state()
        assert isinstance(state, VRAMBridgeState)
        assert state.current_stage is None
        assert state.flash_attention is True
        assert state.stage_order_position == -1

    def test_flash_attention_property(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Flash attention is enabled by default (Req 15.4)."""
        assert vram_manager.flash_attention_enabled is True


# ---------------------------------------------------------------------------
# Test: Mutual exclusion (Req 15.1)
# ---------------------------------------------------------------------------


class TestExclusionRules:
    """FLUX and Hunyuan3D must never coexist."""

    @pytest.mark.asyncio
    async def test_flux_then_hunyuan3d_sequential_allowed(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Sequential FLUX → release → Hunyuan3D is allowed."""
        await vram_manager.acquire_vram_explicit(PipelineStage.FLUX)
        await vram_manager.release_vram()

        # Reset stage order for new object cycle
        vram_manager.reset_stage_order()
        await vram_manager.acquire_vram_explicit(PipelineStage.HUNYUAN3D)
        assert vram_manager.current_stage == PipelineStage.HUNYUAN3D

    @pytest.mark.asyncio
    async def test_flux_and_hunyuan3d_simultaneous_raises(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Attempting FLUX + Hunyuan3D simultaneously raises VRAMExclusionError."""
        # Acquire FLUX
        vram_manager._current_stage = PipelineStage.FLUX

        with pytest.raises(VRAMExclusionError, match="must never coexist"):
            await vram_manager.acquire_vram_explicit(PipelineStage.HUNYUAN3D)

    @pytest.mark.asyncio
    async def test_flux_and_trellis2_simultaneous_raises(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """FLUX + Trellis2 also excluded."""
        vram_manager._current_stage = PipelineStage.FLUX

        with pytest.raises(VRAMExclusionError):
            await vram_manager.acquire_vram_explicit(PipelineStage.TRELLIS2)


# ---------------------------------------------------------------------------
# Test: Stage ordering (Req 15.3)
# ---------------------------------------------------------------------------


class TestStageOrder:
    """Fixed stage order: SAM → FLUX → DA3 → Hunyuan3D."""

    def test_stage_order_forward_valid(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Forward progression through stages is valid."""
        assert vram_manager.validate_stage_order(PipelineStage.SAM)
        vram_manager._stage_order_position = 0

        assert vram_manager.validate_stage_order(PipelineStage.FLUX)
        vram_manager._stage_order_position = 1

        assert vram_manager.validate_stage_order(PipelineStage.DEPTH_ANYTHING_3)
        vram_manager._stage_order_position = 2

        assert vram_manager.validate_stage_order(PipelineStage.HUNYUAN3D)

    def test_stage_order_backward_invalid(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Going backwards in the stage order is invalid."""
        vram_manager._stage_order_position = 2  # At DA3

        # Going back to FLUX (position 1) should be invalid
        assert not vram_manager.validate_stage_order(PipelineStage.FLUX)

    def test_stage_order_skip_valid(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Skipping stages is allowed (e.g., SAM → DA3 skipping FLUX)."""
        vram_manager._stage_order_position = 0  # At SAM
        assert vram_manager.validate_stage_order(PipelineStage.DEPTH_ANYTHING_3)

    def test_trellis2_allowed_as_fallback(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Trellis2 is always valid (fallback for Hunyuan3D)."""
        vram_manager._stage_order_position = 3
        assert vram_manager.validate_stage_order(PipelineStage.TRELLIS2)

    def test_reset_stage_order(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """reset_stage_order brings position back to start."""
        vram_manager._stage_order_position = 3
        vram_manager._current_stage = PipelineStage.HUNYUAN3D

        vram_manager.reset_stage_order()

        assert vram_manager._stage_order_position == -1
        assert vram_manager._current_stage is None

    def test_stage_order_constants(self) -> None:
        """STAGE_ORDER matches the spec: SAM → FLUX → DA3 → Hunyuan3D."""
        assert STAGE_ORDER == (
            PipelineStage.SAM,
            PipelineStage.FLUX,
            PipelineStage.DEPTH_ANYTHING_3,
            PipelineStage.HUNYUAN3D,
        )


# ---------------------------------------------------------------------------
# Test: OOM recovery (Req 15.5)
# ---------------------------------------------------------------------------


class TestOOMRecovery:
    """OOM recovery: /free → wait 5s → retry once → fallback."""

    @pytest.mark.asyncio
    async def test_primary_succeeds(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """When primary succeeds, no fallback is invoked."""
        primary = AsyncMock(return_value="primary_result")
        fallback = AsyncMock(return_value="fallback_result")

        result = await vram_manager.execute_with_oom_recovery(
            primary, fallback
        )

        assert result.success is True
        assert result.method_used == "primary"
        assert result.fell_through is False
        assert result.result == "test_result"  # From mocked execute_with_oom_retry

    @pytest.mark.asyncio
    async def test_primary_oom_falls_to_fallback(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """When primary OOMs after retry, fallback is invoked."""
        vram_manager._manager.execute_with_oom_retry = AsyncMock(
            side_effect=ComfyUIVRAMError("OOM after retry")
        )
        fallback = AsyncMock(return_value="fallback_result")

        result = await vram_manager.execute_with_oom_recovery(
            AsyncMock(), fallback
        )

        assert result.success is True
        assert result.method_used == "fallback"
        assert result.fell_through is True
        assert result.result == "fallback_result"

    @pytest.mark.asyncio
    async def test_both_fail_returns_failure(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """When both primary and fallback fail, returns failure."""
        vram_manager._manager.execute_with_oom_retry = AsyncMock(
            side_effect=ComfyUIVRAMError("OOM")
        )
        fallback = AsyncMock(side_effect=Exception("Fallback also failed"))

        result = await vram_manager.execute_with_oom_recovery(
            AsyncMock(), fallback
        )

        assert result.success is False
        assert result.fell_through is True

    @pytest.mark.asyncio
    async def test_no_fallback_on_oom_returns_failure(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """When primary OOMs with no fallback, returns failure."""
        vram_manager._manager.execute_with_oom_retry = AsyncMock(
            side_effect=ComfyUIVRAMError("OOM")
        )

        result = await vram_manager.execute_with_oom_recovery(
            AsyncMock(), None
        )

        assert result.success is False
        assert result.method_used == "primary"
        assert result.fell_through is False


# ---------------------------------------------------------------------------
# Test: System RAM monitoring (Req 15.6)
# ---------------------------------------------------------------------------


class TestSystemRAM:
    """System RAM pause at >80GB, resume at <72GB."""

    @pytest.mark.asyncio
    async def test_system_ram_ok(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Returns True when system RAM is below threshold."""
        vram_manager._manager.check_system_ram = AsyncMock(return_value=True)
        assert await vram_manager.check_system_ram_ok() is True

    @pytest.mark.asyncio
    async def test_system_ram_pressure(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Returns False when system RAM exceeds 80GB."""
        vram_manager._manager.check_system_ram = AsyncMock(return_value=False)
        assert await vram_manager.check_system_ram_ok() is False

    @pytest.mark.asyncio
    async def test_wait_for_system_ram_delegates(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """wait_for_system_ram delegates to underlying manager."""
        await vram_manager.wait_for_system_ram()
        vram_manager._manager.wait_for_ram_available.assert_called_once()


# ---------------------------------------------------------------------------
# Test: Hard cleanup
# ---------------------------------------------------------------------------


class TestHardCleanup:
    """Hard cleanup releases all VRAM and resets state."""

    @pytest.mark.asyncio
    async def test_hard_cleanup(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """hard_cleanup evicts everything and resets stage tracking."""
        vram_manager._current_stage = PipelineStage.HUNYUAN3D
        vram_manager._stage_order_position = 3

        await vram_manager.hard_cleanup()

        vram_manager._manager.hard_release.assert_called_once()
        assert vram_manager._current_stage is None
        assert vram_manager._stage_order_position == -1


# ---------------------------------------------------------------------------
# Test: Transition behavior (Req 15.2)
# ---------------------------------------------------------------------------


class TestTransitions:
    """Between model transitions: release old model before acquiring new."""

    @pytest.mark.asyncio
    async def test_transition_releases_old_before_new(
        self, vram_manager: UnifiedVRAMManager
    ) -> None:
        """Acquiring a new stage releases the previous one."""
        # Acquire SAM first
        await vram_manager.acquire_vram_explicit(PipelineStage.SAM)
        assert vram_manager.current_stage == PipelineStage.SAM

        # Now acquire FLUX — SAM should be released first
        await vram_manager.acquire_vram_explicit(PipelineStage.FLUX)
        assert vram_manager.current_stage == PipelineStage.FLUX

        # release_model should have been called for the SAM→FLUX transition
        assert vram_manager._manager.release_model.call_count >= 1
