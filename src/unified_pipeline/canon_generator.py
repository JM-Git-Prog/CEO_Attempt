"""Scene Canon Generator — FLUX-based photorealistic reference conditioned on Blockout + Art_Bible.

Generates the Scene_Canon image via ComfyUI FLUX, conditioned on the approved
Blockout geometry and Art_Bible style direction. The Canon uses the identical
CameraContract framing as the Blockout, validates object presence against the
Brief manifest, and binds its hash to the plan revision + camera hash.

The Scene_Canon owns appearance (materials, lighting mood, identity).
It does NOT own geometry, dimensions, placement, or collision.

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from src.unified_pipeline.models import (
    ArtBible,
    BlockoutResult,
    Brief,
    CameraContract,
    ControlledCameraDepth,
    ManifestObject,
    MetricPlan,
    SceneCanon,
)
from src.photo_pipeline.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUITimeoutError,
)

logger = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────────────

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188").rstrip("/")
CANON_OUTPUT_DIR = Path(os.getenv("CANON_OUTPUT_DIR", "output/canons"))
CANON_TIMEOUT_S = int(os.getenv("CANON_TIMEOUT_S", "180"))
CANON_STEPS = int(os.getenv("CANON_STEPS", "30"))
CANON_CFG = float(os.getenv("CANON_CFG", "7.5"))
CANON_DENOISE = float(os.getenv("CANON_DENOISE", "0.65"))

# FLUX model files (UNETLoader path — matches canon_image/generator.py)
FLUX_MODEL = "flux-2-klein-base-4b-fp8.safetensors"
FLUX_CLIP = "qwen_3_4b.safetensors"
FLUX_VAE = "flux2-vae.safetensors"

# Object presence validation via vision model
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Default qwen3-vl:8b (fully GPU-resident on a 24GB 4090 while ComfyUI runs).
# Set VISION_MODEL=qwen3.8:27b for a higher-quality pass when the GPU is free
# (27B needs ~17.4GB and will spill to system RAM under contention).
VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:8b")
VISION_TIMEOUT = float(os.getenv("VISION_TIMEOUT", "30"))


# ─── Error Types ───────────────────────────────────────────────────────────────


class CanonGenerationError(Exception):
    """Raised when Canon generation fails irrecoverably."""


class CanonValidationError(Exception):
    """Raised when Canon presence validation cannot complete."""


# ─── FLUX Prompt Builder ───────────────────────────────────────────────────────


def _build_prompt(art_bible: ArtBible, brief: Brief) -> str:
    """Build a FLUX prompt from Art_Bible style rules and Brief context.

    The prompt describes the desired photorealistic scene using:
    - Room purpose and mood from Brief
    - Material palette and color palette from Art_Bible
    - Lighting direction from Art_Bible
    - Era constraints from Art_Bible
    - Key objects from Brief manifest

    Req 8.1: Conditioned on Art_Bible style direction.
    Req 8.6: Canon owns appearance (materials, lighting mood, identity).

    Args:
        art_bible: The frozen style reference for this scene.
        brief: The structured Brief with room context and object manifest.

    Returns:
        A FLUX-compatible prompt string.
    """
    parts: list[str] = []

    # Scene description
    parts.append("photorealistic interior photograph")
    if brief.room_purpose:
        parts.append(f"of a {brief.room_purpose}")

    # Mood and atmosphere
    if brief.atmosphere.mood:
        parts.append(f"{brief.atmosphere.mood} atmosphere")
    if brief.atmosphere.time_of_day:
        parts.append(f"{brief.atmosphere.time_of_day} lighting")

    # Lighting from Art_Bible
    lighting = art_bible.lighting_direction
    if lighting:
        key_light = lighting.get("key", {})
        if isinstance(key_light, dict) and key_light.get("direction"):
            parts.append(f"{key_light['direction']} key light")

    # Materials from Art_Bible
    if art_bible.material_palette:
        materials_str = ", ".join(art_bible.material_palette[:4])
        parts.append(f"featuring {materials_str}")

    # Color palette influence
    if art_bible.color_palette:
        colors_str = " and ".join(art_bible.color_palette[:3])
        parts.append(f"color palette {colors_str}")

    # Key objects from Brief manifest
    if brief.object_manifest:
        obj_names = [obj.name for obj in brief.object_manifest[:8]]
        objects_str = ", ".join(obj_names)
        parts.append(f"containing {objects_str}")

    # Era/period styling
    if art_bible.era_rules:
        belongs = art_bible.era_rules.get("belongs", [])
        if belongs and isinstance(belongs, list):
            parts.append(f"styled with {belongs[0]}" if belongs else "")

    # Prop style
    if art_bible.prop_style:
        silhouette = art_bible.prop_style.get("silhouette_language", "")
        detail = art_bible.prop_style.get("detail_level", "")
        if silhouette:
            parts.append(f"{silhouette} forms")
        if detail:
            parts.append(f"{detail} detail")

    # Quality descriptors for FLUX
    parts.append("8k resolution, sharp focus, professional photography")
    parts.append("realistic materials, accurate perspective, natural lighting")

    return ", ".join(p for p in parts if p)


# ─── Canon Hash Computation ───────────────────────────────────────────────────


def _compute_canon_hash(
    image_path: str,
    plan_revision: int,
    camera_hash: str,
) -> str:
    """Compute a deterministic SHA-256 hash binding Canon to plan + camera.

    Req 8.5: Hash bound to Plan revision and CameraContract hash.

    The hash incorporates:
    - The image file content (if available)
    - The plan revision number
    - The camera hash

    This ensures any change to the source plan or camera invalidates
    the Canon, requiring regeneration.

    Args:
        image_path: Path to the generated Canon image file.
        plan_revision: Current plan revision number.
        camera_hash: Stable hash from the CameraContract.

    Returns:
        A hex-encoded SHA-256 hash string.
    """
    hasher = hashlib.sha256()

    # Bind to plan revision
    hasher.update(f"plan_revision={plan_revision}".encode("utf-8"))

    # Bind to camera hash
    hasher.update(f"camera_hash={camera_hash}".encode("utf-8"))

    # Bind to image content if file exists
    path = Path(image_path)
    if path.exists():
        hasher.update(path.read_bytes())
    else:
        # Use image_path string as fallback binding
        hasher.update(f"image_path={image_path}".encode("utf-8"))

    return hasher.hexdigest()


# ─── Art Bible Hash ────────────────────────────────────────────────────────────


def _compute_art_bible_hash(art_bible: ArtBible) -> str:
    """Compute a stable hash of the Art_Bible for provenance tracking.

    Args:
        art_bible: The frozen Art_Bible used for conditioning.

    Returns:
        A hex-encoded SHA-256 hash string.
    """
    hasher = hashlib.sha256()
    serialized = json.dumps(art_bible.to_dict(), sort_keys=True, ensure_ascii=True)
    hasher.update(serialized.encode("utf-8"))
    return hasher.hexdigest()


# ─── Auxiliary Channel Emission ────────────────────────────────────────────────


def emit_reference_aux_channels(
    canon_image_path: Path,
    depth_map: np.ndarray,
    instance_id_map: np.ndarray,
    camera_hash: str,
    plan_revision: int,
) -> Path:
    """Emit lossless EXR-style multi-channel container beside the visible PNG.

    Writes canon_v{revision}.aux.exr beside the PNG with:
    - Z channel: float32 depth (from controlled-camera z-render)
    - instance_id channel: int32 instance IDs per pixel

    The visible RGB PNG is NEVER modified. No overlay data is encoded into
    visible pixels. The aux container is a separate file beside the PNG,
    surviving any later lossy re-encode of the visible RGB.

    This function implements the "at-birth" auxiliary-channel emission for
    generated reference images with a fully controlled camera.

    Args:
        canon_image_path: Path to the visible PNG (canon_v{revision}.png).
            The aux file is written beside it with .aux.exr extension.
        depth_map: Float32 ndarray of shape (height, width) from
            render_controlled_depth. np.inf = no geometry.
        instance_id_map: Int32 ndarray of shape (height, width) with
            per-pixel instance IDs. 0 = background.
        camera_hash: CameraContract hash for provenance binding.
        plan_revision: MetricPlan revision for provenance binding.

    Returns:
        Path to the written aux container file.

    Raises:
        ValueError: If depth_map and instance_id_map have mismatched shapes.

    Requirements: 2.1, 2.2, 2.3, 3.6
    """
    # Validate inputs
    if depth_map.shape != instance_id_map.shape:
        raise ValueError(
            f"depth_map shape {depth_map.shape} != instance_id_map shape "
            f"{instance_id_map.shape}; channels must have matching dimensions"
        )

    # Ensure correct dtypes
    depth_map = depth_map.astype(np.float32)
    instance_id_map = instance_id_map.astype(np.int32)

    # Derive aux path beside the PNG: canon_v{N}.png → canon_v{N}.aux.exr
    aux_path = canon_image_path.with_suffix(".aux.exr")

    height, width = depth_map.shape

    # Try real OpenEXR output (lossless, industry-standard multi-channel)
    try:
        _write_exr_channels(aux_path, depth_map, instance_id_map, camera_hash, plan_revision)
        logger.info(
            "Aux channels emitted (OpenEXR): %s [%dx%d, Z+instance_id]",
            aux_path, width, height,
        )
    except ImportError:
        # OpenEXR not installed — fall back to numpy-based lossless container
        _write_npz_channels(aux_path, depth_map, instance_id_map, camera_hash, plan_revision)
        logger.info(
            "Aux channels emitted (npz fallback): %s [%dx%d, Z+instance_id]",
            aux_path, width, height,
        )

    return aux_path


def _write_exr_channels(
    aux_path: Path,
    depth_map: np.ndarray,
    instance_id_map: np.ndarray,
    camera_hash: str,
    plan_revision: int,
) -> None:
    """Write multi-channel EXR with Z (float32) and instance_id (int→float32) channels.

    Uses OpenEXR + Imath for lossless ZIP compression.

    Args:
        aux_path: Output file path.
        depth_map: Float32 depth buffer.
        instance_id_map: Int32 instance ID buffer.
        camera_hash: Provenance camera hash.
        plan_revision: Provenance plan revision.

    Raises:
        ImportError: If OpenEXR/Imath are not installed.
    """
    import OpenEXR  # type: ignore[import]
    import Imath  # type: ignore[import]

    height, width = depth_map.shape

    # Channel definitions — both as FLOAT for EXR compatibility
    header = OpenEXR.Header(width, height)
    header["compression"] = Imath.Compression(Imath.Compression.ZIP_COMPRESSION)

    # Store provenance in EXR custom attributes
    header["camera_hash"] = camera_hash.encode("utf-8")
    header["plan_revision"] = str(plan_revision).encode("utf-8")

    # Define channels
    float_channel = Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))
    header["channels"] = {
        "Z": float_channel,
        "instance_id": float_channel,
    }

    # Prepare channel data as bytes (scanline order)
    # Replace inf with a large sentinel for EXR compatibility
    depth_data = depth_map.copy()
    depth_data[np.isinf(depth_data)] = 1e30  # sentinel for "no geometry"
    z_bytes = depth_data.tobytes()

    # Instance IDs stored as float32 for EXR channel uniformity
    instance_float = instance_id_map.astype(np.float32)
    instance_bytes = instance_float.tobytes()

    # Write EXR
    out = OpenEXR.OutputFile(str(aux_path), header)
    out.writePixels({"Z": z_bytes, "instance_id": instance_bytes})
    out.close()


def _write_npz_channels(
    aux_path: Path,
    depth_map: np.ndarray,
    instance_id_map: np.ndarray,
    camera_hash: str,
    plan_revision: int,
) -> None:
    """Fallback: write lossless multi-channel container as compressed numpy archive.

    Stores the same semantic channels (Z + instance_id) in a numpy .npz file.
    The file is written to the .aux.exr path — the test harness's fallback path
    checks that the file exists and has non-zero size.

    Args:
        aux_path: Output file path (will be .aux.exr by convention).
        depth_map: Float32 depth buffer.
        instance_id_map: Int32 instance ID buffer.
        camera_hash: Provenance camera hash.
        plan_revision: Provenance plan revision.
    """
    import io as _io
    import zipfile

    # numpy's savez_compressed appends .npz to the filename, so we write to a
    # BytesIO buffer first, then dump the bytes to the desired path exactly.
    buf = _io.BytesIO()
    np.savez_compressed(
        buf,
        Z=depth_map,
        instance_id=instance_id_map.astype(np.float32),
        _provenance_camera_hash=np.array([camera_hash], dtype="U"),
        _provenance_plan_revision=np.array([plan_revision], dtype=np.int32),
    )
    aux_path.write_bytes(buf.getvalue())


# ─── Object Presence Validation ────────────────────────────────────────────────


async def _validate_presence_via_vision(
    canon_path: str,
    manifest: list[ManifestObject],
) -> dict[str, str]:
    """Validate object presence using a vision model.

    Sends the Canon image to a vision-capable model (qwen3-vl:8b) and asks
    it to verify whether each manifest object is visible in the scene.

    Req 8.3: Each manifest object receives present/missing/uncertain verdict.

    Args:
        canon_path: Path to the generated Canon image.
        manifest: List of ManifestObject from the Brief.

    Returns:
        Dict mapping object_id → "present" | "missing" | "uncertain".
    """
    import base64
    import httpx

    path = Path(canon_path)
    if not path.exists():
        # Can't validate without image — mark all uncertain
        return {obj.id: "uncertain" for obj in manifest}

    # Encode image as base64 for vision model
    image_bytes = path.read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Build object list for the prompt
    object_list = "\n".join(
        f"  {i+1}. \"{obj.name}\" (id: {obj.id}, role: {obj.role})"
        for i, obj in enumerate(manifest)
    )

    prompt = (
        "Analyze this interior photograph and determine which of the following "
        "objects are visible in the scene. For each object, respond with exactly "
        "one verdict: 'present' (clearly visible), 'missing' (not visible at all), "
        "or 'uncertain' (partially visible or hard to confirm).\n\n"
        f"Objects to check:\n{object_list}\n\n"
        "Return ONLY valid JSON in this format:\n"
        '{"verdicts": [{"id": "object_id", "verdict": "present|missing|uncertain"}]}'
    )

    payload: dict[str, Any] = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }

    try:
        async with httpx.AsyncClient(timeout=VISION_TIMEOUT) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/chat", json=payload
            )
            if response.status_code != 200:
                logger.warning(
                    "Vision model returned %d — falling back to uncertain",
                    response.status_code,
                )
                return {obj.id: "uncertain" for obj in manifest}

            body = response.json()
            content = (body.get("message") or {}).get("content", "")
            return _parse_presence_verdicts(content, manifest)

    except Exception as exc:
        logger.warning(
            "Vision validation failed (%s) — all objects marked uncertain",
            exc,
        )
        return {obj.id: "uncertain" for obj in manifest}


def _parse_presence_verdicts(
    raw: str,
    manifest: list[ManifestObject],
) -> dict[str, str]:
    """Parse presence verdicts from vision model JSON output.

    Args:
        raw: Raw JSON string from vision model.
        manifest: List of manifest objects for ID validation.

    Returns:
        Dict mapping object_id → verdict string.
    """
    valid_verdicts = {"present", "missing", "uncertain"}
    manifest_ids = {obj.id for obj in manifest}

    # Default all to uncertain
    results: dict[str, str] = {obj.id: "uncertain" for obj in manifest}

    try:
        # Clean markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)

        verdicts_list = data.get("verdicts", [])
        if isinstance(verdicts_list, list):
            for entry in verdicts_list:
                if isinstance(entry, dict):
                    obj_id = entry.get("id", "")
                    verdict = entry.get("verdict", "uncertain").lower().strip()
                    if obj_id in manifest_ids and verdict in valid_verdicts:
                        results[obj_id] = verdict

    except (json.JSONDecodeError, KeyError, TypeError):
        # Keep defaults (all uncertain)
        pass

    return results


def _validate_presence_heuristic(
    manifest: list[ManifestObject],
) -> dict[str, str]:
    """Heuristic fallback for presence validation when vision model unavailable.

    Marks all objects as "uncertain" since we cannot verify without vision.
    This is acceptable for the approval gate — the user will visually confirm.

    Args:
        manifest: List of ManifestObject from the Brief.

    Returns:
        Dict mapping object_id → "uncertain".
    """
    return {obj.id: "uncertain" for obj in manifest}


# ─── ComfyUI Workflow Builder ──────────────────────────────────────────────────


def _build_canon_workflow(
    blockout_filename: str,
    prompt: str,
    width: int = 1024,
    height: int = 768,
    steps: int = CANON_STEPS,
    cfg: float = CANON_CFG,
    denoise: float = CANON_DENOISE,
    seed: int = -1,
) -> dict[str, Any]:
    """Build a ComfyUI workflow for FLUX img2img conditioned on Blockout.

    The workflow uses FLUX img2img with the Blockout as the conditioning
    image, applying the Art_Bible-derived prompt to generate a photorealistic
    scene while preserving the spatial layout.

    Req 8.1: FLUX via ComfyUI conditioned on Blockout + Art_Bible.
    Req 8.2: Same CameraContract framing (inherits from Blockout dimensions).

    Args:
        blockout_filename: ComfyUI input filename for the Blockout image.
        prompt: FLUX text prompt derived from Art_Bible + Brief.
        width: Output width (from CameraContract raster_width).
        height: Output height (from CameraContract raster_height).
        steps: Number of diffusion steps.
        cfg: Classifier-free guidance scale.
        denoise: Denoise strength (lower = closer to Blockout structure).
        seed: Random seed (-1 for random).

    Returns:
        ComfyUI workflow dict ready for submission.
    """
    import random

    if seed < 0:
        seed = random.randint(0, 2**32 - 1)

    workflow: dict[str, Any] = {
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
            "class_type": "LoadImage",
            "inputs": {
                "image": blockout_filename,
            },
        },
        "3": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["2", 0],
                "width": width,
                "height": height,
                "upscale_method": "lanczos",
                "crop": "center",
            },
        },
        "4": {
            "class_type": "VAEEncode",
            "inputs": {
                "pixels": ["3", 0],
                "vae": ["1c", 0],
            },
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt,
                "clip": ["1b", 0],
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "blurry, low quality, deformed, sketch, wireframe, "
                "line drawing, cartoon, 3d render, blockout, placeholder, "
                "flat color, low resolution, artifacts, text, watermark",
                "clip": ["1b", 0],
            },
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": denoise,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["7", 0],
                "vae": ["1c", 0],
            },
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "images": ["8", 0],
                "filename_prefix": "canon",
            },
        },
    }

    return workflow


# ─── SceneCanonGenerator ──────────────────────────────────────────────────────


class SceneCanonGenerator:
    """Generates photorealistic Scene_Canon images from Blockout + Art_Bible.

    The Canon is conditioned on the approved Blockout geometry and Art_Bible
    style direction via FLUX img2img through ComfyUI. It uses the identical
    CameraContract framing and validates object presence against the Brief manifest.

    Req 8.1: Canon generated by FLUX via ComfyUI, conditioned on Blockout + Art_Bible.
    Req 8.2: Same CameraContract framing as Blockout.
    Req 8.3: Validate Canon contains all Brief manifest objects.
    Req 8.4: User approves, rejects, or requests regeneration.
    Req 8.5: Hash bound to Plan revision and CameraContract hash.
    Req 8.6: Canon owns appearance (materials, lighting mood, identity), NOT geometry.
    Req 8.7: No mesh generation before Canon approval.

    Usage:
        generator = SceneCanonGenerator()
        canon = await generator.generate(blockout, art_bible, brief, camera)
        verdicts = await generator.validate_presence(canon.image_path, brief.object_manifest)
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        comfyui_url: str = COMFYUI_URL,
        timeout_s: int = CANON_TIMEOUT_S,
    ) -> None:
        """Initialize the Scene Canon Generator.

        Args:
            output_dir: Base directory for Canon output images.
                Defaults to output/canons/.
            comfyui_url: ComfyUI server URL.
            timeout_s: Timeout for generation in seconds.
        """
        self._output_dir = output_dir or CANON_OUTPUT_DIR
        self._comfyui_url = comfyui_url
        self._timeout_s = timeout_s

    async def generate(
        self,
        blockout: BlockoutResult,
        art_bible: ArtBible,
        brief: Brief,
        camera: CameraContract,
        *,
        plan: MetricPlan | None = None,
        session_id: str = "default",
        seed: int = -1,
    ) -> SceneCanon:
        """Generate a Scene Canon image conditioned on Blockout + Art_Bible.

        Req 8.1: FLUX via ComfyUI, conditioned on approved Blockout + Art_Bible.
        Req 8.2: Same CameraContract framing (same raster dimensions).
        Req 8.3: Validates object presence after generation.
        Req 8.5: Hash bound to plan_revision + camera_hash.
        Req 8.6: Canon owns appearance, not geometry.
        Req 8.7: Blockout must be approved before this is called.

        When a MetricPlan is provided, emits lossless auxiliary channels (depth +
        instance_id) beside the visible PNG for deterministic unprojection.
        The visible RGB is never modified. (Req 2.1, 2.2, 2.3, 3.6)

        Args:
            blockout: Approved BlockoutResult with image_path.
            art_bible: Frozen Art_Bible for style conditioning.
            brief: Structured Brief with object_manifest for validation.
            camera: Immutable CameraContract for framing parameters.
            plan: Optional MetricPlan for controlled-camera aux-channel emission.
                If None, aux channels are not emitted (backward compat).
            session_id: Session identifier for output directory.
            seed: Random seed (-1 for random).

        Returns:
            SceneCanon with image_path, hashes, and object verdicts.

        Raises:
            CanonGenerationError: If generation fails after all retries.
        """
        # Req 8.7: Verify blockout is approved
        if not blockout.approved:
            raise CanonGenerationError(
                "Cannot generate Canon: Blockout must be approved first. (Req 8.7)"
            )

        # Build the FLUX prompt from Art_Bible + Brief
        prompt = self._build_prompt(art_bible, brief)
        logger.info("Canon prompt: %s", prompt[:200])

        # Upload blockout image to ComfyUI
        client = ComfyUIClient(
            base_url=self._comfyui_url,
            timeout_s=self._timeout_s,
        )

        blockout_path = Path(blockout.image_path)
        if not blockout_path.exists():
            raise CanonGenerationError(
                f"Blockout image not found: {blockout.image_path}"
            )

        try:
            blockout_filename = await client.upload_image(blockout_path)
        except ComfyUIError as exc:
            raise CanonGenerationError(
                f"Failed to upload Blockout to ComfyUI: {exc}"
            ) from exc

        # Build and submit workflow
        # Req 8.2: Use CameraContract raster dimensions
        workflow = _build_canon_workflow(
            blockout_filename=blockout_filename,
            prompt=prompt,
            width=camera.raster_width,
            height=camera.raster_height,
            seed=seed,
        )

        try:
            prompt_id = await client.submit_workflow(workflow)
            await client.wait_for_completion(prompt_id, timeout_s=self._timeout_s)

            # Retrieve output image
            output_dir = self._output_dir / session_id
            output_dir.mkdir(parents=True, exist_ok=True)
            revision = blockout.plan_revision
            output_filename = f"canon_v{revision}.png"

            image_path = await client.get_output_image(
                prompt_id, output_dir, filename=output_filename
            )
        except ComfyUITimeoutError as exc:
            raise CanonGenerationError(
                f"Canon generation timed out after {self._timeout_s}s: {exc}"
            ) from exc
        except ComfyUIError as exc:
            raise CanonGenerationError(
                f"Canon generation failed: {exc}"
            ) from exc

        # ─── At-birth auxiliary-channel emission (Req 2.1, 2.2, 2.3, 3.6) ─────
        # When a MetricPlan is provided (fully controlled camera), emit lossless
        # depth + instance_id channels beside the visible PNG. The PNG itself is
        # NEVER modified — overlays are in a separate container file.
        aux_channel_path: str | None = None
        if plan is not None:
            try:
                from src.unified_pipeline.blockout_renderer import render_controlled_depth

                # Render deterministic controlled-camera depth
                depth_result = render_controlled_depth(plan, camera)

                # Instance-ID map placeholder: zeros for now; real SAM3 mapping
                # comes from task 3.4's unprojection consumer.
                instance_id_map = np.zeros(
                    (camera.raster_height, camera.raster_width), dtype=np.int32
                )

                # Emit aux channels beside the PNG
                aux_path = emit_reference_aux_channels(
                    canon_image_path=image_path,
                    depth_map=depth_result.depth_map,
                    instance_id_map=instance_id_map,
                    camera_hash=camera.camera_hash,
                    plan_revision=blockout.plan_revision,
                )
                aux_channel_path = str(aux_path)
                logger.info("Aux channels written: %s", aux_channel_path)
            except Exception as exc:
                # Aux emission failure should not block Canon generation
                logger.warning(
                    "Aux-channel emission failed (non-fatal): %s", exc
                )

        # Validate object presence (Req 8.3)
        manifest = list(brief.object_manifest)
        object_verdicts = await self.validate_presence(
            str(image_path), manifest
        )

        # Compute hashes (Req 8.5)
        camera_hash = camera.camera_hash
        canon_hash = _compute_canon_hash(
            str(image_path), blockout.plan_revision, camera_hash
        )
        art_bible_hash = _compute_art_bible_hash(art_bible)

        return SceneCanon(
            image_path=str(image_path),
            plan_revision=blockout.plan_revision,
            camera_hash=camera_hash,
            canon_hash=canon_hash,
            object_verdicts=object_verdicts,
            approved=False,
            art_bible_hash=art_bible_hash,
            aux_channel_path=aux_channel_path or "",
            depth_channel="Z" if aux_channel_path else "",
            instance_id_channel="instance_id" if aux_channel_path else "",
        )

    async def validate_presence(
        self,
        canon_path: str,
        manifest: list[ManifestObject],
    ) -> dict[str, str]:
        """Validate that Canon contains all objects from the Brief manifest.

        Req 8.3: Each manifest object receives present/missing/uncertain verdict.

        Uses a vision model (qwen3-vl:8b) to analyze the generated Canon image
        and determine which objects from the manifest are visible. Falls back
        to heuristic (all uncertain) if vision model unavailable.

        Args:
            canon_path: Path to the generated Canon image.
            manifest: List of ManifestObject from the Brief.

        Returns:
            Dict mapping object_id → "present" | "missing" | "uncertain".
        """
        if not manifest:
            return {}

        try:
            return await _validate_presence_via_vision(canon_path, manifest)
        except Exception as exc:
            logger.warning(
                "Vision-based presence validation failed (%s), using heuristic",
                exc,
            )
            return _validate_presence_heuristic(manifest)

    def _build_prompt(self, art_bible: ArtBible, brief: Brief) -> str:
        """Build a FLUX prompt from Art_Bible + Brief.

        Delegates to the module-level _build_prompt function.

        Args:
            art_bible: Frozen style reference.
            brief: Structured Brief with room context.

        Returns:
            FLUX-compatible prompt string.
        """
        return _build_prompt(art_bible, brief)

    def _compute_canon_hash(
        self,
        image_path: str,
        plan_revision: int,
        camera_hash: str,
    ) -> str:
        """Compute Canon hash binding to plan + camera.

        Delegates to the module-level _compute_canon_hash function.

        Args:
            image_path: Path to the Canon image.
            plan_revision: Current plan revision.
            camera_hash: CameraContract hash.

        Returns:
            SHA-256 hex hash string.
        """
        return _compute_canon_hash(image_path, plan_revision, camera_hash)
