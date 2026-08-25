"""Dream Preview Generator — FLUX text-to-image via ComfyUI.

Generates provisional mood images from conversation-derived prompts within
a 15-second target. Supports multiple variants and records user preference
for Art_Bible conditioning.

Dream Previews are NEVER spatial authority for Plan, Blockout, or
WorldContract geometry.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any

from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)

logger = logging.getLogger(__name__)

# Label applied to all Dream_Preview images (Req 3.3)
PROVISIONAL_LABEL = "PROVISIONAL — not spatial authority"

# Generation timing target plus a terminal wait bound. The target controls UX
# expectations; the larger bound prevents an owned ComfyUI job from being
# abandoned while it is still occupying the shared GPU queue.
GENERATION_TARGET_S = 15
GENERATION_TIMEOUT_S = 360

# FLUX workflow parameters tuned for speed within 15s target
FLUX_STEPS = 20
FLUX_CFG = 3.5

# FLUX model files (UNETLoader path — matches canon_image/generator.py)
FLUX_MODEL = "flux-2-klein-base-4b-fp8.safetensors"
FLUX_CLIP = "qwen_3_4b.safetensors"
FLUX_VAE = "flux2-vae.safetensors"

# Default output directory for dream preview images
DEFAULT_OUTPUT_DIR = Path("output/dream_previews")


class DreamPreviewGenerator:
    """Generates Dream_Preview images using FLUX via ComfyUI.

    Dream_Preview is a provisional, non-authoritative mood image shown during
    conversation to enable visual steering. It reflects proposed era, mood,
    palette, and key objects from the conversation state but is NEVER used as
    spatial authority for Plan, Blockout, or WorldContract geometry.

    Parameters
    ----------
    comfyui_client : ComfyUIClient, optional
        Existing ComfyUI client instance. If None, creates a new one with
        the generation timeout.
    output_dir : Path, optional
        Directory for storing generated preview images.
    """

    def __init__(
        self,
        comfyui_client: ComfyUIClient | None = None,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
    ) -> None:
        self._client = comfyui_client or ComfyUIClient(
            timeout_s=GENERATION_TIMEOUT_S,
            poll_interval_s=0.5,
        )
        self._output_dir = output_dir
        # Session state: session_id → {variants: [...], preferred_index: int | None}
        self._sessions: dict[str, dict[str, Any]] = {}

    async def generate(
        self,
        prompt: str,
        session_id: str,
        variant_count: int = 1,
    ) -> list[str]:
        """Generate Dream_Preview image(s) from a conversation-derived prompt.

        Targets 15-second generation per variant (Req 3.1), but waits up to
        360 seconds for the owned ComfyUI job to become terminal so a slow
        warm-up cannot block every later GPU stage. Each generated image is
        labeled as "PROVISIONAL — not spatial authority" (Req 3.3).

        The prompt should reflect proposed era, mood, palette, and key objects
        from the current conversation state (Req 3.2).

        Parameters
        ----------
        prompt : str
            Text prompt derived from conversation state reflecting era, mood,
            palette, and key objects (Req 3.2).
        session_id : str
            Session identifier for tracking variants and preferences.
        variant_count : int
            Number of variant images to generate (Req 3.5). Default 1.

        Returns
        -------
        list[str]
            Paths to generated preview images. Empty list on timeout or failure.
        """
        if variant_count < 1:
            variant_count = 1

        # Ensure session state exists
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "variants": [],
                "preferred_index": None,
                "generation_count": 0,
            }

        session = self._sessions[session_id]
        output_paths: list[str] = []

        # Check ComfyUI availability
        if not await self._client.health_check():
            logger.warning(
                "ComfyUI unavailable — cannot generate Dream_Preview"
            )
            return []

        start_time = time.monotonic()

        for i in range(variant_count):
            # Check if we've exceeded our overall timeout budget
            elapsed = time.monotonic() - start_time
            remaining = GENERATION_TIMEOUT_S - elapsed
            if remaining <= 2.0:
                logger.warning(
                    "Timeout budget exhausted after %d/%d variants (%.1fs)",
                    i,
                    variant_count,
                    elapsed,
                )
                break

            try:
                path = await self._generate_single(
                    prompt=prompt,
                    session_id=session_id,
                    variant_index=session["generation_count"] + i,
                    timeout_s=min(GENERATION_TIMEOUT_S, remaining),
                )
                if path:
                    output_paths.append(path)
            except (ComfyUITimeoutError, ComfyUIError) as exc:
                logger.warning(
                    "Dream_Preview variant %d failed: %s", i, exc
                )
                continue
            except asyncio.TimeoutError:
                logger.warning(
                    "Dream_Preview variant %d timed out (%.1fs elapsed)",
                    i,
                    time.monotonic() - start_time,
                )
                break

        # Update session state with new variants
        session["variants"].extend(output_paths)
        session["generation_count"] += len(output_paths)

        # Reset preference when regenerating (Req 3.4 — regeneration on feedback)
        session["preferred_index"] = None

        elapsed_total = time.monotonic() - start_time
        logger.info(
            "Dream_Preview: generated %d/%d variants in %.1fs for session %s",
            len(output_paths),
            variant_count,
            elapsed_total,
            session_id,
        )

        return output_paths

    def record_preference(self, session_id: str, variant_index: int) -> None:
        """Record which Dream_Preview variant the user responded positively to.

        Used for Art_Bible conditioning (Req 3.6).

        Parameters
        ----------
        session_id : str
            Session identifier.
        variant_index : int
            Index of the preferred variant in the session's variant list.

        Raises
        ------
        ValueError
            If session_id is unknown or variant_index is out of range.
        """
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")

        session = self._sessions[session_id]
        variants = session["variants"]

        if not variants:
            raise ValueError(
                f"No variants available for session {session_id}"
            )

        if variant_index < 0 or variant_index >= len(variants):
            raise ValueError(
                f"variant_index {variant_index} out of range "
                f"[0, {len(variants) - 1}] for session {session_id}"
            )

        session["preferred_index"] = variant_index
        logger.info(
            "Dream_Preview: recorded preference variant %d for session %s",
            variant_index,
            session_id,
        )

    def get_preferred(self, session_id: str) -> str:
        """Get the path to the user's preferred Dream_Preview image.

        Returns the preferred variant if one was recorded, otherwise the
        first variant generated.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        str
            Path to the preferred (or first) Dream_Preview image.

        Raises
        ------
        ValueError
            If session_id is unknown or no variants exist.
        """
        if session_id not in self._sessions:
            raise ValueError(f"Unknown session: {session_id}")

        session = self._sessions[session_id]
        variants = session["variants"]

        if not variants:
            raise ValueError(
                f"No variants available for session {session_id}"
            )

        preferred_idx = session["preferred_index"]
        if preferred_idx is not None and 0 <= preferred_idx < len(variants):
            return variants[preferred_idx]

        # Default to first variant if no preference recorded
        return variants[0]

    def get_variants(self, session_id: str) -> list[str]:
        """Get all variant paths for a session.

        Parameters
        ----------
        session_id : str
            Session identifier.

        Returns
        -------
        list[str]
            All variant image paths for this session.
        """
        if session_id not in self._sessions:
            return []
        return list(self._sessions[session_id]["variants"])

    def get_label(self) -> str:
        """Return the provisional label applied to all Dream_Preview images.

        Req 3.3: Dream_Preview is NOT spatial authority.
        """
        return PROVISIONAL_LABEL

    # ─── Internal ──────────────────────────────────────────────────────────

    def _build_workflow(self, prompt: str, seed: int) -> dict[str, Any]:
        """Build a FLUX txt2img workflow dict for ComfyUI submission.

        Uses the same ComfyUI API-format workflow structure. Constructs
        inline rather than loading from template to keep the SEED as an
        integer (not a string placeholder).
        """
        return {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"},
            },
            "1b": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"},
            },
            "1c": {
                "class_type": "VAELoader",
                "inputs": {"vae_name": FLUX_VAE},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["1b", 0]},
            },
            "3": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "width": 1024,
                    "height": 768,
                    "batch_size": 1,
                },
            },
            "4": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["5", 0],
                    "latent_image": ["3", 0],
                    "seed": seed,
                    "steps": FLUX_STEPS,
                    "cfg": FLUX_CFG,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                },
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": "", "clip": ["1b", 0]},
            },
            "6": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["4", 0], "vae": ["1c", 0]},
            },
            "7": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["6", 0],
                    "filename_prefix": "dream_preview",
                },
            },
        }

    async def _generate_single(
        self,
        prompt: str,
        session_id: str,
        variant_index: int,
        timeout_s: float = GENERATION_TIMEOUT_S,
    ) -> str | None:
        """Generate a single Dream_Preview image variant.

        Returns the output path on success, None on failure.
        """
        # Prepare output directory
        session_dir = self._output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        filename = f"dream_preview_{variant_index:03d}.png"

        # Generate a unique seed for this variant
        seed = random.randint(1, 2**32 - 1)

        # Build workflow with prompt and seed inline
        workflow = self._build_workflow(prompt, seed)

        # Submit workflow to ComfyUI with timeout
        try:
            prompt_id = await self._client.submit_workflow(
                workflow,
                client_id=f"dream-preview-{session_id}",
                timeout_s=int(timeout_s),
            )
        except ComfyUIError as exc:
            logger.warning("Dream_Preview submission failed: %s", exc)
            return None

        # Wait for completion within timeout
        try:
            await self._client.wait_for_completion(
                prompt_id, timeout_s=int(timeout_s)
            )
        except ComfyUITimeoutError:
            logger.error(
                "Dream_Preview job %s did not become terminal within %ds",
                prompt_id,
                int(timeout_s),
            )
            return None

        # Retrieve output image
        try:
            output_path = await self._client.get_output_image(
                prompt_id=prompt_id,
                output_dir=session_dir,
                filename=filename,
            )
            logger.info("Dream_Preview saved: %s", output_path)
            return str(output_path)
        except ComfyUIError as exc:
            logger.warning("Failed to retrieve Dream_Preview output: %s", exc)
            return None
