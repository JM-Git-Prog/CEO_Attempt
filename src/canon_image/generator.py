"""Canon image generation through local ComfyUI, API fallback, or mock mode."""

from __future__ import annotations

import asyncio
import base64
import os
import random
import secrets
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from src.models import SceneConcept

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")
COMFYUI_ENABLED = os.getenv("COMFYUI_ENABLED", "1").lower() in {"1", "true", "yes"}
COMFYUI_TIMEOUT = int(os.getenv("COMFYUI_TIMEOUT", "300"))
IMAGE_API_URL = os.getenv("IMAGE_API_URL", "").rstrip("/")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

FLUX_MODEL = "flux-2-klein-base-4b-fp8.safetensors"
FLUX_CLIP = "qwen_3_4b.safetensors"
FLUX_VAE = "flux2-vae.safetensors"
_LAST_PROVIDER: dict[str, str] = {}


def get_image_provider(session_id: str) -> str:
    return _LAST_PROVIDER.get(session_id, "pending")


async def check_comfyui() -> dict:
    """Report whether the exact FLUX.2 stack required by the app is available."""
    if not COMFYUI_ENABLED:
        return {"ready": False, "enabled": False, "reason": "disabled"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            stats, models, encoders, vaes = await asyncio.gather(
                client.get(f"{COMFYUI_URL}/system_stats"),
                client.get(f"{COMFYUI_URL}/models/diffusion_models"),
                client.get(f"{COMFYUI_URL}/models/text_encoders"),
                client.get(f"{COMFYUI_URL}/models/vae"),
            )
        for response in (stats, models, encoders, vaes):
            response.raise_for_status()
        missing = [name for name, available in (
            (FLUX_MODEL, models.json()), (FLUX_CLIP, encoders.json()), (FLUX_VAE, vaes.json())
        ) if name not in available]
        device = (stats.json().get("devices") or [{}])[0].get("name", "unknown GPU")
        return {"ready": not missing, "enabled": True, "model": "FLUX.2 Klein 4B FP8", "device": device, "missing": missing}
    except Exception as exc:
        return {"ready": False, "enabled": True, "reason": str(exc)}


def _generate_mock(prompt: str, output_path: Path) -> Path:
    """Create an unmistakably labelled fallback image."""
    width, height = 1024, 768
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        tone = int(18 + 28 * y / height)
        draw.line((0, y, width, y), fill=(tone, tone + 4, tone + 12))
    floor_y = 500
    for y in range(floor_y, height, 48):
        for x in range(0, width, 48):
            color = "#d0cbc0" if ((x // 48 + y // 48) % 2) else "#25262a"
            draw.rectangle((x, y, x + 48, y + 48), fill=color)
    draw.rectangle((120, 360, 900, 510), fill="#594c3c", outline="#d4b78d", width=4)
    for x in (260, 410, 560, 710):
        draw.ellipse((x - 30, 455, x + 30, 485), fill="#b93c36")
        draw.line((x, 480, x, 620), fill="#c4c7ca", width=6)
    draw.rectangle((24, 22, 235, 62), fill="#a03d3d")
    draw.text((38, 34), "MOCK FALLBACK", fill="white")
    draw.text((24, 82), prompt[:145], fill="#c4cad4")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")
    return output_path


def _flux_workflow(prompt: str) -> dict:
    positive = (
        f"{prompt}. Photorealistic interior architectural photography, coherent room layout, "
        "eye-level rectilinear lens, realistic materials, physically plausible designed lighting, "
        "clear furniture silhouettes, no people."
    )
    negative = "panorama, 360 view, equirectangular, fisheye, warped walls, text, watermark, blurry, low quality"
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": 1024, "height": 768, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": secrets.randbits(63), "steps": 20, "cfg": 5.0, "sampler_name": "euler", "scheduler": "simple", "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0], "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "living_room/canon"}},
    }


async def generate_canon_image(concept: SceneConcept, session_id: str, attempt: int = 1) -> Path:
    """Generate a canon image, preferring the installed local FLUX.2 stack."""
    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if COMFYUI_ENABLED:
        try:
            result = await _generate_with_comfyui(concept.image_prompt, output_path, session_id)
            _LAST_PROVIDER[session_id] = "FLUX.2 Klein · ComfyUI"
            return result
        except Exception as exc:
            print(f"ComfyUI generation failed: {exc}")
    if IMAGE_API_URL:
        try:
            result = await _generate_with_api(concept.image_prompt, output_path)
            _LAST_PROVIDER[session_id] = "Image API"
            return result
        except Exception as exc:
            print(f"Image API generation failed: {exc}")
    _LAST_PROVIDER[session_id] = "Mock fallback"
    return _generate_mock(concept.image_prompt, output_path)


