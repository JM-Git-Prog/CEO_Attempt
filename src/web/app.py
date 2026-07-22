"""FastAPI interface for The Living Room."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import shutil
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.canon_image.generator import check_comfyui, get_image_provider
from src.floor_plan.validator import validate_floor_plan
from src.models import PipelineState
from src.orchestrator.llm import LLM_MODEL, OLLAMA_URL
from src.pipeline import WorldBuilder
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
from src.workflow_provenance import normalize_interface_version, workflow_profiles

app = FastAPI(title="The Living Room", version="0.9.0")
sessions: dict[str, WorldBuilder] = {}
session_locks: dict[str, asyncio.Lock] = {}
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _normalize_requested_version(value: str | None, source: str) -> int:
    """Normalize a canonical interface version without silently coercing input."""
    if value is None or value == "":
        return normalize_interface_version(None)
    if not re.fullmatch(r"[0-9]+", value) or value != str(int(value)):
        raise ValueError(f"Malformed {source} interface version: {value!r}")
    version = normalize_interface_version(value)
    if version != int(value):
        raise ValueError(
            f"Unsupported {source} interface version {value}; supported versions are 3-11"
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
        "/api/v8/sessions", "/api/v9/sessions", "/api/v10/sessions", "/api/v11/sessions"
    }
    is_history_api = (
        path in history_roots
        or path.startswith("/api/v8/session/")
        or path.startswith("/api/v9/session/")
        or path.startswith("/api/v10/session/")
        or path.startswith("/api/v11/session/")
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
    builder = WorldBuilder(interface_version=_request_version(request))
    sessions[builder.session.session_id] = builder
    builder.save_session()
    return {
        "session_id": builder.session.session_id,
        "interface_version": builder.session.interface_version,
        "workflow_profile_id": builder.session.workflow_profile_id,
        "workflow_url": f"/api/session/{builder.session.session_id}/workflow",
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
        validation = validate_floor_plan(builder.session.floor_plan)
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
    mesh_path = OUTPUT_DIR / session_id / "meshes" / f"{obj_id}.glb"
    if not mesh_path.exists():
        return JSONResponse({"error": "Mesh not found"}, status_code=404)
    return FileResponse(mesh_path, media_type="model/gltf-binary")


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
