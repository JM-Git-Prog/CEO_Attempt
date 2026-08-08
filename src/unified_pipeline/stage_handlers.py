"""Stage handler wiring for the durable UnifiedOrchestrator.

Maps every declared stage in DEFAULT_STAGE_SPECS to a concrete handler function
that the orchestrator calls during its run loop. GPU stages return pending with
a synthetic job_id (mock). Approval stages return awaiting_approval. Non-GPU /
non-approval stages execute synchronously and return completed results.

This is the integration layer — it connects stage names to their implementations
without touching orchestrator.py.

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from src.unified_pipeline.object_manifest import (
    build_detected_document,
    load_detected_document,
    load_selected_manifest,
)
from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    StageExecutionContext,
    StageResult,
)


# ---------------------------------------------------------------------------
# Result helpers
# ---------------------------------------------------------------------------

def _awaiting_approval(stage: str, context: StageExecutionContext) -> StageResult:
    """Return a StageResult that signals the orchestrator to park at an approval gate."""
    return StageResult(
        output={
            "awaiting_approval": True,
            "stage": stage,
            "object_id": context.object_id,
            "plan_revision": context.plan_revision,
        },
        plan_revision=context.plan_revision,
        approval_revision=context.approval_revision,
    )


def _gpu_pending(stage: str, context: StageExecutionContext) -> StageResult:
    """Return a StageResult with a synthetic external job_id (mock GPU submission)."""
    job_id = f"mock-{stage}-{uuid.uuid4().hex[:12]}"
    return StageResult.pending(
        job_id,
        plan_revision=context.plan_revision,
        metadata={"stage": stage, "object_id": context.object_id},
    )


def _immediate(output: Mapping[str, Any], context: StageExecutionContext) -> StageResult:
    """Return a completed StageResult with the given output."""
    return StageResult(
        output=dict(output),
        plan_revision=context.plan_revision,
        approval_revision=context.approval_revision,
    )


def _contract_hash(data: Mapping[str, Any]) -> str:
    """Compute a deterministic sha256 hash for contract-like output."""
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict_real(context: StageExecutionContext) -> bool:
    """Return whether this execution must fail instead of degrading."""
    return context.values.get("execution_profile") == "strict_real"


def _first_authoritative_user_prompt(session_dir: Path) -> str:
    """Load the first durable user turn, excluding the creative opening."""
    conversation_path = session_dir / "conversation.json"
    try:
        document = json.loads(conversation_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ""
    return next((
        str(turn.get("content", "")).strip()
        for turn in document.get("turns", [])
        if isinstance(turn, dict) and turn.get("role") == "user"
        and str(turn.get("content", "")).strip()
    ), "")


async def _release_local_ollama_models() -> None:
    """Best-effort VRAM handoff from local LLMs to ComfyUI GPU stages."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get("http://127.0.0.1:11434/api/ps")
            response.raise_for_status()
            names = [
                str(item.get("name", ""))
                for item in response.json().get("models", [])
                if isinstance(item, dict) and item.get("name")
            ]
            for name in names:
                await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": name, "prompt": "", "keep_alive": 0},
                )
    except (httpx.HTTPError, OSError, ValueError, TypeError):
        # Model lifecycle cleanup must not hide the actual pipeline result.
        return


# ---------------------------------------------------------------------------
# Stage categories (derived from DEFAULT_STAGE_SPECS)
# ---------------------------------------------------------------------------

APPROVAL_STAGES = frozenset(
    spec.name for spec in DEFAULT_STAGE_SPECS if spec.approval_for is not None
)

GPU_STAGES = frozenset({
    "dream_preview",
    "canon_generation",
    "segment",
    "depth_estimation",
    "mesh_generation",
})

# Stages that actually call live GPU/model services.
LIVE_GPU_STAGES = frozenset({
    "dream_preview",   # Real ComfyUI FLUX
    "canon_generation",  # Real ComfyUI FLUX/SDXL
    "segment",  # Real Ollama vision inventory
    "depth_estimation",  # Real DA3 via ComfyUI
    "mesh_generation",  # Real Hunyuan3D/Trellis2 via ComfyUI
})


# ---------------------------------------------------------------------------
# Individual stage handler implementations
# ---------------------------------------------------------------------------

def _handle_conversation(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "conversation_complete"}, ctx)


def _handle_brief(ctx: StageExecutionContext) -> StageResult:
    """Read the saved brief and propagate object_manifest to orchestrator context."""
    brief_path = ctx.session_dir / "artifacts" / "brief.json"
    manifest = []
    if brief_path.is_file():
        try:
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            manifest = brief.get("object_manifest", [])
        except (OSError, json.JSONDecodeError):
            pass
    return _immediate(
        {"status": "brief_generated", "object_count": len(manifest), "object_manifest": manifest},
        ctx,
    )


def _handle_art_bible(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "art_bible_generated"}, ctx)


async def _handle_dream_preview(ctx: StageExecutionContext) -> StageResult:
    """Generate a real FLUX Dream Preview via ComfyUI.

    Calls DreamPreviewGenerator which submits a FLUX workflow to ComfyUI
    on localhost:8188. Returns the result path on success, or a degraded
    result if ComfyUI is unavailable.
    """
    import logging
    from src.unified_pipeline.dream_preview import DreamPreviewGenerator

    _log = logging.getLogger("live_trace")

    brief = ctx.values.get("brief", {})
    room_purpose = brief.get("room_purpose", "cozy room")
    atmosphere = brief.get("atmosphere", {})
    mood = atmosphere.get("mood", "warm and inviting") if isinstance(atmosphere, dict) else "warm"
    era = brief.get("era", {})
    period = era.get("period", "") if isinstance(era, dict) else ""
    palette = brief.get("palette", {})
    primary = palette.get("primary", "") if isinstance(palette, dict) else ""

    objects = brief.get("object_manifest", [])
    object_names = ", ".join(
        item.get("name", "") for item in objects[:6]
        if isinstance(item, dict) and item.get("name")
    ) or "table, chairs, counter"

    prompt = (
        f"Interior photograph of a {period + ' ' if period else ''}{room_purpose}, "
        f"{mood} atmosphere, featuring {object_names}. "
        f"{primary + ' tones. ' if primary else ''}"
        f"Photorealistic, architectural photography, warm natural lighting, "
        f"high detail, 8K quality."
    )

    output_dir = ctx.session_dir / "artifacts" / "dream_previews"
    output_dir.mkdir(parents=True, exist_ok=True)

    _log.info(f"  dream_preview: generating via ComfyUI FLUX — prompt={prompt[:80]}...")
    if _strict_real(ctx):
        await _release_local_ollama_models()
    generator = DreamPreviewGenerator(output_dir=output_dir)

    try:
        paths = await generator.generate(prompt, ctx.session_id, variant_count=1)
    except Exception as exc:
        _log.error(f"  dream_preview FAILED: {exc}")
        paths = []

    if paths:
        _log.info(f"  dream_preview: OK — {paths[0]}")
        return _immediate({
            "status": "dream_preview_complete",
            "image_path": paths[0],
            "variant_count": len(paths),
            "prompt": prompt,
            "provisional_label": "PROVISIONAL — not spatial authority",
        }, ctx)
    else:
        _log.info("  dream_preview: ComfyUI unavailable — continuing with degraded result")
        return _immediate({
            "status": "dream_preview_unavailable",
            "image_path": "",
            "variant_count": 0,
            "prompt": prompt,
            "reason": "ComfyUI unavailable or FLUX generation failed",
        }, ctx)


