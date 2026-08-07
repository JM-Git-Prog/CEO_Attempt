"""V16 web adapter for the durable Unified World Pipeline.

The adapter owns HTTP concerns only: conversation state, artifact delivery,
approval writes, progress replay, and material notifications. Pipeline authority
remains in :class:`UnifiedOrchestrator`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import re
import traceback
import uuid
from contextlib import suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from src.models import PipelineState, SessionMode
from src.session_manager import SessionManager
from src.unified_pipeline.conversation import (
    ConversationEngine,
    ConversationState,
    ConversationTurn,
    _user_confirms_stable,
)
from src.unified_pipeline.object_manifest import (
    build_selected_manifest,
    load_detected_document,
)
from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    DurableCheckpointStore,
    UnifiedOrchestrator,
)
from src.unified_pipeline.stage_handlers import build_handlers
from src.workflow_provenance import profile_for

INTERFACE_VERSION = 16
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_APPROVAL_STAGES = {
    "canon": "canon_approval",
    "canon_approval": "canon_approval",
    "blockout": "blockout_approval",
    "blockout_approval": "blockout_approval",
    "mesh": "mesh_approval",
    "mesh_approval": "mesh_approval",
    "world": "final_world_qa",
    "final_world": "final_world_qa",
    "final_world_qa": "final_world_qa",
}
_conversations: dict[str, ConversationEngine] = {}
_orchestrators: dict[str, UnifiedOrchestrator] = {}
_tasks: dict[str, asyncio.Task] = {}
_locks: dict[str, asyncio.Lock] = {}


def register_unified_orchestrator(orchestrator: UnifiedOrchestrator) -> None:
    """Attach Task 10.2's durable orchestrator to its V16 web session."""
    _orchestrators[orchestrator.session_id] = orchestrator


def _launch_pipeline(session_id: str, session_dir: Path, brief: dict) -> None:
    """Create the orchestrator and kick off the durable pipeline as a background task.

    Called once when steering stabilizes and the Brief is ready. The orchestrator
    runs asynchronously — the SSE endpoint streams its progress events to the UI.
    """
    _log = logging.getLogger("live_trace")
    if session_id in _orchestrators:
        _log.info(f"  pipeline already attached for {session_id[:8]}")
        return

    handlers = build_handlers()
    orchestrator = UnifiedOrchestrator(
        session_id=session_id,
        session_dir=session_dir,
        handlers=handlers,
        stages=DEFAULT_STAGE_SPECS,
    )
    _orchestrators[session_id] = orchestrator

    async def _run_pipeline():
        _log.info(f"  PIPELINE STARTED for {session_id[:8]}")
        _write_meta(session_dir, state="running")
        try:
            result = await orchestrator.run({
                "brief": brief,
                "execution_profile": "strict_real",
                "source_hash": hashlib.sha256(
                    json.dumps(brief, sort_keys=True).encode()
                ).hexdigest(),
            })
            _log.info(f"  PIPELINE RESULT: state={result.state} stage={result.stage}")
            if result.state == "completed":
                _write_meta(session_dir, state="completed")
            elif result.state == "awaiting_approval":
                _write_meta(session_dir, state="awaiting_approval", approval_stage=result.stage)
                # Emit an explicit progress event so the SSE/UI knows about the approval gate
                _append_progress(session_dir, {
                    "current_stage": result.stage,
                    "state": "awaiting_approval",
                    "plan_revision": orchestrator.current_plan_revision,
                    "finality": "provisional",
                    "message": f"Waiting for approval on {result.stage.replace('_', ' ')}",
                })
            elif result.state == "awaiting_external":
                _write_meta(session_dir, state="awaiting_external", pending_stage=result.stage)
            else:
                _write_meta(session_dir, state=result.state)
        except Exception as exc:
            _log.error(f"  PIPELINE ERROR: {exc}\n{traceback.format_exc()[-400:]}")
            _write_meta(session_dir, state="error", error=str(exc))

    _tasks[session_id] = asyncio.create_task(_run_pipeline())


def clear_unified_web_state() -> None:
    """Clear process-local adapters; durable session files are untouched."""
    _conversations.clear()
    _orchestrators.clear()
    _tasks.clear()
    _locks.clear()


def _session_dir(root: Path, session_id: str) -> Path:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid session ID")
    return root.resolve() / session_id

