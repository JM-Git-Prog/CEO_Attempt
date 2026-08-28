"""V2.0 API routes — "One Prompt, One Room" streamlined pipeline.

Two user touchpoints only:
1. POST /api/v2/session/{id}/describe — user describes, system generates hero Canon
2. POST /api/v2/session/{id}/approve — user confirms, full automated build begins

The pipeline (Phases 2–5) runs without further user interaction and streams
progress via SSE at GET /api/v2/session/{id}/stream.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.models import SessionMode
from src.session_manager import SessionManager
from src.unified_pipeline.conversation import ConversationEngine, ConversationTurn

_log = logging.getLogger("live_trace")

# ─── Per-process state ─────────────────────────────────────────────────────────

_v2_conversations: dict[str, ConversationEngine] = {}
_v2_pipelines: dict[str, asyncio.Task] = {}
_v2_events: dict[str, list[dict[str, Any]]] = {}
_v2_locks: dict[str, asyncio.Lock] = {}


def create_v2_router(output_root: Callable[[], Path]) -> APIRouter:
    """Build the V2.0 routes using the app's current output root."""
    router = APIRouter()

    def _session_dir(session_id: str) -> Path:
        root = output_root()
        d = root / session_id
        if not d.is_dir():
            raise ValueError(f"Session not found: {session_id}")
        return d

    def _emit_event(session_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Append a typed event to the session's SSE queue."""
        events = _v2_events.setdefault(session_id, [])
        events.append({"type": event_type, "data": data, "time": time.time()})

    def _write_meta(session_dir: Path, **changes: object) -> None:
        path = session_dir / "session_meta.json"
        doc = {}
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        doc.update(changes)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        tmp.replace(path)

    # ─── POST /api/v2/session/start ────────────────────────────────────────────

    @router.post("/api/v2/session/start")
    async def v2_start(request: Request):
        """Create a V2.0 session and return the opening message."""
        root = output_root()
        manager = SessionManager(output_base=root)
        session = manager.create_session("", SessionMode.MVP)

        session_dir = Path(session.output_path)
        _write_meta(
            session_dir,
            session_id=session.session_id,
            interface_version="2.0",
            state="awaiting_description",
            created_at=datetime.now(timezone.utc).isoformat(),
            pipeline_version="v2.0-multi-view",
        )

        # Create conversation engine
        engine = ConversationEngine()
        engine._state.session_id = session.session_id  # noqa: SLF001

        # Generate opening message via Ollama
        try:
            opening = await engine.generate_opening()
        except Exception as exc:
            _log.warning(f"V2 opening generation failed: {exc}")
            opening = "What kind of room are you imagining? Describe it and I'll bring it to life."

        _v2_conversations[session.session_id] = engine
        _v2_events[session.session_id] = []

        return {
            "session_id": session.session_id,
            "interface_version": "2.0",
            "state": "awaiting_description",
            "opening_message": opening,
        }

    # ─── POST /api/v2/session/{id}/describe ────────────────────────────────────

    @router.post("/api/v2/session/{session_id}/describe")
    async def v2_describe(session_id: str, request: Request):
        """Accept the user's room description, extract Brief, generate hero Canon.

        This is the ONE interaction before approval — the user describes what they
        want and immediately gets a hero Canon image back.
        """
        try:
            session_dir = _session_dir(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        try:
            payload = await request.json()
            message = str(payload.get("message", "")).strip()
            if not message:
                raise ValueError("message is required")
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        _log.info(f"V2 describe: session={session_id[:8]} msg={message[:80]}")

        engine = _v2_conversations.get(session_id)
        if engine is None:
            return JSONResponse({"error": "Session conversation not found"}, status_code=409)

        # Force stability immediately — V2.0 skips multi-turn steering
        engine._state.steering_stable = True  # noqa: SLF001
        engine._state.turns.append(
            ConversationTurn(role="user", content=message)
        )
        engine._state.turn_count += 1

        # Extract Brief directly
        brief = await engine.extract_brief()
        brief_doc = brief.to_dict()

        # Save Brief
        artifacts_dir = session_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "brief.json").write_text(
            json.dumps(brief_doc, indent=2), encoding="utf-8"
        )
        _write_meta(session_dir, state="generating_hero", user_prompt=message)

        # Generate hero Canon via ComfyUI FLUX
        hero_url = ""
        try:
            hero_path = await _generate_hero_canon(session_id, session_dir, brief_doc, message)
            hero_url = f"/api/v2/session/{session_id}/artifact/hero_canon"
            _emit_event(session_id, "hero_ready", {"image_url": hero_url})
            _write_meta(session_dir, state="awaiting_approval", hero_canon=str(hero_path))
        except Exception as exc:
            _log.error(f"V2 hero canon failed: {exc}\n{traceback.format_exc()[-300:]}")
            _write_meta(session_dir, state="hero_failed", error=str(exc))
            return JSONResponse({
                "session_id": session_id,
                "message": "I generated a design brief but couldn't create the preview image. You can still approve to proceed.",
                "brief": brief_doc,
                "hero_image_url": "",
                "state": "hero_failed",
            })

        return {
            "session_id": session_id,
            "message": "Here's my vision for your room.",
            "brief": brief_doc,
            "hero_image_url": hero_url,
            "state": "awaiting_approval",
        }

    # ─── POST /api/v2/session/{id}/approve ─────────────────────────────────────

    @router.post("/api/v2/session/{session_id}/approve")
    async def v2_approve(session_id: str, request: Request):
        """User approves the hero Canon — trigger full automated pipeline (Phases 2–5)."""
        try:
            session_dir = _session_dir(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        meta = {}
        meta_path = session_dir / "session_meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

        if meta.get("state") not in ("awaiting_approval", "hero_failed"):
            return JSONResponse(
                {"error": f"Session state is '{meta.get('state')}', not awaiting approval"},
                status_code=409,
            )

        _write_meta(session_dir, state="building", approved_at=datetime.now(timezone.utc).isoformat())
        _log.info(f"V2 approved: session={session_id[:8]} — launching pipeline")

        # Launch the automated pipeline as a background task
        if session_id not in _v2_pipelines:
            task = asyncio.create_task(_run_v2_pipeline(session_id, session_dir))
            _v2_pipelines[session_id] = task

        return {
            "session_id": session_id,
            "state": "building",
            "stream_url": f"/api/v2/session/{session_id}/stream",
        }

    # ─── GET /api/v2/session/{id}/stream — SSE ────────────────────────────────

    @router.get("/api/v2/session/{session_id}/stream")
    async def v2_stream(session_id: str):
        """Server-Sent Events stream for pipeline progress."""
        async def event_generator():
            last_index = 0
            while True:
                events = _v2_events.get(session_id, [])
                while last_index < len(events):
                    ev = events[last_index]
                    yield f"event: {ev['type']}\ndata: {json.dumps(ev['data'])}\n\n"
                    last_index += 1
                    # Check if pipeline is done
                    if ev["type"] in ("world_ready", "error_event", "pipeline_complete"):
                        return
                await asyncio.sleep(0.5)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ─── GET /api/v2/session/{id}/status ───────────────────────────────────────

    @router.get("/api/v2/session/{session_id}/status")
    async def v2_status(session_id: str):
        """Return current pipeline state."""
        try:
            session_dir = _session_dir(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        meta_path = session_dir / "session_meta.json"
        if meta_path.is_file():
            return json.loads(meta_path.read_text(encoding="utf-8"))
        return {"state": "unknown"}

    # ─── GET /api/v2/session/{id}/artifact/{name} ──────────────────────────────

    @router.get("/api/v2/session/{session_id}/artifact/{artifact_name}")
    async def v2_artifact(session_id: str, artifact_name: str):
        """Serve pipeline artifacts (images, meshes)."""
        from fastapi.responses import FileResponse

        try:
            session_dir = _session_dir(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        artifact_map = {
            "hero_canon": session_dir / "artifacts" / "canon.png",
            "depth": session_dir / "artifacts" / "depth.png",
            "catalog": session_dir / "artifacts" / "catalog.json",
        }

        # Check for view artifacts: view_0, view_1, etc.
        if artifact_name.startswith("view_"):
            idx = artifact_name.split("_")[1]
            path = session_dir / "artifacts" / "views" / f"view_{idx}" / "canon.png"
            if path.is_file():
                return FileResponse(path, media_type="image/png")
            return JSONResponse({"error": "View not found"}, status_code=404)

        # Check for mesh artifacts: mesh_{uuid}
        if artifact_name.startswith("mesh_"):
            mesh_id = artifact_name[5:]
            path = session_dir / "artifacts" / "meshes" / f"{mesh_id}.glb"
            if path.is_file():
                return FileResponse(path, media_type="model/gltf-binary")
            return JSONResponse({"error": "Mesh not found"}, status_code=404)

        path = artifact_map.get(artifact_name)
        if path and path.is_file():
            suffix = path.suffix.lower()
            media = {".png": "image/png", ".jpg": "image/jpeg", ".glb": "model/gltf-binary", ".json": "application/json"}.get(
                suffix, "application/octet-stream"
            )
            return FileResponse(path, media_type=media)

        return JSONResponse({"error": f"Artifact '{artifact_name}' not found"}, status_code=404)

    # ─── GET /api/v2/session/{id}/scene — scene manifest for Three.js ─────────

    @router.get("/api/v2/session/{session_id}/scene")
    async def v2_scene(session_id: str):
        """Return the assembled scene manifest for client-side Three.js loading."""
        try:
            session_dir = _session_dir(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        scene_path = session_dir / "artifacts" / "scene.json"
        if not scene_path.is_file():
            return JSONResponse({"error": "Scene not yet assembled"}, status_code=404)

        return json.loads(scene_path.read_text(encoding="utf-8"))

    # ─── GET /api/v2/session/{id}/place-ui — placement game page ──────────────

    @router.get("/api/v2/place")
    async def v2_place_page():
        """Serve the drag-and-drop placement game UI."""
        from fastapi.responses import HTMLResponse
        template_path = Path(__file__).parent / "templates" / "place_v2.html"
        return HTMLResponse(template_path.read_text(encoding="utf-8"))

    # ─── POST /api/v2/session/{id}/place — back-project drop to 3D ────────────

    @router.post("/api/v2/session/{session_id}/place")
    async def v2_place_object(session_id: str, request: Request):
        """Receive a drop coordinate (px, py) and back-project to 3D via depth map."""
        import math
        import numpy as np
        from PIL import Image

        try:
            session_dir = _session_dir(session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)

        body = await request.json()
        uuid = body.get("uuid")
        px = body.get("px")  # normalized [0,1]
        py = body.get("py")  # normalized [0,1]

        if uuid is None or px is None or py is None:
            return JSONResponse({"error": "uuid, px, py required"}, status_code=400)

        # Load depth map
        depth_path = session_dir / "artifacts" / "depth.png"
        if not depth_path.is_file():
            return JSONResponse({"error": "No depth map"}, status_code=404)

        depth = np.array(Image.open(depth_path).convert("L")).astype(np.float32)
        img_h, img_w = depth.shape

        # Sample depth at drop point
        dx = int(px * img_w)
        dy = int(py * img_h)
        dx = max(0, min(img_w - 1, dx))
        dy = max(0, min(img_h - 1, dy))
        # Median of patch for robustness
        patch_r = 10
        patch = depth[max(0, dy-patch_r):dy+patch_r, max(0, dx-patch_r):dx+patch_r]
        depth_val = float(np.median(patch)) if patch.size > 0 else 128.0

        # Load scene for room dimensions
        scene_path = session_dir / "artifacts" / "scene.json"
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        room_dims = scene.get("room_dimensions", [4.5, 4.5, 3.0])
        room_d = room_dims[1]

        # Back-project: depth convention 0=far, 255=near
        min_depth_m = 0.5
        max_depth_m = room_d
        metric_depth = max_depth_m - (depth_val / 255.0) * (max_depth_m - min_depth_m)

        # Pinhole back-projection (60 deg horizontal FOV)
        fov_h_rad = math.radians(70.0)
        focal_length_px = (img_w / 2) / math.tan(fov_h_rad / 2)

        room_x = (px * img_w - img_w / 2) / focal_length_px * metric_depth
        room_z = -(metric_depth - room_d / 2)

        # Y elevation: use vertical position as hint
        # Objects in lower half of image = floor level, upper = elevated
        if py > 0.7:
            room_y = 0.0
        elif py > 0.4:
            room_y = 0.5
        elif py > 0.2:
            room_y = 1.5
        else:
            room_y = 2.2  # ceiling-level

        # Clamp to room
        room_w = room_dims[0]
        room_x = max(-room_w/2, min(room_w/2, room_x))
        room_z = max(-room_d/2, min(room_d/2, room_z))

        # Update scene.json
        for obj in scene.get("objects", []):
            if obj["uuid"] == uuid:
                obj["position"] = {
                    "x": round(float(room_x), 3),
                    "y": round(float(room_y), 3),
                    "z": round(float(room_z), 3),
                }
                break

        scene_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "uuid": uuid,
            "pixel": {"px": px, "py": py},
            "depth_value": depth_val,
            "position": {"x": round(float(room_x), 3), "y": round(float(room_y), 3), "z": round(float(room_z), 3)},
        }

    return router


# ─── Hero Canon Generation ─────────────────────────────────────────────────────


async def _generate_hero_canon(
    session_id: str,
    session_dir: Path,
    brief: dict[str, Any],
    user_prompt: str,
) -> Path:
    """Generate the hero Canon image via FLUX through ComfyUI.

    Simplified version of the V16 canon_generation stage — single image,
    no blockout conditioning (text-to-image only for speed).
    """
    from src.photo_pipeline.comfyui_client import ComfyUIClient
    from src.unified_pipeline.dream_preview import FLUX_CLIP, FLUX_MODEL, FLUX_VAE

    # Build prompt from Brief
    room_purpose = brief.get("room_purpose", "room")
    atmosphere = brief.get("atmosphere", {})
    mood = atmosphere.get("mood", "warm and inviting") if isinstance(atmosphere, dict) else "warm"
    era = brief.get("era", {})
    period = era.get("period", "") if isinstance(era, dict) else ""
    palette = brief.get("palette", {})
    primary = palette.get("primary", "") if isinstance(palette, dict) else ""

    objects = brief.get("object_manifest", [])
    object_names = ", ".join(
        item.get("name", "") for item in objects[:8]
        if isinstance(item, dict) and item.get("name")
    ) or "furniture and fixtures"

    prompt = (
        f"Photorealistic interior photograph of a "
        f"{period + ' ' if period else ''}{room_purpose}, "
        f"{mood} atmosphere, featuring {object_names}. "
        f"{primary + ' tones. ' if primary else ''}"
        f"Exact user request: {user_prompt}. "
        f"Professional architectural photography, natural lighting, "
        f"high detail, 8K resolution, sharp focus, magazine quality."
    )

    negative = (
        "blurry, low quality, deformed, sketch, wireframe, cartoon, "
        "3d render, text, watermark, duplicate objects, empty room"
    )

    # Output path
    artifacts_dir = session_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = artifacts_dir / "canon.png"

    # Submit FLUX workflow to ComfyUI
    client = ComfyUIClient(timeout_s=600, poll_interval_s=0.75)
    if not await client.health_check():
        raise RuntimeError("ComfyUI not available on localhost:8188")

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
            "inputs": {"text": negative, "clip": ["2", 0]},
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
            "inputs": {"images": ["8", 0], "filename_prefix": "v2_hero_canon"},
        },
    }

    prompt_id = await client.submit_workflow(workflow, client_id=f"v2-hero-{session_id[:16]}")
    await client.wait_for_completion(prompt_id, timeout_s=600)
    await client.get_output_image(prompt_id=prompt_id, output_dir=artifacts_dir, filename="canon.png")

    # Release VRAM for subsequent stages
    await client.release_vram()

    _log.info(f"V2 hero canon generated: {output_path}")
    return output_path


# ─── Automated Pipeline (Phases 2–5) ──────────────────────────────────────────


async def _run_v2_pipeline(session_id: str, session_dir: Path) -> None:
    """Run the full automated V2.0 pipeline after user approval.

    Phase 2: Multi-view generation (5 views + depth)
    Phase 3: Vision catalog (object detection across views)
    Phase 4: Mesh generation (one GLB per cataloged object)
    Phase 5: Assembly (room shell + objects → walkable Three.js scene)

    Each phase emits SSE events for progressive UI updates.
    """
    _log.info(f"V2 pipeline starting for {session_id[:8]}")

    def emit(event_type: str, data: dict[str, Any]) -> None:
        events = _v2_events.setdefault(session_id, [])
        events.append({"type": event_type, "data": data, "time": time.time()})

    try:
        # Load the Brief
        brief_path = session_dir / "artifacts" / "brief.json"
        if not brief_path.is_file():
            raise RuntimeError("Brief not found — cannot proceed")
        brief = json.loads(brief_path.read_text(encoding="utf-8"))

        # Phase 2: Multi-view generation
        emit("phase_start", {"phase": "densify", "message": "Generating multiple views..."})
        from src.unified_pipeline.multi_view_generator import generate_multi_views
        views = await generate_multi_views(brief, session_dir, emit_fn=emit)

        # Phase 3: Vision catalog
        emit("phase_start", {"phase": "catalog", "message": "Analyzing objects across views..."})
        from src.unified_pipeline.vision_catalog import catalog_objects
        catalog = await catalog_objects(views, brief, session_dir, emit_fn=emit)

        # Phase 4: Mesh generation
        emit("phase_start", {"phase": "build", "message": "Building 3D objects..."})
        from src.unified_pipeline.v2_mesh_builder import build_meshes
        meshes = await build_meshes(catalog, views, session_dir, emit_fn=emit)

        # Phase 5: Assembly
        emit("phase_start", {"phase": "assemble", "message": "Assembling walkable world..."})
        from src.unified_pipeline.v2_assembler import assemble_world
        scene = await assemble_world(brief, meshes, session_dir, emit_fn=emit)

        # Done
        emit("world_ready", {
            "scene_url": f"/api/v2/session/{session_id}/scene",
            "object_count": len(meshes),
        })
        emit("pipeline_complete", {"status": "success", "total_objects": len(meshes)})

        # Update meta
        meta_path = session_dir / "session_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        meta["state"] = "complete"
        meta["completed_at"] = datetime.now(timezone.utc).isoformat()
        meta["object_count"] = len(meshes)
        tmp = meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(meta_path)

    except Exception as exc:
        _log.error(f"V2 pipeline error: {exc}\n{traceback.format_exc()[-500:]}")
        emit("error_event", {"phase": "pipeline", "message": str(exc)})
