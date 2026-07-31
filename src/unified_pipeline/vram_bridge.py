"""Unified pipeline adapter for the V14 VRAM manager.

Bridges the existing `src/photo_pipeline/vram_manager.py` into the
unified pipeline, enforcing sequential model loading on the RTX 4090
(24GB VRAM) with warm CPU caching.

Key guarantees:
- FLUX and Hunyuan3D never loaded simultaneously (Req 15.1)
- Between transitions: call ComfyUI /free and wait for VRAM < 4GB (Req 15.2)
- Fixed stage order: SAM → FLUX → unload → DA3 → unload → Hunyuan3D per object (Req 15.3)
- Flash attention enabled for all inference (Req 15.4)
- OOM recovery: call /free, wait 5s, retry once, then fall to next method (Req 15.5)
- System RAM pause at >80GB, resume at <72GB (Req 15.6)

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Coroutine

from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIVRAMError
from src.photo_pipeline.vram_manager import (
    VRAMManager,
    VRAM_FREE_THRESHOLD_GB,
    OOM_RETRY_WAIT_S,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline stage definitions and VRAM budget estimates
# ---------------------------------------------------------------------------


class PipelineStage(str, Enum):
    """Ordered pipeline stages that consume VRAM.

    Fixed order per Req 15.3:
    SAM → FLUX → unload → DA3 → unload → Hunyuan3D (per object) → unload
    """

    SAM = "sam_vit_h"
    FLUX = "flux_pipeline"
    DEPTH_ANYTHING_3 = "depth_anything_3"
    HUNYUAN3D = "hunyuan3d_v2.1"
    TRELLIS2 = "trellis2"


# Estimated VRAM usage per stage (GB)
_STAGE_VRAM_ESTIMATES: dict[PipelineStage, float] = {
    PipelineStage.SAM: 4.0,
    PipelineStage.FLUX: 12.0,
    PipelineStage.DEPTH_ANYTHING_3: 6.0,
    PipelineStage.HUNYUAN3D: 14.0,
    PipelineStage.TRELLIS2: 10.0,
}

# Models that MUST NOT coexist in VRAM (Req 15.1)
_EXCLUSIVE_PAIRS: set[frozenset[PipelineStage]] = {
    frozenset({PipelineStage.FLUX, PipelineStage.HUNYUAN3D}),
    frozenset({PipelineStage.FLUX, PipelineStage.TRELLIS2}),
}

# The canonical stage execution order (Req 15.3)
STAGE_ORDER: tuple[PipelineStage, ...] = (
    PipelineStage.SAM,
    PipelineStage.FLUX,
    PipelineStage.DEPTH_ANYTHING_3,
    PipelineStage.HUNYUAN3D,
)


@dataclass(frozen=True)
class VRAMBridgeState:
    """Snapshot of the VRAM bridge state for monitoring."""

    current_stage: str | None
    estimated_usage_gb: float
    system_ram_ok: bool
    flash_attention: bool
    stage_order_position: int


# ---------------------------------------------------------------------------
# Fallback result type for OOM recovery chain
# ---------------------------------------------------------------------------


class OOMFallbackResult:
    """Result from an OOM-recovery-aware execution."""

    def __init__(
        self,
        result: Any = None,
        success: bool = True,
        method_used: str = "",
        fell_through: bool = False,
    ) -> None:
        self.result = result
        self.success = success
        self.method_used = method_used
        self.fell_through = fell_through


# ---------------------------------------------------------------------------
# UnifiedVRAMManager
# ---------------------------------------------------------------------------


class UnifiedVRAMManager:
    """Adapter wrapping the V14 VRAMManager for the unified pipeline.

    Enforces the fixed stage ordering and mutual exclusion rules that
    the unified pipeline requires. The underlying VRAMManager handles
    warm CPU caching, system RAM monitoring, and ComfyUI communication.

    Usage:
        client = ComfyUIClient()
        vram = UnifiedVRAMManager(client)

        async with vram.acquire_vram(PipelineStage.FLUX):
            result = await run_flux_workflow(...)

        # or explicit acquire/release:
        await vram.acquire_vram_explicit(PipelineStage.HUNYUAN3D)
        result = await run_hunyuan(...)
        await vram.release_vram()
    """

    def __init__(
        self,
        client: ComfyUIClient,
        max_vram_gb: float = 24.0,
    ) -> None:
        self._manager = VRAMManager(client, max_vram_gb=max_vram_gb)
        self._client = client
        self._current_stage: PipelineStage | None = None
        self._stage_order_position: int = -1
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_stage(self) -> PipelineStage | None:
        """The currently active pipeline stage, or None if idle."""
        return self._current_stage

    @property
    def flash_attention_enabled(self) -> bool:
        """Whether flash attention is enabled (Req 15.4)."""
        return self._manager.flash_attention_enabled

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_state(self) -> VRAMBridgeState:
        """Return a snapshot of current VRAM bridge state."""
        inner = self._manager.get_state()
        return VRAMBridgeState(
            current_stage=self._current_stage.value if self._current_stage else None,
            estimated_usage_gb=inner.estimated_usage_gb,
            system_ram_ok=inner.system_ram_gb < 80.0,
            flash_attention=self._manager.flash_attention_enabled,
            stage_order_position=self._stage_order_position,
        )

    # ------------------------------------------------------------------
    # Context manager API
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def acquire_vram(
        self, stage: PipelineStage
    ) -> AsyncGenerator[None, None]:
        """Context manager to acquire VRAM for a pipeline stage.

        Enforces exclusion rules (Req 15.1), calls /free and waits for
        VRAM < 4GB between transitions (Req 15.2), and validates stage
        ordering (Req 15.3).

        Usage:
            async with vram.acquire_vram(PipelineStage.FLUX):
                await run_flux(...)

        Yields after VRAM is acquired and safe to use. Releases on exit.
        """
        await self._acquire(stage)
        try:
            yield
        finally:
            await self._release()

    # ------------------------------------------------------------------
    # Explicit acquire/release API
    # ------------------------------------------------------------------

    async def acquire_vram_explicit(self, stage: PipelineStage) -> None:
        """Explicitly acquire VRAM for a stage (non-context-manager).

        Must be paired with a matching release_vram() call.
        """
        await self._acquire(stage)

    async def release_vram(self) -> None:
        """Release VRAM held by the current stage.

        Calls /free and waits for VRAM < 4GB per Req 15.2.
        """
        await self._release()

    # ------------------------------------------------------------------
    # Wait for VRAM threshold
    # ------------------------------------------------------------------

    async def wait_for_free(self, threshold_gb: float = VRAM_FREE_THRESHOLD_GB) -> None:
        """Wait until VRAM usage drops below threshold.

        Per Req 15.2, between model transitions we must ensure VRAM < 4GB
        before loading the next model.

        Args:
            threshold_gb: VRAM threshold in GB (default 4.0).
        """
        await self._manager._wait_for_vram_free()

    # ------------------------------------------------------------------
    # OOM recovery: Req 15.5
    # ------------------------------------------------------------------

    async def execute_with_oom_recovery(
        self,
        primary_fn: Callable[..., Coroutine[Any, Any, Any]],
        fallback_fn: Callable[..., Coroutine[Any, Any, Any]] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> OOMFallbackResult:
        """Execute inference with OOM retry and fallback chain.

        Per Req 15.5:
        1. Try primary_fn
        2. On OOM: call /free, wait 5s, retry primary_fn once
        3. If retry fails: fall to fallback_fn (next method in chain)

        Args:
            primary_fn: Primary inference coroutine.
            fallback_fn: Optional fallback coroutine if primary fails twice.
            *args, **kwargs: Arguments passed to whichever function runs.

        Returns:
            OOMFallbackResult with result data and which method was used.
        """
        try:
            result = await self._manager.execute_with_oom_retry(
                primary_fn, *args, **kwargs
            )
            return OOMFallbackResult(
                result=result,
                success=True,
                method_used="primary",
            )
        except ComfyUIVRAMError as exc:
            logger.warning(
                "Primary method failed after OOM retry: %s", exc
            )
            if fallback_fn is not None:
                logger.info("Falling to next method in chain (Req 15.5)")
                try:
                    result = await fallback_fn(*args, **kwargs)
                    return OOMFallbackResult(
                        result=result,
                        success=True,
                        method_used="fallback",
                        fell_through=True,
                    )
                except Exception as fallback_exc:
                    logger.error(
                        "Fallback method also failed: %s", fallback_exc
                    )
                    return OOMFallbackResult(
                        success=False,
                        method_used="fallback",
                        fell_through=True,
                    )
            return OOMFallbackResult(
                success=False,
                method_used="primary",
                fell_through=False,
            )

    # ------------------------------------------------------------------
    # Stage order validation (Req 15.3)
    # ------------------------------------------------------------------

    def validate_stage_order(self, stage: PipelineStage) -> bool:
        """Check if requesting this stage is valid given current position.

        The fixed order is: SAM → FLUX → DA3 → Hunyuan3D.
        Stages can be skipped (e.g., no DA3 if depth not needed), but
        going backwards is not allowed within a single object's processing.

        Returns True if the transition is valid.
        """
        if stage not in STAGE_ORDER:
            # Trellis2 is a fallback for Hunyuan3D, allowed at same position
            if stage == PipelineStage.TRELLIS2:
                return True
            return True  # Unknown stages are allowed (extensibility)

        requested_pos = STAGE_ORDER.index(stage)
        return requested_pos >= self._stage_order_position

    def reset_stage_order(self) -> None:
        """Reset stage order position for a new object/iteration.

        Call this between objects when starting a new SAM→...→Hunyuan3D cycle.
        """
        self._stage_order_position = -1
        self._current_stage = None

    # ------------------------------------------------------------------
    # System RAM check (Req 15.6)
    # ------------------------------------------------------------------

    async def check_system_ram_ok(self) -> bool:
        """Check system RAM is below pause threshold (80GB).

        Returns True if safe to proceed, False if paused.
        Per Req 15.6: pause at >80GB, resume at <72GB.
        """
        return await self._manager.check_system_ram()

    async def wait_for_system_ram(self) -> None:
        """Block until system RAM drops below resume threshold (72GB)."""
        await self._manager.wait_for_ram_available()

    # ------------------------------------------------------------------
    # Hard cleanup
    # ------------------------------------------------------------------

    async def hard_cleanup(self) -> None:
        """Hard-release all VRAM and system RAM cache.

        Calls /free, evicts warm cache, resets stage tracking.
        Use at session end or after unrecoverable errors.
        """
        await self._manager.hard_release()
        self._current_stage = None
        self._stage_order_position = -1

    # ------------------------------------------------------------------
    # Internal: acquire/release with exclusion and ordering
    # ------------------------------------------------------------------

    async def _acquire(self, stage: PipelineStage) -> None:
        """Internal acquire with all safety checks."""
        async with self._lock:
            # 1. Validate stage order (Req 15.3)
            if not self.validate_stage_order(stage):
                raise VRAMStageOrderError(
                    f"Stage '{stage.value}' requested out of order. "
                    f"Current position: {self._stage_order_position}, "
                    f"stage order: {[s.value for s in STAGE_ORDER]}"
                )

            # 2. Check exclusion (Req 15.1)
            if self._current_stage is not None:
                pair = frozenset({self._current_stage, stage})
                if pair in _EXCLUSIVE_PAIRS:
                    raise VRAMExclusionError(
                        f"Cannot load '{stage.value}' while "
                        f"'{self._current_stage.value}' is active. "
                        f"These models must never coexist (Req 15.1)."
                    )

            # 3. If another stage is active, release it first (Req 15.2)
            if self._current_stage is not None and self._current_stage != stage:
                logger.info(
                    "Transitioning %s → %s: releasing and waiting for VRAM < %.1f GB",
                    self._current_stage.value,
                    stage.value,
                    VRAM_FREE_THRESHOLD_GB,
                )
                await self._manager.release_model()

            # 4. Check system RAM (Req 15.6)
            ram_ok = await self._manager.check_system_ram()
            if not ram_ok:
                logger.warning("System RAM pressure — waiting before acquiring %s", stage.value)
                await self._manager.wait_for_ram_available()

            # 5. Acquire the model in the underlying manager
            estimated_gb = _STAGE_VRAM_ESTIMATES.get(stage, 8.0)
            await self._manager.acquire_model(stage.value, estimated_gb)

            # 6. Update tracking
            self._current_stage = stage
            if stage in STAGE_ORDER:
                self._stage_order_position = STAGE_ORDER.index(stage)

            logger.info(
                "Acquired VRAM for stage '%s' (est %.1f GB, position %d)",
                stage.value,
                estimated_gb,
                self._stage_order_position,
            )

    async def _release(self) -> None:
        """Internal release: soft-release the model and wait for VRAM < 4GB."""
        async with self._lock:
            if self._current_stage is None:
                return

            stage_name = self._current_stage.value
            logger.info("Releasing VRAM for stage '%s'", stage_name)
            await self._manager.release_model()
            self._current_stage = None

            logger.debug(
                "Stage '%s' released, VRAM soft-freed (warm in CPU RAM)",
                stage_name,
            )


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class VRAMStageOrderError(Exception):
    """Raised when a stage is requested out of the required order."""


class VRAMExclusionError(Exception):
    """Raised when mutually exclusive models would be loaded simultaneously."""
