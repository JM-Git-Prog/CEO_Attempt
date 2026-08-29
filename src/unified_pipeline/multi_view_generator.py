"""V2.0 Multi-View Generator — Phase 2 (Densify).

Generates 5 Canon views from different camera positions within the room,
plus depth maps for each. View 1 is the hero Canon (already generated).
Views 2–5 are generated looking at the N/E/S/W walls respectively.

This eliminates single-view recovery by providing the pipeline with
full 360-degree visual coverage of the room.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.photo_pipeline.comfyui_client import ComfyUIClient
from src.unified_pipeline.dream_preview import FLUX_CLIP, FLUX_MODEL, FLUX_VAE
from src.unified_pipeline.plan_generator import MetricPlanGenerator
from src.unified_pipeline.models import Brief, MetricPlan

logger = logging.getLogger("live_trace")


@dataclass
class ViewResult:
    """Result of generating one view."""

    index: int
    canon_path: str
    depth_path: str
    camera_position: tuple[float, float, float]
    camera_target: tuple[float, float, float]
    camera_fov: float = 60.0
    width: int = 1024
    height: int = 768
    sha256: str = ""


@dataclass
class MultiViewResult:
    """Complete result of Phase 2 — all 5 views."""

    views: list[ViewResult] = field(default_factory=list)
    metric_plan: MetricPlan | None = None
    room_dimensions: tuple[float, float, float] = (4.0, 4.0, 2.7)
    # Exact-pose capture manifest (from CapturePlanner) when available. Carries
    # per-camera K/R/t for downstream depth back-projection. None when the
    # legacy cardinal-camera path is used.
    capture_manifest: Any = None


def _planner_cameras(
    metric_plan: MetricPlan,
    width: float,
    depth: float,
    ceiling: float,
) -> tuple[list[dict[str, Any]], Any]:
    """Build cameras from CapturePlanner, returning legacy dicts + the manifest.

    The returned dict list matches the shape produced by
    ``_compute_cardinal_cameras`` (position/target/label) so the existing
    generation loop is unchanged. The CaptureManifest is returned alongside so
    downstream stages can use the exact known K/R/t for back-projection.

    Falls back to legacy cardinal cameras (manifest=None) if CapturePlanner is
    unavailable or errors — preserving backward compatibility.
    """
    try:
        from src.unified_pipeline.capture_planner import CapturePlanner
        from src.unified_pipeline.models import CameraContract

        eye_height = min(1.62, ceiling * 0.6)
        contract = CameraContract(
            position=(0.0, eye_height, 0.0),
            target=(0.0, eye_height * 0.9, -depth / 2),
        )
        manifest = CapturePlanner(metric_plan, contract).plan()
        cameras = [
            {
                "position": cam.position,
                "target": cam.target,
                "label": cam.label,
            }
            for cam in manifest.cameras
        ]
        if not cameras:
            raise ValueError("CapturePlanner produced no cameras")
        logger.info(
            "  V2 using CapturePlanner: %d cameras (exact K/R/t manifest)",
            len(cameras),
        )
        return cameras, manifest
    except Exception as exc:  # noqa: BLE001 - fall back to legacy path
        logger.warning(
            "  V2 CapturePlanner unavailable (%s); using cardinal cameras", exc
        )
        return _compute_cardinal_cameras(width, depth, ceiling), None


def _compute_cardinal_cameras(
    width: float, depth: float, ceiling: float
) -> list[dict[str, Any]]:
    """Compute 5 camera positions for full room coverage.

    View 0 (hero): center of room, looking at the primary wall (negative Z)
    View 1: center, looking at North wall (+Z)
    View 2: center, looking at East wall (+X)
    View 3: center, looking at South wall (-Z) — same as hero but included for completeness
    View 4: center, looking at West wall (-X)

    All cameras are at eye height (1.62m) in the center of the room.
    """
    eye_height = min(1.62, ceiling * 0.6)
    cx, cz = 0.0, 0.0  # Center of room in contract space

    cameras = [
        {  # View 0: Hero — looking at "primary" wall (arbitrary, we pick -Z)
            "position": (cx, eye_height, cz),
            "target": (cx, eye_height * 0.9, -depth / 2),
            "label": "hero_south",
        },
        {  # View 1: Looking North (+Z)
            "position": (cx, eye_height, cz),
            "target": (cx, eye_height * 0.9, depth / 2),
            "label": "north",
        },
        {  # View 2: Looking East (+X)
            "position": (cx, eye_height, cz),
            "target": (width / 2, eye_height * 0.9, cz),
            "label": "east",
        },
        {  # View 3: Looking South (-Z) — hero direction
            "position": (cx, eye_height, cz),
            "target": (cx, eye_height * 0.9, -depth / 2),
            "label": "south",
        },
        {  # View 4: Looking West (-X)
            "position": (cx, eye_height, cz),
            "target": (-width / 2, eye_height * 0.9, cz),
            "label": "west",
        },
    ]
    return cameras


def _build_view_prompt(brief: dict[str, Any], camera_label: str) -> str:
    """Build a FLUX prompt for a specific view direction."""
    room_purpose = brief.get("room_purpose", "room")
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
    ) or "furniture and fixtures"

    # Add directional context to the prompt
    direction_hints = {
        "hero_south": "looking at the main wall",
        "north": "looking at the back wall",
        "east": "looking at the right wall",
        "south": "looking at the main wall",
        "west": "looking at the left wall",
    }
    direction = direction_hints.get(camera_label, "")

    prompt = (
        f"Photorealistic interior photograph of a "
        f"{period + ' ' if period else ''}{room_purpose}, "
        f"{mood} atmosphere, {direction}, "
        f"featuring {object_names}. "
        f"{primary + ' tones. ' if primary else ''}"
        f"Professional architectural photography, natural lighting, "
        f"high detail, 8K resolution, sharp focus, consistent style."
    )
    return prompt


async def _generate_view_image(
    client: ComfyUIClient,
    prompt: str,
    output_dir: Path,
    filename: str,
    seed: int | None = None,
) -> Path:
    """Submit a FLUX text-to-image workflow and retrieve the result."""
    if seed is None:
        seed = random.randint(1, 2**32 - 1)

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
            "inputs": {
                "text": "blurry, low quality, deformed, sketch, text, watermark, "
                "cartoon, 3d render, empty room, no furniture",
                "clip": ["2", 0],
            },
        },
        "6": {
            "class_type": "EmptyFlux2LatentImage",
            "inputs": {"width": 1024, "height": 768, "batch_size": 1},
        },
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
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "v2_view"},
        },
    }

    prompt_id = await client.submit_workflow(workflow, client_id=f"v2-view-{filename}")
    await client.wait_for_completion(prompt_id, timeout_s=600)

    output_dir.mkdir(parents=True, exist_ok=True)
    await client.get_output_image(prompt_id=prompt_id, output_dir=output_dir, filename=filename)

    return output_dir / filename


async def _generate_depth(
    client: ComfyUIClient,
    canon_path: Path,
    output_dir: Path,
    depth_filename: str,
) -> Path:
    """Generate a depth map for a view image using Depth Anything V2."""
    import httpx

    # Upload the canon image to ComfyUI
    canon_filename = canon_path.name
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            with open(canon_path, "rb") as f:
                files = {"image": (canon_filename, f, "image/png")}
                resp = await http.post("http://localhost:8188/upload/image", files=files)
                if resp.status_code == 200:
                    data = resp.json()
                    canon_filename = data.get("name", canon_filename)
    except Exception as exc:
        logger.warning(f"  depth upload failed: {exc}")

    # Build depth workflow
    workflow = {
        "1": {
            "class_type": "LoadImage",
            "inputs": {"image": canon_filename},
        },
        "2": {
            "class_type": "DownloadAndLoadDepthAnythingV2Model",
            "inputs": {"model": "depth_anything_v2_vitl_fp32.safetensors"},
        },
        "3": {
            "class_type": "DepthAnything_V2",
            "inputs": {"images": ["1", 0], "da_model": ["2", 0]},
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {"images": ["3", 0], "filename_prefix": "v2_depth"},
        },
    }

    prompt_id = await client.submit_workflow(workflow, client_id=f"v2-depth-{depth_filename}")
    await client.wait_for_completion(prompt_id, timeout_s=180)

    output_dir.mkdir(parents=True, exist_ok=True)
    await client.get_output_image(prompt_id=prompt_id, output_dir=output_dir, filename=depth_filename)

    return output_dir / depth_filename


async def generate_multi_views(
    brief: dict[str, Any],
    session_dir: Path,
    *,
    emit_fn: Callable[[str, dict[str, Any]], None] | None = None,
) -> MultiViewResult:
    """Generate 5 views + depth maps for full room coverage (Phase 2: Densify).

    View 0 is the hero Canon (already generated in Phase 1).
    Views 1–4 are generated here looking at each cardinal wall.
    Depth maps are generated for all 5 views.

    Args:
        brief: The structured Brief dict from Phase 1.
        session_dir: Session output directory.
        emit_fn: Optional SSE event emitter.

    Returns:
        MultiViewResult with all view paths and camera parameters.
    """
    def emit(etype: str, data: dict[str, Any]) -> None:
        if emit_fn:
            emit_fn(etype, data)

    # Generate MetricPlan from Brief for room dimensions
    from src.unified_pipeline.models import (
        Atmosphere, Brief as BriefModel, Era, GameConcept,
        ManifestObject, Palette, RealCapability,
    )

    # Build a Brief model from the dict for the plan generator
    manifest_objects = tuple(
        ManifestObject(
            name=obj.get("name", ""),
            role=obj.get("role", ""),
            count=obj.get("count", 1),
            material_hint=obj.get("material_hint", ""),
            is_architectural=obj.get("is_architectural", False),
        )
        for obj in brief.get("object_manifest", [])
        if isinstance(obj, dict)
    )
    atm = brief.get("atmosphere", {})
    era_d = brief.get("era", {})
    pal = brief.get("palette", {})

    brief_model = BriefModel(
        room_purpose=brief.get("room_purpose", "room"),
        atmosphere=Atmosphere(
            mood=atm.get("mood", "") if isinstance(atm, dict) else "",
            lighting_direction=atm.get("lighting_direction", "") if isinstance(atm, dict) else "",
            time_of_day=atm.get("time_of_day", "") if isinstance(atm, dict) else "",
        ),
        era=Era(
            period=era_d.get("period", "") if isinstance(era_d, dict) else "",
            style_exclusions=tuple(era_d.get("style_exclusions", [])) if isinstance(era_d, dict) else (),
        ),
        palette=Palette(
            primary=pal.get("primary", "") if isinstance(pal, dict) else "",
            accent=pal.get("accent", "") if isinstance(pal, dict) else "",
            material_finishes=tuple(pal.get("material_finishes", [])) if isinstance(pal, dict) else (),
        ),
        object_manifest=manifest_objects,
        success_criteria=brief.get("success_criteria", ""),
    )

    generator = MetricPlanGenerator()
    metric_plan = generator.generate_deterministic(brief_model)
    width, depth, ceiling = metric_plan.room_dimensions

    # Save MetricPlan
    artifacts_dir = session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    plan_data = {
        "room_dimensions": list(metric_plan.room_dimensions),
        "template_id": metric_plan.template_id,
        "object_placements": list(metric_plan.object_placements),
        "walls": [w if isinstance(w, dict) else {} for w in metric_plan.walls],
        "openings": list(metric_plan.openings),
    }
    (artifacts_dir / "metric_plan.json").write_text(
        json.dumps(plan_data, indent=2, default=str), encoding="utf-8"
    )

    # Compute camera positions. Prefer CapturePlanner (exact K/R/t manifest),
    # fall back to legacy cardinal cameras. Existing generation loop is unchanged.
    cameras, capture_manifest = _planner_cameras(metric_plan, width, depth, ceiling)

    # Persist the manifest for downstream back-projection when available.
    if capture_manifest is not None:
        try:
            (artifacts_dir / "capture_manifest.json").write_text(
                json.dumps(capture_manifest.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - manifest persistence is best-effort
            logger.warning("  V2 could not persist capture_manifest: %s", exc)

    # View 0 = hero Canon (already exists)
    hero_path = artifacts_dir / "canon.png"
    views_dir = artifacts_dir / "views"
    views_dir.mkdir(parents=True, exist_ok=True)

    result = MultiViewResult(
        metric_plan=metric_plan,
        room_dimensions=(width, depth, ceiling),
        capture_manifest=capture_manifest,
    )

    # Add hero view (index 0) — already generated
    hero_view = ViewResult(
        index=0,
        canon_path=str(hero_path),
        depth_path="",  # Will be set after depth generation
        camera_position=cameras[0]["position"],
        camera_target=cameras[0]["target"],
    )
    result.views.append(hero_view)

    emit("view_generated", {"view_index": 0, "label": "hero", "status": "existing"})

    # Initialize ComfyUI client
    client = ComfyUIClient(timeout_s=600, poll_interval_s=0.75)
    if not await client.health_check():
        logger.error("ComfyUI not available — skipping multi-view generation")
        emit("error_event", {"phase": "densify", "message": "ComfyUI unavailable"})
        return result

    # Generate views 1–4 sequentially (one FLUX job at a time for VRAM)
    for i in range(1, min(5, len(cameras))):
        cam = cameras[i]
        view_dir = views_dir / f"view_{i}"
        view_dir.mkdir(parents=True, exist_ok=True)

        prompt = _build_view_prompt(brief, cam["label"])
        logger.info(f"  V2 generating view {i} ({cam['label']}): {prompt[:60]}...")

        try:
            canon_path = await _generate_view_image(
                client, prompt, view_dir, "canon.png"
            )
            sha = hashlib.sha256(canon_path.read_bytes()).hexdigest()

            view = ViewResult(
                index=i,
                canon_path=str(canon_path),
                depth_path="",
                camera_position=cam["position"],
                camera_target=cam["target"],
                sha256=sha,
            )
            result.views.append(view)

            emit("view_generated", {
                "view_index": i,
                "label": cam["label"],
                "image_url": f"/api/v2/session/{session_dir.name}/artifact/view_{i}",
            })
            logger.info(f"  V2 view {i} generated: {canon_path}")

        except Exception as exc:
            logger.error(f"  V2 view {i} failed: {exc}")
            emit("view_generated", {
                "view_index": i,
                "label": cam["label"],
                "status": "failed",
                "error": str(exc),
            })

    # Release FLUX VRAM before depth estimation
    try:
        await client.release_vram()
    except Exception:
        pass

    # Generate depth maps for all available views
    logger.info(f"  V2 generating depth maps for {len(result.views)} views...")
    for view in result.views:
        canon_p = Path(view.canon_path)
        if not canon_p.is_file():
            continue

        view_dir = canon_p.parent
        try:
            depth_path = await _generate_depth(
                client, canon_p, view_dir, "depth.png"
            )
            view.depth_path = str(depth_path)
            emit("depth_ready", {"view_index": view.index})
        except Exception as exc:
            logger.warning(f"  V2 depth for view {view.index} failed: {exc}")

    # Release VRAM after depth
    try:
        await client.release_vram()
    except Exception:
        pass

    # Save view metadata
    views_meta = {
        "view_count": len(result.views),
        "room_dimensions": list(result.room_dimensions),
        "views": [
            {
                "index": v.index,
                "canon_path": v.canon_path,
                "depth_path": v.depth_path,
                "camera_position": list(v.camera_position),
                "camera_target": list(v.camera_target),
                "camera_fov": v.camera_fov,
                "sha256": v.sha256,
            }
            for v in result.views
        ],
    }
    (artifacts_dir / "views_meta.json").write_text(
        json.dumps(views_meta, indent=2), encoding="utf-8"
    )

    logger.info(f"  V2 multi-view complete: {len(result.views)} views, dimensions={result.room_dimensions}")
    return result