def _meta(session_dir: Path) -> dict:
    path = session_dir / "session_meta.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def _write_meta(session_dir: Path, **changes: object) -> dict:
    document = _meta(session_dir)
    document.update(changes)
    path = session_dir / "session_meta.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    temporary.replace(path)
    return document


def _append_progress(session_dir: Path, event: dict) -> None:
    """Append a progress event to the orchestrator progress.jsonl for SSE delivery."""
    progress_dir = session_dir / "orchestrator"
    progress_dir.mkdir(parents=True, exist_ok=True)
    progress_path = progress_dir / "progress.jsonl"
    # Read existing to get next sequence number
    sequence = 1
    if progress_path.is_file():
        lines = progress_path.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            try:
                last = json.loads(lines[-1])
                sequence = int(last.get("sequence", 0)) + 1
            except (json.JSONDecodeError, ValueError):
                sequence = len(lines) + 1
    event["sequence"] = sequence
    event.setdefault("session_id", "")
    event.setdefault("elapsed_seconds", 0.0)
    with progress_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def _conversation_path(session_dir: Path) -> Path:
    return session_dir / "conversation.json"


def _save_conversation(engine: ConversationEngine, session_dir: Path) -> None:
    state = engine.state
    document = {
        "session_id": state.session_id,
        "turns": [asdict(turn) for turn in state.turns],
        "proposed_brief": state.proposed_brief,
        "steering_stable": state.steering_stable,
        "turn_count": state.turn_count,
        "started_at": state.started_at,
    }
    _conversation_path(session_dir).write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )


