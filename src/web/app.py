"""FastAPI interface for The Living Room."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.canon_image.generator import check_comfyui, get_image_provider
from src.models import PipelineState
from src.orchestrator.llm import LLM_MODEL, OLLAMA_URL
from src.pipeline import WorldBuilder
from src.web.templates import get_index_html

app = FastAPI(title="The Living Room", version="0.4.0")
sessions: dict[str, WorldBuilder] = {}
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _restore_builder(session_id: str) -> WorldBuilder | None:
    builder = sessions.get(session_id)
    if builder:
        return builder
    session_path = OUTPUT_DIR / session_id / "session.json"
    if not session_path.exists():
        return None
    builder = WorldBuilder(session_id=session_id)
    sessions[session_id] = builder
    return builder


def _error(builder: WorldBuilder | None, exc: Exception, status_code: int = 500):
    if builder:
        builder.session.state = PipelineState.ERROR
        builder.session.error = str(exc)
        builder.save_session()
    return JSONResponse({"error": str(exc)}, status_code=status_code)


def _plan_payload(builder: WorldBuilder, plan) -> dict:
    session_id = builder.session.session_id
    version = builder.session.plan_revision
    return {
        "session_id": session_id,
        "artifact": "plan",
        "state": builder.session.state.value,
        "concept": builder.session.scene_concept.model_dump(),
        "floor_plan": plan.model_dump(),
        "floor_plan_image": f"/api/session/{session_id}/floor_plan?v={version}",
        "blockout_image": f"/api/session/{session_id}/blockout?v={version}",
        "plan_revision": version,
        "warnings": builder.session.plan_warnings,
        "progress": builder.session.progress_messages,
    }


def _snapshot_payload(builder: WorldBuilder) -> dict:
    session = builder.session
    common = {
        "session_id": session.session_id,
        "state": session.state.value,
        "user_description": session.user_description,
        "progress": session.progress_messages,
    }
    if session.scene_graph and session.output_path:
        return {
            **common,
            "artifact": "world",
            "scene_graph": session.scene_graph.model_dump(),
            "download_url": f"/api/session/{session.session_id}/download",
        }
    if session.canon_image_path and session.scene_concept:
        attempt = len(list((OUTPUT_DIR / session.session_id).glob("canon_v*.png"))) or 1
        return {
            **common,
            "artifact": "canon",
            "concept": session.scene_concept.model_dump(),
            "canon_image": f"/api/session/{session.session_id}/canon_image?v={attempt}",
            "provider": get_image_provider(session.session_id),
            "attempt": attempt,
        }
    if session.floor_plan and session.scene_concept:
        return {**_plan_payload(builder, session.floor_plan), "user_description": session.user_description}
    return {**common, "artifact": "empty"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        version = int(request.query_params.get("v", "4"))
    except ValueError:
        version = 4
    return HTMLResponse(
        get_index_html(version),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/readiness")
async def readiness():
    comfy = await check_comfyui()
    ollama = {"ready": False, "model": LLM_MODEL}
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(f"{OLLAMA_URL.rstrip('/')}/api/tags")
            response.raise_for_status()
        names = [item.get("name", "") for item in response.json().get("models", [])]
        ollama.update(ready=any(name == LLM_MODEL or name.startswith(f"{LLM_MODEL}:") for name in names), available=names)
    except Exception as exc:
        ollama["reason"] = str(exc)
    return {"api": True, "comfyui": comfy, "ollama": ollama, "image_stack": "FLUX.2 Klein 4B FP8", "mesh_stack": "Procedural now · Hunyuan3D next"}


@app.post("/api/session")
async def create_session():
    builder = WorldBuilder()
    sessions[builder.session.session_id] = builder
    builder.save_session()
    return {"session_id": builder.session.session_id}


@app.get("/api/session/latest/snapshot")
async def latest_session_snapshot():
    if sessions:
        builder = next(reversed(sessions.values()))
        return _snapshot_payload(builder)
    candidates = list(OUTPUT_DIR.glob("*/session.json"))
    if not candidates:
        return JSONResponse({"error": "No active session"}, status_code=404)
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    builder = _restore_builder(latest.parent.name)
    return _snapshot_payload(builder)


@app.get("/api/session/{session_id}/snapshot")
async def session_snapshot(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return _snapshot_payload(builder)


@app.post("/api/session/{session_id}/describe")
async def describe(session_id: str, request: Request):
    builder = sessions.setdefault(session_id, WorldBuilder(session_id=session_id))
    try:
        description = str((await request.json()).get("description", "")).strip()
        if not description:
            raise ValueError("Describe a room before generating")
        builder.session.error = None
        builder.session.progress_messages.clear()
        await builder.step_interpret(description)
        plan = await builder.step_build_floor_plan()
        builder.session.state = PipelineState.AWAITING_PLAN_APPROVAL
        builder.save_session()
        return _plan_payload(builder, plan)
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/floor_plan")
async def get_floor_plan(session_id: str):
    builder = sessions.get(session_id)
    path = Path(builder.session.floor_plan_path) if builder and builder.session.floor_plan_path else None
    if not path or not path.exists():
        return JSONResponse({"error": "No floor plan for this session"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/session/{session_id}/blockout")
async def get_blockout(session_id: str):
    builder = sessions.get(session_id)
    path = Path(builder.session.blockout_path) if builder and builder.session.blockout_path else None
    if not path or not path.exists():
        return JSONResponse({"error": "No blockout for this session"}, status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/{session_id}/revise_plan")
async def revise_plan(session_id: str, request: Request):
    builder = sessions.get(session_id)
    if not builder or not builder.session.floor_plan:
        return JSONResponse({"error": "Session or plan not found"}, status_code=404)
    try:
        feedback = str((await request.json()).get("feedback", "")).strip()
        if not feedback:
            raise ValueError("Describe what should change in the plan")
        builder.session.error = None
        plan = await builder.step_build_floor_plan(feedback)
        builder.session.state = PipelineState.AWAITING_PLAN_APPROVAL
        builder.save_session()
        return _plan_payload(builder, plan)
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/approve_plan")
async def approve_plan(session_id: str):
    builder = sessions.get(session_id)
    if not builder or not builder.session.floor_plan:
        return JSONResponse({"error": "Session or plan not found"}, status_code=404)
    try:
        builder.session.error = None
        builder.session.floor_plan_approved = True
        await builder.step_generate_image(attempt=1)
        builder.session.state = PipelineState.AWAITING_APPROVAL
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "concept": builder.session.scene_concept.model_dump(),
            "canon_image": f"/api/session/{session_id}/canon_image?v=1",
            "provider": get_image_provider(session_id),
            "progress": builder.session.progress_messages,
        }
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/canon_image")
async def get_canon_image(session_id: str):
    builder = sessions.get(session_id)
    if not builder or not builder.session.canon_image_path:
        return JSONResponse({"error": "No canon image for this session"}, status_code=404)
    path = Path(builder.session.canon_image_path)
    if not path.exists():
        return JSONResponse({"error": "Canon image file is missing"}, status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/{session_id}/approve")
async def approve_image(session_id: str):
    builder = sessions.get(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    try:
        builder.session.error = None
        await builder.step_build_scene_graph()
        mesh_paths = await asyncio.to_thread(builder.step_generate_assets)
        project_path = await asyncio.to_thread(builder.step_assemble, mesh_paths)
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "progress": builder.session.progress_messages,
            "project_path": str(project_path),
            "download_url": f"/api/session/{session_id}/download",
            "scene_graph": builder.session.scene_graph.model_dump(),
            "mesh_urls": {obj_id: f"/api/session/{session_id}/mesh/{obj_id}" for obj_id in mesh_paths},
        }
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/reject")
async def reject_image(session_id: str, request: Request):
    builder = sessions.get(session_id)
    if not builder or not builder.session.scene_concept:
        return JSONResponse({"error": "Session or concept not found"}, status_code=404)
    try:
        feedback = str((await request.json()).get("feedback", "")).strip()
        if not feedback:
            raise ValueError("Revision feedback is required")
        concept = builder.session.scene_concept
        revised_prompt = f"{concept.image_prompt}. Revision requirement: {feedback}. Preserve all other approved scene details."
        builder.session.scene_concept = concept.model_copy(update={"image_prompt": revised_prompt})
        attempt = len(list((OUTPUT_DIR / session_id).glob("canon_v*.png"))) + 1
        await builder.step_generate_image(attempt=attempt)
        builder.session.state = PipelineState.AWAITING_APPROVAL
        builder.save_session()
        return {"state": builder.session.state.value, "canon_image": f"/api/session/{session_id}/canon_image?v={attempt}", "provider": get_image_provider(session_id), "attempt": attempt, "progress": builder.session.progress_messages}
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/revise_world")
async def revise_world(session_id: str, request: Request):
    """Capture feedback as session memory, compare render to canon, and rebuild."""
    builder = sessions.get(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    try:
        form = await request.form()
        feedback = str(form.get("feedback", "")).strip()
        upload = form.get("render")
        if not feedback:
            raise ValueError("Describe what should change in the world")
        if upload is None or not hasattr(upload, "read"):
            raise ValueError("A current 3D render capture is required")
        content = await upload.read()
        if not content:
            raise ValueError("The 3D render capture was empty")
        revision = builder.session.world_revision + 1
        render_path = builder.output_dir / f"world_render_v{revision}.png"
        render_path.write_bytes(content)
        builder.session.error = None
        report = await builder.step_refine_world(feedback, render_path)
        mesh_paths = await asyncio.to_thread(builder.step_generate_assets)
        project_path = await asyncio.to_thread(builder.step_assemble, mesh_paths)
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "revision": builder.session.world_revision,
            "report": report,
            "scene_graph": builder.session.scene_graph.model_dump(),
            "project_path": str(project_path),
            "download_url": f"/api/session/{session_id}/download?revision={revision}",
            "mesh_urls": {
                obj_id: f"/api/session/{session_id}/mesh/{obj_id}?revision={revision}"
                for obj_id in mesh_paths
            },
            "progress": builder.session.progress_messages,
        }
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/mesh/{obj_id}")
async def get_mesh(session_id: str, obj_id: str):
    mesh_path = OUTPUT_DIR / session_id / "meshes" / f"{obj_id}.glb"
    if not mesh_path.exists():
        return JSONResponse({"error": "Mesh not found"}, status_code=404)
    return FileResponse(mesh_path, media_type="model/gltf-binary")


@app.get("/api/session/{session_id}/scene_data")
async def get_scene_data(session_id: str):
    builder = sessions.get(session_id)
    if not builder or not builder.session.scene_graph:
        return JSONResponse({"error": "No scene built yet"}, status_code=404)
    return builder.session.scene_graph.model_dump()


@app.get("/api/session/{session_id}/download")
async def download_project(session_id: str):
    builder = sessions.get(session_id)
    if not builder or not builder.session.output_path:
        return JSONResponse({"error": "No project yet"}, status_code=404)
    zip_path = OUTPUT_DIR / session_id / "project"
    await asyncio.to_thread(shutil.make_archive, str(zip_path), "zip", builder.session.output_path)
    return FileResponse(f"{zip_path}.zip", media_type="application/zip", filename=f"living_room_{session_id}.zip")


@app.get("/api/session/{session_id}/status")
async def get_status(session_id: str):
    builder = sessions.get(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {"session_id": session_id, "state": builder.session.state.value, "progress": builder.session.progress_messages, "error": builder.session.error, "provider": get_image_provider(session_id), "has_image": builder.session.canon_image_path is not None, "has_project": builder.session.output_path is not None}
