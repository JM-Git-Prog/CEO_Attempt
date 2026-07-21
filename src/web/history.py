"""Read-only access to persisted V8/V9 history evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

STAGES = ("brief", "plan", "blockout", "canon", "world", "compare")
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_REVISIONED = {
    "plan": ("floor_plan_v", ".json"),
    "blockout": ("blockout_v", ".png"),
    "canon": ("canon_v", ".png"),
    "compare": ("world_render_v", ".png"),
}
_MEDIA_TYPES = {
    "plan": "image/svg+xml",
    "blockout": "image/png",
    "canon": "image/png",
    "compare": "image/png",
}
_PATH_KEYS = {"path", "paths", "output_path", "workflow_records", "generation_manifests"}


class ArtifactVerificationError(ValueError):
    """A persisted artifact differs from its recorded workflow digest."""


def _session_id(value: Any) -> str:
    value = str(value)
    if not _SESSION_ID.fullmatch(value):
        raise ValueError("Invalid session_id")
    return value


def _stage(value: Any) -> str:
    value = str(value).lower()
    if value not in STAGES:
        raise ValueError(f"Invalid stage; expected one of: {', '.join(STAGES)}")
    return value


def _revision(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not re.fullmatch(r"(?:0|[1-9][0-9]*)", str(value)):
        raise ValueError("revision must be a non-negative integer")
    return int(value)


def _inside(base: Path, path: Path, *, must_exist: bool = True) -> Path:
    base = base.resolve()
    path = path.resolve(strict=must_exist)
    if not path.is_relative_to(base):
        raise ValueError("Path escapes the session directory")
    return path


def _session_dir(output_dir: str | Path, session_id: Any) -> Path:
    root = Path(output_dir).resolve()
    directory = _inside(root, root / _session_id(session_id), must_exist=False)
    if not directory.is_dir() or not (directory / "session.json").is_file():
        raise FileNotFoundError("Session not found")
    return directory


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid persisted JSON: {path.name}") from exc


def _session(output_dir: str | Path, session_id: Any) -> tuple[Path, dict]:
    directory = _session_dir(output_dir, session_id)
    payload = _load_json(_inside(directory, directory / "session.json"))
    if not isinstance(payload, dict) or payload.get("session_id") != directory.name:
        raise ValueError("Persisted session identity is invalid")
    return directory, payload


def _numbers(directory: Path, prefix: str, suffix: str) -> list[int]:
    found: list[int] = []
    pattern = re.compile(rf"^{re.escape(prefix)}([1-9][0-9]*){re.escape(suffix)}$")
    for path in directory.iterdir():
        match = pattern.fullmatch(path.name) if path.is_file() else None
        if match and _inside(directory, path).is_file():
            found.append(int(match.group(1)))
    return sorted(set(found))


def _snapshots(directory: Path) -> list[dict]:
    workflow = directory / "workflow"
    if not workflow.is_dir():
        return []
    documents: list[dict] = []
    for path in sorted(workflow.glob("snapshot_*.json"), reverse=True):
        try:
            document = _load_json(_inside(directory, path))
        except ValueError:
            continue
        if isinstance(document, dict) and document.get("session_id") == directory.name:
            document["_snapshot_name"] = path.name
            documents.append(document)
    return documents


def _world_revisions(directory: Path, session: dict) -> list[int]:
    revisions = set(_numbers(directory, "scene_graph_v", ".json"))
    if session.get("scene_graph") is not None:
        revisions.add(int(session.get("world_revision") or 0))
    for snapshot in _snapshots(directory):
        state = snapshot.get("session") or {}
        if isinstance(state, dict) and state.get("scene_graph") is not None:
            revisions.add(int(state.get("world_revision") or 0))
    return sorted(revisions)


def _compare_revisions(directory: Path, session: dict) -> list[int]:
    revisions = set(_numbers(directory, "world_render_v", ".png"))
    history = session.get("revision_history") or []
    revisions.update(
        int(item["revision"])
        for item in history
        if isinstance(item, dict) and str(item.get("revision", "")).isdigit()
        and int(item["revision"]) > 0
    )
    return sorted(revisions)


def _stage_revisions(directory: Path, session: dict, stage: str) -> list[int]:
    if stage == "brief":
        return [1] if session.get("scene_concept") is not None else []
    if stage == "world":
        return _world_revisions(directory, session)
    if stage == "compare":
        return _compare_revisions(directory, session)
    prefix, suffix = _REVISIONED[stage]
    revisions = _numbers(directory, prefix, suffix)
    if stage == "plan":
        revisions = sorted(set(revisions) | set(_numbers(directory, prefix, ".svg")))
    return revisions


def list_sessions(output_dir: str | Path, *, version_filter: int | None = None) -> dict:
    """List persisted sessions grouped by their recorded interface version."""
    root = Path(output_dir).resolve()
    groups: dict[str, list[dict]] = {}
    if not root.is_dir():
        return {"interface_versions": groups, "total": 0}
    for session_file in root.glob("*/session.json"):
        try:
            directory = _inside(root, session_file.parent)
            session = _load_json(_inside(directory, session_file))
            session_id = _session_id(session.get("session_id"))
            if session_id != directory.name:
                continue
            version = str(int(session["interface_version"]))
        except (KeyError, TypeError, ValueError, OSError):
            continue
        # When a version filter is provided, only include sessions for that
        # version (and allow older sessions to be visible too for history).
        if version_filter is not None and int(version) > version_filter:
            continue
        groups.setdefault(version, []).append({
            "session_id": session_id,
            "state": session.get("state"),
            "interface_version": int(version),
            "workflow_profile_id": session.get("workflow_profile_id") or None,
        })
    for sessions in groups.values():
        sessions.sort(key=lambda item: item["session_id"])
    ordered = dict(sorted(groups.items(), key=lambda item: int(item[0]), reverse=True))
    return {"interface_versions": ordered, "sessions": [item for group in ordered.values() for item in group], "total": sum(map(len, ordered.values()))}


def get_session_stages(output_dir: str | Path, session_id: str) -> dict:
    """Describe stage availability and persisted revision numbers."""
    directory, session = _session(output_dir, session_id)
    stages = {}
    for stage in STAGES:
        revisions = _stage_revisions(directory, session, stage)
        stages[stage] = {"available": bool(revisions), "revisions": revisions}
    return {
        "session_id": directory.name,
        "interface_version": session.get("interface_version"),
        "stages": stages,
    }


def _looks_absolute_path(value: str) -> bool:
    return bool(re.match(r"^(?:[A-Za-z]:[\\/]|/|\\\\)", value))


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _PATH_KEYS or lowered.endswith(("_path", "_paths")):
                continue
            clean[str(key)] = _sanitize(item)
        return clean
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str) and _looks_absolute_path(value):
        return "[redacted]"
    return value


def _select_revision(revisions: list[int], revision: Any) -> int:
    requested = _revision(revision)
    if not revisions:
        raise FileNotFoundError("Stage is not available")
    selected = max(revisions) if requested is None else requested
    if selected not in revisions:
        raise FileNotFoundError("Stage revision not found")
    return selected


def _world_context(directory: Path, session: dict, revision: int) -> dict:
    candidate = directory / f"scene_graph_v{revision}.json"
    if revision > 0 and candidate.is_file():
        return {
            "revision": revision,
            "scene_graph": _load_json(_inside(directory, candidate)),
            "camera_contract": session.get("camera_contract"),
        }
    states = [session, *[(item.get("session") or {}) for item in _snapshots(directory)]]
    for state in states:
        if (isinstance(state, dict) and state.get("scene_graph") is not None
                and int(state.get("world_revision") or 0) == revision):
            return {
                "revision": revision,
                "scene_graph": state["scene_graph"],
                "camera_contract": state.get("camera_contract") or session.get("camera_contract"),
            }
    raise FileNotFoundError("World revision not found")


def _canon_context(directory: Path, session: dict, revision: int) -> dict:
    manifests = []
    workflow = directory / "workflow"
    if workflow.is_dir():
        for path in sorted(workflow.glob(f"canon_v{revision}_*.json")):
            document = _load_json(_inside(directory, path))
            if isinstance(document, dict):
                manifests.append(document)
    return {
        "attempt": revision,
        "concept": session.get("scene_concept"),
        "provider": session.get("canon_provider"),
        "camera_contract": session.get("camera_contract"),
        "camera_alignment": session.get("canon_alignment"),
        "generation": manifests,
    }


def _artifact_url(
    session_id: str, stage: str, revision: int, interface_version: int
) -> str:
    query = urlencode({"revision": revision})
    api_version = 9 if interface_version >= 9 else 8
    return f"/api/v{api_version}/session/{session_id}/stage/{stage}/artifact?{query}"


def get_stage_evidence(
    output_dir: str | Path, session_id: str, stage: str, revision: int | str | None = None
) -> dict:
    """Return sanitized JSON evidence and an opaque URL for any file artifact."""
    directory, session = _session(output_dir, session_id)
    stage = _stage(stage)
    selected = _select_revision(_stage_revisions(directory, session, stage), revision)
    interface_version = int(session.get("interface_version") or 8)
    artifact_url: str | None = None
    if stage == "brief":
        context = {
            "revision": selected,
            "user_description": session.get("user_description", ""),
            "concept": session.get("scene_concept"),
        }
    elif stage == "plan":
        path = directory / f"floor_plan_v{selected}.json"
        context = {
            "revision": selected,
            "floor_plan": _load_json(_inside(directory, path)),
            "camera_contract": session.get("camera_contract"),
        }
        if (directory / f"floor_plan_v{selected}.svg").is_file():
            artifact_url = _artifact_url(directory.name, stage, selected, interface_version)
    elif stage == "blockout":
        context = {
            "revision": selected,
            "plan_revision": selected,
            "camera_contract": session.get("camera_contract"),
        }
        artifact_url = _artifact_url(directory.name, stage, selected, interface_version)
    elif stage == "canon":
        context = _canon_context(directory, session, selected)
        artifact_url = _artifact_url(directory.name, stage, selected, interface_version)
    elif stage == "world":
        context = _world_context(directory, session, selected)
    else:
        history = session.get("revision_history") or []
        matches = [item for item in history if isinstance(item, dict) and item.get("revision") == selected]
        context = {"revision": selected, "revision_history": matches}
        if (directory / f"world_render_v{selected}.png").is_file():
            artifact_url = _artifact_url(directory.name, stage, selected, interface_version)
    return {
        "session_id": directory.name,
        "stage": stage,
        "revision": selected,
        "context": _sanitize(context),
        "artifact_url": artifact_url,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _recorded_digest(directory: Path, artifact: Path) -> tuple[str, str] | None:
    relative = artifact.relative_to(directory).as_posix()
    endings = {relative, f"{directory.name}/{relative}"}
    for snapshot in _snapshots(directory):
        records = snapshot.get("artifacts") or []
        for record in records:
            if not isinstance(record, dict) or not record.get("sha256"):
                continue
            recorded = str(record.get("path", "")).replace("\\", "/").rstrip("/")
            if any(recorded == ending or recorded.endswith(f"/{ending}") for ending in endings):
                return str(record["sha256"]).lower(), str(snapshot["_snapshot_name"])
    return None


def resolve_verified_artifact(
    output_dir: str | Path, session_id: str, stage: str, revision: int | str | None = None
) -> tuple[Path, str, dict]:
    """Resolve an artifact and verify it against immutable workflow evidence."""
    directory, session = _session(output_dir, session_id)
    stage = _stage(stage)
    if stage not in _MEDIA_TYPES:
        raise FileNotFoundError(f"Stage {stage} has embedded evidence, not a file artifact")
    selected = _select_revision(_stage_revisions(directory, session, stage), revision)
    if stage == "plan":
        candidate = directory / f"floor_plan_v{selected}.svg"
    elif stage == "compare":
        candidate = directory / f"world_render_v{selected}.png"
    else:
        prefix, suffix = _REVISIONED[stage]
        candidate = directory / f"{prefix}{selected}{suffix}"
    if not candidate.is_file():
        raise FileNotFoundError("Artifact not found")
    candidate = _inside(directory, candidate)
    actual = _sha256(candidate)
    recorded = _recorded_digest(directory, candidate)
    if recorded:
        expected, snapshot = recorded
        if actual.lower() != expected:
            raise ArtifactVerificationError("Artifact SHA-256 does not match workflow snapshot")
        verification = {
            "verified": True,
            "sha256": actual,
            "recorded_sha256": expected,
            "source": snapshot,
            "warning": None,
        }
    else:
        verification = {
            "verified": False,
            "sha256": actual,
            "recorded_sha256": None,
            "source": None,
            "warning": "Legacy artifact has no recorded workflow SHA-256; integrity is unverified.",
        }
    return candidate, _MEDIA_TYPES[stage], verification