def _load_conversation(session_id: str, session_dir: Path) -> ConversationEngine | None:
    engine = _conversations.get(session_id)
    if engine is not None:
        return engine
    path = _conversation_path(session_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        engine = ConversationEngine()
        engine._state = ConversationState(  # noqa: SLF001 - durable adapter restore
            session_id=session_id,
            turns=[ConversationTurn(**item) for item in raw.get("turns", [])],
            proposed_brief=dict(raw.get("proposed_brief", {})),
            steering_stable=bool(raw.get("steering_stable", False)),
            turn_count=int(raw.get("turn_count", 0)),
            started_at=float(raw.get("started_at", 0.0)),
        )
    except (OSError, ValueError, TypeError):
        return None
    _conversations[session_id] = engine
    return engine


def _path_values(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        preferred = (
            "image_path", "mesh_path", "artifact_path", "output_path", "path",
            "output_paths", "preview_paths",
        )
        for key in preferred:
            if key in value:
                yield from _path_values(value[key])
        for key, item in value.items():
            if key not in preferred:
                yield from _path_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _path_values(item)


def _safe_existing_artifact(session_dir: Path, raw_path: str, suffixes: tuple[str, ...]) -> Path | None:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = session_dir / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file() or not resolved.is_relative_to(session_dir.resolve()):
        return None
    return resolved if resolved.suffix.lower() in suffixes else None


def _artifact_path(
    session_dir: Path,
    session_id: str,
    stages: tuple[str, ...],
    suffixes: tuple[str, ...],
    *,
    object_id: str | None = None,
) -> Path | None:
    store_root = session_dir / "orchestrator" / "checkpoints"
    if store_root.is_dir():
        store = DurableCheckpointStore(session_dir, session_id)
        for stage in stages:
            checkpoint = store.load(stage, object_id)
            if checkpoint is None:
                continue
            for raw_path in _path_values(checkpoint.output):
                found = _safe_existing_artifact(session_dir, raw_path, suffixes)
                if found is not None:
                    return found
    return None


def _compiled_mesh_path(session_dir: Path, object_id: str) -> Path | None:
    """Resolve an exact object-bound compiled mesh and verify its contract hash."""
    scene_path = session_dir / "compiled" / "browser" / "scene.json"
    if not scene_path.is_file():
        return None
    try:
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for instance in scene.get("instances", []):
        if not isinstance(instance, dict) or str(instance.get("object_id", "")) != object_id:
            continue
        asset_uri = instance.get("asset_uri")
        binding = instance.get("asset_binding", {})
        if not isinstance(asset_uri, str) or not isinstance(binding, dict):
            return None
        candidate = _safe_existing_artifact(
            session_dir, f"compiled/browser/{asset_uri}", (".glb",)
        )
        expected_hash = str(binding.get("asset_id", ""))
        if candidate is None or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            return None
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected_hash:
            return None
        return candidate
    return None


def unified_artifact_response(
    root: Path,
    session_id: str,
    kind: str,
    *,
    object_id: str | None = None,
):
    """Return one V16 artifact without exposing paths outside its session."""
    try:
        session_dir = _session_dir(root, session_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
        return None
    if object_id is not None and not _SESSION_ID.fullmatch(object_id):
        return JSONResponse({"error": "Invalid object ID"}, status_code=400)

    settings = {
        "dream_preview": (("dream_preview",), (".png", ".jpg", ".jpeg", ".webp")),
        "blockout": (("blockout", "spatial_reconstruction"), (".png", ".jpg", ".jpeg", ".webp")),
        "canon": (("canon_generation", "scene_canon", "canon"), (".png", ".jpg", ".jpeg", ".webp")),
        "mesh": (("material_pass_1", "mesh_generation"), (".glb", ".gltf")),
    }
    stages, suffixes = settings[kind]
    path = _artifact_path(
        session_dir, session_id, stages, suffixes, object_id=object_id
    )
    if path is None:
        patterns = {
            "dream_preview": (
                "dream_preview*.png", "dream_previews/*.png",
                "artifacts/dream_preview*.png", "artifacts/dream_previews/*.png",
            ),
            "blockout": (
                "blockout*.png", "artifacts/blockout*.png",
                "artifacts/blockout/*.png",
            ),
            "canon": (
                "canon*.png", "artifacts/canon*.png",
                "artifacts/canon_generation*.png", "artifacts/scene_canon*.png",
            ),
            "mesh": (
                f"objects/{object_id}.glb", f"meshes/{object_id}.glb",
                f"artifacts/{object_id}.glb",
                f"objects/{session_id}/{object_id}.glb",
            ),
        }[kind]
        for pattern in patterns:
            path = next((item for item in session_dir.glob(pattern) if item.is_file()), None)
            if path is not None:
                break
        if path is None and kind == "mesh" and object_id is not None:
            path = _compiled_mesh_path(session_dir, object_id)
    if path is None:
        return JSONResponse({"error": f"{kind.replace('_', ' ').title()} not found"}, status_code=404)
    media_type = mimetypes.guess_type(path.name)[0] or (
        "model/gltf-binary" if path.suffix.lower() == ".glb" else "application/octet-stream"
    )
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


def unified_sse_response(root: Path, session_id: str, after_sequence: int = 0):
    """Stream durable orchestrator progress with reconnect replay."""
    try:
        session_dir = _session_dir(root, session_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
        return None
    progress_path = session_dir / "orchestrator" / "progress.jsonl"

    async def events():
        # V16 dual-state fix: immediately emit terminal if session is already dead
        meta = _meta(session_dir)
        if meta.get("state") == "error":
            yield (
                f"event: pipeline.terminal\n"
                f"data: {json.dumps({'state': 'error', 'reason': meta.get('error', 'unknown')})}\n\n"
            )
            return

        sequence = max(0, after_sequence)
        idle_ticks = 0
        while True:
            emitted = False
            if progress_path.is_file():
                with suppress(OSError, ValueError, TypeError):
                    for line in progress_path.read_text(encoding="utf-8").splitlines():
                        event = json.loads(line)
                        current = int(event.get("sequence", 0))
                        if current > sequence:
                            sequence = current
                            emitted = True
                            yield (
                                f"id: {current}\nevent: pipeline.progress\ndata: "
                                f"{json.dumps(event, sort_keys=True)}\n\n"
                            )
            meta = _meta(session_dir)
            state = str(meta.get("state", ""))
            if state in {"completed", "ready", "error", "failed"}:
                yield f"event: pipeline.terminal\ndata: {json.dumps({'state': state})}\n\n"
                return
            idle_ticks = 0 if emitted else idle_ticks + 1
            if idle_ticks >= 60:
                yield ": keepalive\n\n"
                idle_ticks = 0
            await asyncio.sleep(0.5)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def create_unified_router(output_root: Callable[[], Path]) -> APIRouter:
    """Build the additive V16 routes using the app's current output root."""
    router = APIRouter()

    @router.post("/api/session/unified/start")
    async def start_unified_session(request: Request):
        _log = logging.getLogger("live_trace")
        _log.info("POST /api/session/unified/start — creating session")
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError
        except Exception:
            payload = {}
        root = output_root()
        manager = SessionManager(output_base=root)
        session = manager.create_session("", SessionMode.MVP)
        session.interface_version = INTERFACE_VERSION
        session.workflow_profile = profile_for(INTERFACE_VERSION)
        session.workflow_profile_id = session.workflow_profile["id"]
        manager._save_session(session)  # noqa: SLF001 - shared lifecycle persistence
        session_dir = Path(session.output_path)
        now = datetime.now(timezone.utc).isoformat()
        _write_meta(
            session_dir,
            session_id=session.session_id,
            interface_version=INTERFACE_VERSION,
            source_type="conversation",
            state="awaiting_description",
            created_at=now,
            queue_policy="shared_fifo_compilation",
            lifecycle="session_manager_ttl",
        )
        engine = ConversationEngine()
        engine.state.session_id = session.session_id
        _log.info(f"  session={session.session_id} — calling Ollama for opening...")
        try:
            opening = await engine.generate_opening()
            _log.info(f"  opening generated ({len(opening)} chars)")
        except Exception as exc:
            _log.error(f"  OPENING FAILED: {exc}\n{traceback.format_exc()[-300:]}")
            opening = "Welcome! Describe the space you'd like to create."
        _conversations[session.session_id] = engine
        _save_conversation(engine, session_dir)
        _log.info(f"  session ready: {session.session_id}")
        return {
            "session_id": session.session_id,
            "interface_version": INTERFACE_VERSION,
            "state": "awaiting_description",
            "opening_message": opening,
            "events_url": f"/api/session/{session.session_id}/events",
            "materials_ws_url": f"/api/session/{session.session_id}/materials",
            "stage_urls": {
                name: f"/api/session/{session.session_id}/{name}"
                for name in ("dream_preview", "blockout", "canon")
            },
            "mesh_url_template": f"/api/session/{session.session_id}/mesh/{{object_id}}",
        }

    @router.post("/api/session/{session_id}/message")
    async def unified_message(session_id: str, request: Request):
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        meta = _meta(session_dir)
        if meta.get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)
        # Allow game design messages during pipeline — don't reject
        session_state = meta.get("state", "")
        if session_state not in ("awaiting_description", "brief_ready", "running",
                                  "awaiting_approval", "awaiting_external", ""):
            return JSONResponse({
                "error": f"Session is {session_state}.",
                "session_id": session_id,
                "state": session_state,
            }, status_code=409)
        try:
            payload = await request.json()
            message = str(payload.get("message", "")).strip()
            if not message:
                raise ValueError("message is required")
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        _log.info(f"POST /message session={session_id[:8]} msg={message[:80]}")
        async with _locks.setdefault(session_id, asyncio.Lock()):
            engine = _load_conversation(session_id, session_dir)
            if engine is None:
                return JSONResponse({"error": "Conversation state is unavailable"}, status_code=409)

            # Fix #3: Confirmation detection — enforce BEFORE calling interpret_response
            # If user clearly confirms, skip the LLM call entirely and extract brief immediately
            if _user_confirms_stable(message):
                _log.info("  user confirmed stable — skipping LLM, extracting Brief directly")
                engine._state.steering_stable = True  # noqa: SLF001
                engine._state.turns.append(ConversationTurn(role="user", content=message))
                engine._state.turn_count += 1
                brief = await engine.extract_brief()
                brief_document = brief.to_dict()
                artifacts = session_dir / "artifacts"
                artifacts.mkdir(exist_ok=True)
                (artifacts / "brief.json").write_text(
                    json.dumps(brief_document, indent=2), encoding="utf-8"
                )
                _write_meta(session_dir, state="brief_ready")
                _save_conversation(engine, session_dir)
                _launch_pipeline(session_id, session_dir, brief_document)
                return {
                    "session_id": session_id,
                    "interface_version": INTERFACE_VERSION,
                    "message": "Brief locked. Starting pipeline...",
                    "steering_stable": True,
                    "turn_count": engine.state.turn_count,
                    "brief": brief_document,
                }

            try:
                response = await engine.interpret_response(message)
                _log.info(f"  response ({len(response)} chars): {response[:100]}")
            except Exception as exc:
                _log.error(f"  MESSAGE FAILED: {exc}\n{traceback.format_exc()[-300:]}")
                raise
            result: dict[str, object] = {
                "session_id": session_id,
                "interface_version": INTERFACE_VERSION,
                "message": response,
                "steering_stable": engine.is_stable,
                "turn_count": engine.state.turn_count,
            }
            if engine.is_stable:
                _log.info("  steering stabilized — extracting Brief")
                brief = await engine.extract_brief()
                brief_document = brief.to_dict()
                artifacts = session_dir / "artifacts"
                artifacts.mkdir(exist_ok=True)
                (artifacts / "brief.json").write_text(
                    json.dumps(brief_document, indent=2), encoding="utf-8"
                )
                result["brief"] = brief_document
                _write_meta(session_dir, state="brief_ready")
                _log.info(f"  Brief saved — {len(brief_document.get('object_manifest', []))} objects")
                # Kick off the durable pipeline
                _launch_pipeline(session_id, session_dir, brief_document)
            _save_conversation(engine, session_dir)
            return result

    @router.post("/api/session/{session_id}/game_message")
    async def unified_game_message(session_id: str, request: Request):
        """Handle game design conversation messages during pipeline execution.

        While the GPU builds the 3D world, the user designs the GAME overlay
        through continued conversation. This runs parallel to the pipeline.
        """
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            payload = await request.json()
            message = str(payload.get("message", "")).strip()
            if not message:
                return JSONResponse({"error": "message is required"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "invalid request"}, status_code=400)

        _log.info(f"  game_message[{session_id[:8]}]: {message[:60]}")

        # Get the brief for context
        brief_path = session_dir / "artifacts" / "brief.json"
        brief_context = ""
        if brief_path.is_file():
            try:
                brief = json.loads(brief_path.read_text(encoding="utf-8"))
                room = brief.get("room_purpose", "room")
                objects = [o.get("name", "") for o in brief.get("object_manifest", []) if isinstance(o, dict)]
                brief_context = f"Room: {room}. Objects: {', '.join(objects[:6])}."
            except Exception:
                pass

        # Use Ollama for game design conversation
        try:
            import httpx
            ollama_prompt = (
                f"You are a game designer creating a game for a 3D room. {brief_context} "
                f"The user is designing the game while the room is being built. "
                f"Respond concisely (2-3 sentences) to their game design idea. "
                f"Be creative and enthusiastic. Suggest mechanics, rules, or scoring that fit the room.\n\n"
                f"User: {message}"
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": "llama3.1:latest", "prompt": ollama_prompt, "stream": False,
                          "options": {"temperature": 0.8, "num_predict": 150}},
                )
                if resp.status_code == 200:
                    response = resp.json().get("response", "").strip()
                else:
                    response = "Game idea noted! I'll incorporate this into the design."
        except Exception:
            response = "Great idea! I'll weave that into the game mechanics once the world is ready."

        # Save game conversation to session
        game_conv_path = session_dir / "game_conversation.json"
        game_history = []
        if game_conv_path.is_file():
            try:
                game_history = json.loads(game_conv_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        game_history.append({"role": "user", "content": message})
        game_history.append({"role": "assistant", "content": response})
        game_conv_path.write_text(json.dumps(game_history, indent=2), encoding="utf-8")

        return {"message": response, "turn": len(game_history) // 2}

    @router.post("/api/session/{session_id}/approve/{stage}")
    async def unified_approve(session_id: str, stage: str, request: Request):
        _log = logging.getLogger("live_trace")
        try:
            return await _unified_approve_inner(session_id, stage, request)
        except Exception as exc:
            _log.error("APPROVAL UNHANDLED ERROR: %s\n%s", exc, traceback.format_exc())
            return JSONResponse(
                {"error": f"Internal error: {type(exc).__name__}: {exc}"},
                status_code=500,
            )

    async def _unified_approve_inner(session_id: str, stage: str, request: Request):
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)
        approval_stage = _APPROVAL_STAGES.get(stage)
        if approval_stage is None:
            return JSONResponse({"error": f"Unsupported approval stage: {stage}"}, status_code=400)
        orchestrator = _orchestrators.get(session_id)
        if orchestrator is None:
            return JSONResponse(
                {"error": "Unified orchestrator is not attached to this session"},
                status_code=409,
            )
        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                payload = {}
        except Exception:
            payload = {}
        writer_id = str(payload.get("writer_id", "web-user")).strip() or "web-user"

        selected_detected = None
        selected_ids: list[object] = []
        if approval_stage == "blockout_approval" and bool(payload.get("approved", True)):
            selection = payload.get("selected_object_ids")
            if selection is None:
                selection = payload.get("selected_objects")
            if not isinstance(selection, list):
                return JSONResponse(
                    {"error": "blockout approval requires selected objects"},
                    status_code=409,
                )
            for item in selection:
                if isinstance(item, dict):
                    selected_ids.append(item.get("object_id", item.get("id")))
                else:
                    selected_ids.append(item)
            try:
                selected_detected = load_detected_document(
                    session_dir / "artifacts" / "detected_objects.json"
                )
                build_selected_manifest(
                    selected_detected,
                    selected_ids,
                    plan_revision=orchestrator.current_plan_revision,
                    approval_revision=0,
                )
            except (KeyError, OSError, TypeError, ValueError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)

        try:
            # Lazy evaluation: only call current_plan_revision if payload doesn't supply it
            # This prevents ValueError from max([]) on a transiently empty checkpoint store
            raw_rev = payload.get("plan_revision")
            revision = int(raw_rev) if raw_rev is not None else orchestrator.current_plan_revision
            with orchestrator.approval_writer(writer_id) as writer_token:
                decision = orchestrator.record_approval(
                    stage=approval_stage,
                    writer_id=writer_id,
                    writer_token=writer_token,
                    plan_revision=revision,
                    approved=bool(payload.get("approved", True)),
                    object_id=(str(payload["object_id"]) if payload.get("object_id") else None),
                    feedback=str(payload.get("feedback", "")),
                )
        except (ValueError, RuntimeError, KeyError, TypeError, OSError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)

        if selected_detected is not None:
            selected_manifest = build_selected_manifest(
                selected_detected,
                selected_ids,
                plan_revision=revision,
                approval_revision=int(getattr(decision, "approval_revision", 1)),
            )
            artifacts_dir = session_dir / "artifacts"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            selected_path = artifacts_dir / "selected_objects.json"
            temporary_path = selected_path.with_suffix(".json.tmp")
            temporary_path.write_text(
                json.dumps(selected_manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            temporary_path.replace(selected_path)
            _log.info(
                "  blockout approval: bound %d selected canon objects",
                selected_manifest["object_count"],
            )

        existing = _tasks.get(session_id)
        if existing is None or existing.done():
            _log.info("  PIPELINE RESUMING after approval for %s (stage=%s)", session_id[:8], stage)

            async def _resume_pipeline():
                try:
                    result = await orchestrator.run()
                    _log.info("  PIPELINE RESULT after approval: state=%s stage=%s", result.state, result.stage)
                    if result.state == "awaiting_approval":
                        _write_meta(session_dir, state="awaiting_approval", pending_stage=result.stage)
                        _append_progress(session_dir, {
                            "current_stage": result.stage,
                            "state": "awaiting_approval",
                            "plan_revision": orchestrator.current_plan_revision,
                            "message": f"Waiting for approval on {result.stage.replace('_', ' ')}",
                        })
                    elif result.state == "completed":
                        _write_meta(session_dir, state="completed")
                    elif result.state == "awaiting_external":
                        _write_meta(session_dir, state="awaiting_external", pending_stage=result.stage)
                    else:
                        _write_meta(session_dir, state=result.state)
                except Exception as exc:
                    _log.error("  PIPELINE ERROR after approval: %s\n%s", exc, traceback.format_exc()[-400:])
                    _write_meta(session_dir, state="error", error=str(exc))

            _tasks[session_id] = asyncio.create_task(_resume_pipeline())
        else:
            _log.info("  Pipeline task still running for %s — not restarting", session_id[:8])
        _write_meta(session_dir, state="running")
        return {"session_id": session_id, "decision": decision.to_dict(), "state": "running"}

    @router.get("/api/session/{session_id}/object_picker")
    async def object_picker(session_id: str):
        """Return detected objects JSON for the interactive blockout picker UI."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)

        # Canonical detection document is authoritative; picker JSON is legacy presentation data.
        artifacts_dir = session_dir / "artifacts"
        detected_path = artifacts_dir / "detected_objects.json"
        picker_path = artifacts_dir / "object_picker.json"

        data = None
        for path in (detected_path, picker_path):
            if path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    break
                except (OSError, json.JSONDecodeError):
                    continue

        if data is None:
            return JSONResponse({"error": "No detected objects available"}, status_code=404)

        return JSONResponse(data)

    @router.get("/api/session/{session_id}/dream_preview")
    async def unified_dream_preview(session_id: str):
        response = unified_artifact_response(output_root(), session_id, "dream_preview")
        return response or JSONResponse({"error": "Unified session not found"}, status_code=404)

    @router.get("/api/session/{session_id}/canon")
    async def unified_canon(session_id: str):
        response = unified_artifact_response(output_root(), session_id, "canon")
        return response or JSONResponse({"error": "Unified session not found"}, status_code=404)

    @router.get("/api/session/{session_id}/scene_graph")
    async def unified_scene_graph(session_id: str):
        """Project the finalized WorldContract for the QA harness."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)

        artifacts = session_dir / "artifacts"
        contract_path = artifacts / "world_contract.json"
        graph_path = artifacts / "scene_graph.json"
        if not contract_path.is_file() or not graph_path.is_file():
            return JSONResponse({"objects": [], "ready": False})
        try:
            from src.unified_pipeline.object_manifest import file_sha256
            from src.unified_pipeline.world_contract import WorldContract, verify_hash

            contract = WorldContract.from_dict(json.loads(contract_path.read_text(encoding="utf-8")))
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            graph_hash = str(graph.pop("document_sha256", ""))
            encoded = json.dumps(
                graph, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            if hashlib.sha256(encoded).hexdigest() != graph_hash:
                raise ValueError("scene graph hash is invalid")
            if not verify_hash(contract) or graph.get("contract_hash") != contract.contract_hash:
                raise ValueError("scene graph does not bind the finalized WorldContract")
            objects = []
            for instance in contract.instances:
                mesh_path = Path(instance.asset_binding.mesh_path)
                has_mesh = (
                    mesh_path.is_file()
                    and mesh_path.suffix.lower() == ".glb"
                    and file_sha256(mesh_path) == instance.asset_binding.asset_id
                )
                objects.append({
                    "objectId": instance.object_id,
                    "name": instance.name,
                    "meshCount": 1 if has_mesh else 0,
                    "hasMesh": has_mesh,
                    "meshUrl": (
                        f"/api/session/{session_id}/mesh/{instance.object_id}"
                        if has_mesh else None
                    ),
                    "position": instance.position.to_dict(),
                    "rotation": instance.rotation.to_dict(),
                    "scale": instance.scale.to_dict(),
                    "role": instance.semantic_label,
                    "physicsIntent": instance.physics_intent,
                    "materialIntent": instance.material_intent.to_dict(),
                    "assetSha256": instance.asset_binding.asset_id,
                    "generator": instance.asset_binding.generator,
                })
            meta = _meta(session_dir)
            complete = meta.get("state") in ("completed", "ready")
            ready = complete and bool(objects) and all(item["hasMesh"] for item in objects)
            return {
                "objects": objects, "ready": ready, "sessionId": session_id,
                "objectCount": len(objects), "state": meta.get("state", "unknown"),
                "contractHash": contract.contract_hash,
                "cameraHash": contract.camera_hash,
                "roomShellRef": contract.room_shell_ref,
                "sceneGraphSha256": graph_hash,
            }
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return JSONResponse(
                {"objects": [], "ready": False, "error": str(exc)}, status_code=409
            )

    @router.websocket("/api/session/{session_id}/materials")
    async def unified_materials(session_id: str, websocket: WebSocket):
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError:
            await websocket.close(code=4400)
            return
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        last_sequence = 0
        progress_path = session_dir / "orchestrator" / "progress.jsonl"
        try:
            while True:
                if progress_path.is_file():
                    with suppress(OSError, ValueError, TypeError):
                        for line in progress_path.read_text(encoding="utf-8").splitlines():
                            event = json.loads(line)
                            sequence = int(event.get("sequence", 0))
                            if sequence <= last_sequence:
                                continue
                            last_sequence = sequence
                            if event.get("current_stage") == "material_pass_2" and event.get("state") == "completed":
                                object_id = str(event.get("object_id", ""))
                                await websocket.send_json({
                                    "type": "material_update",
                                    "object_id": object_id,
                                    "mesh_url": f"/api/session/{session_id}/mesh/{object_id}",
                                    "pass": 2,
                                    "canonical_hash": event.get("canonical_hash", ""),
                                    "plan_revision": event.get("plan_revision", 0),
                                    "finality": event.get("finality", "provisional"),
                                })
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=0.5)
                    if message == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    continue
        except WebSocketDisconnect:
            return

    @router.get("/api/session/{session_id}/health")
    async def unified_health(session_id: str):
        """V16 ground-truth health endpoint — reads both state files and returns
        the authoritative session state, resolving any split-brain disagreement."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        meta = _meta(session_dir)
        if meta.get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)

        # Read session.json (SessionManager state)
        session_json_state = None
        session_json_error = None
        session_file = session_dir / "session.json"
        if session_file.is_file():
            try:
                raw = json.loads(session_file.read_text(encoding="utf-8"))
                session_json_state = raw.get("state")
                session_json_error = raw.get("error")
            except (OSError, ValueError, TypeError):
                pass

        # Read session_meta.json (web adapter state)
        meta_state = meta.get("state")
        meta_error = meta.get("error")

        # Resolve: if session.json says ERROR but meta disagrees, trust session.json
        # (session_manager is the authority on lifecycle)
        resolved_state = meta_state
        resolved_error = meta_error
        if session_json_state in ("error", "ERROR") and meta_state not in ("error", "completed"):
            resolved_state = "error"
            resolved_error = session_json_error or meta_error

        return {
            "session_id": session_id,
            "state": resolved_state,
            "error": resolved_error,
            "meta_state": meta_state,
            "session_json_state": session_json_state,
            "split_brain": (
                session_json_state in ("error", "ERROR")
                and meta_state not in ("error", "completed", "ready")
            ),
        }

    @router.get("/api/session/{session_id}/status")
    async def unified_status(session_id: str):
        """Lightweight status endpoint for client-side health checks."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        meta = _meta(session_dir)
        if meta.get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)

        # Check session.json as ground truth
        session_file = session_dir / "session.json"
        session_json_error = None
        if session_file.is_file():
            try:
                raw = json.loads(session_file.read_text(encoding="utf-8"))
                if raw.get("state") in ("error", "ERROR"):
                    error_raw = raw.get("error", "")
                    try:
                        session_json_error = json.loads(error_raw) if error_raw else {}
                    except (ValueError, TypeError):
                        session_json_error = {"reason_code": error_raw}
                    return {
                        "session_id": session_id,
                        "state": "error",
                        "error": session_json_error,
                    }
            except (OSError, ValueError, TypeError):
                pass

        return {
            "session_id": session_id,
            "state": meta.get("state", "unknown"),
            "error": None,
        }

    @router.get("/api/session/{session_id}/world/{path:path}")
    async def unified_world_file(session_id: str, path: str):
        """Serve compiled browser world files (JS, HTML, JSON, GLB, etc.)."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        compiled_dir = session_dir / "compiled" / "browser"
        if not compiled_dir.is_dir():
            return JSONResponse({"error": "Compiled world not found"}, status_code=404)

        # Sanitize path to prevent directory traversal
        target = (compiled_dir / path).resolve()
        if not str(target).startswith(str(compiled_dir.resolve())):
            return JSONResponse({"error": "Invalid path"}, status_code=400)

        if not target.is_file():
            return JSONResponse({"error": "File not found"}, status_code=404)

        # Determine MIME type
        mime_map = {
            ".html": "text/html",
            ".js": "application/javascript",
            ".mjs": "application/javascript",
            ".json": "text/json",
            ".glb": "model/gltf-binary",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        suffix = target.suffix.lower()
        media_type = mime_map.get(suffix) or mimetypes.guess_type(str(target))[0] or "application/octet-stream"

        return FileResponse(str(target), media_type=media_type)

    @router.get("/api/session/{session_id}/world")
    async def unified_world_index(session_id: str):
        """Serve the compiled world's index.html (entry point for the 3D viewer)."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        compiled_dir = session_dir / "compiled" / "browser"
        index_file = compiled_dir / "index.html"

        if not index_file.is_file():
            return JSONResponse({"error": "Compiled world not available"}, status_code=404)

        return FileResponse(str(index_file), media_type="text/html")

    return router
