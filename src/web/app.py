"""The Living Room - Web Interface (FastAPI)"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from src.pipeline import WorldBuilder
from src.web.templates import get_index_html

app = FastAPI(title="The Living Room", version="0.1.0")
sessions: dict[str, WorldBuilder] = {}
OUTPUT_DIR = Path("output")


@app.get("/", response_class=HTMLResponse)
async def index():
    return get_index_html()


@app.post("/api/session")
async def create_session():
    builder = WorldBuilder()
    sessions[builder.session.session_id] = builder
    return {"session_id": builder.session.session_id}


@app.post("/api/session/{session_id}/describe")
async def describe(session_id: str, request: Request):
    body = await request.json()
    description = body.get("description", "")
    if session_id not in sessions:
        builder = WorldBuilder(session_id=session_id)
        sessions[session_id] = builder
    else:
        builder = sessions[session_id]
    await builder.step_interpret(description)
    await builder.step_generate_image()
    return {
        "state": builder.session.state.value,
        "concept": builder.session.scene_concept.model_dump() if builder.session.scene_concept else None,
        "canon_image": f"/api/session/{session_id}/canon_image",
        "progress": builder.session.progress_messages,
    }


@app.get("/api/session/{session_id}/canon_image")
async def get_canon_image(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    builder = sessions[session_id]
    if not builder.session.canon_image_path:
        return JSONResponse({"error": "No image yet"}, status_code=404)
    return FileResponse(builder.session.canon_image_path, media_type="image/png")


@app.post("/api/session/{session_id}/approve")
async def approve_image(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    builder = sessions[session_id]
    await builder.step_build_scene_graph()
    mesh_paths = builder.step_generate_assets()
    project_path = builder.step_assemble(mesh_paths)
    return {
        "state": builder.session.state.value,
        "progress": builder.session.progress_messages,
        "project_path": str(project_path),
        "download_url": f"/api/session/{session_id}/download",
        "scene_graph": builder.session.scene_graph.model_dump() if builder.session.scene_graph else None,
        "mesh_urls": {obj_id: f"/api/session/{session_id}/mesh/{obj_id}" for obj_id in mesh_paths},
    }


@app.post("/api/session/{session_id}/reject")
async def reject_image(session_id: str, request: Request):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    body = await request.json()
    builder = sessions[session_id]
    attempt = len(list((OUTPUT_DIR / session_id).glob("canon_v*.png"))) + 1
    await builder.step_generate_image(attempt=attempt)
    return {
        "state": builder.session.state.value,
        "canon_image": f"/api/session/{session_id}/canon_image",
        "progress": builder.session.progress_messages,
    }


@app.get("/api/session/{session_id}/mesh/{obj_id}")
async def get_mesh(session_id: str, obj_id: str):
    """Serve individual mesh .glb files for the 3D viewer."""
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    mesh_path = OUTPUT_DIR / session_id / "meshes" / f"{obj_id}.glb"
    if not mesh_path.exists():
        return JSONResponse({"error": "Mesh not found"}, status_code=404)
    return FileResponse(mesh_path, media_type="model/gltf-binary")


@app.get("/api/session/{session_id}/scene_data")
async def get_scene_data(session_id: str):
    """Get the scene graph JSON for the 3D viewer."""
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    builder = sessions[session_id]
    if not builder.session.scene_graph:
        return JSONResponse({"error": "No scene built yet"}, status_code=404)
    return builder.session.scene_graph.model_dump()


@app.get("/api/session/{session_id}/download")
async def download_project(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    builder = sessions[session_id]
    if not builder.session.output_path:
        return JSONResponse({"error": "No project yet"}, status_code=404)
    zip_path = OUTPUT_DIR / session_id / "project"
    shutil.make_archive(str(zip_path), "zip", builder.session.output_path)
    return FileResponse(f"{zip_path}.zip", media_type="application/zip", filename=f"living_room_{session_id}.zip")


@app.get("/api/session/{session_id}/status")
async def get_status(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    builder = sessions[session_id]
    return {
        "session_id": session_id,
        "state": builder.session.state.value,
        "progress": builder.session.progress_messages,
        "has_image": builder.session.canon_image_path is not None,
        "has_project": builder.session.output_path is not None,
    }
