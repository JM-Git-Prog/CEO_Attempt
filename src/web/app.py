"""FastAPI interface for The Living Room."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.canon_image.generator import check_comfyui, get_image_provider
from src.floor_plan.validator import validate_floor_plan
from src.models import PipelineState, SessionMode
from src.orchestrator.llm import LLM_MODEL, OLLAMA_URL
from src.pipeline import SemanticBatchRejectedError, WorldBuilder
from src.session_manager import SessionManager
from src.telemetry import read_telemetry
from src.web.event_log import append_event
from src.web.history import (
    ArtifactVerificationError,
    get_session_stages,
    get_stage_evidence,
    list_sessions,
    resolve_verified_artifact,
)
from src.web.templates import get_index_html
from src.web.unified_routes import (
    create_unified_router,
    unified_artifact_response,
    unified_sse_response,
)
from src.workflow_provenance import normalize_interface_version, workflow_profiles

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
STATIC_DIR = Path(__file__).parent / "static"

# Global SessionManager for MVP session lifecycle (Req 12.2, 12.5, 12.6)
_session_manager = SessionManager(output_base=OUTPUT_DIR)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Mark any incomplete sessions from a previous server run as failed (Req 12.6)."""
    count = _session_manager.mark_failed_on_restart()
    if count:
        print(f"[startup] Marked {count} incomplete session(s) as failed (server_restart)")
    yield


app = FastAPI(title="The Living Room", version="0.9.0", lifespan=_lifespan)
sessions: dict[str, WorldBuilder] = {}
session_locks: dict[str, asyncio.Lock] = {}
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Live trace — simple request logging without middleware interference
import logging
_trace_handler = logging.FileHandler(OUTPUT_DIR / "live_trace.log", encoding="utf-8")
_trace_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
_trace_logger = logging.getLogger("live_trace")
_trace_logger.addHandler(_trace_handler)
_trace_logger.setLevel(logging.INFO)
_trace_logger.info("=== Server started — live trace active ===")
app.include_router(create_unified_router(lambda: OUTPUT_DIR))

# 2026-07-31 (John): the ComfyUI "The Line" canvas (origin :8188) polls
# /api/v15fable/line-activity to light up the live stage — localhost-only CORS.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8188", "http://localhost:8188"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# --- v15_Fable (2026-07-30): ADDITIVE hook only — standalone routes in src/v15_fable.py,
# --- standalone page in templates/index_v15_fable.html. No v3-v14 behavior is changed.
from src.v15_fable import router as _v15_fable_router  # noqa: E402
app.include_router(_v15_fable_router)

from src.web.approval_routes import router as _approval_router  # noqa: E402
app.include_router(_approval_router)

# V2.0 (2026-08-26): "One Prompt, One Room" — multi-view pipeline routes.
from src.web.v2_routes import create_v2_router  # noqa: E402
app.include_router(create_v2_router(lambda: OUTPUT_DIR))


def _normalize_requested_version(value: str | None, source: str) -> int:
    """Normalize a canonical interface version without silently coercing input."""
    if value is None or value == "":
        return normalize_interface_version(None)
    if not re.fullmatch(r"[0-9]+", value) or value != str(int(value)):
        raise ValueError(f"Malformed {source} interface version: {value!r}")
    version = normalize_interface_version(value)
    if version != int(value):
        raise ValueError(
            f"Unsupported {source} interface version {value}; supported versions are 3-{normalize_interface_version(None)}"
        )
    return version


def _request_version(request: Request) -> int:
    return _normalize_requested_version(
        request.headers.get("x-app-version"), "X-App-Version header"
    )


def _session_lock(session_id: str) -> asyncio.Lock:
    return session_locks.setdefault(session_id, asyncio.Lock())


def _alignment_review_matches(builder: WorldBuilder) -> bool:
    report = builder.session.canon_alignment or {}
    binding = report.get("binding")
    if report.get("status") != "inconclusive" or not isinstance(binding, dict):
        return False
    return any(
        review.get("decision") == "accepted" and review.get("binding") == binding
        for review in builder.session.canon_alignment_reviews
    )


def _session_artifact_path(builder: WorldBuilder, raw_path: object) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path:
        return None
    root = builder.output_dir.resolve()
    candidate = Path(raw_path)
    candidates = [candidate.resolve()]
    if not candidate.is_absolute():
        candidates.append((root / candidate).resolve())
    return next(
        (path for path in candidates if path.is_file() and path.is_relative_to(root)), None
    )


def _recorded_v11_artifacts(builder: WorldBuilder) -> list[dict]:
    """Return existing compiler/export files explicitly recorded by this session."""
    if builder.session.interface_version < 11:
        return []
    records: list[tuple[str, str, dict]] = []
    compiler = builder.session.compiler_result or {}
    for item in compiler.get("artifacts", []):
        if isinstance(item, dict):
            records.append(("compiler", str(item.get("target_role", "artifact")), item))
    for target, result in builder.session.export_results.items():
        if not isinstance(result, dict):
            continue
        for collection in ("artifacts", "manifests"):
            for item in result.get(collection, []):
                if isinstance(item, dict):
                    records.append((f"export:{target}", str(item.get("target_role", collection)), item))
    for index, path in enumerate(builder.session.compiler_manifests, start=1):
        records.append(("compiler", f"compiler_manifest_{index}", {
            "path": path, "media_type": "application/json"
        }))

    artifacts: list[dict] = []
    seen: set[Path] = set()
    for source, role, item in records:
        path = _session_artifact_path(builder, item.get("path"))
        if path is None or path in seen:
            continue
        seen.add(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = item.get("sha256")
        artifact_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20]
        artifacts.append({
            "id": artifact_id, "source": source, "role": role, "filename": path.name,
            "bytes": path.stat().st_size, "sha256": expected or digest,
            "integrity": "verified" if expected in (None, digest) else "mismatch",
            "media_type": item.get("media_type") or mimetypes.guess_type(path.name)[0]
            or "application/octet-stream",
            "download_url": f"/api/session/{builder.session.session_id}/artifact/{artifact_id}",
        })
    return artifacts


def _v11_runtime_payload(builder: WorldBuilder) -> dict:
    if builder.session.interface_version < 11:
        return {}
    session = builder.session
    result = dict(session.compiler_result or {})
    target = result.get("target")
    status = result.get("status", "not_started")
    if target == "upbge" and status == "native_success":
        execution = "native"
    elif target == "godot" and status == "fallback_success":
        execution = "declared_fallback"
    elif status == "partial_export":
        execution = "partial"
    elif target == "godot" and status == "adapter_success":
        execution = "profile_selected"
    elif result:
        execution = "failed"
    else:
        execution = "not_started"

    versions: dict = {}
    manifest_diagnostics: list[dict] = []
    terminal_path = _session_artifact_path(builder, result.get("terminal_manifest"))
    if terminal_path:
        try:
            terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            versions = terminal.get("compiler") or {}
            manifest_diagnostics = terminal.get("diagnostics") or []
        except (OSError, ValueError, TypeError):
            manifest_diagnostics = [{
                "stage": "web", "code": "manifest_unreadable", "severity": "warning",
                "message": "Recorded terminal compiler manifest could not be read",
            }]

    failures: list[dict] = []
    primary_failure = result.get("primary_failure")
    if isinstance(primary_failure, dict):
        failures.append(primary_failure)
    sidecar = result.get("sidecar")
    if isinstance(sidecar, dict) and not sidecar.get("success", False):
        failures.append(sidecar)
    failures.extend(item for item in manifest_diagnostics if isinstance(item, dict))
    compiler = {
        **result,
        "primary_target": "upbge", "declared_fallback": "godot",
        "target": target, "status": status, "execution": execution,
        "capability": result.get("capability") or {}, "versions": versions,
        "failures": failures, "manifests": list(session.compiler_manifests),
    }
    artifacts = _recorded_v11_artifacts(builder)
    details = {
        "compiler": compiler, "exports": session.export_results,
        "parity": session.parity_report, "runtime": session.runtime_smoke_report,
        "qa": session.qa_evidence, "artifacts": artifacts,
        "attempts": [record.value() for record in session.compiler_attempt_records],
    }
    return {
        "runtime_details": details, "compiler_result": compiler,
        "export_results": session.export_results, "parity_report": session.parity_report,
        "runtime_smoke_report": session.runtime_smoke_report,
        "qa_evidence": session.qa_evidence,
        "compiler_manifests": list(session.compiler_manifests),
        "compiler_attempt_records": [
            record.value() for record in session.compiler_attempt_records
        ],
        "artifact_downloads": artifacts,
    }


