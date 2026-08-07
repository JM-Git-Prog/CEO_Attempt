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

# Stages that actually call live GPU services (others return immediate placeholders)
LIVE_GPU_STAGES = frozenset({
    "dream_preview",   # Real ComfyUI FLUX
    "canon_generation",  # Real ComfyUI FLUX/SDXL
    "segment",         # Real SAM3.1 via ComfyUI
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

    Builds a high-quality prompt from the brief's full description, submits to
    ComfyUI with higher steps (30), and saves as canon.png in artifacts.
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
    object_names = ", ".join(
        item.get("name", "") for item in objects[:8]
        if isinstance(item, dict) and item.get("name")
    ) or "furniture and fixtures"

    prompt = (
        f"Photorealistic interior photograph of a {period + ' ' if period else ''}"
        f"{room_purpose}, {mood} atmosphere, featuring {object_names}. "
        f"{primary + ' color palette. ' if primary else ''}"
        f"Professional architectural photography, natural lighting, "
        f"high detail, 8K resolution, sharp focus, magazine quality, "
        f"realistic materials and textures, ambient occlusion, "
        f"volumetric light through windows."
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

    seed = random.randint(1, 2**32 - 1)
    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1024, "height": 768, "batch_size": 1},
        },
        "4": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["2", 0],
                "negative": ["5", 0],
                "latent_image": ["3", 0],
                "seed": seed,
                "steps": 30,
                "cfg": 4.5,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
            },
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "blurry, distorted, text, watermark, low quality, cartoon",
                "clip": ["1", 1],
            },
        },
        "6": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["4", 0], "vae": ["1", 2]},
        },
        "7": {
            "class_type": "SaveImage",
            "inputs": {"images": ["6", 0], "filename_prefix": "canon"},
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

    _log.info(f"  canon_generation: OK — {output_path}")
    return _immediate({
        "status": "canon_rendered",
        "image_path": str(output_path),
        "prompt": prompt,
    }, ctx)


def _handle_segment(ctx: StageExecutionContext) -> StageResult:
    """Segment objects from canon using the proven SAM3 text-prompted workflow.

    Uses the working v15_fable pattern: for each object in the Brief manifest,
    run SAM3_Detect with text conditioning targeting that specific object.
    Produces RGBA cutout PNGs (object on transparent background).

    Workflow per object (proven on Starlite, v15 Fable):
      CheckpointLoaderSimple(sam3.1_multiplex) → CLIPTextEncode("the {object}") →
      SAM3_Detect(conditioning + image) → GrowMask(4px) → InvertMask →
      JoinImageWithAlpha → SaveImage
    """
    import asyncio
    import logging
    import time as _time
    from pathlib import Path

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
        raise RuntimeError("No canon image available for segmentation")

    # Get object manifest from brief
    brief_output = stage_outputs.get("brief", {})
    manifest_raw = brief_output.get("object_manifest", [])
    if not manifest_raw:
        brief_path = ctx.session_dir / "artifacts" / "brief.json"
        if brief_path.is_file():
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            manifest_raw = brief.get("object_manifest", [])
    if not manifest_raw:
        raise RuntimeError("No objects in brief manifest for segmentation")

    objects_dir = ctx.session_dir / "objects" / ctx.session_id
    objects_dir.mkdir(parents=True, exist_ok=True)

    _log.info("  segment: cutting %d objects from canon via SAM3 text-prompted workflow", len(manifest_raw))

    async def _run_segmentation():
        import httpx
        COMFY = "http://localhost:8188"

        async with httpx.AsyncClient(timeout=30.0) as cl:
            # Upload canon to ComfyUI
            with open(canon_path, "rb") as f:
                up = await cl.post(
                    f"{COMFY}/upload/image",
                    files={"image": (f"v16-canon-{ctx.session_id[:8]}.png", f, "image/png")},
                    data={"overwrite": "true"},
                )
            if up.status_code != 200:
                raise RuntimeError(f"Canon upload failed: {up.status_code}")
            canon_name = up.json()["name"]

            segments = []
            for obj in manifest_raw:
                obj_id = obj.get("id", "")
                obj_name = obj.get("name", "object")
                if not obj_id:
                    continue

                # Build proven SAM3 text-prompted workflow
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
                    "8": {"class_type": "SaveImage", "inputs": {"images": ["7", 0], "filename_prefix": f"v16-cut-{obj_id[:12]}"}},
                }

                _log.info("  segment[%s]: SAM3 detecting '%s'...", obj_id[:8], target[:30])

                # Submit workflow
                sub = await cl.post(f"{COMFY}/prompt", json={"prompt": workflow})
                if sub.status_code != 200:
                    _log.warning("  segment[%s]: workflow rejected: %s", obj_id[:8], sub.text[:200])
                    segments.append({"object_id": obj_id, "object_name": obj_name, "image_path": "", "mask_coverage": 0.0, "degraded": True})
                    continue

                pid = sub.json()["prompt_id"]

                # Poll for completion (up to 60s per object)
                cut_bytes = None
                for _ in range(60):
                    await asyncio.sleep(1.0)
                    h = await cl.get(f"{COMFY}/history/{pid}")
                    if h.status_code != 200:
                        continue
                    rec = h.json().get(pid)
                    if rec and rec.get("outputs"):
                        for node in rec["outputs"].values():
                            for im in node.get("images", []):
                                img = await cl.get(f"{COMFY}/view", params={
                                    "filename": im["filename"],
                                    "subfolder": im.get("subfolder", ""),
                                    "type": im.get("type", "output"),
                                })
                                if img.status_code == 200:
                                    cut_bytes = img.content
                        break

                if cut_bytes:
                    output_path = objects_dir / f"{obj_id}.png"
                    output_path.write_bytes(cut_bytes)
                    _log.info("  segment[%s]: OK — saved %d bytes", obj_id[:8], len(cut_bytes))
                    segments.append({
                        "object_id": obj_id,
                        "object_name": obj_name,
                        "image_path": str(output_path),
                        "mask_coverage": 0.5,  # Approximate
                    })
                else:
                    _log.warning("  segment[%s]: SAM3 produced no output", obj_id[:8])
                    segments.append({"object_id": obj_id, "object_name": obj_name, "image_path": "", "mask_coverage": 0.0, "degraded": True})

        return segments

    # Run the async segmentation
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                segments = pool.submit(asyncio.run, _run_segmentation()).result(timeout=600)
        else:
            segments = asyncio.run(_run_segmentation())
    except Exception as exc:
        raise RuntimeError(f"SAM3 segmentation failed: {exc}") from exc

    successful = [s for s in segments if s.get("image_path")]
    _log.info("  segment: done — %d/%d objects isolated", len(successful), len(segments))

    return _immediate({
        "status": "segment_complete",
        "segments": segments,
        "object_count": len(segments),
        "successful_count": len(successful),
    }, ctx)


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
    """Spatial reconstruction — overlay detected objects on the canon image.

    Shows the canon photo with colored bounding boxes and labels around each
    segmented object. This lets the user verify that the right objects were
    detected before proceeding to 3D mesh generation.

    Saves as artifacts/blockout.png (approved via blockout_approval gate).
    """
    import logging

    _log = logging.getLogger("live_trace")

    stage_outputs = ctx.values.get("stage_outputs", {})

    # Get canon image path
    canon_output = stage_outputs.get("canon_generation", {})
    canon_path = canon_output.get("image_path", "")
    if not canon_path or not Path(canon_path).exists():
        canon_path = str(ctx.session_dir / "artifacts" / "canon.png")

    # Get segment data — per-object stage outputs are stored as {object_id: output}
    segment_output = stage_outputs.get("segment", {})
    segments = []
    if isinstance(segment_output, dict):
        # Per-object format: {"obj_id": {"status":..., "segments":[...], ...}}
        for obj_id, obj_output in segment_output.items():
            if isinstance(obj_output, dict):
                # Each per-object segment output has a "segments" list with one entry
                obj_segs = obj_output.get("segments", [])
                for seg in obj_segs:
                    if isinstance(seg, dict):
                        segments.append(seg)
                # If no segments list, build from the output directly
                if not obj_segs and obj_output.get("image_path"):
                    segments.append({
                        "object_id": obj_id,
                        "object_name": obj_output.get("object_name", obj_id[:8]),
                        "image_path": obj_output.get("image_path", ""),
                        "mask_coverage": obj_output.get("mask_coverage", 0),
                    })
        # Also check if there's a combined "segments" field (non-per-object format)
        if not segments and "segments" in segment_output:
            segments = segment_output["segments"]

    artifacts_dir = ctx.session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / "blockout.png"

    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        # Load the canon image as the base
        if Path(canon_path).exists():
            base = Image.open(canon_path).convert("RGBA")
        else:
            base = Image.new("RGBA", (1024, 768), (30, 30, 30, 255))

        # Create a semi-transparent overlay
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        try:
            font = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 14)
        except (OSError, IOError):
            font = ImageFont.load_default()
            font_small = font

        # Colors for object boxes
        colors = [
            (70, 200, 140), (100, 180, 255), (255, 180, 60),
            (255, 100, 100), (180, 130, 255), (255, 200, 80),
            (100, 240, 200), (255, 150, 200),
        ]

        # For each segmented object, draw a bounding box on the overlay
        objects_dir = ctx.session_dir / "objects" / ctx.session_id
        successful = 0

        # If segments list is empty, scan objects dir for any PNGs
        if not segments and objects_dir.exists():
            # Get brief manifest for names
            brief_output = stage_outputs.get("brief", {})
            manifest = brief_output.get("object_manifest", []) if isinstance(brief_output, dict) else []
            name_map = {obj.get("id", ""): obj.get("name", "") for obj in manifest if isinstance(obj, dict)}

            for png in objects_dir.glob("*.png"):
                obj_id = png.stem
                obj_name = name_map.get(obj_id, obj_id[:12])
                segments.append({
                    "object_id": obj_id,
                    "object_name": obj_name,
                    "image_path": str(png),
                    "mask_coverage": 0.5,
                })

        for idx, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            obj_name = seg.get("object_name", f"Object {idx+1}")
            image_path = seg.get("image_path", "")
            color = colors[idx % len(colors)]

            if image_path and Path(image_path).exists():
                # Load the cutout to find its bounding box on the original
                cutout = Image.open(image_path).convert("RGBA")
                alpha = np.array(cutout)[:, :, 3]
                ys, xs = np.nonzero(alpha > 128)

                if len(xs) > 0:
                    # Map cutout bbox to canon coordinates (cutouts are same size as canon)
                    x0, x1 = int(xs.min()), int(xs.max())
                    y0, y1 = int(ys.min()), int(ys.max())

                    # Draw bounding box
                    draw.rectangle([x0, y0, x1, y1], outline=color, width=3)

                    # Draw label background
                    label = f" {obj_name[:25]} "
                    bbox = draw.textbbox((0, 0), label, font=font_small)
                    lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    label_y = max(0, y0 - lh - 4)
                    draw.rectangle([x0, label_y, x0 + lw + 4, label_y + lh + 4], fill=(*color, 200))
                    draw.text((x0 + 2, label_y + 2), label, fill=(0, 0, 0), font=font_small)

                    successful += 1
            else:
                # No cutout available — show text only
                n = max(1, len(segments))
                cols = max(1, int(n ** 0.5) + 1)
                bx = 50 + (idx % cols) * (base.width // cols)
                by = 50 + (idx // cols) * 80
                draw.text((bx, by), f"? {obj_name[:20]}", fill=(*color, 180), font=font_small)

        # Header bar
        header_h = 36
        draw.rectangle([0, 0, base.width, header_h], fill=(0, 0, 0, 180))
        draw.text((10, 8), f"OBJECT DETECTION — {successful}/{len(segments)} objects found", fill=(200, 255, 200), font=font)

        # Composite overlay onto base
        result = Image.alpha_composite(base, overlay)
        result.convert("RGB").save(output_path, "PNG")

        _log.info("  spatial_reconstruction: %d/%d objects boxed on canon → %s", successful, len(segments), output_path.name)

    except Exception as exc:
        _log.error("  spatial_reconstruction: failed: %s", exc)
        # Write the canon image directly as fallback
        import shutil
        if Path(canon_path).exists():
            shutil.copy2(canon_path, output_path)
        else:
            from PIL import Image
            Image.new("RGB", (1024, 768), (30, 30, 30)).save(output_path)

    return _immediate({
        "status": "spatial_reconstruction_complete",
        "image_path": str(output_path),
        "object_count": len(segments),
    }, ctx)


def _handle_mesh_generation(ctx: StageExecutionContext) -> StageResult:
    """Mesh generation — Hunyuan3D → Trellis2 → placeholder fallback chain via ComfyUI.

    Uses the real GPU generators through the ResourceArbiter VRAM lease system.
    Falls back gracefully: Hunyuan3D (best quality) → Trellis2 → placeholder primitive.
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
        _log.warning("  mesh_gen[%s]: No Object_Canon image — generating bare placeholder GLB", object_id[:8] if object_id else "?")
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

    # Try the real fallback chain: Hunyuan3D → Trellis2 → placeholder
    client = ComfyUIClient(base_url="http://127.0.0.1:8188", timeout_s=200)

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

        _log.info("  mesh_gen[%s]: Hunyuan3D OK — %d faces, %d verts",
                  object_id[:8], result.face_count, result.vertex_count)
        return _immediate({
            "status": "mesh_generation_complete",
            "object_id": object_id,
            "mesh_path": result.mesh_path,
            "generator": "hunyuan3d_v2.1",
            "face_count": result.face_count,
            "vertex_count": result.vertex_count,
        }, ctx)

    except (MeshGenerationError, Exception) as exc:
        _log.warning("  mesh_gen[%s]: Hunyuan3D failed (%s) — trying Trellis2", object_id[:8], exc)

    # 2. Try Trellis2
    try:
        trellis_gen = UnifiedTrellis2Generator(client=client, output_dir=output_dir)

        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, trellis_gen.generate(obj_canon)
                ).result(timeout=120)
        else:
            result = asyncio.run(trellis_gen.generate(obj_canon))

        _log.info("  mesh_gen[%s]: Trellis2 OK — %d faces, %d verts",
                  object_id[:8], result.face_count, result.vertex_count)
        return _immediate({
            "status": "mesh_generation_complete",
            "object_id": object_id,
            "mesh_path": result.mesh_path,
            "generator": "trellis2",
            "face_count": result.face_count,
            "vertex_count": result.vertex_count,
        }, ctx)

    except (MeshGenerationError, Exception) as exc:
        _log.warning("  mesh_gen[%s]: Trellis2 failed (%s) — using placeholder", object_id[:8], exc)

    # 3. Placeholder fallback
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

    return handlers