async def _generate_with_comfyui(prompt: str, output_path: Path, session_id: str) -> Path:
    workflow = _flux_workflow(prompt)
    timeout = httpx.Timeout(30, read=COMFYUI_TIMEOUT, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow, "client_id": f"living-room-{session_id}"})
        if response.status_code != 200:
            raise RuntimeError(f"ComfyUI rejected workflow ({response.status_code}): {response.text[:500]}")
        prompt_id = response.json().get("prompt_id")
        if not prompt_id:
            raise RuntimeError("ComfyUI returned no prompt id")
        started = time.monotonic()
        while time.monotonic() - started < COMFYUI_TIMEOUT:
            await asyncio.sleep(0.75)
            history_response = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
            history_response.raise_for_status()
            entry = history_response.json().get(prompt_id)
            if not entry:
                continue
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI execution failed: {status}")
            for output in entry.get("outputs", {}).values():
                for image in output.get("images", []):
                    image_response = await client.get(f"{COMFYUI_URL}/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                    image_response.raise_for_status()
                    output_path.write_bytes(image_response.content)
                    return output_path
            if status.get("completed"):
                raise RuntimeError("ComfyUI completed without an image")
    raise TimeoutError(f"ComfyUI did not finish within {COMFYUI_TIMEOUT} seconds")


async def _generate_with_api(prompt: str, output_path: Path) -> Path:
    headers = {"Authorization": f"Bearer {IMAGE_API_KEY}"} if IMAGE_API_KEY else {}
    async with httpx.AsyncClient(timeout=COMFYUI_TIMEOUT) as client:
        response = await client.post(f"{IMAGE_API_URL}/images/generations", headers=headers, json={"prompt": prompt, "n": 1, "size": "1024x768"})
        response.raise_for_status()
        item = response.json()["data"][0]
        if item.get("b64_json"):
            output_path.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            image_response = await client.get(item["url"])
            image_response.raise_for_status()
            output_path.write_bytes(image_response.content)
        else:
            raise RuntimeError("Image API returned no image data")
    return output_path


def _conditioned_flux_workflow(prompt: str, image_name: str) -> dict:
    """FLUX.2 reference-latent graph that preserves approved blockout geometry."""
    positive = (
        f"{prompt}. Transform the supplied blockout into a photorealistic interior photograph. "
        "STRICTLY preserve camera position, lens perspective, room proportions, wall openings, "
        "object count, placement, scale, and silhouettes. Change only materials, textures, "
        "lighting, atmosphere, and rendering quality. No people."
    )
    negative = (
        "changed layout, changed camera, moved furniture, added furniture, missing furniture, "
        "warped walls, fisheye, panorama, text, watermark, illustration, low quality"
    )
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": FLUX_VAE}},
        "4": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "5": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "megapixels": 0.8, "resolution_steps": 16}},
        "6": {"class_type": "GetImageSize", "inputs": {"image": ["5", 0]}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["2", 0]}},
        "9": {"class_type": "ReferenceLatent", "inputs": {"conditioning": ["8", 0], "latent": ["7", 0]}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
        "11": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": ["6", 0], "height": ["6", 1], "batch_size": 1}},
        "12": {"class_type": "Flux2Scheduler", "inputs": {"steps": 20, "width": ["6", 0], "height": ["6", 1]}},
        "13": {"class_type": "RandomNoise", "inputs": {"noise_seed": secrets.randbits(63)}},
        "14": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "15": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["9", 0], "negative": ["10", 0], "cfg": 3.5}},
        "16": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["13", 0], "guider": ["15", 0], "sampler": ["14", 0], "sigmas": ["12", 0], "latent_image": ["11", 0]}},
        "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 1], "vae": ["3", 0]}},
        "18": {"class_type": "SaveImage", "inputs": {"images": ["17", 0], "filename_prefix": "living_room/conditioned_canon"}},
    }


async def generate_conditioned_canon(
    concept: SceneConcept,
    blockout_path: Path,
    session_id: str,
    attempt: int = 1,
) -> Path:
    """Generate canon appearance from the approved camera-matched blockout."""
    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if COMFYUI_ENABLED:
        try:
            timeout = httpx.Timeout(30, read=COMFYUI_TIMEOUT, write=30, pool=30)
            async with httpx.AsyncClient(timeout=timeout) as client:
                with blockout_path.open("rb") as image_file:
                    upload = await client.post(
                        f"{COMFYUI_URL}/upload/image",
                        files={"image": (blockout_path.name, image_file, "image/png")},
                        data={"overwrite": "true"},
                    )
                upload.raise_for_status()
                uploaded = upload.json()
                image_name = "/".join(part for part in (uploaded.get("subfolder", ""), uploaded.get("name", blockout_path.name)) if part)
                workflow = _conditioned_flux_workflow(concept.image_prompt, image_name)
                result = await _run_comfy_workflow(client, workflow, output_path, session_id)
            _LAST_PROVIDER[session_id] = "FLUX.2 Klein · blockout conditioned"
            return result
        except Exception as exc:
            print(f"Conditioned ComfyUI generation failed: {exc}")
    return await generate_canon_image(concept, session_id, attempt)


async def _run_comfy_workflow(
    client: httpx.AsyncClient,
    workflow: dict,
    output_path: Path,
    session_id: str,
) -> Path:
    response = await client.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow, "client_id": f"living-room-{session_id}"},
    )
    if response.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow ({response.status_code}): {response.text[:500]}")
    prompt_id = response.json().get("prompt_id")
    if not prompt_id:
        raise RuntimeError("ComfyUI returned no prompt id")
    started = time.monotonic()
    while time.monotonic() - started < COMFYUI_TIMEOUT:
        await asyncio.sleep(0.75)
        history = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
        history.raise_for_status()
        entry = history.json().get(prompt_id)
        if not entry:
            continue
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            raise RuntimeError(f"ComfyUI execution failed: {status}")
        for output in entry.get("outputs", {}).values():
            for image in output.get("images", []):
                result = await client.get(f"{COMFYUI_URL}/view", params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                result.raise_for_status()
                output_path.write_bytes(result.content)
                return output_path
        if status.get("completed"):
            raise RuntimeError("ComfyUI completed without an image")
    raise TimeoutError(f"ComfyUI did not finish within {COMFYUI_TIMEOUT} seconds")