@app.middleware("http")
async def log_session_api(request: Request, call_next):
    """Log backend session-process operations under the calling UI revision."""
    path = request.url.path
    try:
        request_version = _request_version(request)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    is_session_api = path.startswith("/api/session")
    history_roots = {
        "/api/v8/sessions", "/api/v9/sessions", "/api/v10/sessions", "/api/v11/sessions",
        "/api/v14/sessions",
    }
    is_history_api = (
        path in history_roots
        or path.startswith("/api/v8/session/")
        or path.startswith("/api/v9/session/")
        or path.startswith("/api/v10/session/")
        or path.startswith("/api/v11/session/")
        or path.startswith("/api/v14/session/")
    )
    if not (is_session_api or is_history_api):
        return await call_next(request)
    version = str(request_version)
    parts = path.split("/")
    session_index = 4 if is_history_api and path not in history_roots else 3
    session_id = parts[session_index] if len(parts) > session_index else None
    route = path.replace(session_id, "{session_id}") if session_id else path
    try:
        response = await call_next(request)
    except Exception:
        await asyncio.to_thread(append_event, OUTPUT_DIR, {
            "app_version": version, "session_id": session_id, "event_type": "process",
            "action": f"{request.method} {route}", "details": {"status": 500},
        })
        raise
    details: dict[str, object] = {"status": response.status_code}
    builder = sessions.get(session_id) if session_id else None
    if builder:
        details["state"] = builder.session.state.value
        if builder.session.progress_messages:
            details["progress"] = builder.session.progress_messages[-1]
    await asyncio.to_thread(append_event, OUTPUT_DIR, {
        "app_version": version, "session_id": session_id, "event_type": "process",
        "action": f"{request.method} {route}", "details": details,
    })
    return response


@app.post("/api/events")
async def record_event(request: Request):
    """Record a sanitized browser lifecycle, process, click, or test event."""
    try:
        record = await asyncio.to_thread(append_event, OUTPUT_DIR, await request.json())
        return {"logged": True, "timestamp": record["timestamp"], "app_version": record["app_version"]}
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


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
        "validation_report": builder.session.plan_validation.model_dump(),
        "progress": builder.session.progress_messages,
        "interface_version": builder.session.interface_version,
        "workflow_profile_id": builder.session.workflow_profile_id,
        "camera_contract": (
            builder.session.camera_contract.model_dump()
            if builder.session.camera_contract else None
        ),
        "composition_evidence": builder.session.composition_evidence,
        "workflow_url": f"/api/session/{session_id}/workflow",
        **_v11_runtime_payload(builder),
    }


def _snapshot_payload(builder: WorldBuilder) -> dict:
    session = builder.session
    common = {
        "session_id": session.session_id,
        "state": session.state.value,
        "user_description": session.user_description,
        "progress": session.progress_messages,
        "interface_version": session.interface_version,
        "workflow_profile_id": session.workflow_profile_id,
        "camera_contract": (
            session.camera_contract.model_dump() if session.camera_contract else None
        ),
        "canon_alignment": session.canon_alignment,
        "canon_attempt": session.canon_attempt,
        "canon_alignment_reviewed": _alignment_review_matches(builder),
        "workflow_url": f"/api/session/{session.session_id}/workflow",
        **_v11_runtime_payload(builder),
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
            "provider": session.canon_provider or get_image_provider(session.session_id),
            "attempt": attempt,
        }
    if session.floor_plan and session.scene_concept:
        return {**_plan_payload(builder, session.floor_plan), "user_description": session.user_description}
    return {**common, "artifact": "empty"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # V2.0 (2026-08-26): reimagined multi-view pipeline — "One Prompt, One Room".
    # Non-numeric version string, standalone page. No V3–V16 behavior changed.
    if request.query_params.get("v") in ("2.0", "20"):
        page = Path(__file__).parent / "templates" / "index_v2_0.html"
        return HTMLResponse(page.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})
    # V2.1 (2026-08-31): panorama-first walkable room. A 360° equirectangular
    # panorama is generated from the room center and rendered as an inside-out
    # sky-sphere (immediate non-empty view), with the panorama also projected
    # onto the exact room box for collidable walls. Additive standalone page;
    # V2.0 remains accessible and behaviorally unchanged.
    if request.query_params.get("v") in ("2.1", "21"):
        page = Path(__file__).parent / "templates" / "index_v2_1.html"
        return HTMLResponse(page.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})
    # V17 (2026-08-30): split-screen — builder-agent chat (left) + live walkable
    # Three.js world (right). Additive early branch, standalone page. Reuses the
    # V16 unified pipeline API verbatim; no V3–V16 behavior changed.
    if request.query_params.get("v") in ("17", "17.0"):
        page = Path(__file__).parent / "templates" / "index_v17.html"
        return HTMLResponse(page.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})
    # v15_Fable (2026-07-30): additive early branch — non-numeric version, standalone page.
    # 15_Fable_Dev (2026-07-31): SAME page, dev flag read client-side — TRELLIS 2 one-pass
    # prop lane (The Line v1.1_Dev) instead of blast+paint. Prod lane untouched.
    if request.query_params.get("v") in ("15", "15_Fable", "15_Fable_Dev"):
        page = Path(__file__).parent / "templates" / "index_v15_fable.html"
        return HTMLResponse(page.read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})
    try:
        version = _normalize_requested_version(request.query_params.get("v"), "page")
    except ValueError as exc:
        return HTMLResponse(
            f"<!doctype html><title>Invalid interface version</title><h1>400</h1><p>{escape(str(exc))}</p>",
            status_code=400,
        )
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


@app.get("/api/workflow/profiles")
async def get_workflow_profiles():
    return {"schema_version": 1, "profiles": workflow_profiles()}