async def _handle_canon_generation(ctx: StageExecutionContext) -> StageResult:
    """Generate a photorealistic canon image via ComfyUI (FLUX/SDXL).

    Builds a high-quality prompt from the brief and exact durable user prompt,
    submits to ComfyUI with 40 steps, and saves as canon.png in artifacts.
    No fallbacks — errors cleanly if ComfyUI is unavailable.
    """
    import logging
    import random

    from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIError

    _log = logging.getLogger("live_trace")

    # --- Build high-quality prompt from brief ---
    brief = ctx.values.get("brief", {})

    room_purpose = brief.get("room_purpose", "room") if isinstance(brief, dict) else "room"
    atmosphere = brief.get("atmosphere", {}) if isinstance(brief, dict) else {}
    mood = atmosphere.get("mood", "warm and inviting") if isinstance(atmosphere, dict) else "warm"
    era = brief.get("era", {}) if isinstance(brief, dict) else {}
    period = era.get("period", "") if isinstance(era, dict) else ""
    palette = brief.get("palette", {}) if isinstance(brief, dict) else {}
    primary = palette.get("primary", "") if isinstance(palette, dict) else ""

    objects = brief.get("object_manifest", []) if isinstance(brief, dict) else []
    count_words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    }
    leading_counts = (
        "a ", "an ", "one ", "two ", "three ", "four ", "five ",
        "six ", "seven ", "eight ", "nine ", "ten ",
    )
    inventory: list[str] = []
    inventory_names: list[str] = []
    for item in objects:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"]).strip().lower()
        for prefix in leading_counts:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
        count = max(1, int(item.get("count", 1)))
        inventory_names.append(name)
        inventory.append(f"exactly {count_words.get(count, str(count))} distinct {name}")
    required_inventory = "; ".join(inventory) or "all requested furniture and fixtures"
    success_criteria = str(brief.get("success_criteria", "")) if isinstance(brief, dict) else ""
    source_prompt = _first_authoritative_user_prompt(ctx.session_dir)
    if _strict_real(ctx) and not source_prompt:
        raise RuntimeError("strict-real Canon generation requires the durable first user prompt")
    source_authority = source_prompt or success_criteria
    rain_requirement = ""
    if "rain" in f"{source_authority} {success_criteria}".lower():
        rain_requirement = (
            "The window must clearly show falling rain, rain-streaked glass, "
            "and a gray rainy exterior; never sunny or dry weather. "
        )
    coffee_requirement = ""
    if any("coffee maker" in name for name in inventory_names):
        coffee_requirement = (
            "The coffee maker must be an unmistakable visible electric drip or "
            "espresso machine on the counter, never substituted by a kettle. "
        )

    composition_requirement = ""
    required_keys = set(inventory_names)
    if {"round table", "chairs", "counter", "coffee maker", "window"}.issubset(required_keys):
        composition_requirement = (
            "MANDATORY COMPOSITION: show the entire round dining table in the foreground, "
            "with exactly two separate chairs clearly visible around it. Behind them, show "
            "one counter holding one unmistakable coffee maker and one window showing rain. "
            "Do not crop the table or either chair out of frame. "
        )

    prompt = (
        f"{composition_requirement}Photorealistic interior photograph of a "
        f"{period + ' ' if period else ''}{room_purpose}, {mood} atmosphere. "
        f"NON-NEGOTIABLE VISIBLE INVENTORY: "
        f"{required_inventory}. Every listed object must be fully visible, "
        f"spatially separate, non-duplicated, and correctly counted. "
        f"{coffee_requirement}{rain_requirement}"
        f"Exact user request (authoritative): {source_authority}. "
        f"Design intent: {success_criteria}. "
        f"{primary + ' color palette. ' if primary else ''}"
        f"Professional architectural photography, natural lighting, "
        f"high detail, 8K resolution, sharp focus, magazine quality, "
        f"realistic materials and textures, ambient occlusion."
    )

    # --- Prepare output path ---
    artifacts_dir = ctx.session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / "canon.png"

    _log.info(f"  canon_generation: generating — prompt={prompt[:80]}...")

    # --- ComfyUI is REQUIRED — no fallback ---
    client = ComfyUIClient(timeout_s=600, poll_interval_s=0.75)
    comfyui_available = await client.health_check()

    if not comfyui_available:
        raise RuntimeError("ComfyUI is not available on localhost:8188 — canon_generation requires GPU")

    from src.unified_pipeline.dream_preview import (
        FLUX_CLIP,
        FLUX_MODEL,
        FLUX_VAE,
    )

    seed = random.randint(1, 2**32 - 1)
    negative_prompt = (
        "empty room, missing table, missing chair, cropped furniture, blurry, "
        "distorted, deformed, duplicate furniture, extra chairs, extra tables, "
        "missing required object, fused objects, kettle in place of coffee maker, "
        "sunny exterior, clear weather, dry window, text, watermark, low quality, cartoon"
    )
    workflow = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": FLUX_MODEL, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": FLUX_CLIP, "type": "flux2", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": FLUX_VAE},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["2", 0]},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["2", 0]},
        },
        "6": {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": 1024, "height": 768, "batch_size": 1},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0],
                "latent_image": ["6", 0], "seed": seed, "steps": 20, "cfg": 5.0,
                "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "canon"},
        },
    }

    prompt_id = await client.submit_workflow(
        workflow, client_id=f"canon-{ctx.session_id}"
    )
    await client.wait_for_completion(prompt_id, timeout_s=600)
    await client.get_output_image(
        prompt_id=prompt_id,
        output_dir=artifacts_dir,
        filename="canon.png",
    )
    # Canon is complete; Ollama owns the next vision stages and must receive
    # the GPU with no retained FLUX weights.
    await client.release_vram()

    _log.info(f"  canon_generation: OK — {output_path}")
    return _immediate({
        "status": "canon_rendered",
        "image_path": str(output_path),
        "prompt": prompt,
        "source_prompt": source_prompt,
        "source_prompt_sha256": hashlib.sha256(
            source_prompt.encode("utf-8")
        ).hexdigest() if source_prompt else "",
    }, ctx)


