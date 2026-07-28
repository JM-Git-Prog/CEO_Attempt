"""Fail-open, content-free telemetry for V8+ pipeline work."""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Iterator

TELEMETRY_SCHEMA_VERSION = 1
_MIN_ETA_SAMPLES = 3
_DEFAULT_HEARTBEAT_SECONDS = 2.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: object, fallback: str = "unknown") -> str:
    text = str(value or fallback)
    cleaned = "".join(char for char in text if char.isalnum() or char in "-_.@")
    return (cleaned or fallback)[:128]


def _confidence(sample_count: int) -> str:
    if sample_count < _MIN_ETA_SAMPLES:
        return "collecting"
    if sample_count < 5:
        return "low"
    if sample_count < 10:
        return "medium"
    return "high"


def _sanitized_event(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    event = {
        "event": _safe_name(payload.get("event")),
        "status": _safe_name(payload.get("status")),
        "stage": _safe_name(payload.get("stage")),
        "substep": _safe_name(payload.get("substep")),
        "timestamp": str(payload.get("timestamp", ""))[:64],
    }
    try:
        event["monotonic_elapsed_seconds"] = max(
            0.0, round(float(payload.get("monotonic_elapsed_seconds", 0.0)), 3)
        )
    except (TypeError, ValueError):
        event["monotonic_elapsed_seconds"] = 0.0
    if payload.get("error_type"):
        event["error_type"] = _safe_name(payload["error_type"])
    for field in (
        "compilation_id", "target", "producing_adapter", "manifest_sha256",
        "parity_status", "runtime_status",
    ):
        if payload.get(field) is not None:
            event[field] = _safe_name(payload[field])
    roles = payload.get("artifact_roles")
    if isinstance(roles, list):
        event["artifact_roles"] = [_safe_name(role) for role in roles[:64]]
    if payload.get("artifact_count") is not None:
        try:
            event["artifact_count"] = max(0, int(payload["artifact_count"]))
        except (TypeError, ValueError):
            event["artifact_count"] = 0
    return event


class TelemetryRecorder:
    """Record V8+ pipeline activity without ever affecting pipeline control flow."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        interface_version: int,
        workflow_profile: dict | None,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        self.output_dir = Path(output_dir)
        try:
            self.enabled = int(interface_version) >= 8
        except (TypeError, ValueError):
            self.enabled = False
        profile = workflow_profile if isinstance(workflow_profile, dict) else {}
        self.workflow_profile_id = _safe_name(profile.get("id"))
        self.heartbeat_seconds = max(0.1, float(heartbeat_seconds))
        self.state_path = self.output_dir / "telemetry.json"
        self.events_path = self.output_dir / "telemetry_events.jsonl"
        self.samples_path = self.output_dir.parent / "telemetry" / "timing_samples.jsonl"
        self._lock = threading.RLock()
        self._active: dict | None = None
        self._heartbeat_stop: threading.Event | None = None
        self._heartbeat_thread: threading.Thread | None = None
        if self.enabled:
            self._guard(self._initialize)

    def _guard(self, operation, *args) -> None:
        try:
            operation(*args)
        except Exception:
            pass

    def _initialize(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.samples_path.parent.mkdir(parents=True, exist_ok=True)
        # Only write idle if no telemetry state exists yet; preserve terminal
        # states (completed/failed/idle) from previous pipeline runs.
        if not self.state_path.exists():
            self._write_state("idle", None, 0.0)

    @contextmanager
    def substep(self, stage: str, substep: str) -> Iterator[None]:
        """Measure one real operation; pipeline exceptions always pass through."""
        token = self.start(stage, substep)
        try:
            yield
        except BaseException as exc:
            self.fail(token, exc)
            raise
        else:
            self.complete(token)

    def start(self, stage: str, substep: str) -> dict | None:
        if not self.enabled:
            return None
        token = {
            "stage": _safe_name(stage),
            "substep": _safe_name(substep),
            "started_at": _utc_now(),
            "started_monotonic": time.monotonic(),
        }
        try:
            self._stop_heartbeat()
            with self._lock:
                self._active = token
                self._append_event("substep_started", "started", token, 0.0)
                self._write_state("active", token, 0.0)
            self._start_heartbeat()
        except Exception:
            pass
        return token

    def complete(self, token: dict | None) -> None:
        if not self.enabled or token is None:
            return
        try:
            self._stop_heartbeat()
            elapsed = max(0.0, time.monotonic() - token["started_monotonic"])
            with self._lock:
                self._append_event("substep_completed", "completed", token, elapsed)
                self._append_sample(token, elapsed)
                if self._active is token:
                    self._active = None
                self._write_state("completed", token, elapsed)
        except Exception:
            pass

    def fail(self, token: dict | None, error: BaseException) -> None:
        if not self.enabled or token is None:
            return
        try:
            self._stop_heartbeat()
            elapsed = max(0.0, time.monotonic() - token["started_monotonic"])
            with self._lock:
                self._append_event(
                    "substep_failed", "failed", token, elapsed, type(error).__name__
                )
                if self._active is token:
                    self._active = None
                self._write_state("failed", token, elapsed, type(error).__name__)
        except Exception:
            pass

    def update_substep(self, stage: str, elapsed_s: float) -> None:
        """Update telemetry state for MVP SSE progress without full substep lifecycle."""
        if not self.enabled:
            return
        try:
            token = {"stage": _safe_name(stage), "substep": _safe_name(stage),
                     "started_at": _utc_now(), "started_monotonic": time.monotonic() - elapsed_s}
            with self._lock:
                self._active = token
                self._write_state("active", token, elapsed_s)
        except Exception:
            pass

    def record_compiler_event(
        self,
        *,
        phase: str,
        compilation_id: str,
        target: str,
        status: str,
        manifest_sha256: str,
        producing_adapter: str | None = None,
        artifact_roles: tuple[str, ...] = (),
        parity_status: str | None = None,
        runtime_status: str | None = None,
    ) -> None:
        """Append content-free compiler provenance without affecting control flow."""
        if not self.enabled:
            return
        try:
            payload = {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "event": f"compiler_{_safe_name(phase)}",
                "status": _safe_name(status),
                "stage": "assemble",
                "substep": "compile_world_contract",
                "timestamp": _utc_now(),
                "monotonic_elapsed_seconds": 0.0,
                "compilation_id": _safe_name(compilation_id),
                "target": _safe_name(target),
                "producing_adapter": (
                    _safe_name(producing_adapter) if producing_adapter else None
                ),
                "manifest_sha256": _safe_name(manifest_sha256),
                "artifact_count": len(artifact_roles),
                "artifact_roles": [_safe_name(role) for role in artifact_roles],
                "parity_status": _safe_name(parity_status) if parity_status else None,
                "runtime_status": _safe_name(runtime_status) if runtime_status else None,
            }
            with self._lock:
                self._append_json_line(self.events_path, payload)
        except Exception:
            pass

    def _start_heartbeat(self) -> None:
        stop = threading.Event()
        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(stop,),
            name="pipeline-telemetry-heartbeat",
            daemon=True,
        )
        self._heartbeat_stop = stop
        self._heartbeat_thread = thread
        thread.start()

    def _stop_heartbeat(self) -> None:
        stop, thread = self._heartbeat_stop, self._heartbeat_thread
        self._heartbeat_stop = None
        self._heartbeat_thread = None
        if stop is not None:
            stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.heartbeat_seconds + 0.25)

    def _heartbeat_loop(self, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_seconds):
            try:
                with self._lock:
                    token = self._active
                    if token is None:
                        return
                    elapsed = max(0.0, time.monotonic() - token["started_monotonic"])
                    self._append_event("worker_heartbeat", "active", token, elapsed)
                    self._write_state("active", token, elapsed)
            except Exception:
                continue

    def _append_event(
        self,
        event: str,
        status: str,
        token: dict,
        elapsed: float,
        error_type: str | None = None,
    ) -> None:
        payload = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "event": event,
            "status": status,
            "stage": token["stage"],
            "substep": token["substep"],
            "timestamp": _utc_now(),
            "monotonic_elapsed_seconds": round(elapsed, 3),
        }
        if error_type:
            payload["error_type"] = _safe_name(error_type)
        self._append_json_line(self.events_path, payload)

    def _append_sample(self, token: dict, elapsed: float) -> None:
        self._append_json_line(
            self.samples_path,
            {
                "schema_version": TELEMETRY_SCHEMA_VERSION,
                "workflow_profile_id": self.workflow_profile_id,
                "stage": token["stage"],
                "substep": token["substep"],
                "completed_at": _utc_now(),
                "monotonic_elapsed_seconds": round(elapsed, 3),
            },
        )

    @staticmethod
    def _append_json_line(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()

    def _matching_durations(self, token: dict) -> list[float]:
        if not self.samples_path.exists():
            return []
        durations: list[float] = []
        with self.samples_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    sample = json.loads(line)
                    if (
                        sample.get("workflow_profile_id") == self.workflow_profile_id
                        and sample.get("stage") == token["stage"]
                        and sample.get("substep") == token["substep"]
                    ):
                        value = float(sample["monotonic_elapsed_seconds"])
                        if value >= 0.0:
                            durations.append(value)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return durations

    def _eta(self, token: dict | None, elapsed: float) -> dict:
        if token is None:
            return {
                "status": "inactive",
                "remaining_seconds": None,
                "sample_count": 0,
                "confidence": "collecting",
            }
        durations = self._matching_durations(token)
        sample_count = len(durations)
        if sample_count < _MIN_ETA_SAMPLES:
            return {
                "status": "collecting",
                "remaining_seconds": None,
                "sample_count": sample_count,
                "confidence": "collecting",
            }
        remaining = max(0.0, median(durations) - elapsed)
        return {
            "status": "estimated",
            "remaining_seconds": round(remaining, 1),
            "sample_count": sample_count,
            "confidence": _confidence(sample_count),
        }

    def _write_state(
        self,
        status: str,
        token: dict | None,
        elapsed: float,
        error_type: str | None = None,
    ) -> None:
        active = status == "active" and token is not None
        updated_at = _utc_now()
        eta = self._eta(token if active else None, elapsed)
        payload = {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "enabled": True,
            "workflow_profile_id": self.workflow_profile_id,
            "status": status,
            "stage": token["stage"] if token else None,
            "substep": token["substep"] if token else None,
            "current_substep": token["substep"] if token else None,
            "started_at": token["started_at"] if token else None,
            "updated_at": updated_at,
            "heartbeat_at": updated_at,
            "stale_after_seconds": round(max(6.0, self.heartbeat_seconds * 3), 1),
            "monotonic_elapsed_seconds": round(max(0.0, elapsed), 3),
            "elapsed_seconds": round(max(0.0, elapsed), 3),
            "heartbeat": {"status": "active", "updated_at": updated_at} if active else None,
            "eta": eta["remaining_seconds"],
            "eta_seconds": eta["remaining_seconds"],
            "eta_status": eta["status"],
            "sample_count": eta["sample_count"],
            "confidence": eta["confidence"],
        }
        if error_type:
            payload["error_type"] = _safe_name(error_type)
        temporary = self.state_path.with_name(
            f".{self.state_path.name}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8"
        )
        temporary.replace(self.state_path)


def read_telemetry(output_dir: str | Path) -> dict:
    """Return only the documented, content-free telemetry fields."""
    directory = Path(output_dir)
    state_path = directory / "telemetry.json"
    result = {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "enabled": False,
        "workflow_profile_id": None,
        "status": "unavailable",
        "stage": None,
        "substep": None,
        "current_substep": None,
        "started_at": None,
        "updated_at": None,
        "heartbeat_at": None,
        "heartbeat_age_seconds": None,
        "stale_after_seconds": 30.0,
        "stale": False,
        "monotonic_elapsed_seconds": 0.0,
        "elapsed_seconds": 0.0,
        "heartbeat": None,
        "eta": None,
        "eta_seconds": None,
        "eta_status": "inactive",
        "sample_count": 0,
        "confidence": "collecting",
        "events": [],
    }
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        elapsed = max(
            0.0, round(float(state.get("monotonic_elapsed_seconds", 0.0)), 3)
        )
        remaining = state.get("eta_seconds")
        remaining = max(0.0, round(float(remaining), 1)) if remaining is not None else None
        heartbeat_at = str(state.get("heartbeat_at", ""))[:64] or None
        stale_after = max(1.0, float(state.get("stale_after_seconds", 30.0)))
        heartbeat_age = None
        if heartbeat_at:
            heartbeat_age = max(
                0.0,
                round(
                    (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat_at)).total_seconds(),
                    1,
                ),
            )
        result.update(
            enabled=bool(state.get("enabled")),
            workflow_profile_id=_safe_name(state.get("workflow_profile_id")),
            status=_safe_name(state.get("status")),
            stage=_safe_name(state.get("stage")) if state.get("stage") else None,
            substep=_safe_name(state.get("substep")) if state.get("substep") else None,
            current_substep=(
                _safe_name(state.get("current_substep"))
                if state.get("current_substep")
                else None
            ),
            started_at=str(state.get("started_at", ""))[:64] or None,
            updated_at=str(state.get("updated_at", ""))[:64] or None,
            heartbeat_at=heartbeat_at,
            heartbeat_age_seconds=heartbeat_age,
            stale_after_seconds=round(stale_after, 1),
            stale=heartbeat_age is not None and heartbeat_age > stale_after,
            monotonic_elapsed_seconds=elapsed,
            elapsed_seconds=elapsed,
            eta=remaining,
            eta_seconds=remaining,
            eta_status=_safe_name(state.get("eta_status")),
            sample_count=max(0, int(state.get("sample_count", 0))),
            confidence=_safe_name(state.get("confidence")),
        )
        heartbeat = state.get("heartbeat")
        if isinstance(heartbeat, dict):
            result["heartbeat"] = {
                "status": _safe_name(heartbeat.get("status")),
                "updated_at": str(heartbeat.get("updated_at", ""))[:64],
            }
        if state.get("error_type"):
            result["error_type"] = _safe_name(state["error_type"])
    except Exception:
        return result

    try:
        events = []
        with (directory / "telemetry_events.jsonl").open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = _sanitized_event(json.loads(line))
                    if event:
                        events.append(event)
                except json.JSONDecodeError:
                    continue
        result["events"] = events[-100:]
    except Exception:
        pass
    return result