def _v8_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ArtifactVerificationError):
        return JSONResponse({"error": str(exc)}, status_code=409)
    if isinstance(exc, FileNotFoundError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/v8/sessions")
async def v8_sessions():
    return list_sessions(OUTPUT_DIR, version_filter=8)


@app.get("/api/v9/sessions")
async def v9_sessions():
    return list_sessions(OUTPUT_DIR, version_filter=9)


@app.get("/api/v10/sessions")
async def v10_sessions():
    return list_sessions(OUTPUT_DIR, version_filter=10)


@app.get("/api/v11/sessions")
async def v11_sessions():
    return list_sessions(OUTPUT_DIR, version_filter=11)


@app.get("/api/v8/session/{session_id}/stages")
@app.get("/api/v9/session/{session_id}/stages")
@app.get("/api/v10/session/{session_id}/stages")
@app.get("/api/v11/session/{session_id}/stages")
async def v8_session_stages(session_id: str):
    try:
        return get_session_stages(OUTPUT_DIR, session_id)
    except (FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)


@app.get("/api/v8/session/{session_id}/stage/{stage}")
@app.get("/api/v9/session/{session_id}/stage/{stage}")
@app.get("/api/v10/session/{session_id}/stage/{stage}")
@app.get("/api/v11/session/{session_id}/stage/{stage}")
async def v8_stage(session_id: str, stage: str, revision: str | None = None):
    try:
        return get_stage_evidence(OUTPUT_DIR, session_id, stage, revision)
    except (FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)


@app.get("/api/v8/session/{session_id}/stage/{stage}/artifact")
@app.get("/api/v9/session/{session_id}/stage/{stage}/artifact")
@app.get("/api/v10/session/{session_id}/stage/{stage}/artifact")
@app.get("/api/v11/session/{session_id}/stage/{stage}/artifact")
async def v8_stage_artifact(session_id: str, stage: str, revision: str | None = None):
    try:
        path, media_type, verification = resolve_verified_artifact(
            OUTPUT_DIR, session_id, stage, revision
        )
    except (ArtifactVerificationError, FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)
    headers = {
        "Cache-Control": "no-store",
        "X-Artifact-Integrity": "verified" if verification["verified"] else "unverified",
        "X-Artifact-SHA256": verification["sha256"],
    }
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/api/v8/session/{session_id}/telemetry")
@app.get("/api/v9/session/{session_id}/telemetry")
@app.get("/api/v10/session/{session_id}/telemetry")
@app.get("/api/v11/session/{session_id}/telemetry")
async def v8_telemetry(session_id: str):
    try:
        stages = get_session_stages(OUTPUT_DIR, session_id)
    except (FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)
    payload = read_telemetry(OUTPUT_DIR / session_id)
    payload.update(
        session_id=session_id,
        interface_version=stages.get("interface_version"),
        availability="recorded" if payload["enabled"] else "not_recorded",
    )
    return payload


@app.post("/api/session")
async def create_session(request: Request):
    # Parse optional mode from request body (default: "mvp" per Req 10.4)
    mode = SessionMode.MVP
    try:
        body = await request.json()
        raw_mode = str(body.get("mode", "mvp")).strip().lower()
        if raw_mode == "full":
            mode = SessionMode.FULL
        elif raw_mode != "mvp":
            return JSONResponse(
                {"error": f"Unsupported mode: {raw_mode!r}; expected 'mvp' or 'full'"},
                status_code=400,
            )
    except Exception:
        # No body or unparseable body → default to MVP
        pass

    builder = WorldBuilder(interface_version=_request_version(request))
    builder.session.mode = mode
    sessions[builder.session.session_id] = builder
    builder.save_session()
    return {
        "session_id": builder.session.session_id,
        "mode": builder.session.mode.value,
        "interface_version": builder.session.interface_version,
        "workflow_profile_id": builder.session.workflow_profile_id,
        "workflow_url": f"/api/session/{builder.session.session_id}/workflow",
    }


@app.post("/api/session/photo/upload")
async def upload_photo(request: Request):
    """Accept a photo file upload and save it to a temp location."""
    import tempfile
    form = await request.form()
    photo = form.get("photo")
    if not photo:
        return JSONResponse({"error": "No photo file provided"}, status_code=400)

    # Save to a temp file in the output directory
    upload_dir = OUTPUT_DIR / "_uploads"
    upload_dir.mkdir(exist_ok=True)

    suffix = ".png" if "png" in (photo.content_type or "") else ".jpg"
    dest = upload_dir / f"{uuid.uuid4().hex[:12]}{suffix}"

    contents = await photo.read()
    dest.write_bytes(contents)

    return {"path": str(dest), "size": len(contents), "filename": photo.filename}


@app.post("/api/session/photo")
async def create_photo_session(request: Request):
    """Create a photo pipeline session and run the photo-to-world pipeline.

    Accepts a JSON body with:
      - source_image: str (path to an RGB image on local disk)
      - mode: "mvp" | "full" (optional, default "mvp")

    Routes to PhotoPipelineOrchestrator.run() when source_type="photo".
    The resulting WorldContract feeds into the same UPBGE compilation chain as text.

    Requirements: 14.1, 14.2, 14.3, 14.4, 14.5
    """
    from src.photo_pipeline.orchestrator import (
        PhotoPipelineOrchestrator,
        PipelineError,
        PipelineTimeoutError,
        PipelineValidationError,
    )
    from src.photo_pipeline.models import PhotoPipelineConfig

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Request body must be valid JSON with 'source_image' field"},
            status_code=400,
        )

    source_image_str = body.get("source_image", "")
    if not source_image_str:
        return JSONResponse(
            {"error": "source_image path is required"},
            status_code=400,
        )

    source_image = Path(source_image_str)
    if not source_image.exists():
        return JSONResponse(
            {"error": f"Source image not found: {source_image}"},
            status_code=400,
        )

    # Parse mode (mvp/full)
    raw_mode = str(body.get("mode", "mvp")).strip().lower()
    if raw_mode == "full":
        mode = SessionMode.FULL
    elif raw_mode == "mvp":
        mode = SessionMode.MVP
    else:
        return JSONResponse(
            {"error": f"Unsupported mode: {raw_mode!r}; expected 'mvp' or 'full'"},
            status_code=400,
        )

    # Create session with source_type="photo"
    session_id = str(uuid.uuid4())[:8]
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Configure and run photo pipeline orchestrator (full chain including compilation)
    config = PhotoPipelineConfig()
    orchestrator = PhotoPipelineOrchestrator(
        config=config,
        session_dir=session_dir,
        session_id=session_id,
    )

    try:
        manifest, compilation_result = await orchestrator.run_full(source_image)
    except PipelineValidationError as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "session_id": session_id,
                "source_type": "photo",
                "stage": "input_validation",
                "reason_code": "validation_failed",
            },
            status_code=400,
        )
    except PipelineTimeoutError as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "session_id": session_id,
                "source_type": "photo",
                "stage": "pipeline",
                "reason_code": "timeout",
            },
            status_code=504,
        )
    except PipelineError as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "session_id": session_id,
                "source_type": "photo",
                "stage": "pipeline",
                "reason_code": "pipeline_error",
            },
            status_code=500,
        )
    except Exception as exc:
        # Catch any unhandled exception (ComfyUI node errors, etc.)
        import traceback
        traceback.print_exc()
        error_msg = str(exc)
        # Provide user-friendly messages for known infrastructure issues
        if "missing_node_type" in error_msg or "not found" in error_msg.lower():
            error_msg = (
                "The photo pipeline requires ComfyUI custom nodes that are not installed. "
                "Please install the required nodes (SAM, MoGe-2, Hunyuan3D) in ComfyUI."
            )
        return JSONResponse(
            {
                "error": error_msg,
                "session_id": session_id,
                "source_type": "photo",
                "stage": "pipeline",
                "reason_code": "infrastructure_error",
            },
            status_code=503,
        )

    # Store session metadata with source_type="photo" for Requirement 14.5
    session_meta = {
        "session_id": session_id,
        "source_type": "photo",
        "mode": mode.value,
        "source_image_path": str(source_image),
        "quality_classification": manifest.quality_classification,
        "total_duration_s": manifest.total_duration_s,
        "object_count": len(manifest.objects),
        "compilation_success": compilation_result.success,
        "compilation_reason_code": compilation_result.reason_code,
    }
    (session_dir / "photo_session_meta.json").write_text(
        json.dumps(session_meta, indent=2), encoding="utf-8"
    )

    # The WorldContract is already persisted by the orchestrator at
    # session_dir / "world_contract.json". The compilation bridge produces
    # artifacts in session_dir / "photo_compile/".
    world_contract_path = manifest.world_contract_path

    return {
        "session_id": session_id,
        "source_type": "photo",
        "mode": mode.value,
        "state": "completed" if compilation_result.success else "compilation_failed",
        "quality_classification": manifest.quality_classification,
        "total_duration_s": manifest.total_duration_s,
        "object_count": len(manifest.objects),
        "world_contract_path": str(world_contract_path) if world_contract_path else None,
        "compilation_success": compilation_result.success,
        "compilation_reason_code": compilation_result.reason_code,
        "runtime_candidate_path": str(compilation_result.runtime_candidate_path) if compilation_result.runtime_candidate_path else None,
        "launch_pid": getattr(compilation_result.launch_result, "pid", None) if compilation_result.launch_result else None,
    }


@app.post("/api/session/photo/browser")
async def create_photo_session_browser(request: Request):
    """Photo pipeline for browser-embedded game (no external launch)."""
    from src.photo_pipeline.orchestrator import (
        PhotoPipelineOrchestrator,
        PipelineError,
        PipelineTimeoutError,
        PipelineValidationError,
    )
    from src.photo_pipeline.models import PhotoPipelineConfig

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    source_image_str = body.get("source_image", "")
    if not source_image_str:
        return JSONResponse({"error": "source_image required"}, status_code=400)

    source_image = Path(source_image_str)
    if not source_image.exists():
        return JSONResponse({"error": f"Not found: {source_image}"}, status_code=400)

    session_id = str(uuid.uuid4())[:8]
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    config = PhotoPipelineConfig()
    orchestrator = PhotoPipelineOrchestrator(
        config=config,
        session_dir=session_dir,
        session_id=session_id,
    )

    try:
        # Use run() NOT run_full() — skip UPBGE compilation
        manifest = await orchestrator.run(source_image)
    except PipelineValidationError as exc:
        return JSONResponse({"error": str(exc), "session_id": session_id}, status_code=400)
    except PipelineTimeoutError as exc:
        return JSONResponse({"error": str(exc), "session_id": session_id}, status_code=504)
    except (PipelineError, Exception) as exc:
        import traceback; traceback.print_exc()
        return JSONResponse({"error": str(exc), "session_id": session_id}, status_code=500)

    # Build browser-friendly scene descriptor from WorldContract
    wc_path = manifest.world_contract_path
    scene_data = _build_browser_scene(wc_path, session_dir, manifest)

    # Save scene data for the frontend to fetch
    scene_json_path = session_dir / "browser_scene.json"
    scene_json_path.write_text(json.dumps(scene_data, indent=2), encoding="utf-8")

    return {
        "session_id": session_id,
        "source_type": "photo",
        "quality_classification": manifest.quality_classification,
        "total_duration_s": manifest.total_duration_s,
        "object_count": len(manifest.objects),
        "scene_url": f"/api/session/{session_id}/browser_scene",
    }


@app.get("/api/session/{session_id}/browser_scene")
async def get_browser_scene(session_id: str):
    """Return the Three.js scene descriptor for in-browser rendering."""
    scene_path = OUTPUT_DIR / session_id / "browser_scene.json"
    if not scene_path.exists():
        return JSONResponse({"error": "No browser scene for this session"}, status_code=404)
    return JSONResponse(json.loads(scene_path.read_text(encoding="utf-8")))