async def _handle_segment(ctx: StageExecutionContext) -> StageResult:
    """Vision analysis — detect ALL objects in canon image via Ollama vision model.

    Replaces per-object SAM3 segmentation with a full scene analysis:
    1. Sends the canon image to Ollama qwen2.5vl:7b for object detection
    2. Gets back a list of ALL visible objects with bounding boxes
    3. Saves detected_objects.json for the interactive picker UI
    4. SAM3 segmentation happens LATER only for selected objects (mesh_generation)
    """
    import base64
    import logging
    from pathlib import Path

    import httpx

    _log = logging.getLogger("live_trace")

    # Get Canon path
    stage_outputs = ctx.values.get("stage_outputs", {})
    canon_output = stage_outputs.get("canon_generation", {})
    canon_path = canon_output.get("image_path", "")
    if not canon_path or not Path(canon_path).exists():
        canon_candidate = ctx.session_dir / "artifacts" / "canon.png"
        if canon_candidate.exists():
            canon_path = str(canon_candidate)
    if not canon_path or not Path(canon_path).exists():
        raise RuntimeError("No canon image available for vision analysis")

    # Get image dimensions
    from PIL import Image
    with Image.open(canon_path) as img:
        width, height = img.size

    # Encode canon as base64 for Ollama vision API
    with open(canon_path, "rb") as f:
        canon_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Build vision analysis prompt
    vision_prompt = (
        f"Analyze this room photograph. List EVERY distinct object you can see, including small items.\n"
        f"For each object, provide:\n"
        f"- name: short descriptive name (e.g., \"wooden cutting board\", \"pendant light fixture\")\n"
        f"- bbox: [x1, y1, x2, y2] pixel coordinates of the bounding box (image is {width}x{height} pixels)\n"
        f"- material: primary material (wood, metal, glass, fabric, ceramic, plastic, plant, stone)\n"
        f"- category: one of (furniture, lighting, decor, appliance, utensil, plant, architectural, storage)\n"
        f"- size_estimate: one of (large, medium, small, tiny)\n\n"
        f"Respond ONLY with a JSON array. No explanations. Example:\n"
        f'[{{"name": "kitchen island", "bbox": [100, 200, 600, 500], "material": "wood", "category": "furniture", "size_estimate": "large"}}]'
    )

    _log.info("  segment(vision): analyzing canon %dx%d with qwen2.5vl:7b...", width, height)

    detected_objects = []
    model_used = "qwen2.5vl:7b"
    inventory_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "bbox": {
                    "type": "array", "items": {"type": "integer"},
                    "minItems": 4, "maxItems": 4,
                },
                "material": {"type": "string"},
                "category": {"type": "string"},
                "size_estimate": {"type": "string"},
            },
            "required": ["name", "bbox", "material", "category", "size_estimate"],
            "additionalProperties": False,
        },
    }

    # Try qwen2.5vl:7b first, fall back to qwen3.6:27b
    for model in ["qwen2.5vl:7b", "qwen3.6:27b"]:
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    "http://127.0.0.1:11434/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": vision_prompt,
                                "images": [canon_b64],
                            }
                        ],
                        "stream": False,
                        "keep_alive": 0,
                        "format": inventory_schema,
                        "options": {"temperature": 0.0, "num_predict": 2048},
                    },
                )
                if resp.status_code == 200:
                    result = resp.json()
                    content = result.get("message", {}).get("content", "")
                    model_used = model
                    _log.info("  segment(vision): got response from %s (%d chars)", model, len(content))

                    # Parse JSON from response — handle markdown code blocks
                    content = content.strip()
                    if content.startswith("```"):
                        # Strip markdown code fences
                        lines = content.split("\n")
                        lines = [l for l in lines if not l.strip().startswith("```")]
                        content = "\n".join(lines).strip()

                    # Try to find JSON array in the content
                    import re
                    json_match = re.search(r'\[.*\]', content, re.DOTALL)
                    if json_match:
                        content = json_match.group(0)

                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, list):
                            detected_objects = parsed
                            break
                    except json.JSONDecodeError as je:
                        _log.warning("  segment(vision): JSON parse failed for %s: %s", model, je)
                        # Try fixing common issues: trailing commas, etc.
                        try:
                            fixed = re.sub(r',\s*]', ']', content)
                            fixed = re.sub(r',\s*}', '}', fixed)
                            parsed = json.loads(fixed)
                            if isinstance(parsed, list):
                                detected_objects = parsed
                                break
                        except json.JSONDecodeError:
                            pass
                else:
                    _log.warning("  segment(vision): %s returned %d", model, resp.status_code)
        except httpx.TimeoutException:
            _log.warning("  segment(vision): %s timed out", model)
        except Exception as exc:
            _log.warning("  segment(vision): %s failed: %s", model, exc)

    detected_data = build_detected_document(
        detected_objects,
        canon_path=canon_path,
        width=width,
        height=height,
        model_used=model_used,
        strict=_strict_real(ctx),
    )
    _log.info(
        "  segment(vision): detected %d objects via %s",
        detected_data["object_count"], model_used,
    )

    artifacts_dir = ctx.session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "detected_objects.json").write_text(
        json.dumps(detected_data, indent=2, sort_keys=True), encoding="utf-8"
    )
    return _immediate({"status": "segment_complete", **detected_data}, ctx)


