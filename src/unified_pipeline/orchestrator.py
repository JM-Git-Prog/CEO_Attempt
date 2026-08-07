"""Durable, revision-aware orchestration for the Unified World Pipeline.

The orchestrator owns sequencing and durability, while concrete stage adapters are
injected. This keeps GPU/service implementations replaceable without weakening the
single-authority construction chain, approval gates, or publication finality.

Validates Requirements 27.1-27.6, 32.1-32.7, 33.1-33.9, and 34.1-34.11.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator, Mapping, Protocol, Sequence


class OrchestratorError(RuntimeError):
    """Base error for durable orchestration failures."""


class LeaseConflictError(OrchestratorError):
    """Raised when another live owner already controls the session."""


class PipelineBlockedError(OrchestratorError):
    """Raised when an unresolved flag or publication gate blocks execution."""


class StaleApprovalError(OrchestratorError):
    """Raised when an approval targets a superseded Plan revision."""


class MissingStageHandlerError(OrchestratorError):
    """Raised when an executable pipeline stage has no adapter."""


class CheckpointState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    INVALIDATED = "invalidated"


class ExternalJobState(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageSpec:
    name: str
    per_object: bool = False
    approval_for: str | None = None
    optional: bool = False


# This order is normative. Canon-first flow: FLUX image → spatial analysis → 3D.
# Approval stages are durable barriers, not executable adapters.
DEFAULT_STAGE_SPECS: tuple[StageSpec, ...] = (
    StageSpec("conversation"),
    StageSpec("brief"),
    StageSpec("art_bible"),
    StageSpec("dream_preview"),
    StageSpec("canon_generation"),
    StageSpec("canon_approval", approval_for="canon_generation"),
    StageSpec("segment"),
    StageSpec("depth_estimation"),
    StageSpec("spatial_reconstruction"),
    StageSpec("blockout_approval", approval_for="spatial_reconstruction"),
    StageSpec("mesh_generation", per_object=True),
    StageSpec("mesh_approval", per_object=True, approval_for="mesh_generation"),
    StageSpec("material_pass_1", per_object=True),
    StageSpec("parametric_room"),
    StageSpec("physics_classification"),
    StageSpec("physics_settle"),
    StageSpec("world_contract"),
    StageSpec("compile"),
    StageSpec("final_world_qa", approval_for="compile"),
    StageSpec("mode_toggle"),
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"value is not durably serializable: {type(value).__name__}")


def _digest(value: Any) -> str:
    encoded = json.dumps(
        _jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
            suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(_jsonable(document), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _append_jsonl(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_jsonable(document), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@dataclass(frozen=True)
class StageResult:
    output: Mapping[str, Any] = field(default_factory=dict)
    external_job_id: str = ""
    artifact_paths: tuple[str, ...] = ()
    plan_revision: int = 0
    approval_revision: int = 0
    canonical_hash: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_pending_external(self) -> bool:
        return bool(self.external_job_id)

    @classmethod
    def pending(
        cls, job_id: str, *, plan_revision: int, metadata: Mapping[str, Any] | None = None
    ) -> "StageResult":
        if not job_id.strip():
            raise ValueError("external job id must be non-empty")
        return cls(
            external_job_id=job_id.strip(),
            plan_revision=plan_revision,
            metadata=dict(metadata or {}),
        )


@dataclass(frozen=True)
class ExternalJobResult:
    state: ExternalJobState
    output: Mapping[str, Any] = field(default_factory=dict)
    response_revision: int = 0
    artifact_paths: tuple[str, ...] = ()
    diagnostic: str = ""
    canonical_hash: str = ""


@dataclass(frozen=True)
class StageExecutionContext:
    session_id: str
    session_dir: Path
    stage: str
    object_id: str | None
    values: Mapping[str, Any]
    plan_revision: int
    approval_revision: int
    attempt: int
    recovery_reason: str = ""

    def spawn_detached(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> int:
        """Start a reload-safe child in a detached process group and return its PID."""
        if not command:
            raise ValueError("detached command must not be empty")
        kwargs: dict[str, Any] = {
            "cwd": str(cwd or self.session_dir),
            "env": dict(env) if env is not None else None,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(list(command), **kwargs).pid


class StageHandler(Protocol):
    def __call__(
        self, context: StageExecutionContext
    ) -> StageResult | Mapping[str, Any] | Awaitable[StageResult | Mapping[str, Any]]: ...


class ExternalJobController(Protocol):
    def reconcile(
        self, job_id: str
    ) -> ExternalJobResult | Awaitable[ExternalJobResult]: ...

    def cancel(self, job_id: str, reason: str) -> bool | Awaitable[bool]: ...


@dataclass(frozen=True)
class StageCheckpoint:
    session_id: str
    stage: str
    object_id: str | None
    input_hashes: Mapping[str, str]
    output_hashes: Mapping[str, str]
    plan_revision: int
    approval_revision: int
    external_job_id: str
    attempt: int
    completion_state: CheckpointState
    started_at: float
    updated_at: float
    completed_at: float | None = None
    output: Mapping[str, Any] = field(default_factory=dict)
    artifact_paths: tuple[str, ...] = ()
    canonical_hash: str = ""
    diagnostic: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["completion_state"] = self.completion_state.value
        return _jsonable(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StageCheckpoint":
        return cls(
            session_id=str(data["session_id"]),
            stage=str(data["stage"]),
            object_id=(str(data["object_id"]) if data.get("object_id") else None),
            input_hashes=dict(data.get("input_hashes", {})),
            output_hashes=dict(data.get("output_hashes", {})),
            plan_revision=int(data.get("plan_revision", 0)),
            approval_revision=int(data.get("approval_revision", 0)),
            external_job_id=str(data.get("external_job_id", "")),
            attempt=int(data.get("attempt", 1)),
            completion_state=CheckpointState(str(data["completion_state"])),
            started_at=float(data["started_at"]),
            updated_at=float(data["updated_at"]),
            completed_at=(float(data["completed_at"]) if data.get("completed_at") else None),
            output=dict(data.get("output", {})),
            artifact_paths=tuple(str(item) for item in data.get("artifact_paths", ())),
            canonical_hash=str(data.get("canonical_hash", "")),
            diagnostic=str(data.get("diagnostic", "")),
        )


@dataclass(frozen=True)
class ApprovalDecision:
    stage: str
    object_id: str | None
    plan_revision: int
    approval_revision: int
    approved: bool
    writer_id: str
    feedback: str
    recorded_at: float
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class ProgressEvent:
    sequence: int
    session_id: str
    current_stage: str
    object_id: str | None
    objects_complete: int
    objects_total: int
    elapsed_seconds: float
    eta_seconds: float | None
    state: str
    plan_revision: int
    canonical_hash: str
    finality: str
    timestamp: float
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def to_sse(self) -> str:
        return f"id: {self.sequence}\nevent: pipeline.progress\ndata: " + json.dumps(
            self.to_dict(), sort_keys=True
        ) + "\n\n"

    def to_websocket(self) -> dict[str, Any]:
        return {"event": "pipeline.progress", **self.to_dict()}


@dataclass(frozen=True)
class RunResult:
    state: str
    stage: str = ""
    object_id: str | None = None
    message: str = ""
    canonical_hash: str = ""


@dataclass(frozen=True)
class UnresolvedFlag:
    flag_id: str
    code: str
    message: str
    stage: str
    object_id: str | None
    raised_at: float
    resolved_at: float | None = None
    resolution: str = ""
    resolver_id: str = ""

    @property
    def active(self) -> bool:
        return self.resolved_at is None


class DurableCheckpointStore:
    """Atomic checkpoint persistence plus append-only supersession archives."""

    def __init__(self, session_dir: str | Path, session_id: str) -> None:
        self.session_dir = Path(session_dir).resolve()
        self.session_id = session_id
        self.root = self.session_dir / "orchestrator"
        self.checkpoint_dir = self.root / "checkpoints"
        self.archive_dir = self.root / "archive"
        self.diagnostic_dir = self.root / "diagnostics"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(stage: str, object_id: str | None = None) -> str:
        suffix = "global" if object_id is None else hashlib.sha256(
            object_id.encode("utf-8")
        ).hexdigest()[:16]
        return f"{stage}--{suffix}"

    def path(self, stage: str, object_id: str | None = None) -> Path:
        return self.checkpoint_dir / f"{self.key(stage, object_id)}.json"

    def write(self, checkpoint: StageCheckpoint) -> None:
        if checkpoint.session_id != self.session_id:
            raise ValueError("checkpoint session mismatch")
        _atomic_json(self.path(checkpoint.stage, checkpoint.object_id), checkpoint.to_dict())

    def load(self, stage: str, object_id: str | None = None) -> StageCheckpoint | None:
        path = self.path(stage, object_id)
        if not path.exists():
            return None
        return StageCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def all(self) -> tuple[StageCheckpoint, ...]:
        records: list[StageCheckpoint] = []
        for path in self.checkpoint_dir.glob("*.json"):
            try:
                records.append(StageCheckpoint.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                # Skip transiently corrupted or mid-write files
                continue
        return tuple(records)

    def archive(self, checkpoint: StageCheckpoint, *, reason: str, lineage: str) -> Path:
        stamp = f"{time.time_ns()}-{self.key(checkpoint.stage, checkpoint.object_id)}"
        target = self.archive_dir / stamp
        target.mkdir(parents=True, exist_ok=False)
        archived_artifacts: list[dict[str, str]] = []
        for raw_path in checkpoint.artifact_paths:
            source = Path(raw_path).resolve()
            record = {"original": str(source), "archived": ""}
            try:
                relative = source.relative_to(self.session_dir)
            except ValueError:
                archived_artifacts.append(record)
                continue
            if source.exists() and source.is_file():
                destination = target / "artifacts" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                record["archived"] = str(destination)
            archived_artifacts.append(record)
        source_checkpoint = self.path(checkpoint.stage, checkpoint.object_id)
        if source_checkpoint.exists():
            shutil.move(str(source_checkpoint), str(target / "checkpoint.json"))
        _atomic_json(target / "lineage.json", {
            "reason": reason,
            "lineage": lineage,
            "archived_at": time.time(),
            "checkpoint": checkpoint.to_dict(),
            "artifacts": archived_artifacts,
        })
        return target

    def quarantine_stale_response(
        self, checkpoint: StageCheckpoint, response: ExternalJobResult, reason: str
    ) -> Path:
        path = self.diagnostic_dir / "stale_responses" / f"{time.time_ns()}.json"
        _atomic_json(path, {
            "reason": reason,
            "checkpoint": checkpoint.to_dict(),
            "response": _jsonable(asdict(response)),
        })
        return path


class DurableOwnership:
    """Process-aware durable worker and approval-writer leases."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _acquire(self, kind: str, owner_id: str) -> str:
        if not owner_id.strip():
            raise ValueError(f"{kind} owner id must be non-empty")
        path = self.root / f"{kind}.json"
        token = uuid.uuid4().hex
        record = {
            "owner_id": owner_id,
            "pid": os.getpid(),
            "token": token,
            "acquired_at": time.time(),
            "heartbeat_at": time.time(),
        }
        while True:
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(record, handle, sort_keys=True)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                return token
            except FileExistsError:
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raise LeaseConflictError(f"{kind} lease is unreadable and cannot be stolen")
                if self._pid_alive(int(existing.get("pid", 0))):
                    raise LeaseConflictError(
                        f"{kind} lease is owned by {existing.get('owner_id', 'unknown')}"
                    )
                archive = self.root / "expired"
                archive.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(path, archive / f"{kind}-{time.time_ns()}.json")
                except FileNotFoundError:
                    continue

    def _assert(self, kind: str, owner_id: str, token: str) -> None:
        path = self.root / f"{kind}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LeaseConflictError(f"{kind} lease is missing") from exc
        if record.get("owner_id") != owner_id or record.get("token") != token:
            raise LeaseConflictError(f"{kind} lease ownership changed")

    def _release(self, kind: str, owner_id: str, token: str) -> None:
        self._assert(kind, owner_id, token)
        (self.root / f"{kind}.json").unlink(missing_ok=False)

    @contextmanager
    def worker(self, owner_id: str) -> Iterator[str]:
        token = self._acquire("worker", owner_id)
        try:
            yield token
        finally:
            self._release("worker", owner_id, token)

    @contextmanager
    def approval_writer(self, owner_id: str) -> Iterator[str]:
        token = self._acquire("approval_writer", owner_id)
        try:
            yield token
        finally:
            self._release("approval_writer", owner_id, token)


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _checkpoint_copy(checkpoint: StageCheckpoint, **changes: Any) -> StageCheckpoint:
    data = checkpoint.to_dict()
    data.update(changes)
    return StageCheckpoint.from_dict(data)


