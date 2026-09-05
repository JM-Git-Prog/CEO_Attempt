"""V16 web adapter for the durable Unified World Pipeline.

The adapter owns HTTP concerns only: conversation state, artifact delivery,
approval writes, progress replay, and material notifications. Pipeline authority
remains in :class:`UnifiedOrchestrator`.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import mimetypes
import re
import time
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
    build_plan_bound_selected_manifest,
    load_detected_document,
    resolve_plan_selected_objects,
)
from src.unified_pipeline.orchestrator import (
    DEFAULT_STAGE_SPECS,
    DurableCheckpointStore,
    UnifiedOrchestrator,
)
from src.unified_pipeline import warehouse
from src.unified_pipeline import event_log, model_router
from src.unified_pipeline import stations
from src.unified_pipeline.stage_handlers import (
    authoritative_user_prompt,
    build_handlers,
    compose_dream_prompt,
    load_revisions,
)
from src.workflow_provenance import profile_for

INTERFACE_VERSION = 16
# Route-scoped capability policy for the generated world document. Pointer Lock
# is required by the native first-person controller; unrelated sensitive browser
# capabilities remain denied instead of inheriting a broader application policy.
WORLD_PERMISSIONS_POLICY = ", ".join((
    "accelerometer=()",
    "camera=()",
    "geolocation=()",
    "gyroscope=()",
    "magnetometer=()",
    "microphone=()",
    "payment=()",
    "usb=()",
    "pointer-lock=(self)",
))
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_APPROVAL_STAGES = {
    "canon": "canon_approval",
    "canon_approval": "canon_approval",
    "blockout": "blockout_approval",
    "blockout_approval": "blockout_approval",
    "object_canon": "object_canon_approval",
    "object_canon_approval": "object_canon_approval",
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
                    "session_id": session_id,
                    "current_stage": result.stage,
                    "state": "awaiting_approval",
                    "plan_revision": orchestrator.current_plan_revision,
                    "canonical_hash": result.canonical_hash,
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


# ── reference pictures (2026-09-03): pasted or dropped into the chat box ──
_REFERENCE_MAX_BYTES = 12 * 1024 * 1024


def _references_path(session_dir: Path) -> Path:
    return session_dir / "artifacts" / "references.json"


def _references(session_dir: Path) -> dict:
    path = _references_path(session_dir)
    if not path.is_file():
        return {"references": []}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"references": []}
    if not isinstance(document, dict) or not isinstance(document.get("references"), list):
        return {"references": []}
    return document


def _write_references(session_dir: Path, document: dict) -> None:
    path = _references_path(session_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
    temporary.replace(path)


def _note_reference(session_dir: Path, reference: object, message: str) -> None:
    """The sentence sent right after a picture is that picture's note (what it is for)."""
    if reference is None:
        return
    try:
        n = int(reference)
    except (TypeError, ValueError):
        return
    document = _references(session_dir)
    for record in document["references"]:
        if isinstance(record, dict) and record.get("id") == n:
            record["note"] = message
            document["last_used"] = n
            try:
                _write_references(session_dir, document)
            except OSError as exc:
                logging.getLogger("live_trace").warning("  reference #%s note not saved: %s", n, exc)
            return


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
    # PROVENANCE (2026-09-04). Every `role:"assistant"` turn below is raw model output,
    # and until today this file recorded no model at all. That cost 227 archived sessions
    # — their briefs and floor plans are unusable as training data because nothing can
    # prove which model wrote them. One field prevents the whole class.
    state = engine.state
    document = {
        "session_id": state.session_id,
        "model": getattr(engine, "_model", None) or getattr(engine, "_session_model", None),
        "turns": [asdict(turn) for turn in state.turns],
        "proposed_brief": state.proposed_brief,
        "steering_stable": state.steering_stable,
        "turn_count": state.turn_count,
        "started_at": state.started_at,
    }
    _conversation_path(session_dir).write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )


async def _start_missing_props(session_id: str, missing: list) -> list[str]:
    """Start the $0 prop factory for anything the warehouse does not hold.

    2026-09-02, John: "if we don't have assets that we can use, you can make sure
    the chat is intelligent enough to make them and catalog them." §6 of the
    vision has described this since June and nothing had ever checked the shelf.

    Deliberately routed through the Pick Board rather than spawned here: the board
    owns the job queue, the duplicate check and the GPU lock (the 4090 is a
    one-person workshop), and it is the single writer of decisions — so every
    prop still stops at John's PICK gate, and filing itself in the warehouse is
    what the factory already does. Nothing here spends money.
    """
    import httpx

    _log = logging.getLogger("live_trace")
    started: list[str] = []
    for item in missing[:6]:  # a room's worth; never an unbounded queue
        subject = " ".join(str(item.get("name", "")).split())[:80]
        if not re.fullmatch(r"[A-Za-z0-9 ]{2,80}", subject):
            continue
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "http://127.0.0.1:8194/api/make",
                    json={"subject": subject, "seeds": 4},
                )
            if response.status_code < 400:
                started.append(subject)
                _log.info("  warehouse gap -> factory queued: %s", subject)
            else:
                _log.info("  warehouse gap -> board refused %s: %s", subject, response.status_code)
        except Exception as exc:
            _log.info("  warehouse gap -> board unreachable for %s: %s", subject, exc)
            break  # the board is down; stop trying the rest
    return started