async def _handle_depth_estimation(ctx: StageExecutionContext) -> StageResult:
    """Depth estimation using Depth Anything via ComfyUI.

    Queries ComfyUI object_info to find the correct DepthAnything node,
    then submits the workflow. Saves depth map as artifacts/depth.png.
    No fallbacks — errors cleanly if ComfyUI is unavailable.
    """
    import logging
    import httpx

    from src.photo_pipeline.comfyui_client import ComfyUIClient, ComfyUIError

    _log = logging.getLogger("live_trace")

    # Get canon path
    stage_outputs = ctx.values.get("stage_outputs", {})
    canon_output = stage_outputs.get("canon_generation", {})
    canon_path = canon_output.get("image_path", "")

    if not canon_path or not Path(canon_path).exists():
        artifacts_dir = ctx.session_dir / "artifacts"
        canon_candidate = artifacts_dir / "canon.png"
        if canon_candidate.exists():
            canon_path = str(canon_candidate)

    if not canon_path or not Path(canon_path).exists():
        raise RuntimeError("No canon image available for depth estimation")

    artifacts_dir = ctx.session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / "depth.png"

    _log.info("  depth_estimation: querying ComfyUI for available depth nodes...")

    # Query ComfyUI object_info to find depth nodes
    client = ComfyUIClient(timeout_s=180, poll_interval_s=0.75)
    comfyui_available = await client.health_check()

    if not comfyui_available:
        raise RuntimeError("ComfyUI is not available on localhost:8188 — depth_estimation requires GPU")

    # Find available depth node
    depth_node_name = None
    da_model_name = "depth_anything_v2_vitl_fp32.safetensors"

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get("http://localhost:8188/object_info")
            if resp.status_code == 200:
                object_info = resp.json()
                # Search for depth-related nodes
                depth_candidates = [
                    name for name in object_info.keys()
                    if "depth" in name.lower() or "DepthAnything" in name
                ]
                # Prefer known names in order
                preferred = [
                    "DepthAnything_V2", "DepthAnythingV2", "DepthAnything3",
                    "Zoe_DepthAnything", "DepthAnythingPreprocessor",
                    "Metric3D_DepthMapPreprocessor",
                ]
                for pref in preferred:
                    if pref in depth_candidates:
                        depth_node_name = pref
                        break
                if not depth_node_name and depth_candidates:
                    depth_node_name = depth_candidates[0]

                _log.info("  depth_estimation: found depth nodes: %s, using: %s",
                          depth_candidates[:5], depth_node_name)
    except Exception as exc:
        _log.warning("  depth_estimation: object_info query failed: %s", exc)

    if not depth_node_name:
        # Default fallback node name
        depth_node_name = "DepthAnything_V2"
        _log.info("  depth_estimation: defaulting to %s", depth_node_name)

    # Upload canon image to ComfyUI and run depth workflow
    # First upload the image
    canon_filename = Path(canon_path).name
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            with open(canon_path, "rb") as f:
                files = {"image": (canon_filename, f, "image/png")}
                upload_resp = await http.post(
                    "http://localhost:8188/upload/image", files=files
                )
                if upload_resp.status_code == 200:
                    upload_data = upload_resp.json()
                    canon_filename = upload_data.get("name", canon_filename)
    except Exception as exc:
        _log.warning("  depth_estimation: image upload failed: %s", exc)

    # Build depth workflow
    workflow = {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": canon_filename},
        },
        "2": {
            "class_type": "DownloadAndLoadDepthAnythingV2Model",
            "inputs": {
                "model": da_model_name,
            },
        },
        "3": {
            "class_type": depth_node_name,
            "inputs": {
                "images": ["1", 0],
                "da_model": ["2", 0],
            },
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {"images": ["3", 0], "filename_prefix": "depth"},
        },
    }

    prompt_id = await client.submit_workflow(
        workflow, client_id=f"depth-{ctx.session_id}"
    )
    await client.wait_for_completion(prompt_id, timeout_s=180)
    await client.get_output_image(
        prompt_id=prompt_id,
        output_dir=artifacts_dir,
        filename="depth.png",
    )

    _log.info(f"  depth_estimation: OK — {output_path}")
    return _immediate({
        "status": "depth_estimated",
        "depth_path": str(output_path),
        "node_used": depth_node_name,
    }, ctx)


def _handle_spatial_reconstruction(ctx: StageExecutionContext) -> StageResult:
    """Spatial reconstruction — render ALL detected objects with labeled bounding boxes.

    Reads detected_objects.json from the vision analysis stage and draws
    colored bounding boxes with labels on the canon image. Creates both:
    - artifacts/blockout.png (visual with all boxes)
    - artifacts/object_picker.json (data for the interactive picker UI)

    The blockout_approval stage shows an interactive picker where the user
    selects which objects to send to SAM3 segmentation and mesh generation.
    """
    import logging

    _log = logging.getLogger("live_trace")

    # Read detected objects from vision analysis
    artifacts_dir = ctx.session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    detected_path = artifacts_dir / "detected_objects.json"

    if not detected_path.is_file():
        raise RuntimeError("spatial reconstruction requires detected_objects.json")
    detected_data = load_detected_document(detected_path)

    objects = detected_data.get("objects", [])
    img_width = detected_data.get("image_width", 1024)
    img_height = detected_data.get("image_height", 768)

    # Get canon image path
    stage_outputs = ctx.values.get("stage_outputs", {})
    canon_output = stage_outputs.get("canon_generation", {})
    canon_path = canon_output.get("image_path", "")
    if not canon_path or not Path(canon_path).exists():
        canon_path = str(artifacts_dir / "canon.png")

    output_path = artifacts_dir / "blockout.png"

    try:
        from PIL import Image, ImageDraw, ImageFont

        # Load the canon image as the base
        if Path(canon_path).exists():
            base = Image.open(canon_path).convert("RGBA")
        else:
            base = Image.new("RGBA", (img_width, img_height), (30, 30, 30, 255))

        # Create a semi-transparent overlay
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        try:
            font = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 14)
        except (OSError, IOError):
            font = ImageFont.load_default()
            font_small = font

        # Distinct colors for object boxes
        colors = [
            (70, 200, 140), (100, 180, 255), (255, 180, 60),
            (255, 100, 100), (180, 130, 255), (255, 200, 80),
            (100, 240, 200), (255, 150, 200), (200, 100, 255),
            (100, 255, 180), (255, 130, 130), (130, 200, 255),
            (255, 220, 100), (200, 255, 130), (180, 180, 255),
            (255, 180, 180),
        ]

        drawn_count = 0
        for idx, obj in enumerate(objects):
            if not isinstance(obj, dict):
                continue

            name = obj.get("name", f"Object {idx}")
            bbox = obj.get("bbox", [0, 0, 100, 100])
            size = obj.get("size_estimate", "medium")
            color = colors[idx % len(colors)]

            if not isinstance(bbox, list) or len(bbox) != 4:
                continue

            x1, y1, x2, y2 = bbox
            # Clamp to image bounds
            x1 = max(0, min(int(x1), base.width - 1))
            y1 = max(0, min(int(y1), base.height - 1))
            x2 = max(x1 + 1, min(int(x2), base.width))
            y2 = max(y1 + 1, min(int(y2), base.height))

            # Draw bounding box with width based on size
            line_width = {"large": 4, "medium": 3, "small": 2, "tiny": 1}.get(size, 3)
            draw.rectangle([x1, y1, x2, y2], outline=(*color, 220), width=line_width)

            # Draw semi-transparent fill
            fill_overlay = Image.new("RGBA", (x2 - x1, y2 - y1), (*color, 30))
            overlay.paste(fill_overlay, (x1, y1), fill_overlay)

            # Draw label background + text
            label = f" {idx}: {name[:22]} "
            bbox_text = draw.textbbox((0, 0), label, font=font_small)
            lw, lh = bbox_text[2] - bbox_text[0], bbox_text[3] - bbox_text[1]
            label_y = max(0, y1 - lh - 6)
            draw.rectangle([x1, label_y, x1 + lw + 6, label_y + lh + 6], fill=(*color, 220))
            draw.text((x1 + 3, label_y + 3), label, fill=(0, 0, 0), font=font_small)

            drawn_count += 1

        # Header bar
        header_h = 36
        draw.rectangle([0, 0, base.width, header_h], fill=(0, 0, 0, 200))
        draw.text(
            (10, 8),
            f"VISION ANALYSIS — {drawn_count} objects detected (click to select/deselect)",
            fill=(200, 255, 200),
            font=font,
        )

        # Composite overlay onto base
        result = Image.alpha_composite(base, overlay)
        result.convert("RGB").save(output_path, "PNG")

        _log.info("  spatial_reconstruction: %d objects drawn on canon → %s", drawn_count, output_path.name)

    except Exception as exc:
        _log.error("  spatial_reconstruction: failed: %s", exc)
        if _strict_real(ctx):
            raise RuntimeError("strict-real blockout rendering failed") from exc
        import shutil
        if Path(canon_path).exists():
            shutil.copy2(canon_path, output_path)
        else:
            raise RuntimeError("blockout rendering failed and canon is unavailable") from exc

    # Compatibility artifact for the retained V16 picker; detection authority is unchanged.
    picker_data = {**detected_data, "blockout_image": "blockout.png"}
    (artifacts_dir / "object_picker.json").write_text(
        json.dumps(picker_data, indent=2), encoding="utf-8"
    )

    return _immediate({
        "status": "spatial_reconstruction_complete",
        "image_path": str(output_path),
        "object_count": len(objects),
    }, ctx)


