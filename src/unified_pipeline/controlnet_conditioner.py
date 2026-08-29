"""ControlNet depth-conditioned generation for the Unified World Pipeline.

Injects MetricPlan-authored depth maps into SDXL image generation via ComfyUI
ControlNet, so generated images follow MetricPlan geometry BY CONSTRUCTION.
This is the "inject" half of the inject-then-validate architecture: geometry
flows downhill from the spatial authority into generation, never uphill from a
hallucinated image back into geometry.

Depth conditioning uses the proven-compatible SDXL base + promax union
ControlNet (depth) stack from geometry_injection.py. Non-SDXL backbones
(FLUX/Z-Image/Lumina2) are INCOMPATIBLE with the promax ControlNet, so this
module deliberately targets SDXL to match the only installed, architecture-
compatible depth ControlNet.

The depth map produced by depth_sequence_renderer uses meters with ``np.inf``
for "no geometry". ControlNet depth models expect a normalized, disparity-like
image (near = bright, far = dark) in [0, 1]. ``normalize_depth_for_controlnet``
performs that conversion deterministically.

If ControlNet nodes are unavailable in the local ComfyUI, callers should fall
back to the existing img2img-with-blockout path (Canon generator behavior).

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Proven-compatible depth conditioning stack (see geometry_injection.py):
# SDXL base + promax union ControlNet (depth). FLUX/Z-Image/Lumina2 + promax is
# INCOMPATIBLE (architecture mismatch), so this module targets SDXL.
SDXL_CHECKPOINT = "sd_xl_base_1.0.safetensors"
PROMAX_CONTROLNET = "diffusion_pytorch_model_promax.safetensors"
# Depth conditioning strength / schedule proven in geometry_injection.py.
DEFAULT_STRENGTH = 0.45
DEFAULT_END_PERCENT = 0.6
DEFAULT_NEGATIVE = (
    "blurry, distorted, low quality, warped, deformed, cartoon, illustration"
)
# ControlNet node class types we require to be present.
REQUIRED_CONTROLNET_NODES = (
    "ControlNetLoader",
    "SetUnionControlNetType",
    "ControlNetApplyAdvanced",
)


def normalize_depth_for_controlnet(
    depth_map: np.ndarray, far_clip_m: float = 15.0
) -> np.ndarray:
    """Convert a metric depth map (meters, inf = no geometry) to a ControlNet image.

    ControlNet depth conditioning expects a disparity-like uint8 image where
    NEAR surfaces are BRIGHT and FAR surfaces are DARK. Steps:
      1. Replace inf / non-finite with ``far_clip_m`` (treated as far background).
      2. Clip to [0, far_clip_m].
      3. Invert-normalize: near -> 1.0, far -> 0.0.
      4. Scale to uint8 [0, 255].

    Args:
        depth_map: (H, W) float depth in meters; inf marks no geometry.
        far_clip_m: Depth at/after which everything is treated as background.

    Returns:
        (H, W, 3) uint8 array suitable as a ControlNet depth conditioning image.
    """
    depth = np.asarray(depth_map, dtype=np.float64)
    filled = np.where(np.isfinite(depth), depth, far_clip_m)
    filled = np.clip(filled, 0.0, far_clip_m)
    # Invert so near is bright; guard against a zero-range map.
    if far_clip_m <= 0.0:
        disparity = np.zeros_like(filled)
    else:
        disparity = 1.0 - (filled / far_clip_m)
    gray = np.clip(disparity * 255.0, 0.0, 255.0).astype(np.uint8)
    return np.stack([gray, gray, gray], axis=-1)


class ControlNetConditioner:
    """Builds and runs ControlNet depth-conditioned FLUX workflows via ComfyUI.

    Workflow-building and availability logic are unit-testable without a GPU;
    the actual generation requires a live ComfyUI instance.
    """

    def __init__(
        self,
        comfyui_url: str = "http://localhost:8188",
        default_strength: float = DEFAULT_STRENGTH,
        controlnet_model: str = PROMAX_CONTROLNET,
        checkpoint: str = SDXL_CHECKPOINT,
        end_percent: float = DEFAULT_END_PERCENT,
    ) -> None:
        self._url = comfyui_url.rstrip("/")
        self._default_strength = default_strength
        self._controlnet_model = controlnet_model
        self._checkpoint = checkpoint
        self._end_percent = end_percent

    # ── Availability ─────────────────────────────────────────────────────────

    async def check_availability(self) -> bool:
        """Return True if ComfyUI is reachable AND ControlNet nodes are present.

        Queries ``/object_info`` and checks for the required ControlNet node
        class types. On any failure, returns False so the caller falls back.
        """
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{self._url}/object_info")
                if resp.status_code != 200:
                    logger.warning(
                        "ControlNet availability: /object_info -> %s",
                        resp.status_code,
                    )
                    return False
                info = resp.json()
        except Exception as exc:  # noqa: BLE001 - availability is best-effort
            logger.warning("ControlNet availability check failed: %s", exc)
            return False

        available = self._controlnet_nodes_present(info)
        if not available:
            logger.info(
                "ControlNet nodes not present; caller should use img2img fallback"
            )
        return available

    def _controlnet_nodes_present(self, object_info: dict[str, Any]) -> bool:
        """Check the /object_info payload for the required ControlNet nodes."""
        if not isinstance(object_info, dict):
            return False
        return all(node in object_info for node in REQUIRED_CONTROLNET_NODES)

    # ── Workflow construction ────────────────────────────────────────────────

    def build_workflow(
        self,
        depth_filename: str,
        prompt: str,
        *,
        strength: float | None = None,
        seed: int = -1,
        width: int = 1024,
        height: int = 768,
        negative_prompt: str = DEFAULT_NEGATIVE,
    ) -> dict[str, Any]:
        """Build a ComfyUI SDXL + promax depth-ControlNet workflow graph.

        Matches the proven-compatible pair from geometry_injection.py: SDXL base
        checkpoint + promax union ControlNet set to depth mode via
        SetUnionControlNetType, applied with ControlNetApplyAdvanced. This is the
        only depth-conditioning stack with an installed, architecture-compatible
        ControlNet model on this machine.

        Args:
            depth_filename: Filename of the uploaded depth conditioning image.
            prompt: Positive text prompt.
            strength: ControlNet conditioning strength (default from ctor, 0.45).
            seed: Sampler seed (-1 for random handled by caller/ComfyUI).
            width: Output width.
            height: Output height.
            negative_prompt: Negative text prompt.

        Returns:
            A ComfyUI prompt graph (dict of node_id -> node spec).
        """
        strength = self._default_strength if strength is None else strength
        strength = float(np.clip(strength, 0.0, 1.0))

        return {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": self._checkpoint},
            },
            "4": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": prompt},
            },
            "5": {
                "class_type": "CLIPTextEncode",
                "inputs": {"clip": ["1", 1], "text": negative_prompt},
            },
            "6": {
                "class_type": "LoadImage",
                "inputs": {"image": depth_filename},
            },
            "7": {
                "class_type": "ControlNetLoader",
                "inputs": {"control_net_name": self._controlnet_model},
            },
            "14": {
                "class_type": "SetUnionControlNetType",
                "inputs": {"control_net": ["7", 0], "type": "depth"},
            },
            "8": {
                "class_type": "ControlNetApplyAdvanced",
                "inputs": {
                    "positive": ["4", 0],
                    "negative": ["5", 0],
                    "control_net": ["14", 0],
                    "image": ["6", 0],
                    "strength": strength,
                    "start_percent": 0.0,
                    "end_percent": self._end_percent,
                },
            },
            "10": {
                "class_type": "EmptyLatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "11": {
                "class_type": "KSampler",
                "inputs": {
                    "model": ["1", 0],
                    "positive": ["8", 0],
                    "negative": ["8", 1],
                    "latent_image": ["10", 0],
                    "seed": seed,
                    "steps": 25,
                    "cfg": 6.5,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": 1.0,
                },
            },
            "12": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["11", 0], "vae": ["1", 2]},
            },
            "13": {
                "class_type": "SaveImage",
                "inputs": {"images": ["12", 0], "filename_prefix": "conditioned_view"},
            },
        }

    # ── Generation ───────────────────────────────────────────────────────────

    async def generate_conditioned(
        self,
        depth_render,
        prompt: str,
        *,
        strength: float | None = None,
        seed: int = -1,
        output_dir: Path | None = None,
    ) -> Path:
        """Generate one depth-conditioned image (requires live ComfyUI).

        Normalizes the depth render, uploads it, submits the ControlNet
        workflow, and retrieves the output image.

        Args:
            depth_render: A DepthRender (from depth_sequence_renderer) with a
                ``.depth_map`` float array and ``.camera_label``.
            prompt: Positive text prompt.
            strength: ControlNet strength (default from ctor).
            seed: Sampler seed.
            output_dir: Directory for the generated PNG.

        Returns:
            Path to the generated image.

        Raises:
            RuntimeError: If ComfyUI is unavailable or generation fails.
        """
        import random

        from PIL import Image

        from src.photo_pipeline.comfyui_client import ComfyUIClient

        out_dir = Path(output_dir) if output_dir else Path("output/conditioned")
        out_dir.mkdir(parents=True, exist_ok=True)

        # KSampler requires a non-negative seed; -1 means "pick a random one".
        if seed is None or seed < 0:
            seed = random.randint(1, 2**32 - 1)

        # Normalize depth -> conditioning image and write it to disk for upload.
        cond_img = normalize_depth_for_controlnet(depth_render.depth_map)
        cond_path = out_dir / f"cond_{depth_render.camera_label}.png"
        Image.fromarray(cond_img).save(cond_path)

        client = ComfyUIClient(base_url=self._url)
        if not await client.health_check():
            raise RuntimeError("ComfyUI unavailable for ControlNet generation")

        depth_filename = await client.upload_image(cond_path)
        workflow = self.build_workflow(
            depth_filename, prompt, strength=strength, seed=seed
        )
        prompt_id = await client.submit_workflow(workflow)
        await client.wait_for_completion(prompt_id, timeout_s=180)

        out_name = f"conditioned_{depth_render.camera_label}.png"
        image_path = await client.get_output_image(
            prompt_id, out_dir, filename=out_name
        )
        logger.info(
            "generate_conditioned: %s -> %s (strength=%s)",
            depth_render.camera_label,
            image_path,
            strength if strength is not None else self._default_strength,
        )
        return Path(image_path)