def _build_browser_scene(wc_path, session_dir, manifest):
    """Convert WorldContract into a Three.js-friendly scene descriptor."""
    wc = json.loads(wc_path.read_text(encoding="utf-8"))

    room = wc.get("room", {})
    dims = room.get("dimensions", {})

    # Build material lookup
    mat_lookup = {}
    for mat in wc.get("materials", []):
        mat_lookup[mat["id"]] = mat

    # Build scene objects
    objects = []
    for inst in wc.get("instances", []):
        mat = mat_lookup.get(inst.get("material_id"), {})
        transform = inst.get("transform", {})
        pos = transform.get("position_m", {})
        rot = transform.get("rotation_deg", {})
        dim = inst.get("dimensions", {})

        objects.append({
            "id": inst["id"],
            "name": inst.get("name", ""),
            "shape": inst.get("primitive_shape", "box"),
            "position": [pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
            "rotation": [rot.get("x", 0), rot.get("y", 0), rot.get("z", 0)],
            "dimensions": [dim.get("width_m", 1), dim.get("height_m", 1), dim.get("depth_m", 1)],
            "color": mat.get("base_color", "#808080"),
            "metallic": mat.get("metallic", 0),
            "roughness": mat.get("roughness", 0.8),
        })

    # Lights
    lights = []
    for light in wc.get("lights", []):
        pos = light.get("position_m", {})
        dir_v = light.get("direction", {})
        lights.append({
            "id": light["id"],
            "type": light.get("light_type", "point"),
            "position": [pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
            "direction": [dir_v.get("x", 0), dir_v.get("y", -1), dir_v.get("z", 0)],
            "color": light.get("color", "#FFFFFF"),
            "intensity": light.get("intensity", 50),
        })

    # Room materials
    floor_mat = mat_lookup.get(room.get("floor_material_id"), {})
    wall_mat = mat_lookup.get(room.get("wall_material_id"), {})
    ceiling_mat = mat_lookup.get(room.get("ceiling_material_id"), {})

    return {
        "version": "browser-scene/v1",
        "room": {
            "width": dims.get("width_m", 5),
            "height": dims.get("height_m", 2.7),
            "depth": dims.get("depth_m", 4),
            "floor_color": floor_mat.get("base_color", "#8b7355"),
            "wall_color": wall_mat.get("base_color", "#d0c8b8"),
            "ceiling_color": ceiling_mat.get("base_color", "#e8e0d8"),
        },
        "objects": objects,
        "lights": lights,
        "camera": {
            "position": [0, 1.6, 3],
            "fov": 60,
        },
        "quality": manifest.quality_classification,
    }


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


@app.get("/api/session/{session_id}/workflow")
async def session_workflow(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    manifest_path = builder.output_dir / "workflow_manifest.json"
    if not manifest_path.exists():
        return JSONResponse({"error": "Workflow manifest not found"}, status_code=404)
    return JSONResponse(json.loads(manifest_path.read_text(encoding="utf-8")))


@app.get("/api/session/{session_id}/artifact/{artifact_id}")
async def download_recorded_artifact(session_id: str, artifact_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    record = next(
        (item for item in _recorded_v11_artifacts(builder) if item["id"] == artifact_id), None
    )
    if not record:
        return JSONResponse(
            {"error": "Artifact is not recorded for this V11 session"}, status_code=404
        )
    if record["integrity"] != "verified":
        return JSONResponse({"error": "Recorded artifact integrity check failed"}, status_code=409)
    paths = []
    compiler = builder.session.compiler_result or {}
    paths.extend(item.get("path") for item in compiler.get("artifacts", []) if isinstance(item, dict))
    paths.extend(builder.session.compiler_manifests)
    for result in builder.session.export_results.values():
        if isinstance(result, dict):
            for collection in ("artifacts", "manifests"):
                paths.extend(
                    item.get("path") for item in result.get(collection, []) if isinstance(item, dict)
                )
    path = next((
        candidate for candidate in (_session_artifact_path(builder, item) for item in paths)
        if candidate and hashlib.sha256(str(candidate).encode("utf-8")).hexdigest()[:20]
        == artifact_id
    ), None)
    if path is None:
        return JSONResponse({"error": "Artifact is no longer available"}, status_code=404)
    return FileResponse(
        path, media_type=record["media_type"], filename=record["filename"],
        headers={"Cache-Control": "no-store", "X-Artifact-SHA256": record["sha256"]},
    )


@app.post("/api/session/{session_id}/describe")
async def describe(session_id: str, request: Request):
    builder = _restore_builder(session_id)
    if not builder:
        builder = WorldBuilder(
            session_id=session_id, interface_version=_request_version(request)
        )
        sessions[session_id] = builder
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
    except asyncio.CancelledError:
        builder.session.state = PipelineState.ERROR
        builder.session.error = "Planning request cancelled"
        builder.save_session()
        raise
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/floor_plan")
async def get_floor_plan(session_id: str):
    builder = _restore_builder(session_id)
    path = Path(builder.session.floor_plan_path) if builder and builder.session.floor_plan_path else None
    if not path or not path.exists():
        return JSONResponse({"error": "No floor plan for this session"}, status_code=404)
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/api/session/{session_id}/blockout")
async def get_blockout(session_id: str):
    unified = unified_artifact_response(OUTPUT_DIR, session_id, "blockout")
    if unified is not None:
        return unified
    builder = _restore_builder(session_id)
    path = Path(builder.session.blockout_path) if builder and builder.session.blockout_path else None
    if not path or not path.exists():
        return JSONResponse({"error": "No blockout for this session"}, status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/{session_id}/revise_plan")
async def revise_plan(session_id: str, request: Request):
    builder = _restore_builder(session_id)
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
    builder = _restore_builder(session_id)
    if not builder or not builder.session.floor_plan:
        return JSONResponse({"error": "Session or plan not found"}, status_code=404)
    # V10: recompute authoritative geometry and block approval on every request.
    if builder.session.interface_version >= 11:
        composition = builder.session.composition_evidence or {}
        if composition.get("status") != "accepted" or builder.session.camera_contract is None:
            builder.save_session()
            return JSONResponse(
                {
                    "error": "Plan camera cannot fully frame every required object at the fixed corner and field of view",
                    "composition_evidence": composition,
                },
                status_code=409,
            )
    if builder.session.interface_version >= 10:
        validation = validate_floor_plan(builder.session.floor_plan, tolerance="strict")
        builder.session.plan_validation = validation
        if not validation.valid:
            builder.save_session()
            return JSONResponse(
                {
                    "error": "Plan has unresolved geometry issues that must be fixed before approval",
                    "validation_report": validation.model_dump(),
                },
                status_code=409,
            )
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
            "provider": builder.session.canon_provider or get_image_provider(session_id),
            "camera_contract": (
                builder.session.camera_contract.model_dump()
                if builder.session.camera_contract else None
            ),
            "camera_alignment": builder.session.canon_alignment,
            "progress": builder.session.progress_messages,
            **_v11_runtime_payload(builder),
        }
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/canon_image")
async def get_canon_image(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.canon_image_path:
        return JSONResponse({"error": "No canon image for this session"}, status_code=404)
    path = Path(builder.session.canon_image_path)
    if not path.exists():
        return JSONResponse({"error": "Canon image file is missing"}, status_code=404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/session/{session_id}/approve")
async def approve_image(session_id: str, request: Request):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    alignment = builder.session.canon_alignment or {}
    if builder.session.interface_version >= 10:
        # V10 three-state policy: aligned passes, misaligned blocks, inconclusive needs review
        status = alignment.get("status", "")
        if status == "misaligned":
            return JSONResponse(
                {
                    "error": "Canon is confidently misaligned with the approved blockout. Revise the Plan/Camera instead of retrying.",
                    "camera_alignment": alignment,
                },
                status_code=409,
            )
        if status == "inconclusive" and not _alignment_review_matches(builder):
            retry_policy = alignment.get("retry_policy", {})
            return JSONResponse(
                {
                    "error": "Camera alignment is inconclusive. Either retry or explicitly accept the current Canon.",
                    "camera_alignment": alignment,
                    "manual_review_allowed": retry_policy.get("manual_review_allowed", False),
                },
                status_code=409,
            )
    elif (
        builder.session.interface_version >= 9
        and not alignment.get("passed", False)
    ):
        return JSONResponse(
            {
                "error": (
                    "Canon camera alignment gate failed; regenerate the Canon before "
                    "building the World"
                ),
                "camera_alignment": alignment,
            },
            status_code=409,
        )
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
            "camera_contract": (
                builder.session.camera_contract.model_dump()
                if builder.session.camera_contract else None
            ),
            "mesh_urls": {obj_id: f"/api/session/{session_id}/mesh/{obj_id}" for obj_id in mesh_paths},
            **_v11_runtime_payload(builder),
        }
    except SemanticBatchRejectedError as exc:
        return _error(builder, exc, status_code=422)
    except Exception as exc:
        return _error(builder, exc)


@app.post("/api/session/{session_id}/reject")
async def reject_image(session_id: str, request: Request):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.scene_concept:
        return JSONResponse({"error": "Session or concept not found"}, status_code=404)
    try:
        feedback = str((await request.json()).get("feedback", "")).strip()
        if not feedback:
            raise ValueError("Revision feedback is required")
        attempt = len(list((OUTPUT_DIR / session_id).glob("canon_v*.png"))) + 1
        if builder.session.interface_version >= 10:
            # V10: pass feedback as ephemeral generation context, never mutate the concept
            alignment = builder.session.canon_alignment or {}
            retry_mode = "alignment_retry" if not alignment.get("passed") else "visual_revision"
            await builder.step_generate_image(
                attempt=attempt,
                generation_feedback=feedback,
                retry_mode=retry_mode,
            )
        else:
            # V8/V9: legacy concept mutation retained for behavioral stability
            concept = builder.session.scene_concept
            revised_prompt = f"{concept.image_prompt}. Revision requirement: {feedback}. Preserve all other approved scene details."
            builder.session.scene_concept = concept.model_copy(update={"image_prompt": revised_prompt})
            await builder.step_generate_image(attempt=attempt)
        builder.session.state = PipelineState.AWAITING_APPROVAL
        builder.save_session()
        return {
            "state": builder.session.state.value,
            "canon_image": f"/api/session/{session_id}/canon_image?v={attempt}",
            "provider": builder.session.canon_provider or get_image_provider(session_id),
            "attempt": attempt,
            "camera_contract": (
                builder.session.camera_contract.model_dump()
                if builder.session.camera_contract else None
            ),
            "camera_alignment": builder.session.canon_alignment,
            "progress": builder.session.progress_messages,
        }
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)



@app.post("/api/session/{session_id}/accept_alignment")
async def accept_alignment(session_id: str, request: Request):
    """V10: explicitly accept an inconclusive Canon alignment after review."""
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    if builder.session.interface_version < 10:
        return JSONResponse({"error": "Manual alignment review is only available in V10+"}, status_code=400)
    alignment = builder.session.canon_alignment or {}
    if alignment.get("status") != "inconclusive":
        return JSONResponse({"error": "Only inconclusive alignments can be manually accepted"}, status_code=400)
    binding = alignment.get("binding")
    if not isinstance(binding, dict):
        return JSONResponse({"error": "Alignment report has no binding record"}, status_code=400)
    review = {
        "decision": "accepted",
        "binding": binding,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "user",
    }
    builder.session.canon_alignment_reviews.append(review)
    builder.save_session()
    return {
        "accepted": True,
        "binding": binding,
        "camera_alignment": alignment,
        "review": review,
    }


@app.post("/api/session/{session_id}/qa")
async def adjudicate_qa(session_id: str, request: Request):
    """Append a V11 human verdict; compiler failures remain non-overridable."""
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    if builder.session.interface_version < 11:
        return JSONResponse(
            {"error": "Compiler QA adjudication is only available in V11"},
            status_code=400,
        )
    try:
        payload = await request.json()
        reviewer_id = str(payload.get("reviewer_id", "user")).strip()
        verdict = str(payload.get("verdict", "")).strip()
        rationale = str(payload.get("rationale", "")).strip()
        if not reviewer_id or verdict not in {"approved", "rejected"} or not rationale:
            raise ValueError(
                "reviewer_id, approved/rejected verdict, and rationale are required"
            )
        evidence = builder.adjudicate_v11_qa(reviewer_id, verdict, rationale)
        return {
            "state": builder.session.state.value,
            "evidence": evidence.model_dump(mode="json"),
            **_v11_runtime_payload(builder),
        }
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)


@app.post("/api/session/{session_id}/revise_world")
async def revise_world(session_id: str, request: Request):
    """Capture feedback as session memory, compare render to canon, and rebuild."""
    builder = _restore_builder(session_id)
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
            "camera_contract": (
                builder.session.camera_contract.model_dump()
                if builder.session.camera_contract else None
            ),
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
    """Serve a mesh GLB for a V14 or unified V16 session object.

    Searches multiple naming conventions used by different generators:
    - {obj_id}_hunyuan3d.glb (Hunyuan3D output)
    - {obj_id}_trellis2.glb (Trellis2 output)
    - obj_{obj_id}_placeholder.glb (placeholder fallback)
    - meshes/{obj_id}.glb (legacy path)
    """
    unified = unified_artifact_response(
        OUTPUT_DIR, session_id, "mesh", object_id=obj_id
    )
    if unified is not None:
        return unified
    session_dir = OUTPUT_DIR / session_id
    candidates = [
        session_dir / "objects" / f"{obj_id}_hunyuan3d.glb",
        session_dir / "objects" / f"{obj_id}_trellis2.glb",
        session_dir / "objects" / f"obj_{obj_id}_placeholder.glb",
        session_dir / "meshes" / f"{obj_id}.glb",
        session_dir / "meshes" / f"{obj_id}_placeholder.glb",
        session_dir / "meshes" / f"{obj_id}_hunyuan3d.glb",
        session_dir / "meshes" / f"{obj_id}_trellis2.glb",
    ]
    for mesh_path in candidates:
        if mesh_path.exists():
            return FileResponse(mesh_path, media_type="model/gltf-binary")
    return JSONResponse({"error": "Mesh not found"}, status_code=404)


@app.get("/api/session/{session_id}/scene_data")
async def get_scene_data(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.scene_graph:
        return JSONResponse({"error": "No scene built yet"}, status_code=404)
    return builder.session.scene_graph.model_dump()


@app.get("/api/session/{session_id}/download")
async def download_project(session_id: str):
    builder = _restore_builder(session_id)
    if not builder or not builder.session.output_path:
        return JSONResponse({"error": "No project yet"}, status_code=404)
    zip_path = OUTPUT_DIR / session_id / "project"
    await asyncio.to_thread(shutil.make_archive, str(zip_path), "zip", builder.session.output_path)
    return FileResponse(f"{zip_path}.zip", media_type="application/zip", filename=f"living_room_{session_id}.zip")


@app.get("/api/session/{session_id}/status")
async def get_status(session_id: str):
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return {"session_id": session_id, "state": builder.session.state.value, "progress": builder.session.progress_messages, "error": builder.session.error, "provider": builder.session.canon_provider or get_image_provider(session_id), "has_image": builder.session.canon_image_path is not None, "has_project": builder.session.output_path is not None, "interface_version": builder.session.interface_version, "workflow_profile_id": builder.session.workflow_profile_id, "workflow_url": f"/api/session/{session_id}/workflow", **_v11_runtime_payload(builder)}

# --- MVP Mode Endpoints (Requirements 9.1, 9.2, 9.3, 9.4, 9.5) ---

# Track background MVP pipeline tasks per session
_mvp_tasks: dict[str, asyncio.Task] = {}


def _parse_structured_error(error: str | None) -> dict:
    """Parse session.error into structured failure info for web display.

    If the error is JSON-parseable with stage/reason_code/message, use those.
    Otherwise treat as a plain string message with unknown stage/reason.
    Implements Requirements 9.4, 9.5.
    """
    if not error:
        return {"stage": "unknown", "reason_code": "unknown", "message": "Unknown error"}
    try:
        parsed = json.loads(error)
        if isinstance(parsed, dict) and "stage" in parsed:
            return {
                "stage": parsed.get("stage", "unknown"),
                "reason_code": parsed.get("reason_code", "unknown"),
                "message": parsed.get("message", error),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    # Plain string error — extract reason_code from prefix if present (e.g. "parity_failed: ...")
    if ":" in error:
        parts = error.split(":", 1)
        return {
            "stage": "unknown",
            "reason_code": parts[0].strip(),
            "message": parts[1].strip() if len(parts) > 1 else error,
        }
    return {"stage": "unknown", "reason_code": "unknown", "message": error}


@app.post("/api/session/{session_id}/describe_mvp")
async def describe_mvp(session_id: str, request: Request):
    """MVP-mode describe endpoint — kicks off the full pipeline as a background task.

    Accepts a mode parameter (default: "mvp"). When mode="mvp", invokes
    builder.run_mvp(description) as an async background task and returns
    immediately so the client can stream progress via the SSE /events endpoint.

    Uses SessionManager for proper session isolation (Req 12.2, 12.5).
    Implements Requirements 9.1, 9.2, 9.3.
    """
    builder = _restore_builder(session_id)
    if not builder:
        builder = WorldBuilder(
            session_id=session_id, interface_version=_request_version(request)
        )
        # Ensure MVP session has proper isolation subdirectories (Req 12.2)
        (builder.output_dir / "input").mkdir(parents=True, exist_ok=True)
        (builder.output_dir / "output").mkdir(parents=True, exist_ok=True)
        (builder.output_dir / "tmp").mkdir(parents=True, exist_ok=True)
        sessions[session_id] = builder

    try:
        body = await request.json()
        description = str(body.get("description", "")).strip()
        mode = str(body.get("mode", "mvp")).strip().lower()

        if not description:
            raise ValueError("Describe a room before generating")

        if mode != "mvp":
            # Fall through to existing full-mode behavior via the standard describe endpoint
            builder.session.error = None
            builder.session.progress_messages.clear()
            await builder.step_interpret(description)
            plan = await builder.step_build_floor_plan()
            builder.session.state = PipelineState.AWAITING_PLAN_APPROVAL
            builder.save_session()
            return _plan_payload(builder, plan)

        # MVP mode: start pipeline in background, return immediately
        builder.session.error = None
        builder.session.progress_messages.clear()
        builder.session.mode = SessionMode.MVP
        builder.session.state = PipelineState.GENERATING_CONCEPT
        builder.save_session()

        async def _run_mvp_pipeline():
            try:
                result = await builder.run_mvp(
                    description, session_manager=_session_manager
                )
                # Store result summary in session for later retrieval
                builder.session.error = None
                if not result.success:
                    builder.session.state = PipelineState.ERROR
                    # Store structured failure info as JSON for web layer parsing
                    builder.session.error = json.dumps({
                        "stage": result.failure_stage or "unknown",
                        "reason_code": result.failure_reason_code or "unknown",
                        "message": result.failure_diagnostic or result.failure_reason_code or "Pipeline failed",
                    })
                else:
                    # Store launch fallback info if launch failed but pipeline succeeded
                    if result.launch_result and not result.launch_result.success:
                        builder.session.launch_fallback = {
                            "launch_failed": True,
                            "reason_code": result.launch_result.reason_code,
                            "diagnostics": result.launch_result.diagnostics,
                            "fallback_instructions": result.launch_result.fallback_instructions,
                        }
                builder.save_session()
            except Exception as exc:
                builder.session.state = PipelineState.ERROR
                builder.session.error = json.dumps({
                    "stage": "unknown",
                    "reason_code": "unhandled_exception",
                    "message": str(exc),
                })
                builder.save_session()

        task = asyncio.create_task(_run_mvp_pipeline())
        _mvp_tasks[session_id] = task

        return {
            "session_id": session_id,
            "mode": "mvp",
            "state": builder.session.state.value,
            "events_url": f"/api/session/{session_id}/events",
            "message": "MVP pipeline started. Connect to events_url for SSE progress.",
        }
    except ValueError as exc:
        return _error(builder, exc, 400)
    except Exception as exc:
        return _error(builder, exc)


@app.get("/api/session/{session_id}/events")
async def session_events(session_id: str, request: Request):
    """SSE endpoint delivering real-time stage progress for MVP pipeline.

    Streams stage transitions (interpreting, planning, building_scene, compiling,
    validating, launching, game_running) within 2 seconds of occurrence (Req 9.1).

    Each event is a JSON object with 'stage' and 'elapsed' fields.
    Terminal event has stage='done' with final state and result summary.
    """
    try:
        after_sequence = int(request.headers.get("last-event-id", "0"))
    except ValueError:
        after_sequence = 0
    unified = unified_sse_response(OUTPUT_DIR, session_id, after_sequence)
    if unified is not None:
        return unified
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    async def event_generator():
        last_seen = 0
        while True:
            messages = builder.session.progress_messages[last_seen:]
            for msg in messages:
                if msg.startswith("sse:"):
                    parts = msg.split(":")
                    stage = parts[1] if len(parts) > 1 else ""
                    elapsed = parts[2] if len(parts) > 2 else ""
                    yield f"data: {json.dumps({'stage': stage, 'elapsed': elapsed})}\n\n"
                last_seen += 1

            # Check terminal conditions
            if builder.session.state in (PipelineState.READY, PipelineState.ERROR):
                # Build terminal payload
                terminal: dict = {
                    "stage": "done",
                    "state": builder.session.state.value,
                }
                if builder.session.state == PipelineState.READY:
                    terminal["game_running"] = builder.session.game_pid is not None
                    terminal["download_url"] = f"/api/session/{session_id}/download_blend"
                    if builder.session.quality_label:
                        terminal["quality_label"] = builder.session.quality_label
                    # Include launch fallback info if auto-launch failed (Req 1.8)
                    if builder.session.launch_fallback:
                        terminal["launch_failed"] = True
                        terminal["fallback_instructions"] = (
                            builder.session.launch_fallback.get("fallback_instructions")
                        )
                elif builder.session.state == PipelineState.ERROR:
                    # Structured failure display (Req 9.4, 9.5)
                    failure_info = _parse_structured_error(builder.session.error)
                    terminal["error"] = failure_info["message"]
                    terminal["failure_stage"] = failure_info["stage"]
                    terminal["reason_code"] = failure_info["reason_code"]
                yield f"data: {json.dumps(terminal)}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/session/{session_id}/download_blend")
async def download_blend(session_id: str):
    """Serve the compiled .blend artifact for download (Req 9.3).

    Returns the Playable_Artifact .blend file produced by the MVP pipeline.
    """
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if not builder.session.output_path:
        return JSONResponse(
            {"error": "No compiled artifact available for this session"},
            status_code=404,
        )

    blend_path = Path(builder.session.output_path)
    if not blend_path.exists() or not blend_path.is_file():
        return JSONResponse(
            {"error": "Compiled .blend file no longer exists on disk"},
            status_code=404,
        )

    return FileResponse(
        blend_path,
        media_type="application/x-blender",
        filename=f"game_{session_id}.blend",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/session/{session_id}/mvp_result")
async def mvp_result(session_id: str):
    """Return the MVP pipeline result summary for a completed session.

    Provides the full result payload including success status, quality label,
    game running state, artifact download URL, and any failure info.
    """
    builder = _restore_builder(session_id)
    if not builder:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    if builder.session.state not in (PipelineState.READY, PipelineState.ERROR):
        return JSONResponse(
            {
                "session_id": session_id,
                "state": builder.session.state.value,
                "complete": False,
                "message": "Pipeline still in progress. Use /events for real-time updates.",
            },
            status_code=202,
        )

    result: dict = {
        "session_id": session_id,
        "state": builder.session.state.value,
        "complete": True,
        "success": builder.session.state == PipelineState.READY,
        "mode": builder.session.mode.value if builder.session.mode else "mvp",
        "quality_label": builder.session.quality_label,
        "game_running": builder.session.game_pid is not None,
        "game_pid": builder.session.game_pid,
    }

    if builder.session.output_path:
        result["download_url"] = f"/api/session/{session_id}/download_blend"
        result["artifact_path"] = builder.session.output_path

    if builder.session.state == PipelineState.ERROR:
        # Structured failure info (Req 9.4, 9.5) — not generic error
        failure_info = _parse_structured_error(builder.session.error)
        result["error"] = failure_info["message"]
        result["failure_stage"] = failure_info["stage"]
        result["reason_code"] = failure_info["reason_code"]

    # Launch fallback: pipeline succeeded but auto-launch failed (Req 1.4, 1.8)
    if builder.session.launch_fallback:
        result["launch_failed"] = True
        result["fallback_instructions"] = (
            builder.session.launch_fallback.get("fallback_instructions")
        )
        # Ensure download_url is always present when launch fails
        if "download_url" not in result and builder.session.output_path:
            result["download_url"] = f"/api/session/{session_id}/download_blend"

    return result


# --- V14 Routes (Requirements 8.4, 8.5, 8.6, 8.7, 12.1, 12.3, 12.4, 12.5) ---

# Track active V14 material WebSocket connections per session
_v14_material_connections: dict[str, list[WebSocket]] = {}


async def _v14_build_room(
    session_dir: Path,
    session_id: str,
    manifest,
    event_cb,
) -> None:
    """Wire V14 WorldContract into the existing room-building path.

    After the V14 orchestrator produces its WorldContract, this function:
      1. Builds browser_scene.json (parametric room with positioned objects)
         for proper Three.js rendering with walls/floor/ceiling + object placement.
      2. Runs the existing UPBGE compilation bridge (same chain as V11-V13)
         for native runtime and GLB export.
      3. Emits a 'world_built' SSE event so the V14 viewer switches from
         raw-GLB-at-origin mode to proper room rendering.

    This is the integration layer that connects:
      V14 pipeline output → existing WorldBuilder compilation infrastructure
    """
    from src.photo_pipeline.compilation_bridge import (
        CompilationBridgeResult,
        run_compilation_chain,
    )
    from src.world_contract import WorldContract

    # Locate the V14 WorldContract
    wc_path = session_dir / "world_contract_v14.json"
    if not wc_path.exists():
        # Try manifest's path if available
        if manifest and manifest.world_contract_path:
            wc_path = manifest.world_contract_path
    if not wc_path.exists():
        # Cannot proceed without a WorldContract
        await event_cb({
            "event": "room_build",
            "stage": "room_compilation",
            "status": "failed",
            "session_id": session_id,
            "reason": "world_contract_not_found",
        })
        return

    # --- Step 1: Build browser_scene.json (parametric room for Three.js) ---
    try:
        wc_data = json.loads(wc_path.read_text(encoding="utf-8"))
        quality = getattr(manifest, "quality_classification", "full") if manifest else "full"
        scene_data = _build_v14_browser_scene(wc_data, session_id, quality)
        scene_json_path = session_dir / "browser_scene.json"
        scene_json_path.write_text(json.dumps(scene_data, indent=2), encoding="utf-8")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        await event_cb({
            "event": "room_build",
            "stage": "browser_scene",
            "status": "failed",
            "session_id": session_id,
            "reason": str(exc),
        })
        return

    # --- Step 2: Emit world_built SSE event ---
    # This tells the V14 viewer to switch to proper room rendering
    events_path = session_dir / "v14_events.jsonl"
    world_built_event = {
        "type": "world_built",
        "browser_scene_url": f"/api/session/{session_id}/browser_scene",
        "room": scene_data.get("room", {}),
        "object_count": len(scene_data.get("objects", [])),
    }
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(world_built_event, default=str) + "\n")

    # --- Step 3: Run UPBGE compilation bridge (same path as V11-V13) ---
    try:
        contract = WorldContract.model_validate_json(wc_path.read_text(encoding="utf-8"))

        # Run compilation in executor (it's synchronous)
        loop = asyncio.get_running_loop()
        compilation_result: CompilationBridgeResult = await loop.run_in_executor(
            None,
            lambda: run_compilation_chain(
                contract,
                session_dir,
                fullscreen=False,  # Browser session — no auto-launch
                launch_timeout_s=10.0,
                smoke_timeout_s=15.0,
            ),
        )

        # Emit compilation result SSE event
        compile_event = {
            "type": "compilation_complete",
            "success": compilation_result.success,
            "reason_code": compilation_result.reason_code,
            "runtime_candidate": str(compilation_result.runtime_candidate_path)
            if compilation_result.runtime_candidate_path
            else None,
        }
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(compile_event, default=str) + "\n")

        # Update session metadata with compilation results
        meta_path = session_dir / "session_meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta.update({
                "compilation_success": compilation_result.success,
                "compilation_reason_code": compilation_result.reason_code,
            })
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    except Exception as exc:
        import traceback
        traceback.print_exc()
        # Compilation failure is non-fatal — browser scene still works
        fail_event = {
            "type": "compilation_complete",
            "success": False,
            "reason_code": "compilation_exception",
            "error": str(exc),
        }
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(fail_event, default=str) + "\n")