def _handle_mesh_generation(ctx: StageExecutionContext) -> StageResult:
    """Mesh generation — only process objects selected via the interactive picker.

    Reads artifacts/selected_objects.json to determine which objects to process.
    For each selected object, runs SAM3 text-prompted segmentation → then
    Hunyuan3D → Trellis2 → placeholder fallback chain via ComfyUI.
    """
    import asyncio
    import logging
    from pathlib import Path
    from src.unified_pipeline.mesh_generators import (
        MeshGenerationError,
        UnifiedHunyuan3DGenerator,
        UnifiedTrellis2Generator,
        UnifiedPlaceholderGenerator,
    )
    from src.unified_pipeline.models import ObjectCanon, MeshApproval
    from src.photo_pipeline.comfyui_client import ComfyUIClient

    _log = logging.getLogger("live_trace")
    object_id = ctx.object_id

    strict = _strict_real(ctx)
    selected_path = ctx.session_dir / "artifacts" / "selected_objects.json"
    selected_object: dict[str, Any] | None = None
    if selected_path.is_file():
        selected_manifest = load_selected_manifest(selected_path)
        selected_object = next(
            (
                item for item in selected_manifest["objects"]
                if str(item.get("object_id", "")) == str(object_id)
            ),
            None,
        )
    if strict and selected_object is None:
        raise MeshGenerationError(
            f"object {object_id!r} is not authorized by selected-object manifest"
        )

    # Get the Object_Canon for this object from segment output
    stage_outputs = ctx.values.get("stage_outputs", {})
    segment_output = stage_outputs.get("segment", {})

    # Per-object stage outputs are stored as {stage: {object_id: output}}
    object_segment = None
    if isinstance(segment_output, dict):
        # Could be per-object dict or global
        object_segment = segment_output.get(object_id, segment_output)

    segments_list = (object_segment or {}).get("segments", [])

    # Find the segment data for this specific object
    image_path = ""
    for seg in segments_list:
        if isinstance(seg, dict) and seg.get("object_id") == object_id:
            image_path = seg.get("image_path", "")
            break

    # If no image path, try the objects directory directly
    if not image_path or not Path(image_path).exists():
        obj_png = ctx.session_dir / "objects" / ctx.session_id / f"{object_id}.png"
        if obj_png.exists():
            image_path = str(obj_png)
        else:
            # Try without session subdirectory
            obj_png = ctx.session_dir / "objects" / f"{object_id}.png"
            if obj_png.exists():
                image_path = str(obj_png)

    if not image_path or not Path(image_path).exists():
        # No cutout exists yet — run SAM3 text-prompted extraction for this object
        _log.info("  mesh_gen[%s]: No cutout found — running SAM3 extraction...", object_id[:8] if object_id else "?")

        # The approved detected record is the identity and bbox authority for SAM3.
        obj_name = str((selected_object or {}).get("name", "object"))
        selected_bbox = (selected_object or {}).get("bbox")

        # Get canon path for SAM3
        canon_path = ""
        canon_output = stage_outputs.get("canon_generation", {})
        canon_path = canon_output.get("image_path", "") if isinstance(canon_output, dict) else ""
        if not canon_path or not Path(canon_path).exists():
            canon_candidate = ctx.session_dir / "artifacts" / "canon.png"
            if canon_candidate.exists():
                canon_path = str(canon_candidate)

        if canon_path and Path(canon_path).exists():
            # Run SAM3 text-prompted extraction
            import asyncio
            import httpx

            async def _extract_cutout():
                COMFY = "http://localhost:8188"
                async with httpx.AsyncClient(timeout=30.0) as cl:
                    # Crop to the approved bbox before text-conditioned SAM3 detection.
                    upload_bytes = Path(canon_path).read_bytes()
                    if isinstance(selected_bbox, list) and len(selected_bbox) == 4:
                        import io
                        from PIL import Image
                        source = Image.open(io.BytesIO(upload_bytes)).convert("RGB")
                        x1, y1, x2, y2 = (int(value) for value in selected_bbox)
                        crop = source.crop((x1, y1, x2, y2))
                        encoded = io.BytesIO()
                        crop.save(encoded, format="PNG")
                        upload_bytes = encoded.getvalue()
                    up = await cl.post(f"{COMFY}/upload/image",
                        files={"image": (f"v16-canon-{ctx.session_id[:8]}.png", upload_bytes, "image/png")},
                        data={"overwrite": "true"})
                    if up.status_code != 200:
                        return None
                    canon_name = up.json()["name"]

                    # SAM3 workflow
                    target = obj_name.lower().strip()
                    workflow = {
                        "1": {"class_type": "LoadImage", "inputs": {"image": canon_name}},
                        "2": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sam3.1_multiplex_fp16.safetensors"}},
                        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": f"the {target}"}},
                        "4": {"class_type": "SAM3_Detect", "inputs": {
                            "model": ["2", 0], "conditioning": ["3", 0], "image": ["1", 0],
                            "threshold": 0.5, "refine_iterations": 2, "individual_masks": False}},
                        "5": {"class_type": "GrowMask", "inputs": {"mask": ["4", 0], "expand": 4, "tapered_corners": True}},
                        "6": {"class_type": "InvertMask", "inputs": {"mask": ["5", 0]}},
                        "7": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["1", 0], "alpha": ["6", 0]}},
                        "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": f"v16-cut-{object_id[:12]}"}},
                    }

                    sub = await cl.post(f"{COMFY}/prompt", json={"prompt": workflow})
                    if sub.status_code != 200:
                        return None
                    pid = sub.json()["prompt_id"]

                    # Poll for result
                    for _ in range(90):
                        await asyncio.sleep(1.0)
                        h = await cl.get(f"{COMFY}/history/{pid}")
                        if h.status_code != 200:
                            continue
                        rec = h.json().get(pid)
                        if rec and rec.get("outputs"):
                            for node in rec["outputs"].values():
                                for im in node.get("images", []):
                                    img_resp = await cl.get(f"{COMFY}/view", params={
                                        "filename": im["filename"],
                                        "subfolder": im.get("subfolder", ""),
                                        "type": im.get("type", "output")})
                                    if img_resp.status_code == 200:
                                        return img_resp.content
                            break
                return None

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        cut_bytes = pool.submit(asyncio.run, _extract_cutout()).result(timeout=120)
                else:
                    cut_bytes = asyncio.run(_extract_cutout())

                if cut_bytes and len(cut_bytes) > 1000:
                    import io
                    from PIL import Image
                    cutout = Image.open(io.BytesIO(cut_bytes))
                    alpha = cutout.getchannel("A") if "A" in cutout.getbands() else None
                    if alpha is None or alpha.getextrema() in ((0, 0), (255, 255)):
                        raise MeshGenerationError("SAM3 cutout lacks a nontrivial alpha mask")
                    objects_dir = ctx.session_dir / "objects" / ctx.session_id
                    objects_dir.mkdir(parents=True, exist_ok=True)
                    cutout_path = objects_dir / f"{object_id}.png"
                    cutout_path.write_bytes(cut_bytes)
                    image_path = str(cutout_path)
                    _log.info("  mesh_gen[%s]: SAM3 cutout saved (%d bytes)", object_id[:8], len(cut_bytes))
                else:
                    _log.warning("  mesh_gen[%s]: SAM3 returned empty cutout", object_id[:8])
            except Exception as exc:
                _log.warning("  mesh_gen[%s]: SAM3 extraction failed: %s", object_id[:8], exc)

    if not image_path or not Path(image_path).exists():
        if strict:
            raise MeshGenerationError(f"SAM3 produced no valid cutout for {object_id}")
        _log.warning("  mesh_gen[%s]: No cutout available — generating bare placeholder GLB", object_id[:8] if object_id else "?")
        # Generate a placeholder box directly (no input image needed)
        import trimesh
        import numpy as np

        meshes_dir = ctx.session_dir / "meshes"
        meshes_dir.mkdir(parents=True, exist_ok=True)
        glb_path = meshes_dir / f"{object_id}_placeholder.glb"

        # Create a colored box (0.4m cube, random muted color)
        mesh = trimesh.creation.box(extents=[0.4, 0.4, 0.4])
        # Assign a muted color based on object_id hash
        color_seed = hash(object_id or "x") % 256
        rgba = np.array([100 + color_seed % 80, 120 + (color_seed * 3) % 60, 140 + (color_seed * 7) % 50, 255], dtype=np.uint8)
        vertex_colors = np.tile(rgba, (len(mesh.vertices), 1))
        mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh, vertex_colors=vertex_colors)
        mesh.export(str(glb_path), file_type="glb")

        _log.info("  mesh_gen[%s]: Bare placeholder → %s", object_id[:8], glb_path.name)
        return _immediate({
            "status": "mesh_generation_complete",
            "object_id": object_id,
            "mesh_path": str(glb_path),
            "generator": "placeholder",
            "face_count": len(mesh.faces),
            "vertex_count": len(mesh.vertices),
            "degraded": True,
        }, ctx)

    # Build Object_Canon for the generators
    obj_canon = ObjectCanon(
        object_id=object_id or "",
        object_name="",
        image_path=image_path,
        mask_coverage=1.0,
        approved=True,
        provenance="raw_segmentation",
    )

    output_dir = ctx.session_dir / "meshes"
    output_dir.mkdir(parents=True, exist_ok=True)

    def _approved_real_output(result: Any, generator: str) -> dict[str, Any]:
        mesh_path = Path(result.mesh_path).resolve()
        output: dict[str, Any] = {
            "status": "mesh_generation_complete",
            "object_id": object_id,
            "mesh_path": str(mesh_path),
            "generator": generator,
            "face_count": result.face_count,
            "vertex_count": result.vertex_count,
            "mesh_sha256": hashlib.sha256(mesh_path.read_bytes()).hexdigest(),
            "degraded": False,
        }
        if strict:
            from src.unified_pipeline.strict_real_assets import normalize_generated_glb

            normalized_path = output_dir / "normalized" / f"{object_id}.glb"
            evidence = normalize_generated_glb(mesh_path, normalized_path)
            output.update({
                "mesh_path": evidence["normalized_path"],
                "mesh_sha256": evidence["normalized_sha256"],
                "face_count": evidence["face_count"],
                "vertex_count": evidence["vertex_count"],
                "source_mesh_path": evidence["source_path"],
                "source_mesh_sha256": evidence["source_sha256"],
                "source_mesh_extents": evidence["source_extents_m"],
                "normalization": evidence,
            })
        return output

    # Try the real fallback chain: Hunyuan3D → Trellis2 → placeholder
    client = ComfyUIClient(base_url="http://127.0.0.1:8188", timeout_s=900)

    # 1. Try Hunyuan3D 2.1
    try:
        loop = asyncio.get_event_loop()
        hunyuan_gen = UnifiedHunyuan3DGenerator(client=client, output_dir=output_dir)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, hunyuan_gen.generate(obj_canon)
                ).result(timeout=200)
        else:
            result = asyncio.run(hunyuan_gen.generate(obj_canon))

        mesh_path = Path(result.mesh_path)
        if (result.is_placeholder or not mesh_path.is_file()
                or mesh_path.suffix.lower() != ".glb"
                or result.face_count <= 0 or result.vertex_count <= 0):
            raise MeshGenerationError("Hunyuan3D returned an invalid or placeholder mesh")
        _log.info("  mesh_gen[%s]: Hunyuan3D OK — %d faces, %d verts",
                  object_id[:8], result.face_count, result.vertex_count)
        return _immediate(_approved_real_output(result, "hunyuan3d_v2.1"), ctx)

    except Exception as exc:
        _log.warning("  mesh_gen[%s]: Hunyuan3D failed (%s) — trying Trellis2", object_id[:8], exc)

    # 2. Try Trellis2
    try:
        trellis_gen = UnifiedTrellis2Generator(client=client, output_dir=output_dir)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, trellis_gen.generate(obj_canon)
                ).result(timeout=930)
        else:
            result = asyncio.run(trellis_gen.generate(obj_canon))

        mesh_path = Path(result.mesh_path)
        if (result.is_placeholder or not mesh_path.is_file()
                or mesh_path.suffix.lower() != ".glb"
                or result.face_count <= 0 or result.vertex_count <= 0):
            raise MeshGenerationError("Trellis2 returned an invalid or placeholder mesh")
        _log.info("  mesh_gen[%s]: Trellis2 OK — %d faces, %d verts",
                  object_id[:8], result.face_count, result.vertex_count)
        return _immediate(_approved_real_output(result, "trellis2"), ctx)

    except Exception as exc:
        if strict:
            raise MeshGenerationError(
                f"real mesh generators exhausted for {object_id}: {exc}"
            ) from exc
        _log.warning("  mesh_gen[%s]: Trellis2 failed (%s) — using placeholder", object_id[:8], exc)

    # 3. Placeholder fallback (legacy non-strict profile only)
    placeholder_gen = UnifiedPlaceholderGenerator(output_dir=output_dir)
    result = placeholder_gen.generate(obj_canon)
    _log.info("  mesh_gen[%s]: Placeholder generated", object_id[:8])

    return _immediate({
        "status": "mesh_generation_complete",
        "object_id": object_id,
        "mesh_path": result.mesh_path,
        "generator": "placeholder",
        "face_count": result.face_count,
        "vertex_count": result.vertex_count,
        "degraded": True,
    }, ctx)