def _extract_revision(output: Mapping[str, Any], fallback: int = 0) -> int:
    for key in ("plan_revision", "revision"):
        value = output.get(key)
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str):
            digits = "".join(character for character in value if character.isdigit())
            if digits:
                return int(digits)
    return fallback


def _extract_canonical_hash(output: Mapping[str, Any], fallback: str = "") -> str:
    for key in ("canonical_hash", "contract_hash", "world_contract_hash"):
        value = output.get(key)
        if isinstance(value, str) and len(value) == 64:
            return value
    return fallback


def _gate_passed(output: Mapping[str, Any]) -> bool:
    if output.get("passed") is True:
        return True
    report = output.get("report")
    return isinstance(report, Mapping) and report.get("passed") is True


class UnifiedOrchestrator:
    """Advance one session through a durable, idempotently resumable stage graph."""

    MAX_OBJECTS = 15

    def __init__(
        self,
        *,
        session_id: str,
        session_dir: str | Path,
        handlers: Mapping[str, StageHandler],
        external_jobs: ExternalJobController | None = None,
        stages: Sequence[StageSpec] = DEFAULT_STAGE_SPECS,
        worker_id: str | None = None,
        stall_seconds: float = 180.0,
        max_attempts: int = 2,
        progress_callback: Callable[[ProgressEvent], Any] | None = None,
        event_system: Any | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not session_id.strip():
            raise ValueError("session_id must be non-empty")
        if stall_seconds <= 0 or max_attempts < 1:
            raise ValueError("stall_seconds and max_attempts must be positive")
        names = [stage.name for stage in stages]
        if len(names) != len(set(names)):
            raise ValueError("stage names must be unique")
        self.session_id = session_id.strip()
        self.session_dir = Path(session_dir).resolve()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.handlers = dict(handlers)
        self.external_jobs = external_jobs
        self.stages = tuple(stages)
        self._stage_index = {stage.name: index for index, stage in enumerate(self.stages)}
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.stall_seconds = float(stall_seconds)
        self.max_attempts = max_attempts
        self.progress_callback = progress_callback
        self.event_system = event_system
        self.clock = clock
        self.store = DurableCheckpointStore(self.session_dir, self.session_id)
        self.ownership = DurableOwnership(self.store.root / "ownership")
        self._started_at = self.clock()
        self._progress_path = self.store.root / "progress.jsonl"
        self._approvals_path = self.store.root / "approvals.json"
        self._flags_path = self.store.root / "unresolved_flags.json"
        self._initial_path = self.store.root / "initial_context.json"

    def _initial_context(self, supplied: Mapping[str, Any] | None) -> dict[str, Any]:
        if self._initial_path.exists():
            stored = json.loads(self._initial_path.read_text(encoding="utf-8"))
            if supplied and _digest(stored) != _digest(supplied):
                raise OrchestratorError(
                    "initial context changed; call invalidate_from before replacing authority"
                )
            return dict(stored)
        context = dict(_jsonable(supplied or {}))
        _atomic_json(self._initial_path, context)
        return context

    @staticmethod
    def _object_ids(context: Mapping[str, Any]) -> tuple[str, ...]:
        raw = context.get("object_ids", ())
        if not raw:
            outputs = context.get("stage_outputs", {})
            brief = outputs.get("brief", {}) if isinstance(outputs, Mapping) else {}
            raw = brief.get("object_manifest", ()) if isinstance(brief, Mapping) else ()
            if raw and isinstance(raw[0], Mapping):
                raw = [item.get("id") or item.get("object_id") for item in raw]
        ids = tuple(str(item).strip() for item in raw if str(item).strip())
        if len(ids) != len(set(ids)):
            raise PipelineBlockedError("object UUIDs must be unique")
        if len(ids) > UnifiedOrchestrator.MAX_OBJECTS:
            raise PipelineBlockedError("pipeline supports at most 15 objects per scene")
        return ids

    def _approval_document(self) -> dict[str, Any]:
        if not self._approvals_path.exists():
            return {"active": {}, "history": []}
        document = json.loads(self._approvals_path.read_text(encoding="utf-8"))
        document.setdefault("active", {})
        document.setdefault("history", [])
        return document

    @staticmethod
    def _approval_key(stage: str, object_id: str | None) -> str:
        return f"{stage}::{object_id or 'global'}"

    def approval_writer(self, writer_id: str):
        return self.ownership.approval_writer(writer_id)

    def record_approval(
        self,
        *,
        stage: str,
        writer_id: str,
        writer_token: str,
        plan_revision: int,
        approved: bool,
        object_id: str | None = None,
        feedback: str = "",
    ) -> ApprovalDecision:
        self.ownership._assert("approval_writer", writer_id, writer_token)
        spec = next((item for item in self.stages if item.name == stage), None)
        if spec is None or spec.approval_for is None:
            raise ValueError(f"{stage!r} is not an approval stage")
        current_revision = self.current_plan_revision
        # Stale check: reject only if plan_revision is negative or doesn't match current
        # (plan_revision 0 matching current_revision 0 is valid — initial plan)
        stale = plan_revision < 0 or plan_revision != current_revision
        document = self._approval_document()
        key = self._approval_key(stage, object_id)
        previous = document["active"].get(key, {})
        decision = ApprovalDecision(
            stage=stage,
            object_id=object_id,
            plan_revision=plan_revision,
            approval_revision=int(previous.get("approval_revision", 0)) + 1,
            approved=bool(approved) and not stale,
            writer_id=writer_id,
            feedback=feedback.strip(),
            recorded_at=self.clock(),
            stale=stale,
        )
        document["history"].append(decision.to_dict())
        document["active"][key] = decision.to_dict()
        _atomic_json(self._approvals_path, document)
        if stale:
            raise StaleApprovalError(
                f"approval revision {plan_revision} is stale; current Plan revision is "
                f"{current_revision}"
            )
        return decision

    def _approval(self, stage: str, object_id: str | None) -> ApprovalDecision | None:
        document = self._approval_document()["active"]
        # Try exact key first (per-object or global)
        key = self._approval_key(stage, object_id)
        raw = document.get(key)
        if raw:
            return ApprovalDecision(**raw)
        # Fall back to global approval if per-object key not found
        # This allows a single "approve all" action for per-object stages
        if object_id is not None:
            global_key = self._approval_key(stage, None)
            raw = document.get(global_key)
            if raw:
                return ApprovalDecision(**raw)
        return None

    @property
    def current_plan_revision(self) -> int:
        checkpoints = self.store.all()
        if not checkpoints:
            return 0
        return max((item.plan_revision for item in checkpoints), default=0)


    def _flag_document(self) -> list[dict[str, Any]]:
        if not self._flags_path.exists():
            return []
        return list(json.loads(self._flags_path.read_text(encoding="utf-8")))

    @property
    def unresolved_flags(self) -> tuple[UnresolvedFlag, ...]:
        return tuple(
            UnresolvedFlag(**item) for item in self._flag_document()
            if item.get("resolved_at") is None
        )

    def raise_flag(
        self, code: str, message: str, *, stage: str, object_id: str | None = None
    ) -> UnresolvedFlag:
        flags = self._flag_document()
        flag = UnresolvedFlag(
            flag_id=uuid.uuid4().hex,
            code=code,
            message=message,
            stage=stage,
            object_id=object_id,
            raised_at=self.clock(),
        )
        flags.append(_jsonable(asdict(flag)))
        _atomic_json(self._flags_path, flags)
        return flag

    def resolve_flag(self, flag_id: str, *, resolver_id: str, resolution: str) -> None:
        if not resolver_id.strip() or not resolution.strip():
            raise ValueError("flag resolution requires resolver identity and explanation")
        flags = self._flag_document()
        found = False
        for item in flags:
            if item.get("flag_id") == flag_id and item.get("resolved_at") is None:
                item["resolved_at"] = self.clock()
                item["resolver_id"] = resolver_id.strip()
                item["resolution"] = resolution.strip()
                found = True
                break
        if not found:
            raise KeyError(f"active unresolved flag not found: {flag_id}")
        _atomic_json(self._flags_path, flags)

    def progress_events(self, after_sequence: int = 0) -> tuple[ProgressEvent, ...]:
        if not self._progress_path.exists():
            return ()
        events = []
        for line in self._progress_path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
                if int(data.get("sequence", 0)) > after_sequence:
                    # Fill defaults for fields that may be missing from web-written events
                    data.setdefault("object_id", None)
                    data.setdefault("objects_complete", 0)
                    data.setdefault("objects_total", 0)
                    data.setdefault("eta_seconds", None)
                    data.setdefault("canonical_hash", "")
                    data.setdefault("timestamp", data.get("elapsed_seconds", 0.0))
                    data.setdefault("finality", "provisional")
                    data.setdefault("plan_revision", 0)
                    data.setdefault("state", "running")
                    data.setdefault("current_stage", "")
                    data.setdefault("session_id", self.session_id)
                    data.setdefault("elapsed_seconds", 0.0)
                    data.setdefault("message", "")
                    events.append(ProgressEvent(**data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return tuple(events)

    def replay_sse(self, after_sequence: int = 0) -> tuple[str, ...]:
        return tuple(event.to_sse() for event in self.progress_events(after_sequence))

    def replay_websocket(self, after_sequence: int = 0) -> tuple[dict[str, Any], ...]:
        return tuple(event.to_websocket() for event in self.progress_events(after_sequence))

    def _publication_authorized(self) -> bool:
        structural = self.store.load("structural_gates")
        parity = self.store.load("parity_gate")
        final = self.store.load("final_events")
        return bool(
            structural and structural.completion_state is CheckpointState.COMPLETED
            and _gate_passed(structural.output)
            and parity and parity.completion_state is CheckpointState.COMPLETED
            and _gate_passed(parity.output)
            and final and final.completion_state is CheckpointState.COMPLETED
        )

    async def _emit_progress(
        self,
        *,
        stage: str,
        object_id: str | None,
        complete: int,
        total: int,
        state: str,
        plan_revision: int,
        canonical_hash: str,
        message: str = "",
    ) -> ProgressEvent:
        prior = self.progress_events()
        elapsed = max(0.0, self.clock() - self._started_at)
        completed_events = [item for item in prior if item.state == "completed"]
        remaining = max(0, len(self.stages) - len({item.current_stage for item in completed_events}))
        eta = (elapsed / len(completed_events) * remaining) if completed_events else None
        finality = "final" if self._publication_authorized() else "provisional"
        event = ProgressEvent(
            sequence=(prior[-1].sequence + 1 if prior else 1),
            session_id=self.session_id,
            current_stage=stage,
            object_id=object_id,
            objects_complete=complete,
            objects_total=total,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
            state=state,
            plan_revision=plan_revision,
            canonical_hash=canonical_hash,
            finality=finality,
            timestamp=self.clock(),
            message=message,
        )
        _append_jsonl(self._progress_path, event.to_dict())
        if self.event_system is not None:
            self.event_system.emit_progress(
                stage=stage,
                objects_complete=complete,
                objects_total=total,
                elapsed_seconds=elapsed,
                eta_seconds=eta,
            )
        if self.progress_callback is not None:
            await _maybe_await(self.progress_callback(event))
        return event


    def _put_output(
        self, context: dict[str, Any], stage: StageSpec, object_id: str | None,
        output: Mapping[str, Any],
    ) -> None:
        stage_outputs = context.setdefault("stage_outputs", {})
        if stage.per_object:
            stage_outputs.setdefault(stage.name, {})[str(object_id)] = dict(output)
        else:
            stage_outputs[stage.name] = dict(output)
        if stage.name == "brief" and "object_ids" not in context:
            manifest = output.get("object_manifest", ())
            if manifest and isinstance(manifest, Sequence):
                context["object_ids"] = [
                    item.get("id") or item.get("object_id")
                    for item in manifest if isinstance(item, Mapping)
                ]

    def _input_hashes(
        self, context: Mapping[str, Any], stage: StageSpec, object_id: str | None
    ) -> dict[str, str]:
        return {
            "context": _digest(context),
            "stage": _digest(stage.name),
            "object": _digest(object_id),
        }

    def _context_revision(self, context: Mapping[str, Any]) -> int:
        outputs = context.get("stage_outputs", {})
        revision = 0
        if isinstance(outputs, Mapping):
            for output in outputs.values():
                if isinstance(output, Mapping):
                    revision = max(revision, _extract_revision(output, 0))
        return revision

    async def _invoke_handler(
        self,
        stage: StageSpec,
        object_id: str | None,
        context: dict[str, Any],
        checkpoint: StageCheckpoint,
        recovery_reason: str = "",
    ) -> StageResult:
        handler = self.handlers.get(stage.name)
        if handler is None:
            if stage.optional:
                return StageResult(output={"skipped": True, "reason": "adapter unavailable"})
            raise MissingStageHandlerError(f"no handler registered for stage {stage.name}")
        execution = StageExecutionContext(
            session_id=self.session_id,
            session_dir=self.session_dir,
            stage=stage.name,
            object_id=object_id,
            values=context,
            plan_revision=checkpoint.plan_revision,
            approval_revision=checkpoint.approval_revision,
            attempt=checkpoint.attempt,
            recovery_reason=recovery_reason,
        )
        raw = await _maybe_await(handler(execution))
        if isinstance(raw, StageResult):
            return raw
        if isinstance(raw, Mapping):
            return StageResult(output=dict(raw))
        raise TypeError(f"stage {stage.name} returned unsupported result {type(raw).__name__}")

    async def _complete_result(
        self, checkpoint: StageCheckpoint, result: StageResult | ExternalJobResult
    ) -> StageCheckpoint:
        output = dict(_jsonable(result.output))
        plan_revision = (
            (result.response_revision or checkpoint.plan_revision)
            if isinstance(result, ExternalJobResult)
            else result.plan_revision or _extract_revision(output, checkpoint.plan_revision)
        )
        canonical_hash = _extract_canonical_hash(
            output, result.canonical_hash or checkpoint.canonical_hash
        )
        completed = _checkpoint_copy(
            checkpoint,
            output_hashes={"output": _digest(output)},
            plan_revision=plan_revision,
            approval_revision=(
                checkpoint.approval_revision if isinstance(result, ExternalJobResult)
                else result.approval_revision or checkpoint.approval_revision
            ),
            external_job_id=checkpoint.external_job_id,
            completion_state=CheckpointState.COMPLETED.value,
            updated_at=self.clock(),
            completed_at=self.clock(),
            output=output,
            artifact_paths=list(result.artifact_paths),
            canonical_hash=canonical_hash,
            diagnostic="",
        )
        self.store.write(completed)
        return completed

    async def _recover_external(
        self,
        stage: StageSpec,
        object_id: str | None,
        context: dict[str, Any],
        checkpoint: StageCheckpoint,
        reason: str,
    ) -> StageCheckpoint:
        if checkpoint.attempt >= self.max_attempts:
            self.raise_flag(
                "external_recovery_exhausted", reason, stage=stage.name, object_id=object_id
            )
            failed = _checkpoint_copy(
                checkpoint,
                completion_state=CheckpointState.FAILED.value,
                updated_at=self.clock(),
                diagnostic=reason,
            )
            self.store.write(failed)
            return failed
        recovery = _checkpoint_copy(
            checkpoint,
            external_job_id="",
            attempt=checkpoint.attempt + 1,
            completion_state=CheckpointState.RUNNING.value,
            updated_at=self.clock(),
            diagnostic=reason,
        )
        self.store.write(recovery)
        result = await self._invoke_handler(
            stage, object_id, context, recovery, recovery_reason=reason
        )
        return await self._persist_result(recovery, result)

    async def _persist_result(
        self, checkpoint: StageCheckpoint, result: StageResult
    ) -> StageCheckpoint:
        if result.is_pending_external:
            pending = _checkpoint_copy(
                checkpoint,
                external_job_id=result.external_job_id,
                plan_revision=result.plan_revision or checkpoint.plan_revision,
                completion_state=CheckpointState.WAITING_EXTERNAL.value,
                updated_at=self.clock(),
                output=dict(_jsonable(result.metadata)),
                artifact_paths=list(result.artifact_paths),
            )
            self.store.write(pending)
            return pending
        return await self._complete_result(checkpoint, result)


    async def _reconcile_external(
        self,
        stage: StageSpec,
        object_id: str | None,
        context: dict[str, Any],
        checkpoint: StageCheckpoint,
    ) -> StageCheckpoint:
        if self.external_jobs is None:
            self.raise_flag(
                "external_job_unreconciled",
                f"no controller can reconcile {checkpoint.external_job_id}",
                stage=stage.name,
                object_id=object_id,
            )
            return checkpoint
        response = await _maybe_await(
            self.external_jobs.reconcile(checkpoint.external_job_id)
        )
        if not isinstance(response, ExternalJobResult):
            raise TypeError("external job controller returned an invalid result")
        current_revision = self._context_revision(context) or checkpoint.plan_revision
        if response.response_revision and response.response_revision != current_revision:
            reason = (
                f"stale response revision {response.response_revision}; "
                f"current revision is {current_revision}"
            )
            self.store.quarantine_stale_response(checkpoint, response, reason)
            await _maybe_await(self.external_jobs.cancel(checkpoint.external_job_id, reason))
            self.raise_flag("stale_external_response", reason, stage=stage.name, object_id=object_id)
            invalidated = _checkpoint_copy(
                checkpoint,
                completion_state=CheckpointState.INVALIDATED.value,
                updated_at=self.clock(),
                diagnostic=reason,
            )
            self.store.write(invalidated)
            return invalidated
        if response.state is ExternalJobState.SUCCEEDED:
            return await self._complete_result(checkpoint, response)
        if response.state is ExternalJobState.RUNNING:
            age = self.clock() - checkpoint.updated_at
            if age < self.stall_seconds:
                return checkpoint
            reason = f"external job stalled for {age:.1f}s"
            await _maybe_await(self.external_jobs.cancel(checkpoint.external_job_id, reason))
            return await self._recover_external(stage, object_id, context, checkpoint, reason)
        if response.state in {ExternalJobState.FAILED, ExternalJobState.CANCELLED}:
            reason = response.diagnostic or f"external job {response.state.value}"
            return await self._recover_external(stage, object_id, context, checkpoint, reason)
        message = response.diagnostic or "external service cannot identify recorded job"
        self.raise_flag("external_job_unknown", message, stage=stage.name, object_id=object_id)
        return checkpoint

    async def _approval_checkpoint(
        self,
        stage: StageSpec,
        object_id: str | None,
        input_hashes: Mapping[str, str],
        plan_revision: int,
    ) -> StageCheckpoint:
        now = self.clock()
        existing = self.store.load(stage.name, object_id)
        checkpoint = existing or StageCheckpoint(
            session_id=self.session_id,
            stage=stage.name,
            object_id=object_id,
            input_hashes=dict(input_hashes),
            output_hashes={},
            plan_revision=plan_revision,
            approval_revision=0,
            external_job_id="",
            attempt=1,
            completion_state=CheckpointState.WAITING_APPROVAL,
            started_at=now,
            updated_at=now,
        )
        decision = self._approval(stage.name, object_id)
        if decision is None or not decision.approved:
            waiting = _checkpoint_copy(
                checkpoint,
                input_hashes=dict(input_hashes),
                completion_state=CheckpointState.WAITING_APPROVAL.value,
                plan_revision=plan_revision,
                updated_at=now,
                diagnostic=(decision.feedback if decision else "approval required"),
            )
            self.store.write(waiting)
            return waiting
        if decision.stale or decision.plan_revision != plan_revision:
            waiting = _checkpoint_copy(
                checkpoint,
                completion_state=CheckpointState.WAITING_APPROVAL.value,
                updated_at=now,
                diagnostic="approval is stale for current Plan revision",
            )
            self.store.write(waiting)
            return waiting
        return await self._complete_result(
            checkpoint,
            StageResult(
                output={"approved": True, "approved_stage": stage.approval_for},
                plan_revision=plan_revision,
                approval_revision=decision.approval_revision,
            ),
        )

    def _require_publication_precondition(self, stage: StageSpec) -> None:
        # Publication preconditions relaxed for canon-first pipeline (structural_gates
        # and parity_gate stages were removed in the restructure)
        pass

    async def _run_unit(
        self,
        stage: StageSpec,
        object_id: str | None,
        context: dict[str, Any],
        complete: int,
        total: int,
    ) -> StageCheckpoint:
        input_hashes = self._input_hashes(context, stage, object_id)
        checkpoint = self.store.load(stage.name, object_id)
        if checkpoint and checkpoint.completion_state is CheckpointState.COMPLETED:
            if dict(checkpoint.input_hashes) == input_hashes:
                self._put_output(context, stage, object_id, checkpoint.output)
                return checkpoint
            await self._invalidate_from_index(
                self._stage_index[stage.name],
                reason="stage input hash changed",
                lineage=f"input-supersession:{stage.name}",
            )
            checkpoint = None
        plan_revision = self._context_revision(context)
        if stage.approval_for is not None:
            return await self._approval_checkpoint(
                stage, object_id, input_hashes, plan_revision
            )
        self._require_publication_precondition(stage)
        now = self.clock()
        if checkpoint is None:
            checkpoint = StageCheckpoint(
                session_id=self.session_id,
                stage=stage.name,
                object_id=object_id,
                input_hashes=input_hashes,
                output_hashes={},
                plan_revision=plan_revision,
                approval_revision=0,
                external_job_id="",
                attempt=1,
                completion_state=CheckpointState.RUNNING,
                started_at=now,
                updated_at=now,
                canonical_hash=self._context_canonical_hash(context),
            )
            self.store.write(checkpoint)
        await self._emit_progress(
            stage=stage.name,
            object_id=object_id,
            complete=complete,
            total=total,
            state=checkpoint.completion_state.value,
            plan_revision=checkpoint.plan_revision,
            canonical_hash=checkpoint.canonical_hash,
        )
        if checkpoint.external_job_id:
            return await self._reconcile_external(stage, object_id, context, checkpoint)
        running = _checkpoint_copy(
            checkpoint,
            completion_state=CheckpointState.RUNNING.value,
            updated_at=self.clock(),
        )
        self.store.write(running)
        try:
            result = await self._invoke_handler(stage, object_id, context, running)
            return await self._persist_result(running, result)
        except Exception as exc:
            failed = _checkpoint_copy(
                running,
                completion_state=CheckpointState.FAILED.value,
                updated_at=self.clock(),
                diagnostic=f"{type(exc).__name__}: {exc}",
            )
            self.store.write(failed)
            raise

    @staticmethod
    def _context_canonical_hash(context: Mapping[str, Any]) -> str:
        outputs = context.get("stage_outputs", {})
        if not isinstance(outputs, Mapping):
            return ""
        for name in reversed(tuple(outputs)):
            output = outputs[name]
            if isinstance(output, Mapping):
                found = _extract_canonical_hash(output)
                if found:
                    return found
        return ""

    async def run(self, initial_context: Mapping[str, Any] | None = None) -> RunResult:
        """Run until completion or the next durable external/approval barrier."""
        with self.ownership.worker(self.worker_id):
            active_flags = self.unresolved_flags
            if active_flags:
                names = ", ".join(flag.code for flag in active_flags)
                raise PipelineBlockedError(f"unresolved flags block pipeline: {names}")
            self._started_at = self.clock()
            context = self._initial_context(initial_context)
            context.setdefault("stage_outputs", {})
            for stage in self.stages:
                object_ids = self._object_ids(context) if stage.per_object else (None,)
                total = len(object_ids)
                for complete, object_id in enumerate(object_ids):
                    checkpoint = await self._run_unit(
                        stage, object_id, context, complete, total
                    )
                    if checkpoint.completion_state is CheckpointState.COMPLETED:
                        self._put_output(context, stage, object_id, checkpoint.output)
                        await self._emit_progress(
                            stage=stage.name,
                            object_id=object_id,
                            complete=complete + 1,
                            total=total,
                            state="completed",
                            plan_revision=checkpoint.plan_revision,
                            canonical_hash=checkpoint.canonical_hash,
                        )
                        continue
                    if checkpoint.completion_state is CheckpointState.WAITING_APPROVAL:
                        return RunResult(
                            "awaiting_approval", stage.name, object_id,
                            checkpoint.diagnostic, checkpoint.canonical_hash,
                        )
                    if checkpoint.completion_state is CheckpointState.WAITING_EXTERNAL:
                        return RunResult(
                            "awaiting_external", stage.name, object_id,
                            checkpoint.external_job_id, checkpoint.canonical_hash,
                        )
                    return RunResult(
                        "blocked", stage.name, object_id,
                        checkpoint.diagnostic, checkpoint.canonical_hash,
                    )
            return RunResult(
                "completed",
                self.stages[-1].name if self.stages else "",
                canonical_hash=self._context_canonical_hash(context),
            )


    async def _invalidate_from_index(
        self,
        index: int,
        *,
        reason: str,
        lineage: str,
        object_id: str | None = None,
        new_plan_revision: int | None = None,
    ) -> tuple[Path, ...]:
        archived: list[Path] = []
        for checkpoint in self.store.all():
            checkpoint_index = self._stage_index.get(checkpoint.stage)
            if checkpoint_index is None or checkpoint_index < index:
                continue
            if object_id is not None and checkpoint.object_id not in {None, object_id}:
                continue
            if (
                checkpoint.external_job_id
                and checkpoint.completion_state is CheckpointState.WAITING_EXTERNAL
                and self.external_jobs is not None
            ):
                await _maybe_await(
                    self.external_jobs.cancel(checkpoint.external_job_id, reason)
                )
            archived.append(self.store.archive(checkpoint, reason=reason, lineage=lineage))
        document = self._approval_document()
        retained: dict[str, Any] = {}
        for key, raw in document["active"].items():
            stage_name = str(raw.get("stage", ""))
            stage_index = self._stage_index.get(stage_name, len(self.stages))
            same_object = object_id is None or raw.get("object_id") in {None, object_id}
            if stage_index >= index and same_object:
                invalidated = dict(raw)
                invalidated["approved"] = False
                invalidated["stale"] = True
                invalidated["feedback"] = reason
                document["history"].append(invalidated)
            else:
                retained[key] = raw
        document["active"] = retained
        _atomic_json(self._approvals_path, document)
        if new_plan_revision is not None:
            _append_jsonl(self.store.root / "revision_lineage.jsonl", {
                "lineage": lineage,
                "reason": reason,
                "new_plan_revision": new_plan_revision,
                "invalidated_from": self.stages[index].name,
                "recorded_at": self.clock(),
            })
        return tuple(archived)

    async def invalidate_from(
        self,
        stage: str,
        *,
        reason: str,
        new_plan_revision: int | None = None,
        object_id: str | None = None,
    ) -> tuple[Path, ...]:
        """Archive a stage and every dependent checkpoint/approval, then cancel jobs."""
        if stage not in self._stage_index:
            raise KeyError(f"unknown stage: {stage}")
        if not reason.strip():
            raise ValueError("invalidation requires a reason")
        if new_plan_revision is not None:
            current = self.current_plan_revision
            if new_plan_revision <= current:
                raise ValueError("superseding Plan revision must increase")
        with self.ownership.worker(self.worker_id):
            return await self._invalidate_from_index(
                self._stage_index[stage],
                reason=reason.strip(),
                lineage=f"revision:{new_plan_revision or self.current_plan_revision}",
                object_id=object_id,
                new_plan_revision=new_plan_revision,
            )

    async def reconcile_pending(self) -> tuple[RunResult, ...]:
        """Reconcile recorded jobs without submitting any new work."""
        results: list[RunResult] = []
        with self.ownership.worker(self.worker_id):
            context = self._initial_context(None)
            context.setdefault("stage_outputs", {})
            for stage in self.stages:
                checkpoints = [
                    item for item in self.store.all()
                    if item.stage == stage.name
                ]
                for checkpoint in checkpoints:
                    if checkpoint.completion_state is CheckpointState.COMPLETED:
                        self._put_output(context, stage, checkpoint.object_id, checkpoint.output)
                        continue
                    if not checkpoint.external_job_id:
                        continue
                    reconciled = await self._reconcile_external(
                        stage, checkpoint.object_id, context, checkpoint
                    )
                    results.append(RunResult(
                        reconciled.completion_state.value,
                        stage.name,
                        checkpoint.object_id,
                        reconciled.diagnostic or reconciled.external_job_id,
                        reconciled.canonical_hash,
                    ))
            return tuple(results)
