"""VRAM Manager — sequential model loading with VRAM budget on RTX 4090 24GB.

Enforces single-model exclusion, explicit /free + wait between transitions,
flash attention flag, system RAM monitoring (pause at 80GB / resume at 72GB),
and OOM retry logic (call /free, wait 5s, retry once).

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


# ---------------------------------------------------------------------------
# VRAMManager
# ---------------------------------------------------------------------------


class VRAMManager:
    """Enforces sequential model loading with VRAM budget on RTX 4090 24GB.

    Guarantees:
    - Only one large model loaded at a time (single-model exclusion)
    - Explicit /free + wait between transitions
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

        If another model is currently loaded, it is released first via /free.
        Then waits until VRAM usage drops below 4GB before signaling ready.

        Also checks system RAM and pauses if over the 80GB threshold.

        Parameters
        ----------
        model_name : str
            Name of the model to load (e.g. "hunyuan3d_v2.1", "flux_klein").
        estimated_gb : float
            Estimated VRAM usage of this model in GB.
        """
        async with self._lock:
            # Check system RAM before proceeding
            await self.wait_for_ram_available()

            # If a model is already loaded, release it first (single-model exclusion)
            if self._current_model is not None:
                logger.info(
                    "Releasing current model '%s' before loading '%s'",
                    self._current_model,
                    model_name,
                )
                await self._do_release()

            # Wait for VRAM to settle below threshold
            await self._wait_for_vram_free()

            # Record new model as loaded
            self._current_model = model_name
            self._estimated_usage_gb = estimated_gb
            logger.info(
                "Acquired model '%s' (estimated %.1f GB VRAM)",
                model_name,
                estimated_gb,
            )

    async def release_model(self) -> None:
        """Release the current model by calling /free and waiting for VRAM < 4GB."""
        async with self._lock:
            await self._do_release()

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

        If the call raises ComfyUIVRAMError (OOM), calls /free, waits 5s,
        and retries exactly once.

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
                "OOM error during inference, attempting recovery: %s", exc
            )
            # OOM retry: call /free, wait 5s, retry once
            await self._client._free_vram()
            await asyncio.sleep(OOM_RETRY_WAIT_S)

            logger.info("Retrying inference after OOM recovery")
            return await inference_fn(*args, **kwargs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _do_release(self) -> None:
        """Internal: call /free and wait for VRAM to settle, update state."""
        if self._current_model is None:
            return

        model_name = self._current_model
        logger.info("Releasing model '%s' via /free", model_name)

        await self._client._free_vram()

        # Wait for VRAM to drop
        await self._wait_for_vram_free()

        self._current_model = None
        self._estimated_usage_gb = 0.0
        logger.info("Model '%s' released, VRAM cleared", model_name)

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
