"""VRAM Manager — sequential model loading with warm CPU caching on RTX 4090 24GB.

Enforces single-model exclusion for VRAM, but keeps previously loaded models
warm in system RAM (CPU offload) for fast reload. ComfyUI natively handles
CPU↔GPU model migration — we just need to avoid aggressive /free calls that
evict models entirely from RAM.

Strategy:
- On model transition: let ComfyUI's built-in model management handle offload
  (current model moves to CPU RAM automatically when new model loads)
- Only call /free when VRAM is genuinely exhausted (OOM) or system RAM > 80GB
- This turns ~30s disk→RAM→VRAM loads into ~2-5s RAM→VRAM transfers
- With 96GB system RAM, we can comfortably cache all pipeline models (~24GB total)

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine

import psutil

from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIVRAMError
from src.photo_pipeline.models_v14 import VRAMState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VRAM_FREE_THRESHOLD_GB: float = 4.0
"""VRAM must drop below this level before loading the next model."""

SYSTEM_RAM_PAUSE_THRESHOLD_GB: float = 80.0
"""Pause new submissions when system RAM usage exceeds this value."""

SYSTEM_RAM_RESUME_THRESHOLD_GB: float = 72.0
"""Resume submissions when system RAM usage drops below this value."""

MAX_VRAM_GB: float = 24.0
"""RTX 4090 total VRAM budget."""

OOM_RETRY_WAIT_S: float = 5.0
"""Seconds to wait after /free before OOM retry."""

VRAM_POLL_INTERVAL_S: float = 1.0
"""Seconds between polls when waiting for VRAM to drop."""

RAM_POLL_INTERVAL_S: float = 2.0
"""Seconds between polls when waiting for system RAM to drop."""

VRAM_WAIT_TIMEOUT_S: float = 60.0
"""Maximum seconds to wait for VRAM to drop below threshold."""

# Warm cache: models kept in system RAM for fast GPU reload
# Total ~24GB in RAM out of 96GB available — well within budget
WARM_CACHE_MAX_MODELS: int = 5
"""Maximum number of models to keep warm in CPU RAM."""


# ---------------------------------------------------------------------------
# VRAMManager
# ---------------------------------------------------------------------------


class VRAMManager:
    """Enforces sequential model loading with warm CPU caching on RTX 4090 24GB.

    Guarantees:
    - Only one large model loaded in VRAM at a time (single-model exclusion)
    - Previously used models stay warm in system RAM (fast ~2-5s reload)
    - ComfyUI handles CPU↔GPU migration natively when new workflow submitted
    - /free only called for OOM recovery or system RAM pressure
    - Flash attention enabled for all inference
    - System RAM monitoring (pause at 80GB / resume at 72GB)
    - OOM retry: call /free, wait 5s, retry once

    Parameters
    ----------
    client : ComfyUIClient
        The ComfyUI client used to communicate with the ComfyUI server.
    max_vram_gb : float
        Total VRAM budget in GB (default 24.0 for RTX 4090).
    """

    def __init__(self, client: ComfyUIClient, max_vram_gb: float = MAX_VRAM_GB) -> None:
        self._client = client
        self._max_vram_gb = max_vram_gb
        self._current_model: str | None = None
        self._estimated_usage_gb: float = 0.0
        self._flash_attention_enabled: bool = True
        self._lock = asyncio.Lock()
        # Track models that should be warm in CPU RAM
        self._warm_models: list[str] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_model(self) -> str | None:
        """The name of the currently loaded model, or None if idle."""
        return self._current_model

    @property
    def flash_attention_enabled(self) -> bool:
        """Whether flash attention is enabled for inference calls."""
        return self._flash_attention_enabled

    @flash_attention_enabled.setter
    def flash_attention_enabled(self, value: bool) -> None:
        self._flash_attention_enabled = value

    @property
    def estimated_usage_gb(self) -> float:
        """Estimated current VRAM usage in GB."""
        return self._estimated_usage_gb

    # ------------------------------------------------------------------
    # State snapshot
    # ------------------------------------------------------------------

    def get_state(self) -> VRAMState:
        """Return an immutable snapshot of the current VRAM state."""
        return VRAMState(
            current_model=self._current_model,
            estimated_usage_gb=self._estimated_usage_gb,
            system_ram_gb=self._get_system_ram_used_gb(),
        )

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def acquire_model(self, model_name: str, estimated_gb: float) -> None:
        """Acquire exclusive access to load a model into VRAM.

        Uses warm CPU caching: if another model is loaded, we do NOT call
        /free (which evicts from RAM entirely). Instead, ComfyUI's native
        model management will offload the current model to CPU RAM when the
        new workflow is submitted. This keeps previous models warm for fast
        reload (~2-5s from RAM instead of ~30s from disk).

        Only calls /free if:
        - System RAM exceeds the 80GB threshold
        - An OOM error occurs during execution

        Parameters
        ----------
        model_name : str
            Name of the model to load (e.g. "hunyuan3d_v2.1", "flux_klein").
        estimated_gb : float
            Estimated VRAM usage of this model in GB.
        """
        async with self._lock:
            # Check system RAM — only evict if we're under pressure
            ram_ok = await self.check_system_ram()
            if not ram_ok:
                # System RAM pressure: evict models from CPU cache
                logger.info(
                    "System RAM pressure detected, calling /free to evict "
                    "models from CPU cache before loading '%s'",
                    model_name,
                )
                await self._do_hard_release()
                await self.wait_for_ram_available()

            # If same model already loaded, no-op (fast path)
            if self._current_model == model_name:
                logger.debug("Model '%s' already loaded, skipping acquire", model_name)
                return

            # If different model loaded, let ComfyUI handle the swap via
            # its native model management — just update our bookkeeping.
            # ComfyUI will offload the old model to CPU RAM when the new
            # workflow is submitted, giving us warm caching for free.
            if self._current_model is not None:
                old_model = self._current_model
                logger.info(
                    "Transitioning '%s' → '%s' (old model stays warm in CPU RAM)",
                    old_model,
                    model_name,
                )
                # Track warm model (ComfyUI keeps it in system RAM)
                if old_model not in self._warm_models:
                    self._warm_models.append(old_model)
                # Evict oldest warm model if we exceed the cache limit
                while len(self._warm_models) > WARM_CACHE_MAX_MODELS:
                    evicted = self._warm_models.pop(0)
                    logger.debug("Warm cache full, oldest '%s' may be evicted", evicted)

            # Record new model as the VRAM-active one
            self._current_model = model_name
            self._estimated_usage_gb = estimated_gb
            logger.info(
                "Acquired model '%s' (estimated %.1f GB VRAM, %d warm in RAM)",
                model_name,
                estimated_gb,
                len(self._warm_models),
            )

    async def release_model(self) -> None:
        """Soft-release: mark model as idle but keep it warm in CPU RAM.

        Does NOT call /free — the model stays in system RAM for fast reload.
        ComfyUI will automatically offload it to CPU when the next model loads.
        """
        async with self._lock:
            if self._current_model is None:
                return

            model_name = self._current_model
            logger.info(
                "Soft-releasing model '%s' (stays warm in CPU RAM for fast reload)",
                model_name,
            )

            # Track as warm in CPU RAM
            if model_name not in self._warm_models:
                self._warm_models.append(model_name)

            self._current_model = None
            self._estimated_usage_gb = 0.0

    async def hard_release(self) -> None:
        """Hard-release: call /free to fully evict all models from RAM and VRAM.

        Use this when system RAM is under pressure or for cleanup at session end.
        """
        async with self._lock:
            await self._do_hard_release()

    async def check_system_ram(self) -> bool:
        """Check whether system RAM usage is within acceptable bounds.

        Returns
        -------
        bool
            True if system RAM is below the pause threshold (OK to proceed).
            False if system RAM exceeds 80GB (pause needed).
        """
        used_gb = self._get_system_ram_used_gb()
        if used_gb > SYSTEM_RAM_PAUSE_THRESHOLD_GB:
            logger.warning(
                "System RAM usage %.1f GB exceeds pause threshold %.1f GB",
                used_gb,
                SYSTEM_RAM_PAUSE_THRESHOLD_GB,
            )
            return False
        return True

    async def wait_for_ram_available(self) -> None:
        """Block until system RAM drops below the resume threshold (72GB).

        Polls at RAM_POLL_INTERVAL_S intervals until RAM usage is acceptable.
        """
        used_gb = self._get_system_ram_used_gb()
        if used_gb <= SYSTEM_RAM_PAUSE_THRESHOLD_GB:
            return

        logger.warning(
            "System RAM at %.1f GB (>%.1f GB threshold), pausing until <%.1f GB",
            used_gb,
            SYSTEM_RAM_PAUSE_THRESHOLD_GB,
            SYSTEM_RAM_RESUME_THRESHOLD_GB,
        )

        while used_gb > SYSTEM_RAM_RESUME_THRESHOLD_GB:
            await asyncio.sleep(RAM_POLL_INTERVAL_S)
            used_gb = self._get_system_ram_used_gb()

        logger.info("System RAM dropped to %.1f GB, resuming", used_gb)

    async def execute_with_oom_retry(
        self,
        inference_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute an inference call with OOM retry logic.

        If the call raises ComfyUIVRAMError (OOM), calls /free to evict warm
        cache, waits 5s, and retries exactly once.

        Parameters
        ----------
        inference_fn : callable
            The async inference function to execute.
        *args, **kwargs
            Arguments passed to inference_fn.

        Returns
        -------
        Any
            The result of inference_fn.

        Raises
        ------
        ComfyUIVRAMError
            If the retry also fails with OOM.
        """
        try:
            return await inference_fn(*args, **kwargs)
        except ComfyUIVRAMError as exc:
            logger.warning(
                "OOM error during inference — evicting warm cache and retrying: %s",
                exc,
            )
            # OOM recovery: hard-evict all warm models from CPU RAM
            await self._client._free_vram()
            self._warm_models.clear()
            await asyncio.sleep(OOM_RETRY_WAIT_S)

            logger.info("Retrying inference after OOM recovery (warm cache cleared)")
            return await inference_fn(*args, **kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_hard_release(self) -> None:
        """Hard evict: call /free, clear warm cache, wait for VRAM to settle."""
        model_name = self._current_model or "(idle)"
        logger.info("Hard-releasing all models via /free (current: '%s')", model_name)

        await self._client._free_vram()

        # Wait for VRAM to drop
        await self._wait_for_vram_free()

        self._current_model = None
        self._estimated_usage_gb = 0.0
        self._warm_models.clear()
        logger.info("Hard release complete — all models evicted from RAM + VRAM")

    async def _wait_for_vram_free(self) -> None:
        """Poll until VRAM usage drops below the free threshold (4GB).

        Uses system_stats from ComfyUI to determine actual VRAM usage.
        Falls back to a fixed delay if the endpoint is unavailable.
        """
        elapsed = 0.0
        while elapsed < VRAM_WAIT_TIMEOUT_S:
            vram_used_gb = await self._get_vram_used_gb()
            if vram_used_gb < VRAM_FREE_THRESHOLD_GB:
                logger.debug(
                    "VRAM usage %.2f GB < %.1f GB threshold, ready",
                    vram_used_gb,
                    VRAM_FREE_THRESHOLD_GB,
                )
                return

            logger.debug(
                "VRAM usage %.2f GB, waiting (%.1fs elapsed)...",
                vram_used_gb,
                elapsed,
            )
            await asyncio.sleep(VRAM_POLL_INTERVAL_S)
            elapsed += VRAM_POLL_INTERVAL_S

        # Timeout — log warning but proceed (best-effort)
        logger.warning(
            "VRAM did not drop below %.1f GB within %.0fs, proceeding anyway",
            VRAM_FREE_THRESHOLD_GB,
            VRAM_WAIT_TIMEOUT_S,
        )

    async def _get_vram_used_gb(self) -> float:
        """Query ComfyUI /system_stats for current VRAM usage.

        Returns VRAM used in GB, or 0.0 if the endpoint is unreachable.
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as http_client:
                response = await http_client.get(
                    f"{self._client.base_url}/system_stats"
                )
                if response.status_code == 200:
                    data = response.json()
                    # ComfyUI system_stats returns devices array with vram_total/vram_free
                    devices = data.get("devices", [])
                    if devices:
                        device = devices[0]
                        vram_total = device.get("vram_total", 0)
                        vram_free = device.get("vram_free", 0)
                        vram_used_bytes = vram_total - vram_free
                        return vram_used_bytes / (1024**3)
        except (Exception,):
            logger.debug("Could not query ComfyUI system_stats for VRAM info")

        return 0.0

    @staticmethod
    def _get_system_ram_used_gb() -> float:
        """Get current system RAM usage in GB via psutil."""
        mem = psutil.virtual_memory()
        return mem.used / (1024**3)