def _first_user_prompt(engine: ConversationEngine) -> str:
    """The same 'authoritative' sentence the Dream Preview stage injects."""
    return next(
        (turn.content.strip() for turn in engine.state.turns
         if turn.role == "user" and turn.content.strip()),
        "",
    )


def _proposal_view(engine: ConversationEngine, session_dir: Path | None = None) -> dict:
    """What the chat shows John after every reply (V17 Slice 1, 2026-09-02):
    the exact prompt that would render right now, plus the game and REAL ideas
    the model already computed but the page used to throw away."""
    proposed = engine.state.proposed_brief
    # Slice 2a: the shown prompt must match what the renderer will build, which
    # now includes every steering turn and John's revision requirements.
    if session_dir is not None:
        source = authoritative_user_prompt(session_dir)
        revisions = load_revisions(session_dir)
    else:
        source, revisions = _first_user_prompt(engine), ()
    return {
        "render_prompt": compose_dream_prompt(proposed, source or _first_user_prompt(engine), revisions),
        "game_concept": proposed.get("game_concept") or None,
        "real_capabilities": proposed.get("real_capabilities") or None,
    }


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
        # The router picks the talking model (cloud first, by the house law) — the
        # chat no longer answers on the local 8B that shares the card with the painters.
        engine = ConversationEngine(model=await model_router.pick("talk"))
        engine.state.session_id = session.session_id
        _log.info(f"  session={session.session_id} — calling Ollama ({engine._model}) for opening...")  # noqa: SLF001
        try:
            # Where the 3D pane says he is standing, if it has reported yet. Absent
            # is fine — the greeting then asks instead of assuming he is indoors.
            _where = str(payload.get("where") or "").strip() or None
            if _where:
                _log.info("  world says: %s", _where[:120])
            opening = await engine.generate_opening(_where)
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
            "model": engine._model,  # noqa: SLF001 - the rail shows who is talking
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
        _note_reference(session_dir, payload.get("reference"), message)
        # ── a check John asks for becomes a garage wall (the station kit, 2026-09-03) ──
        # "which of these rooms do you like?" is not steering — it is a rule for this
        # session: at the room-picture step, render N and let him choose in the garage.
        rule = stations.parse_rule(message)
        if rule:
            stations.add_rule(session_dir, rule)
            _log.info(f"  STATION RULE {session_id[:8]}: {rule['material']} x{rule['count']}")
            return {
                "session_id": session_id,
                "interface_version": INTERFACE_VERSION,
                "message": stations.rule_sentence(rule, already_rendered=(session_dir / "artifacts" / "canon.png").exists()),
                "steering_stable": False,
                "model_used": None,
                "command": "station-rule",
                "rule": rule,
            }
        # ── the model router, in the chat (John 2026-09-03: auto, override with a word) ──
        if model_router.is_models_command(message):
            return {
                "session_id": session_id,
                "interface_version": INTERFACE_VERSION,
                "message": await model_router.models_sentence(),
                "steering_stable": False,
                "model_used": None,
                "command": "models",
            }
        forced_name, message = model_router.override(message)
        forced = None
        if forced_name:
            forced = await model_router.resolve_override(forced_name)
            if not forced:
                have = await model_router.garage()
                return {
                    "session_id": session_id,
                    "interface_version": INTERFACE_VERSION,
                    "message": f"I don't have \"{forced_name}\" installed. " + (
                        "You have: " + ", ".join(have.all) + '. Say "models" for the lane I use.' if have.all else "Ollama's list is unreachable right now."
                    ),
                    "steering_stable": False,
                    "model_used": None,
                    "command": "override-missing",
                }
        async with _locks.setdefault(session_id, asyncio.Lock()):
            engine = _load_conversation(session_id, session_dir)
            if engine is None:
                return JSONResponse({"error": "Conversation state is unavailable"}, status_code=409)
            # the session's own model is chosen once (a restored session chooses now); a
            # forced model applies to THIS sentence only — every message starts from the default
            if getattr(engine, "_session_model", None) is None:
                engine._session_model = engine._model or await model_router.pick("talk")  # noqa: SLF001
            engine._model = forced or engine._session_model  # noqa: SLF001
            model_used = engine._model  # noqa: SLF001

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
                stock = warehouse.check(
                    brief_document.get("object_manifest", []),
                    str(brief_document.get("room_purpose", "")),
                )
                stock["started"] = await _start_missing_props(session_id, stock["missing"])
                return {
                    "session_id": session_id,
                    "interface_version": INTERFACE_VERSION,
                    "message": "Brief locked. Starting pipeline...",
                    "steering_stable": True,
                    "turn_count": engine.state.turn_count,
                    "model_used": model_used,
                    "brief": brief_document,
                    "warehouse": stock,
                    "warehouse_message": warehouse.sentence(stock),
                    "render_prompt": compose_dream_prompt(
                        brief_document,
                        authoritative_user_prompt(session_dir) or _first_user_prompt(engine),
                        load_revisions(session_dir),
                    ),
                }

            try:
                # The room brain has no eyes. /api/v17/say already looked at any
                # attached photo with minicpm-v; the page carries that one line here
                # so this model stops answering "this one" from its own defaults.
                # (2026-09-03: a brick mansion produced a teal living room.)
                _turn_started = time.monotonic()
                response = await engine.interpret_response(
                    message,
                    str(payload.get("picture_summary") or "").strip() or None,
                    str(payload.get("where") or "").strip() or None,
                )
                _log.info(f"  response ({len(response)} chars): {response[:100]}")
            except Exception as exc:
                _log.error(f"  MESSAGE FAILED: {exc}\n{traceback.format_exc()[-300:]}")
                # The misses are kept too (John, 2026-09-04). A conversation log of
                # successes alone cannot teach anything to avoid a failure.
                event_log.append_event(
                    stage="chat", session=session_id,
                    input={"message": message, "message_sha": event_log.sha(message),
                           "prompt_rendered": None,
                           "picture_summary": str(payload.get("picture_summary") or "").strip(),
                           "where": str(payload.get("where") or "").strip()},
                    model={"route": model_used, "forced": bool(forced)},
                    outcome={"ok": False, "ms": int((time.monotonic() - _turn_started) * 1000),
                             "error": {"kind": "engine", "msg": f"{type(exc).__name__}: {exc}"[:300]}},
                    result=None,
                )
                raise
            result: dict[str, object] = {
                "session_id": session_id,
                "interface_version": INTERFACE_VERSION,
                "message": response,
                "steering_stable": engine.is_stable,
                "turn_count": engine.state.turn_count,
                "model_used": model_used,
                **_proposal_view(engine, session_dir),
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
                # ...and check the shelf before making anything from scratch.
                stock = warehouse.check(
                    brief_document.get("object_manifest", []),
                    str(brief_document.get("room_purpose", "")),
                )
                stock["started"] = await _start_missing_props(session_id, stock["missing"])
                result["warehouse"] = stock
                result["warehouse_message"] = warehouse.sentence(stock)
            # THE ROW THE NORTH STAR NEEDS: John's sentence in, the answer out, with the
            # model that produced it and its digest. Captured here because this is the
            # endpoint the left pane actually calls for a conversational turn —
            # /api/v17/say only classifies, and instrumenting it alone caught nothing.
            _digest = ""
            try:
                _digest = (await model_router.garage()).digests.get(model_used or "", "")
            except Exception:  # noqa: BLE001 - a missing digest must never cost an answer
                _digest = ""
            event_log.append_event(
                stage="chat", session=session_id,
                input={"message": message, "message_sha": event_log.sha(message),
                       # NOT prompt_rendered. The conversation engine assembles its system
                       # prompt at six separate call sites, so the exact string sent is not
                       # reachable from here; the only honest choke point is generate_json,
                       # and stashing it there would race across concurrent sessions. Named
                       # message_sha so it can never be mistaken for the rendered prompt the
                       # `say` rows really do carry. KNOWN GAP, 2026-09-04.
                       "prompt_rendered": None,
                       "picture_summary": str(payload.get("picture_summary") or "").strip(),
                       "where": str(payload.get("where") or "").strip(),
                       "turn_count": engine.state.turn_count},
                model={"route": model_used, "digest": _digest,
                       "cloud": model_router.is_cloud(model_used or ""),
                       "forced": bool(forced), "forced_name": forced_name or None},
                outcome={"ok": True, "ms": int((time.monotonic() - _turn_started) * 1000),
                         "error": None, "path": "conversation"},
                result={"reply": response, "steering_stable": engine.is_stable,
                        "brief_extracted": "brief" in result},
                origin={"message": "human", "reply": model_used},
            )
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
        _note_reference(session_dir, payload.get("reference"), message)

        # a check asked for mid-build is a station rule too (the kit, 2026-09-03) —
        # it takes effect the next time that picture is rendered
        rule = stations.parse_rule(message)
        if rule:
            stations.add_rule(session_dir, rule)
            _log.info(f"  STATION RULE {session_id[:8]} (mid-build): {rule['material']} x{rule['count']}")
            return {
                "session_id": session_id,
                "message": stations.rule_sentence(rule, already_rendered=(session_dir / "artifacts" / "canon.png").exists()),
                "command": "station-rule",
                "rule": rule,
            }

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

        # Use Ollama for game design conversation — the router's choice (cloud first,
        # by the house law), not a hard-coded local model sharing the card with the
        # painters. (2026-09-03, Phase 1: was hard-coded to llama3.1:latest.)
        model_used = await model_router.pick("talk")
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
                    json={"model": model_used, "prompt": ollama_prompt, "stream": False,
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

        return {"message": response, "turn": len(game_history) // 2, "model_used": model_used}

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
        selected_picker = None
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
                selected_picker = json.loads(
                    (session_dir / "artifacts" / "object_picker.json").read_text(
                        encoding="utf-8"
                    )
                )
                resolve_plan_selected_objects(
                    selected_detected, selected_picker, selected_ids
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

        if selected_detected is not None and selected_picker is not None:
            decision_payload = decision.to_dict()
            approval_evidence_sha256 = hashlib.sha256(
                json.dumps(
                    decision_payload, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            selected_manifest = build_plan_bound_selected_manifest(
                selected_detected,
                selected_picker,
                selected_ids,
                plan_revision=revision,
                approval_revision=int(getattr(decision, "approval_revision", 1)),
                approval_evidence_sha256=approval_evidence_sha256,
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
                            "session_id": session_id,
                            "current_stage": result.stage,
                            "state": "awaiting_approval",
                            "plan_revision": orchestrator.current_plan_revision,
                            "canonical_hash": result.canonical_hash,
                            "finality": "provisional",
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

        # Prefer object_picker.json: it carries the per-detection `required` flag
        # and `plan_binding_id` the blockout UI needs to select only detections
        # that map to a required Plan placement (avoids sending unbindable IDs
        # that the approval endpoint rejects with 409). Fall back to the raw
        # detected_objects.json only if the picker artifact is absent.
        artifacts_dir = session_dir / "artifacts"
        detected_path = artifacts_dir / "detected_objects.json"
        picker_path = artifacts_dir / "object_picker.json"

        data = None
        for path in (picker_path, detected_path):
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

    @router.get("/api/session/{session_id}/plan_preview")
    async def unified_plan_preview(session_id: str):
        """Provisional room geometry from the validated Plan, BEFORE any mesh exists.

        /scene_graph deliberately returns nothing until world_contract.json and
        scene_graph.json are both on disk - the seventeenth stage. That left the
        V17 right-hand panel empty for almost the whole run, even though the Plan
        has known the room dimensions, the walls, the openings and every object's
        metric placement since spatial_reconstruction, eight stages earlier.

        This is additive and explicitly PROVISIONAL. It never touches the
        hash-bound contract projection: /scene_graph stays the single source of
        finalized truth, and everything here is labelled provisional so nothing
        downstream can mistake a placeholder for a delivered mesh.
        """
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)

        solution_path = session_dir / "artifacts" / "spatial_solution.json"
        if not solution_path.is_file():
            # Not an error: the Plan simply does not exist yet.
            return {"provisional": True, "ready": False, "objects": []}

        try:
            solution = json.loads(solution_path.read_text(encoding="utf-8"))
            plan = solution.get("metric_plan") or {}
            dimensions = plan.get("room_dimensions") or solution.get("room_dimensions_m")
            if not dimensions or len(dimensions) < 3:
                return {"provisional": True, "ready": False, "objects": []}
            width, depth, ceiling = (float(value) for value in dimensions[:3])

            objects = []
            for placement in plan.get("object_placements", []):
                objects.append({
                    "objectId": placement.get("id", ""),
                    "name": placement.get("name", ""),
                    "x": float(placement.get("x", 0.0)),
                    "y": float(placement.get("y", 0.0)),
                    "rotationDeg": float(placement.get("rotation_deg", 0)),
                    "width": float(placement.get("width", 0.5)),
                    "depth": float(placement.get("depth", 0.5)),
                    "height": float(placement.get("height", 0.8)),
                    "isArchitectural": bool(placement.get("is_architectural", False)),
                })

            # Standing rule: every room carries nine cameras. Derived from the
            # room's own dimensions, so this needs no per-room authoring and
            # cannot drift out of sync with the Plan.
            from src.unified_pipeline.camera_rig import rig_payload

            centre = next(
                (o for o in objects if not o["isArchitectural"]
                 and abs(o["x"] - width / 2) < 0.6 and abs(o["y"] - depth / 2) < 0.6),
                None,
            )
            focus = (
                (centre["x"] - width / 2, centre["height"], centre["y"] - depth / 2)
                if centre else None
            )

            return {
                "provisional": True,
                "ready": True,
                "sessionId": session_id,
                "room": {"width": width, "depth": depth, "height": ceiling},
                "openings": plan.get("openings", []),
                "objects": objects,
                "cameraRig": rig_payload(width, depth, ceiling, focus),
                "planRevision": solution.get("plan_revision", 0),
                "state": _meta(session_dir).get("state", "unknown"),
            }
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return JSONResponse(
                {"provisional": True, "ready": False, "objects": [], "error": str(exc)},
                status_code=409,
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

    @router.get("/api/session/{session_id}/conversation")
    async def unified_conversation(session_id: str):
        """V17 Slice 1 (2026-09-02): everything a reload needs to put the chat
        back — the saved turns plus the session's real state — so the page never
        has to guess which lane it is in or sit on RESUMING forever."""
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        meta = _meta(session_dir)
        if meta.get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)

        def _turns(path: Path, key: str | None) -> list[dict]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return []
            items = raw.get(key, []) if key else raw
            return [
                {"role": str(t.get("role", "")), "content": str(t.get("content", ""))}
                for t in (items if isinstance(items, list) else []) if isinstance(t, dict)
            ]

        turns = _turns(_conversation_path(session_dir), "turns")
        game_turns = _turns(session_dir / "game_conversation.json", None)
        proposal: dict = {}
        model = None
        if any(t["role"] == "user" for t in turns):
            engine = _load_conversation(session_id, session_dir)
            if engine is not None:
                proposal = _proposal_view(engine, session_dir)
                model = getattr(engine, "_session_model", None) or engine._model  # noqa: SLF001
        if model is None:
            model = await model_router.pick("talk")  # what the next sentence will use
        # Slice 2a: a restart is not a crash. SessionManager.mark_failed_on_restart
        # stamps every unfinished session as error/server_restart at boot, which
        # the page then reported as a failed build. Say what actually happened.
        error = meta.get("error")
        restarted = "server_restart" in str(error or "")
        return {
            "session_id": session_id,
            "state": str(meta.get("state", "unknown")),
            "error": ("the Living Room was restarted while this build was running"
                      if restarted else error),
            "restarted": restarted,
            "pending_stage": meta.get("pending_stage") or meta.get("approval_stage"),
            "pipeline_attached": session_id in _orchestrators,
            "revisions": list(load_revisions(session_dir)),
            "turns": turns,
            "game_turns": game_turns,
            "model": model,
            **proposal,
        }

    @router.post("/api/session/{session_id}/retry")
    async def unified_retry(session_id: str):
        """V17 Slice 1 (2026-09-02): "Try again" after a failed stage.

        The orchestrator re-runs a FAILED checkpoint on its next run() — only
        COMPLETED checkpoints are skipped (orchestrator._run_unit) — so a retry
        is: clear the error state and run again from where it stopped. After a
        server restart the orchestrator is not attached; rebuild it from the
        brief on disk exactly as the first launch did.
        """
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        meta = _meta(session_dir)
        if meta.get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)
        state = str(meta.get("state", "unknown"))
        if state != "error":
            return JSONResponse(
                {"error": f"Nothing to retry — the session is {state}.", "state": state},
                status_code=409,
            )
        running = _tasks.get(session_id)
        if running is not None and not running.done():
            return JSONResponse({"error": "The build is still running."}, status_code=409)

        orchestrator = _orchestrators.get(session_id)
        if orchestrator is None:
            try:
                brief = json.loads(
                    (session_dir / "artifacts" / "brief.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError):
                return JSONResponse({"error": "No saved brief to retry from."}, status_code=409)
            _log.info("  RETRY (rebuild after restart) for %s", session_id[:8])
            _write_meta(session_dir, state="running", error=None,
                        retried_at=datetime.now(timezone.utc).isoformat())
            _launch_pipeline(session_id, session_dir, brief)
            return {"session_id": session_id, "state": "running", "mode": "rebuilt"}

        _log.info("  RETRY (resume) for %s", session_id[:8])
        _write_meta(session_dir, state="running", error=None,
                    retried_at=datetime.now(timezone.utc).isoformat())

        async def _retry_pipeline():
            try:
                result = await orchestrator.run()
                _log.info("  PIPELINE RESULT after retry: state=%s stage=%s", result.state, result.stage)
                if result.state == "awaiting_approval":
                    _write_meta(session_dir, state="awaiting_approval", pending_stage=result.stage)
                    _append_progress(session_dir, {
                        "session_id": session_id,
                        "current_stage": result.stage,
                        "state": "awaiting_approval",
                        "plan_revision": orchestrator.current_plan_revision,
                        "canonical_hash": result.canonical_hash,
                        "finality": "provisional",
                        "message": f"Waiting for approval on {result.stage.replace('_', ' ')}",
                    })
                elif result.state == "completed":
                    _write_meta(session_dir, state="completed")
                elif result.state == "awaiting_external":
                    _write_meta(session_dir, state="awaiting_external", pending_stage=result.stage)
                else:
                    _write_meta(session_dir, state=result.state)
            except Exception as exc:
                _log.error("  PIPELINE ERROR after retry: %s\n%s", exc, traceback.format_exc()[-400:])
                _write_meta(session_dir, state="error", error=str(exc))

        _tasks[session_id] = asyncio.create_task(_retry_pipeline())
        return {"session_id": session_id, "state": "running", "mode": "resumed"}

    @router.post("/api/session/{session_id}/revise")
    async def unified_revise(session_id: str, request: Request):
        """V17 Slice 2a (2026-09-02): "Something's wrong" actually changes the picture.

        Rejecting a picture used to record an opinion and nothing else: the
        approval was stored as not-approved with the reason as a diagnostic, the
        stage stayed parked, and the same image sat there (orchestrator
        _approval_checkpoint). John's only real options were approve it or start
        over. Now the reason is appended to the durable revision list that both
        prompt composers read, the picture stage and everything after it are
        archived (never overwritten) with a fresh Plan revision, and the pipeline
        re-runs — so a correction produces a different picture.
        """
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)
        try:
            payload = await request.json()
            reason = " ".join(str((payload or {}).get("reason", "")).split())[:300]
        except Exception:
            reason = ""
        if not reason:
            return JSONResponse(
                {"error": "Say what's wrong — that sentence is what gets rendered next."},
                status_code=400,
            )
        stage = str((payload or {}).get("stage", "canon_generation"))
        return await _revise(session_id, session_dir, reason, stage)

    async def _revise(session_id: str, session_dir, reason: str, stage: str, record: bool = True):
        """The revise body, shared with the garage wall's "none of these" (2026-09-03).

        record=False re-renders without adding the reason to the durable revision
        list — "none of these" is a re-roll, not a correction the prompt should carry.
        """
        _log = logging.getLogger("live_trace")
        if stage not in {"canon_generation", "dream_preview"}:
            return JSONResponse({"error": f"Cannot revise {stage}"}, status_code=400)
        orchestrator = _orchestrators.get(session_id)
        if orchestrator is None:
            return JSONResponse(
                {"error": "This build is not attached any more — press Try again first."},
                status_code=409,
            )
        running = _tasks.get(session_id)
        if running is not None and not running.done():
            return JSONResponse({"error": "The build is still running."}, status_code=409)

        # Durable, append-only: John's taste is an asset, and a re-render must be
        # able to see every correction, not just the newest one.
        artifacts = session_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        revisions_path = artifacts / "revisions.json"
        try:
            document = json.loads(revisions_path.read_text(encoding="utf-8"))
            if not isinstance(document, dict) or not isinstance(document.get("revisions"), list):
                raise ValueError
        except (OSError, ValueError, TypeError):
            document = {"revisions": []}
        if record:
            document["revisions"].append({
                "reason": reason,
                "stage": stage,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
            temporary = revisions_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
            temporary.replace(revisions_path)
        _log.info("  REVISE %s (%s%s): %s", session_id[:8], stage, "" if record else ", re-roll", reason[:80])

        try:
            await orchestrator.invalidate_from(
                stage,
                reason=f"John: {reason}",
                new_plan_revision=orchestrator.current_plan_revision + 1,
            )
        except (KeyError, ValueError, RuntimeError, OSError) as exc:
            return JSONResponse({"error": f"Could not reopen that stage: {exc}"}, status_code=409)

        _write_meta(session_dir, state="running", error=None,
                    revised_at=datetime.now(timezone.utc).isoformat())

        async def _rerun():
            try:
                result = await orchestrator.run()
                _log.info("  PIPELINE RESULT after revise: state=%s stage=%s", result.state, result.stage)
                if result.state == "awaiting_approval":
                    _write_meta(session_dir, state="awaiting_approval", pending_stage=result.stage)
                    _append_progress(session_dir, {
                        "session_id": session_id,
                        "current_stage": result.stage,
                        "state": "awaiting_approval",
                        "plan_revision": orchestrator.current_plan_revision,
                        "canonical_hash": result.canonical_hash,
                        "finality": "provisional",
                        "message": f"Waiting for approval on {result.stage.replace('_', ' ')}",
                    })
                elif result.state == "completed":
                    _write_meta(session_dir, state="completed")
                elif result.state == "awaiting_external":
                    _write_meta(session_dir, state="awaiting_external", pending_stage=result.stage)
                else:
                    _write_meta(session_dir, state=result.state)
            except Exception as exc:
                _log.error("  PIPELINE ERROR after revise: %s\n%s", exc, traceback.format_exc()[-400:])
                _write_meta(session_dir, state="error", error=str(exc))

        _tasks[session_id] = asyncio.create_task(_rerun())
        return {
            "session_id": session_id,
            "state": "running",
            "revisions": [item["reason"] for item in document["revisions"]],
        }

    @router.get("/api/session/{session_id}/wall")
    async def unified_wall(session_id: str):
        """The garage wall for this session (the station kit, 2026-09-03).

        The page polls this while the pipeline waits at the picture gate. It says
        which wall is up, and — the moment the board holds John's answer — applies
        it, once:
          choose → the picture he clicked becomes canon.png, the picture gate is
                   approved in his name, the build continues;
          more   → (John: "#2 while in the background working on #1") three new
                   ones start rendering with the same words right away, and the
                   page asks what should change — a fix he types re-renders again.
        """
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)
        wall = stations.open_wall(session_dir)
        if not wall:
            last = (stations.load(session_dir)["walls"] or [None])[-1]
            return {"session_id": session_id, "wall": None, "last": last}
        try:
            answer = await stations.wall_answer(wall["id"])
        except Exception as exc:
            return {"session_id": session_id, "wall": wall, "answer": None, "board": f"unreachable: {exc}"}
        if not answer:
            return {"session_id": session_id, "wall": wall, "answer": None}

        running = _tasks.get(session_id)
        if running is not None and not running.done():
            return {"session_id": session_id, "wall": wall, "answer": answer, "applied": False, "why": "the build is still running"}
        orchestrator = _orchestrators.get(session_id)
        if orchestrator is None:
            return JSONResponse({"error": "This build is not attached any more — press Try again first."}, status_code=409)

        if answer.get("action") == "choose":
            try:
                stations.apply_choice(session_dir, wall, str(answer.get("tag")))
            except (ValueError, OSError) as exc:
                return JSONResponse({"error": f"Could not use that picture: {exc}"}, status_code=409)
            stations.mark_applied(session_dir, wall["id"], answer)
            try:
                with orchestrator.approval_writer("garage-wall") as writer_token:
                    decision = orchestrator.record_approval(
                        stage="canon_approval", writer_id="garage-wall", writer_token=writer_token,
                        plan_revision=orchestrator.current_plan_revision, approved=True, object_id=None,
                        feedback=f"chosen on the garage wall: {answer.get('tag')}",
                    )
            except (ValueError, RuntimeError, KeyError, TypeError, OSError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)
            _log.info("  WALL %s: chose %s → canon.png, picture gate approved, resuming", session_id[:8], answer.get("tag"))

            async def _resume_after_wall():
                try:
                    result = await orchestrator.run()
                    _log.info("  PIPELINE RESULT after wall: state=%s stage=%s", result.state, result.stage)
                    if result.state == "awaiting_approval":
                        _write_meta(session_dir, state="awaiting_approval", pending_stage=result.stage)
                        _append_progress(session_dir, {
                            "session_id": session_id, "current_stage": result.stage, "state": "awaiting_approval",
                            "plan_revision": orchestrator.current_plan_revision, "canonical_hash": result.canonical_hash,
                            "finality": "provisional", "message": f"Waiting for approval on {result.stage.replace('_', ' ')}",
                        })
                    elif result.state == "completed":
                        _write_meta(session_dir, state="completed")
                    elif result.state == "awaiting_external":
                        _write_meta(session_dir, state="awaiting_external", pending_stage=result.stage)
                    else:
                        _write_meta(session_dir, state=result.state)
                except Exception as exc:
                    _log.error("  PIPELINE ERROR after wall: %s\n%s", exc, traceback.format_exc()[-400:])
                    _write_meta(session_dir, state="error", error=str(exc))

            _tasks[session_id] = asyncio.create_task(_resume_after_wall())
            _write_meta(session_dir, state="running")
            return {"session_id": session_id, "wall": wall, "answer": answer, "applied": True, "action": "choose", "decision": decision.to_dict()}

        # "more": new ones now, same words; the page asks what should change
        stations.mark_applied(session_dir, wall["id"], answer)
        _log.info("  WALL %s: none of these — rendering new ones, asking what should change", session_id[:8])
        out = await _revise(session_id, session_dir, "none of these — new ones", "canon_generation", record=False)
        if isinstance(out, JSONResponse):
            return out
        return {"session_id": session_id, "wall": wall, "answer": answer, "applied": True, "action": "more", "ask_fix": True}

    @router.post("/api/session/{session_id}/note")
    async def unified_note(session_id: str, request: Request):
        """V17 Slice 2a (2026-09-02): a note to Claude, from inside the app.

        John asked whether the chat box could be a direct line to Claude so he
        could improve V17 without leaving V17. A live agent inside the page would
        mix two jobs in one box, bill API rates, and die with the server it just
        edited — so instead, a message that starts with @claude is filed here,
        into a file Claude reads at the start of a session. Same one box, no
        second input, no spend, and the note carries what was on screen when it
        was written.
        """
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        try:
            payload = await request.json()
            text = " ".join(str((payload or {}).get("text", "")).split())[:1000]
        except Exception:
            text = ""
        if not text:
            return JSONResponse({"error": "The note was empty."}, status_code=400)
        context = " ".join(str((payload or {}).get("context", "")).split())[:200]
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        line = (
            f"- [ ] **{stamp}** — {text}\n"
            f"      _session {session_id[:8]}"
            f"{', on screen: ' + context if context else ''}_\n"
        )
        notes_path = Path(__file__).resolve().parents[2] / "NOTES-FOR-CLAUDE.md"
        try:
            if not notes_path.exists():
                notes_path.write_text(
                    "# Notes for Claude — written from inside V17\n\n"
                    "John types `@claude ...` in the V17 chat and the line lands here.\n"
                    "Claude reads this at the start of a session and ticks items off.\n\n",
                    encoding="utf-8",
                )
            with notes_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError as exc:
            return JSONResponse({"error": f"Could not save the note: {exc}"}, status_code=500)
        _log.info("  NOTE for Claude [%s]: %s", session_id[:8], text[:80])
        return {"ok": True, "saved_to": str(notes_path), "note": text}

    @router.post("/api/session/{session_id}/reference")
    async def unified_reference(session_id: str, request: Request):
        """A reference picture, pasted or dropped into the chat box (2026-09-03).

        The bytes are kept exactly as they came (PNG or JPEG) under
        artifacts/references/<n>.<ext>; the sentence John types next becomes
        the picture's note through /message or /game_message.
        """
        _log = logging.getLogger("live_trace")
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if _meta(session_dir).get("interface_version") != INTERFACE_VERSION:
            return JSONResponse({"error": "Unified session not found"}, status_code=404)
        try:
            payload = await request.json()
            image = str((payload or {}).get("image", "")).strip()
            name = " ".join(str((payload or {}).get("name", "")).split())[:200]
        except Exception:
            return JSONResponse({"error": "invalid request"}, status_code=400)
        if image.startswith("data:"):
            image = image.split(",", 1)[1] if "," in image else ""
        if not image:
            return JSONResponse({"error": "image is required"}, status_code=400)
        if len(image) > _REFERENCE_MAX_BYTES * 4 // 3 + 4:
            return JSONResponse({"error": "That picture is over 12 MB."}, status_code=413)
        try:
            raw = base64.b64decode(image)
        except (binascii.Error, ValueError):
            return JSONResponse({"error": "The picture data was not valid base64."}, status_code=400)
        if len(raw) > _REFERENCE_MAX_BYTES:
            return JSONResponse({"error": "That picture is over 12 MB."}, status_code=413)
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            suffix = ".png"
        elif raw.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        else:
            return JSONResponse({"error": "PNG or JPEG pictures only."}, status_code=400)

        folder = session_dir / "artifacts" / "references"
        folder.mkdir(parents=True, exist_ok=True)
        document = _references(session_dir)
        records = document["references"]
        n = max([int(r.get("id", 0)) for r in records if isinstance(r, dict)] + [0]) + 1
        while (folder / f"{n}.png").exists() or (folder / f"{n}.jpg").exists():
            n += 1
        target = folder / f"{n}{suffix}"
        try:
            with target.open("xb") as handle:   # create-only: never overwrite a picture
                handle.write(raw)
            records.append({
                "id": n,
                "file": str(target),
                "name": name,
                "added_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "note": "",
            })
            _write_references(session_dir, document)
        except OSError as exc:
            return JSONResponse({"error": f"Could not save the picture: {exc}"}, status_code=500)
        _log.info("  REFERENCE #%s [%s]: %s bytes %s", n, session_id[:8], len(raw), suffix)
        return {"id": n, "url": f"/api/session/{session_id}/reference/{n}", "count": len(records)}

    @router.get("/api/session/{session_id}/reference/{n}")
    async def unified_reference_file(session_id: str, n: int):
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        folder = session_dir / "artifacts" / "references"
        for suffix, media_type in ((".png", "image/png"), (".jpg", "image/jpeg")):
            target = folder / f"{n}{suffix}"
            if target.is_file():
                return FileResponse(str(target), media_type=media_type, headers={"Cache-Control": "no-store"})
        return JSONResponse({"error": "Reference picture not found"}, status_code=404)

    @router.get("/api/session/{session_id}/references")
    async def unified_references(session_id: str):
        try:
            session_dir = _session_dir(output_root(), session_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return _references(session_dir)

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

        return FileResponse(
            str(target),
            media_type=media_type,
            headers={
                "Cache-Control": "no-store",
                "Permissions-Policy": WORLD_PERMISSIONS_POLICY,
            },
        )

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

        return FileResponse(
            str(index_file),
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Permissions-Policy": WORLD_PERMISSIONS_POLICY,
            },
        )

    return router
