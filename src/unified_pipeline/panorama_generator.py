"""Generate a 360° equirectangular panorama for a V2 session via ComfyUI FLUX.

Writes <session_dir>/artifacts/panorama.png at 2:1 aspect (2048x1024). If a
DiT360 LoRA is present on disk it is applied to FLUX for true panoramic
consistency; otherwise a plain FLUX 2:1 generation is used as a fallback (the
equirect prompt still biases toward a wraparound room view).

The panorama is captured "as if from the center of the room", which is exactly
what src/unified_pipeline/panorama_box_projection.py expects to project onto the
room box. Together these form the panorama pathway that sidesteps the ill-posed
single-perspective scene-recovery problem.
"""
from __future__ import annotations

import glob
import logging
import random
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("live_trace")

# Where local ComfyUI LoRAs live on this machine (see ollama/comfy ops notes).
_LORA_DIR = Path(r"C:\Users\JohnM\ComfyUI-Shared\models\loras")


def _find_dit360_lora() -> str | None:
    """Return the filename of a DiT360 LoRA if present under the LoRA dir, else None."""
    try:
        if not _LORA_DIR.is_dir():
            return None
        for pat in ("*dit360*.safetensors", "*DiT360*.safetensors", "*dit-360*.safetensors"):
            hits = sorted(glob.glob(str(_LORA_DIR / pat)))
            if hits:
                return Path(hits[0]).name
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"  panorama: LoRA scan failed: {exc}")
    return None


def _build_prompt(brief: dict[str, Any]) -> tuple[str, str]:
    """Build (positive, negative) equirectangular prompts from the Brief."""
    room_purpose = brief.get("room_purpose", "room")
    atmosphere = brief.get("atmosphere", {})
    mood = atmosphere.get("mood", "warm and inviting") if isinstance(atmosphere, dict) else "warm"
    era = brief.get("era", {})
    period = era.get("period", "") if isinstance(era, dict) else ""
    palette = brief.get("palette", {})
    primary = palette.get("primary", "") if isinstance(palette, dict) else ""

    objects = brief.get("object_manifest", [])
    object_names = ", ".join(
        item.get("name", "")
        for item in objects[:8]
        if isinstance(item, dict) and item.get("name")
    ) or "furniture and fixtures"

    positive = (
        f"Equirectangular 360 degree panorama of the interior of a "
        f"{period + ' ' if period else ''}{room_purpose}, "
        f"seen from the exact center of the room, {mood} atmosphere, "
        f"featuring {object_names}. {primary + ' tones. ' if primary else ''}"
        f"Seamless spherical VR photosphere, full room interior including floor "
        f"and ceiling, consistent lighting all around, photorealistic, high detail, "
        f"sharp focus. equirectangular projection, 360 panorama, seamless wrap."
    )
    negative = (
        "seam, visible stitch, distortion, warped, people, person, duplicate "
        "objects, text, watermark, blurry, low quality, deformed, flat perspective, "
        "single wall, cropped"
    )
    return positive, negative


def _build_workflow(
    positive: str, negative: str, seed: int, lora_name: str | None
) -> dict[str, Any]:
    """FLUX equirectangular workflow (2048x1024), optionally with a DiT360 LoRA."""
    from src.unified_pipeline.dream_preview import FLUX_CLIP, FLUX_MODEL, FLUX_VAE

    workflow: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 2048, "height": 1024, "batch_size": 1}},
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
                "seed": seed,
                "steps": 20,
                "cfg": 5.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "v2_panorama"}},
    }

    if lora_name:
        # Insert LoraLoaderModelOnly between UNETLoader and KSampler.model.
        workflow["10"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": ["1", 0], "lora_name": lora_name, "strength_model": 1.0},
        }
        workflow["7"]["inputs"]["model"] = ["10", 0]

    return workflow


async def generate_panorama(
    session_id: str,
    session_dir: Path,
    brief: dict[str, Any],
    *,
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> Path:
    """Generate artifacts/panorama.png (equirectangular 2048x1024) for a session."""
    from src.photo_pipeline.comfyui_client import ComfyUIClient

    def emit(etype: str, data: dict[str, Any]) -> None:
        if emit_fn:
            emit_fn(etype, data)

    emit("phase_start", {"phase": "panorama", "message": "Generating 360 panorama..."})

    artifacts_dir = Path(session_dir) / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / "panorama.png"

    positive, negative = _build_prompt(brief)
    lora_name = _find_dit360_lora()
    if lora_name:
        logger.info(f"  panorama: using DiT360 LoRA {lora_name}")
    else:
        logger.info("  panorama: no DiT360 LoRA found; using plain FLUX equirect fallback")

    seed = random.randint(1, 2**32 - 1)
    workflow = _build_workflow(positive, negative, seed, lora_name)

    client = ComfyUIClient(timeout_s=600, poll_interval_s=0.75)
    if not await client.health_check():
        raise RuntimeError("ComfyUI not available on localhost:8188")

    try:
        prompt_id = await client.submit_workflow(workflow, client_id=f"v2-pano-{session_id[:16]}")
        await client.wait_for_completion(prompt_id, timeout_s=600)
        await client.get_output_image(
            prompt_id=prompt_id, output_dir=artifacts_dir, filename="panorama.png"
        )
    except Exception as exc:
        raise RuntimeError(f"Panorama generation failed: {exc}") from exc
    finally:
        await client.release_vram()

    emit("panorama_ready", {"image_url": f"/api/v2/session/{session_id}/artifact/panorama"})
    logger.info(f"  panorama: generated {output_path}")
    return output_path


def _main() -> int:
    import asyncio
    import json
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m src.unified_pipeline.panorama_generator <session_id>")
        return 2
    sid = sys.argv[1]
    root = Path(__file__).resolve().parents[2]
    session_dir = root / "output" / sid
    brief_path = session_dir / "artifacts" / "brief.json"
    brief = {}
    if brief_path.is_file():
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
    out = asyncio.run(generate_panorama(sid, session_dir, brief))
    print(f"OK: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