def _build_v14_browser_scene(wc_data: dict, session_id: str, quality: str) -> dict:
    """Build a Three.js browser scene from a V14 WorldContract dict.

    Produces the same browser-scene/v1 format as _build_browser_scene but:
    - Includes mesh_url for each object (V14 has real GLB meshes)
    - Uses the WorldContract's camera if available
    - Preserves object positions from the WorldContract transform data
    """
    room = wc_data.get("room", {})
    dims = room.get("dimensions", {})

    # Build material lookup
    mat_lookup = {}
    for mat in wc_data.get("materials", []):
        mat_lookup[mat["id"]] = mat

    # Build scene objects with mesh URLs and proper positioning
    objects = []
    for inst in wc_data.get("instances", []):
        mat = mat_lookup.get(inst.get("material_id"), {})
        transform = inst.get("transform", {})
        pos = transform.get("position_m", {})
        rot = transform.get("rotation_deg", {})
        dim = inst.get("dimensions", {})
        scale = transform.get("scale", {})

        obj_entry = {
            "id": inst["id"],
            "name": inst.get("name", ""),
            "shape": inst.get("primitive_shape", "box"),
            "position": [pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
            "rotation": [rot.get("x", 0), rot.get("y", 0), rot.get("z", 0)],
            "scale": [scale.get("x", 1), scale.get("y", 1), scale.get("z", 1)],
            "dimensions": [
                dim.get("width_m", 1),
                dim.get("height_m", 1),
                dim.get("depth_m", 1),
            ],
            "color": mat.get("base_color", "#808080"),
            "metallic": mat.get("metallic", 0),
            "roughness": mat.get("roughness", 0.8),
            # V14 has real GLB meshes — include mesh URL
            "mesh_url": f"/api/session/{session_id}/mesh/{inst['id']}",
        }
        objects.append(obj_entry)

    # Lights
    lights = []
    for light in wc_data.get("lights", []):
        pos = light.get("position_m", {})
        dir_v = light.get("direction", {})
        lights.append({
            "id": light["id"],
            "type": light.get("light_type", "point"),
            "position": [pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
            "direction": [dir_v.get("x", 0), dir_v.get("y", -1), dir_v.get("z", 0)],
            "color": light.get("color", "#FFFFFF"),
            "intensity": light.get("intensity", 50),
        })

    # Room materials for walls/floor/ceiling
    floor_mat = mat_lookup.get(room.get("floor_material_id"), {})
    wall_mat = mat_lookup.get(room.get("wall_material_id"), {})
    ceiling_mat = mat_lookup.get(room.get("ceiling_material_id"), {})

    # Camera from WorldContract (or sensible default)
    camera_data = wc_data.get("camera", {})
    cam_pos = camera_data.get("position_m", {})
    camera = {
        "position": [
            cam_pos.get("x", 0),
            cam_pos.get("y", 1.6),
            cam_pos.get("z", 3),
        ],
        "fov": camera_data.get("fov_deg", 60),
    }

    return {
        "version": "browser-scene/v1",
        "source": "v14-world-contract",
        "room": {
            "width": dims.get("width_m", 5),
            "height": dims.get("height_m", 2.7),
            "depth": dims.get("depth_m", 4),
            "floor_color": floor_mat.get("base_color", "#8b7355"),
            "wall_color": wall_mat.get("base_color", "#d0c8b8"),
            "ceiling_color": ceiling_mat.get("base_color", "#e8e0d8"),
        },
        "objects": objects,
        "lights": lights,
        "camera": camera,
        "quality": quality,
    }

@app.post("/api/session/v14/upload-photo")
async def v14_upload_photo(request: Request):
    """Upload a photo from the browser for V14 pipeline processing.

    Accepts a multipart form with a 'photo' file field.
    Persists the file into a temporary upload directory and returns the
    server-side path for use with the /api/session/v14/photo endpoint.
    """
    from starlette.datastructures import UploadFile as StarletteUpload

    form = await request.form()
    photo = form.get("photo")
    if photo is None or not hasattr(photo, "read"):
        return JSONResponse(
            {"error": "Missing 'photo' file in multipart form"}, status_code=400
        )

    # Validate file type
    filename = getattr(photo, "filename", "upload.jpg") or "upload.jpg"
    ext = Path(filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        return JSONResponse(
            {"error": f"Unsupported file type: {ext}. Use JPEG or PNG."},
            status_code=400,
        )

    # Persist into uploads directory
    upload_dir = OUTPUT_DIR / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:12]}_{Path(filename).stem}{ext}"
    dest = upload_dir / safe_name

    content = await photo.read()
    dest.write_bytes(content)

    return {"server_path": str(dest), "filename": filename, "size_bytes": len(content)}


@app.post("/api/session/v14/photo")
async def create_v14_photo_session(request: Request):
    """V14 photo pipeline endpoint — accepts photo upload and starts V14 pipeline.

    Creates a session with interface_version=14 and initiates the real 3D mesh
    generation pipeline (Hunyuan3D 2.1 with Trellis2 fallback).

    Accepts a JSON body with:
      - source_image: str (path to an RGB image on local disk)
      - mode: "mvp" | "full" (optional, default "mvp")

    Returns immediately with session_id and events_url for SSE progress.

    Requirements: 8.4, 8.6, 12.1, 12.4, 12.5
    """
    from src.photo_pipeline.orchestrator_v14 import (
        V14Orchestrator,
        V14PipelineError,
        V14ValidationError,
    )
    from src.photo_pipeline.models_v14 import V14PipelineConfig

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Request body must be valid JSON with 'source_image' field"},
            status_code=400,
        )

    source_image_str = body.get("source_image", "")
    if not source_image_str:
        return JSONResponse(
            {"error": "source_image path is required"},
            status_code=400,
        )

    source_image = Path(source_image_str)
    if not source_image.exists():
        return JSONResponse(
            {"error": f"Source image not found: {source_image}"},
            status_code=400,
        )

    # Parse mode (mvp/full)
    raw_mode = str(body.get("mode", "mvp")).strip().lower()
    if raw_mode == "full":
        mode = SessionMode.FULL
    elif raw_mode == "mvp":
        mode = SessionMode.MVP
    else:
        return JSONResponse(
            {"error": f"Unsupported mode: {raw_mode!r}; expected 'mvp' or 'full'"},
            status_code=400,
        )

    # Create V14 session with interface_version=14 (Req 12.5)
    session_id = str(uuid.uuid4())[:8]
    session_dir = OUTPUT_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Store V14 session metadata (Req 12.5 — same FIFO queue and TTL cleanup)
    session_meta = {
        "session_id": session_id,
        "interface_version": 14,
        "source_type": "photo",
        "mode": mode.value,
        "source_image_path": str(source_image),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "state": "started",
    }
    (session_dir / "session_meta.json").write_text(
        json.dumps(session_meta, indent=2), encoding="utf-8"
    )

    # Configure and run V14 pipeline orchestrator (real Hunyuan3D + Trellis2)
    config = V14PipelineConfig()

    # SSE event callback: translate orchestrator events to V14 SSE schema and
    # append to session JSONL for the SSE endpoint to poll.
    async def _v14_event_cb(event: dict) -> None:
        """Translate V14Orchestrator events to V14 SSE schema.

        Orchestrator emits: {event, stage, status, session_id, elapsed_s, ...}
        SSE endpoint expects: {type: stage_change|object_complete|room_shell_ready|done|error, ...}
        """
        stage = event.get("stage", "")
        status = event.get("status", "")

        sse_event: dict | None = None

        if status == "started":
            sse_event = {
                "type": "stage_change",
                "stage": stage,
                "total_objects": event.get("total_objects"),
            }
        elif status == "completed" and stage == "pipeline":
            sse_event = {
                "type": "done",
                "object_count": event.get("object_count", 0),
                "quality_classification": event.get("quality_classification"),
            }
        elif status == "completed" and stage == "room_shell_reconstruction":
            sse_event = {"type": "room_shell_ready"}
        elif status == "object_completed":
            mask_id = event.get("mask_id", "")
            sse_event = {
                "type": "object_complete",
                "object_id": mask_id,
                "mesh_url": f"/api/session/{session_id}/mesh/{mask_id}",
                "position": [0, 0, 0],
                "rotation": [0, 0, 0],
                "scale": [1, 1, 1],
            }
        elif status == "completed":
            sse_event = {"type": "stage_change", "stage": stage}

        if sse_event is not None:
            events_path = session_dir / "v14_events.jsonl"
            line = json.dumps(sse_event, default=str) + "\n"
            with open(events_path, "a", encoding="utf-8") as f:
                f.write(line)

    orchestrator = V14Orchestrator(
        config=config,
        session_dir=session_dir,
        session_id=session_id,
        event_callback=_v14_event_cb,
    )

    # Start pipeline in background, return immediately for SSE streaming
    async def _run_v14_pipeline():
        try:
            manifest = await orchestrator.run(source_image)
            # Update session metadata with results
            session_meta.update({
                "state": "completed",
                "quality_classification": manifest.quality_classification,
                "total_duration_s": manifest.total_duration_s,
                "object_count": len(manifest.objects),
            })
            (session_dir / "session_meta.json").write_text(
                json.dumps(session_meta, indent=2), encoding="utf-8"
            )

            # --- V14 Room Building: Wire WorldContract → browser scene + UPBGE ---
            # This is the critical integration that produces a proper walkable 3D
            # room with parametric geometry, positioned objects, and textures —
            # matching what V11-V13 sessions produce via the same path.
            await _v14_build_room(session_dir, session_id, manifest, _v14_event_cb)

        except (V14ValidationError, V14PipelineError) as exc:
            session_meta.update({"state": "error", "error": str(exc)})
            (session_dir / "session_meta.json").write_text(
                json.dumps(session_meta, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            session_meta.update({"state": "error", "error": str(exc)})
            (session_dir / "session_meta.json").write_text(
                json.dumps(session_meta, indent=2), encoding="utf-8"
            )

    task = asyncio.create_task(_run_v14_pipeline())
    _mvp_tasks[session_id] = task

    return {
        "session_id": session_id,
        "interface_version": 14,
        "source_type": "photo",
        "mode": mode.value,
        "state": "started",
        "events_url": f"/api/session/{session_id}/v14/events",
        "mesh_url_template": f"/api/session/{session_id}/mesh/{{object_id}}",
        "room_shell_url": f"/api/session/{session_id}/room_shell",
        "materials_ws_url": f"/api/session/{session_id}/v14/materials",
    }


@app.get("/api/session/{session_id}/room_shell")
async def get_room_shell(session_id: str):
    """Serve the room shell GLB for a V14 session.

    Returns the reconstructed room environment mesh (walls, floor, ceiling)
    generated from depth-displaced grid with Room_Plate texture.

    Requirements: 8.5, 3.1, 3.2
    """
    room_shell_path = OUTPUT_DIR / session_id / "room_shell.glb"
    if not room_shell_path.exists():
        return JSONResponse(
            {"error": "Room shell mesh not found for this session"},
            status_code=404,
        )
    return FileResponse(
        room_shell_path,
        media_type="model/gltf-binary",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/session/{session_id}/v14/events")
async def v14_session_events(session_id: str):
    """V14-specific SSE endpoint delivering real-time pipeline progress.

    Streams stage transitions and per-object mesh completion events for the
    V14 real-3D-mesh pipeline. Each event is a JSON object with fields:
      - type: "stage_change" | "object_complete" | "room_shell_ready" | "done" | "error"
      - stage: current stage name
      - elapsed: elapsed time string
      - objects_complete / objects_total: progress counters (for object_complete events)
      - mesh_url: URL to download the completed object mesh (for object_complete events)
      - object_id: the completed object's identifier

    Terminal event has type='done' with final state and download URLs,
    or type='error' with failure information.

    Requirements: 8.4, 8.5, 9.4
    """
    session_dir = OUTPUT_DIR / session_id
    meta_path = session_dir / "session_meta.json"

    if not session_dir.exists():
        # Also check if it's a standard session
        builder = _restore_builder(session_id)
        if not builder:
            return JSONResponse({"error": "Session not found"}, status_code=404)

    async def v14_event_generator():
        """Generate SSE events by polling session progress files."""
        last_event_index = 0
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            # Check for V14 progress events file
            events_path = session_dir / "v14_events.jsonl"
            if events_path.exists():
                try:
                    lines = events_path.read_text(encoding="utf-8").strip().split("\n")
                    new_lines = lines[last_event_index:]
                    for line in new_lines:
                        if line.strip():
                            event_data = json.loads(line)
                            event_data["elapsed"] = f"{elapsed:.1f}s"
                            yield f"data: {json.dumps(event_data)}\n\n"
                    last_event_index = len(lines)
                except (OSError, json.JSONDecodeError):
                    pass

            # Check session meta for terminal state
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    state = meta.get("state", "")
                    if state == "completed":
                        terminal = {
                            "type": "done",
                            "state": "completed",
                            "elapsed": f"{elapsed:.1f}s",
                            "object_count": meta.get("object_count", 0),
                            "quality_classification": meta.get("quality_classification"),
                            "room_shell_url": f"/api/session/{session_id}/room_shell",
                        }
                        yield f"data: {json.dumps(terminal)}\n\n"
                        return
                    elif state == "error":
                        error_event = {
                            "type": "error",
                            "state": "error",
                            "elapsed": f"{elapsed:.1f}s",
                            "error": meta.get("error", "Unknown error"),
                        }
                        yield f"data: {json.dumps(error_event)}\n\n"
                        return
                except (OSError, json.JSONDecodeError):
                    pass

            # Timeout after 30 minutes of inactivity (generous for multi-object generation)
            if elapsed > 1800:
                timeout_event = {
                    "type": "error",
                    "state": "timeout",
                    "elapsed": f"{elapsed:.1f}s",
                    "error": "SSE stream timed out after 30 minutes",
                }
                yield f"data: {json.dumps(timeout_event)}\n\n"
                return

            await asyncio.sleep(1.0)

    return StreamingResponse(
        v14_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.websocket("/api/session/{session_id}/v14/materials")
async def v14_materials_ws(session_id: str, websocket: WebSocket):
    """WebSocket endpoint for Pass 2 PBR material hot-swap notifications.

    When Pass 2 PBR estimation completes for an object, the server sends a
    JSON message through this WebSocket so the V14_Interface can hot-swap
    the object's material without reloading the full scene.

    Message format (server → client):
    {
        "type": "material_update",
        "object_id": "...",
        "mesh_url": "/api/session/{session_id}/mesh/{object_id}",
        "pass": 2,
        "pbr_channels": ["baseColor", "metallicRoughness", "normal"]
    }

    Requirements: 8.7, 5.1, 5.2
    """
    await websocket.accept()

    # Register this connection for the session
    if session_id not in _v14_material_connections:
        _v14_material_connections[session_id] = []
    _v14_material_connections[session_id].append(websocket)

    try:
        # Keep connection alive, listen for client messages (heartbeat/close)
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client can send ping/pong or close
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send keepalive ping every 30s
                try:
                    await websocket.send_text(json.dumps({"type": "keepalive"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        # Unregister connection
        if session_id in _v14_material_connections:
            connections = _v14_material_connections[session_id]
            if websocket in connections:
                connections.remove(websocket)
            if not connections:
                del _v14_material_connections[session_id]


async def notify_v14_material_update(session_id: str, object_id: str, pbr_channels: list[str] | None = None):
    """Notify connected V14 clients that Pass 2 materials are ready for an object.

    Called by the V14 pipeline when Pass 2 PBR estimation completes.
    Broadcasts to all WebSocket connections for the given session.

    Requirements: 8.7
    """
    if session_id not in _v14_material_connections:
        return

    message = json.dumps({
        "type": "material_update",
        "object_id": object_id,
        "mesh_url": f"/api/session/{session_id}/mesh/{object_id}",
        "pass": 2,
        "pbr_channels": pbr_channels or ["baseColor", "metallicRoughness", "normal"],
    })

    connections = _v14_material_connections[session_id][:]
    for ws in connections:
        try:
            await ws.send_text(message)
        except Exception:
            # Remove dead connections
            if ws in _v14_material_connections.get(session_id, []):
                _v14_material_connections[session_id].remove(ws)


# V14 sessions list endpoint (mirrors V8-V11 pattern)
@app.get("/api/v14/sessions")
async def v14_sessions():
    return list_sessions(OUTPUT_DIR, version_filter=14)


@app.get("/api/v14/session/{session_id}/stages")
async def v14_session_stages(session_id: str):
    try:
        return get_session_stages(OUTPUT_DIR, session_id)
    except (FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)


@app.get("/api/v14/session/{session_id}/stage/{stage}")
async def v14_stage(session_id: str, stage: str, revision: str | None = None):
    try:
        return get_stage_evidence(OUTPUT_DIR, session_id, stage, revision)
    except (FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)


@app.get("/api/v14/session/{session_id}/stage/{stage}/artifact")
async def v14_stage_artifact(session_id: str, stage: str, revision: str | None = None):
    try:
        path, media_type, verification = resolve_verified_artifact(
            OUTPUT_DIR, session_id, stage, revision
        )
    except (ArtifactVerificationError, FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)
    headers = {
        "Cache-Control": "no-store",
        "X-Artifact-Integrity": "verified" if verification["verified"] else "unverified",
        "X-Artifact-SHA256": verification["sha256"],
    }
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/api/v14/session/{session_id}/telemetry")
async def v14_telemetry(session_id: str):
    try:
        stages = get_session_stages(OUTPUT_DIR, session_id)
    except (FileNotFoundError, ValueError) as exc:
        return _v8_error(exc)
    payload = read_telemetry(OUTPUT_DIR / session_id)
    payload.update(
        session_id=session_id,
        interface_version=stages.get("interface_version"),
        availability="recorded" if payload["enabled"] else "not_recorded",
    )
    return payload