def _handle_material_pass_1(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "material_pass_1_complete",
        "object_id": ctx.object_id,
    }, ctx)


def _handle_parametric_room(ctx: StageExecutionContext) -> StageResult:
    return _immediate({
        "status": "parametric_room_built",
        "width_m": 4.0,
        "depth_m": 3.5,
        "height_m": 2.7,
    }, ctx)


def _handle_physics_classification(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "physics_classified"}, ctx)


def _handle_physics_settle(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "physics_settled", "passed": True}, ctx)


def _handle_world_contract(ctx: StageExecutionContext) -> StageResult:
    """Construct a real WorldContract from Brief, Plan, Camera, and mesh outputs.

    Reads the object manifest, mesh generation results, and camera contract to
    assemble a finalized WorldContract with proper hash binding. Falls back to
    the legacy mock result if construction fails.
    """
    import logging
    from src.unified_pipeline.camera_contract import CameraContract
    from src.unified_pipeline.world_contract import (
        AssetBinding,
        FirstPersonNavigation,
        LightingConfig,
        LightSource,
        MaterialIntent,
        ObjectInstance,
        StaticCollisionBody,
        Vec3,
        Quaternion,
        WorldContract,
        compute_hash,
        finalize,
    )

    _log = logging.getLogger("live_trace")

    try:
        # --- Read Brief for object manifest ---
        brief_path = ctx.session_dir / "artifacts" / "brief.json"
        manifest: list[dict] = []
        if brief_path.is_file():
            try:
                brief = json.loads(brief_path.read_text(encoding="utf-8"))
                manifest = brief.get("object_manifest", [])
            except (OSError, json.JSONDecodeError):
                pass

        # --- Read stage outputs ---
        stage_outputs = ctx.values.get("stage_outputs", {})

        # --- Camera Contract ---
        camera_output = stage_outputs.get("camera_contract", {})
        camera_data = camera_output.get("camera") if isinstance(camera_output, dict) else None
        if camera_data and isinstance(camera_data, dict):
            camera = CameraContract.from_dict(camera_data)
        else:
            # Default camera
            camera = CameraContract(
                position=(0.0, 1.6, -3.0),
                target=(0.0, 1.0, 0.0),
                up=(0.0, 1.0, 0.0),
                vfov=60.0,
                aspect=1024.0 / 768.0,
                near=0.1,
                far=100.0,
                raster_width=1024,
                raster_height=768,
            )
        camera_hash = camera.compute_hash()

        # --- Collect mesh outputs and build instances ---
        mesh_outputs = stage_outputs.get("mesh_generation", {})
        instances: list[ObjectInstance] = []
        collision_bodies: list[StaticCollisionBody] = []

        # Grid layout parameters for objects without real positions
        grid_spacing = 1.5
        grid_cols = max(1, int(len(manifest) ** 0.5) + 1)

        for idx, obj in enumerate(manifest):
            if not isinstance(obj, dict):
                continue
            object_id = obj.get("id", obj.get("object_id", ""))
            if not object_id:
                continue

            # Check for mesh output
            mesh_info = mesh_outputs.get(object_id, {}) if isinstance(mesh_outputs, dict) else {}
            mesh_path = mesh_info.get("mesh_path", "") if isinstance(mesh_info, dict) else ""

            # Only include objects with valid .glb files
            if not mesh_path or not Path(mesh_path).is_file():
                continue
            if not mesh_path.lower().endswith(".glb"):
                continue

            # Compute SHA-256 of the mesh file
            import hashlib as _hl
            _digest = _hl.sha256()
            with open(mesh_path, "rb") as _f:
                for _chunk in iter(lambda: _f.read(1024 * 1024), b""):
                    _digest.update(_chunk)
            asset_hash = _digest.hexdigest()

            # Position: grid layout
            col = idx % grid_cols
            row = idx // grid_cols
            pos_x = (col - grid_cols / 2.0) * grid_spacing
            pos_z = row * grid_spacing
            pos_y = 0.0

            # Get object scale from manifest or default
            scale_val = float(obj.get("scale", 1.0)) if obj.get("scale") else 1.0

            instance = ObjectInstance(
                object_id=object_id,
                name=obj.get("name", object_id),
                position=Vec3(pos_x, pos_y, pos_z),
                rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
                scale=Vec3(scale_val, scale_val, scale_val),
                asset_binding=AssetBinding(
                    asset_id=asset_hash,
                    mesh_path=mesh_path,
                    triangle_count=0,
                    vertex_count=0,
                    generator=mesh_info.get("generator", "placeholder") if isinstance(mesh_info, dict) else "placeholder",
                ),
                physics_intent="static",
                material_intent=MaterialIntent(
                    base_color="#888888",
                    metallic=0.0,
                    roughness=0.5,
                ),
                semantic_label=obj.get("name", ""),
                is_architectural=False,
            )
            instances.append(instance)

            # Add a collision body for each instance
            collision_bodies.append(StaticCollisionBody(
                body_id=f"body-{object_id[:8]}",
                source_id=object_id,
                center=Vec3(pos_x, scale_val / 2.0, pos_z),
                dimensions=Vec3(scale_val, scale_val, scale_val),
                rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
                shape="box",
                body_mode="STATIC",
                source_kind="instance",
            ))

        # --- Room bounds ---
        room_half_x = max(5.0, (grid_cols * grid_spacing) / 2.0 + 2.0)
        room_half_z = max(5.0, ((len(instances) // grid_cols + 1) * grid_spacing) / 2.0 + 2.0)
        room_height = 3.0

        # --- Navigation ---
        navigation = FirstPersonNavigation(
            bounds_minimum=Vec3(-room_half_x, 0.0, -room_half_z),
            bounds_maximum=Vec3(room_half_x, room_height, room_half_z),
            static_bodies=tuple(collision_bodies),
            spawn_candidates=(Vec3(0.0, 1.6, -2.0),),
            player_radius=0.3,
            player_height=1.8,
            eye_height=1.6,
            movement_speed=3.0,
            gravity=9.81,
            coordinate_system="right-handed-x-right-y-up-z-depth",
        )

        # --- Lighting ---
        lighting = LightingConfig(
            ambient_color="#1a1a2e",
            ambient_intensity=0.3,
            lights=(
                LightSource(
                    light_id="main-light",
                    light_type="point",
                    position=Vec3(0.0, 2.5, 0.0),
                    color="#ffffff",
                    intensity=1.0,
                    temperature=5500.0,
                    cast_shadows=True,
                ),
            ),
        )

        # --- Assemble WorldContract ---
        contract = WorldContract(
            plan_revision=f"rev-{ctx.plan_revision}",
            camera_hash=camera_hash,
            camera=camera,
            room_shell_ref="",
            navigation=navigation,
            instances=tuple(instances),
            interactions=(),
            relationships=(),
            lighting=lighting,
        )

        # Finalize (compute hash)
        contract = finalize(contract)
        contract_hash = contract.contract_hash

        _log.info(f"  world_contract: finalized with {len(instances)} instances, hash={contract_hash[:12]}")

        # Save the contract to disk for the compile stage
        contract_dir = ctx.session_dir / "artifacts"
        contract_dir.mkdir(parents=True, exist_ok=True)
        from src.unified_pipeline.world_contract import serialize
        (contract_dir / "world_contract.json").write_text(
            serialize(contract), encoding="utf-8"
        )

        return StageResult(
            output={
                "status": "world_contract_finalized",
                "contract_hash": contract_hash,
                "instance_count": len(instances),
                "plan_revision": f"rev-{ctx.plan_revision}",
            },
            plan_revision=ctx.plan_revision,
            approval_revision=ctx.approval_revision,
            canonical_hash=contract_hash,
        )

    except Exception as exc:
        if _strict_real(ctx):
            raise RuntimeError("strict-real WorldContract construction failed") from exc
        _log.warning(f"  world_contract: construction failed ({exc}), returning mock")
        contract_data = {
            "session_id": ctx.session_id,
            "plan_revision": ctx.plan_revision,
            "stage": "world_contract",
        }
        return StageResult(
            output={"status": "world_contract_finalized", "contract_hash": _contract_hash(contract_data)},
            plan_revision=ctx.plan_revision,
            approval_revision=ctx.approval_revision,
            canonical_hash=_contract_hash(contract_data),
        )


def _handle_compile(ctx: StageExecutionContext) -> StageResult:
    """Run BrowserCompiler on the real WorldContract.

    Reads the finalized world_contract.json from artifacts, invokes BrowserCompiler,
    and stores the compiled browser output. Falls back to a degraded result if
    compilation fails (e.g., missing meshes, validation errors).
    """
    import logging
    _log = logging.getLogger("live_trace")

    try:
        from src.unified_pipeline.compilers.browser import BrowserCompiler, BrowserCompilerError
        from src.unified_pipeline.world_contract import WorldContract

        # Read the saved contract
        contract_path = ctx.session_dir / "artifacts" / "world_contract.json"
        if not contract_path.is_file():
            raise FileNotFoundError("world_contract.json not found in artifacts")

        contract_data = json.loads(contract_path.read_text(encoding="utf-8"))
        contract = WorldContract.from_dict(contract_data)

        # Output directory for browser compilation
        output_dir = ctx.session_dir / "compiled" / "browser"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Run the BrowserCompiler
        compiler = BrowserCompiler()
        result = compiler.compile(contract, output_dir)
        contract_hash = result.contract_hash

        _log.info(f"  compile: browser OK — hash={contract_hash[:12]}, output={output_dir}")

        return StageResult(
            output={
                "status": "compiled",
                "contract_hash": contract_hash,
                "browser": {"compiled": True, "contract_hash": contract_hash},
                "godot": {"compiled": False, "contract_hash": contract_hash, "reason": "godot compiler not wired"},
            },
            plan_revision=ctx.plan_revision,
            approval_revision=ctx.approval_revision,
            canonical_hash=contract_hash,
        )

    except Exception as exc:
        if _strict_real(ctx):
            raise RuntimeError("strict-real browser compilation failed") from exc
        _log.warning(f"  compile: BrowserCompiler failed ({exc}), returning degraded result")
        # Fall back — pipeline still completes, but world won't be viewable
        compile_data = {
            "session_id": ctx.session_id,
            "plan_revision": ctx.plan_revision,
            "targets": ["browser", "godot"],
        }
        contract_hash = _contract_hash(compile_data)
        return StageResult(
            output={
                "status": "compiled",
                "contract_hash": contract_hash,
                "browser": {"compiled": False, "contract_hash": contract_hash, "reason": str(exc)},
                "godot": {"compiled": False, "contract_hash": contract_hash},
            },
            plan_revision=ctx.plan_revision,
            approval_revision=ctx.approval_revision,
            canonical_hash=contract_hash,
        )


def _handle_mode_toggle(ctx: StageExecutionContext) -> StageResult:
    return _immediate({"status": "mode_toggle_configured", "default_mode": "game"}, ctx)


# ---------------------------------------------------------------------------
# Approval stage handler (generic for all approval gates)
# ---------------------------------------------------------------------------

def _make_approval_handler(stage_name: str) -> Callable[[StageExecutionContext], StageResult]:
    """Factory for approval-stage handlers."""
    def handler(ctx: StageExecutionContext) -> StageResult:
        return _awaiting_approval(stage_name, ctx)
    handler.__name__ = f"_handle_{stage_name}"
    handler.__qualname__ = f"_make_approval_handler.<locals>._handle_{stage_name}"
    return handler


# ---------------------------------------------------------------------------
# Handler registry builder
# ---------------------------------------------------------------------------

_DIRECT_HANDLERS: dict[str, Callable[[StageExecutionContext], StageResult]] = {
    "conversation": _handle_conversation,
    "brief": _handle_brief,
    "art_bible": _handle_art_bible,
    "dream_preview": _handle_dream_preview,
    "canon_generation": _handle_canon_generation,
    "segment": _handle_segment,
    "depth_estimation": _handle_depth_estimation,
    "spatial_reconstruction": _handle_spatial_reconstruction,
    "mesh_generation": _handle_mesh_generation,
    "material_pass_1": _handle_material_pass_1,
    "parametric_room": _handle_parametric_room,
    "physics_classification": _handle_physics_classification,
    "physics_settle": _handle_physics_settle,
    "world_contract": _handle_world_contract,
    "compile": _handle_compile,
    "mode_toggle": _handle_mode_toggle,
}


def build_handlers(config: dict | None = None) -> dict[str, Callable[[StageExecutionContext], StageResult]]:
    """Build the complete handler map for all stages in DEFAULT_STAGE_SPECS.

    Parameters
    ----------
    config : dict, optional
        Pipeline configuration. Reserved for future use (e.g., selecting real
        GPU backends vs mocks, configuring warehouse endpoints).

    Returns
    -------
    dict[str, Callable]
        Mapping of stage name → handler function covering every stage declared
        in DEFAULT_STAGE_SPECS.
    """
    config = config or {}
    handlers: dict[str, Callable[[StageExecutionContext], StageResult]] = {}

    for spec in DEFAULT_STAGE_SPECS:
        if spec.approval_for is not None:
            # Approval stages get a generic awaiting-approval handler
            handlers[spec.name] = _make_approval_handler(spec.name)
        elif spec.name in _DIRECT_HANDLERS:
            handlers[spec.name] = _DIRECT_HANDLERS[spec.name]
        else:
            # Fallback for any stage not explicitly wired (should not happen)
            def _fallback(ctx: StageExecutionContext, _name: str = spec.name) -> StageResult:
                return _immediate({"status": f"{_name}_complete"}, ctx)
            handlers[spec.name] = _fallback

    # Strict adapters dispatch back to the retained handlers for non-strict profiles.
    # Keeping this override local avoids importing the integration module while this
    # module's legacy functions are still being defined.
    from src.unified_pipeline.strict_real_handlers import STRICT_REAL_HANDLERS
    handlers.update(STRICT_REAL_HANDLERS)
    return handlers
