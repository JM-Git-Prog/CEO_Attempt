"""Hash-bound event finality, transport encoding, and durable replay.

Finality is decided once at ingestion and stored in an append-only journal. SSE,
WebSocket, sidecar, compiler, and replay consumers all receive the same envelope;
transport adapters never infer or promote finality.

Validates Requirements 19.5, 19.6, and 27.2.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .world_contract import WorldContract, verify_hash


_HASH_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


class EventFinality(str, Enum):
    """Authority classification carried by every event."""

    PROVISIONAL = "provisional"
    FINAL = "final"


class EventOrigin(str, Enum):
    """Producer boundary; finality rules are identical for every origin."""

    PIPELINE = "pipeline"
    SSE = "sse"
    WEBSOCKET = "websocket"
    SIDECAR = "sidecar"
    COMPILER = "compiler"


class MismatchPolicy(str, Enum):
    """How an invalid request to claim finality is handled."""

    DOWNGRADE = "downgrade"
    REJECT = "reject"


class EventDisposition(str, Enum):
    ACCEPTED = "accepted"
    DOWNGRADED = "downgraded"
    DUPLICATE = "duplicate"


class EventSystemError(RuntimeError):
    """Base error for fail-closed event handling."""


class EventRejected(EventSystemError):
    """Raised when mismatch policy rejects an invalid final event."""


class InvalidContractBinding(EventSystemError):
    """Raised when a WorldContract cannot authorize final events."""


class ReplayCursorError(EventSystemError):
    """Raised for an unknown reconnect cursor."""


class EventJournalError(EventSystemError):
    """Raised when durable event history is corrupt or cannot be written."""


def _json_copy(value: Any) -> Any:
    """Validate JSON safety and detach callers from persisted event state."""

    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _revision_text(value: Any) -> str:
    return str(value).strip()


def _is_nonzero_revision(value: Any) -> bool:
    revision = _revision_text(value).lower()
    if not revision:
        return False
    compact = revision.removeprefix("revision-").removeprefix("rev-")
    try:
        return int(compact) > 0
    except ValueError:
        return compact not in {"", "0"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PipelineEvent:
    """Immutable event envelope used by storage and every transport."""

    event_id: str
    sequence: int
    session_id: str
    event_type: str
    finality: EventFinality
    origin: EventOrigin
    payload: Mapping[str, Any] = field(default_factory=dict)
    plan_revision: str | None = None
    contract_hash: str | None = None
    producer_event_id: str | None = None
    created_at: str = field(default_factory=_utc_now)
    diagnostic: str | None = None

    @property
    def status(self) -> str:
        """Compatibility alias for existing ``status`` event consumers."""

        return self.finality.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "event_type": self.event_type,
            "status": self.finality.value,
            "finality": self.finality.value,
            "origin": self.origin.value,
            "payload": _json_copy(dict(self.payload)),
            "plan_revision": self.plan_revision,
            "contract_hash": self.contract_hash,
            "producer_event_id": self.producer_event_id,
            "created_at": self.created_at,
            "diagnostic": self.diagnostic,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PipelineEvent:
        status = data.get("finality", data.get("status", "provisional"))
        return cls(
            event_id=str(data["event_id"]),
            sequence=int(data["sequence"]),
            session_id=str(data["session_id"]),
            event_type=str(data["event_type"]),
            finality=EventFinality(str(status)),
            origin=EventOrigin(str(data.get("origin", "pipeline"))),
            payload=_json_copy(data.get("payload", {})),
            plan_revision=(
                None if data.get("plan_revision") is None
                else _revision_text(data["plan_revision"])
            ),
            contract_hash=(
                None if data.get("contract_hash") is None
                else str(data["contract_hash"])
            ),
            producer_event_id=(
                None if data.get("producer_event_id") is None
                else str(data["producer_event_id"])
            ),
            created_at=str(data.get("created_at", _utc_now())),
            diagnostic=(
                None if data.get("diagnostic") is None else str(data["diagnostic"])
            ),
        )

    def to_sse(self) -> str:
        """Encode one standards-compatible SSE record without changing finality."""

        data = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {data}\n\n"

    def to_websocket(self) -> dict[str, Any]:
        """Return the identical envelope for WebSocket ``send_json``."""

        return self.to_dict()

    def to_websocket_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class FinalityDecision:
    event: PipelineEvent
    disposition: EventDisposition
    reason: str | None = None


@dataclass(frozen=True)
class ContractBinding:
    """Minimal verified authority snapshot needed to judge later events."""

    plan_revision: str
    contract_hash: str
    solved_objects: Mapping[str, Mapping[str, Any]]

    @classmethod
    def from_contract(cls, contract: WorldContract) -> ContractBinding:
        if not verify_hash(contract):
            raise InvalidContractBinding("WorldContract hash is missing or invalid")
        if not _is_nonzero_revision(contract.plan_revision):
            raise InvalidContractBinding("WorldContract plan revision must be nonzero")
        if not _HASH_RE.fullmatch(contract.contract_hash):
            raise InvalidContractBinding("WorldContract canonical hash is not SHA-256")

        solved: dict[str, dict[str, Any]] = {}
        for instance in contract.instances:
            if not instance.object_id or instance.object_id in solved:
                raise InvalidContractBinding("WorldContract object identities must be unique")
            solved[instance.object_id] = {
                "position": instance.position.to_dict(),
                "rotation": instance.rotation.to_dict(),
                "scale": instance.scale.to_dict(),
                "asset_binding": instance.asset_binding.to_dict(),
                "material_intent": instance.material_intent.to_dict(),
            }
        return cls(
            plan_revision=_revision_text(contract.plan_revision),
            contract_hash=contract.contract_hash,
            solved_objects=_json_copy(solved),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "contract_hash": self.contract_hash,
            "solved_objects": _json_copy(dict(self.solved_objects)),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ContractBinding:
        revision = _revision_text(data.get("plan_revision", ""))
        contract_hash = str(data.get("contract_hash", ""))
        if not _is_nonzero_revision(revision) or not _HASH_RE.fullmatch(contract_hash):
            raise EventJournalError("journal contains an invalid contract binding")
        return cls(revision, contract_hash, _json_copy(data.get("solved_objects", {})))


class EventSystem:
    """Append-only finality authority and replay source for one session.

    A verified contract is registered first. Structural and compiler parity gates
    then authorize its revision/hash pair. Only after that authorization can an
    event remain ``final``. Invalid claims are either downgraded with diagnostics
    or rejected, according to the caller's explicit policy.
    """

    def __init__(self, session_id: str, journal_path: str | Path | None = None) -> None:
        if not session_id.strip():
            raise ValueError("session_id must not be empty")
        self.session_id = session_id
        self.journal_path = Path(journal_path) if journal_path is not None else None
        self._lock = threading.RLock()
        self._events: list[PipelineEvent] = []
        self._producer_ids: dict[tuple[EventOrigin, str], PipelineEvent] = {}
        self._binding: ContractBinding | None = None
        self._authorized = False
        self._contract_registration_sequence: int | None = None
        self._first_final_sequence: int | None = None
        if self.journal_path is not None:
            self._load_journal()

    @property
    def active_binding(self) -> ContractBinding | None:
        return self._binding

    @property
    def finality_authorized(self) -> bool:
        return self._authorized

    @property
    def events(self) -> tuple[PipelineEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def register_contract(self, contract: WorldContract) -> PipelineEvent:
        """Register a verified contract, invalidating authorization on revision change."""

        binding = ContractBinding.from_contract(contract)
        with self._lock:
            if self._binding == binding:
                for event in reversed(self._events):
                    if event.event_type == "world_contract.registered":
                        return event
            self._binding = binding
            self._authorized = False
            self._first_final_sequence = None
            event = self._new_event(
                event_type="world_contract.registered",
                finality=EventFinality.PROVISIONAL,
                origin=EventOrigin.PIPELINE,
                payload={**binding.to_dict(), "classification": "awaiting_publication_gates"},
                plan_revision=binding.plan_revision,
                contract_hash=binding.contract_hash,
            )
            self._contract_registration_sequence = event.sequence
            return self._append(event)

    def authorize_finality(
        self,
        *,
        plan_revision: str | int,
        contract_hash: str,
        structural_gates_passed: bool,
        parity_gate_passed: bool,
    ) -> PipelineEvent:
        """Authorize final publication only after both gate sets pass."""

        with self._lock:
            reason = self._binding_mismatch(plan_revision, contract_hash)
            if reason is not None:
                raise EventRejected(reason)
            if self._authorized and structural_gates_passed and parity_gate_passed:
                for prior in reversed(self._events):
                    if (
                        prior.event_type == "world_contract.finalized"
                        and prior.plan_revision == self._binding.plan_revision
                        and prior.contract_hash == self._binding.contract_hash
                    ):
                        return prior
            if not structural_gates_passed or not parity_gate_passed:
                failed = []
                if not structural_gates_passed:
                    failed.append("structural_gates")
                if not parity_gate_passed:
                    failed.append("parity_gate")
                self._authorized = False
                return self._append(self._new_event(
                    event_type="publication.blocked",
                    finality=EventFinality.PROVISIONAL,
                    origin=EventOrigin.PIPELINE,
                    payload={"failed_gates": failed},
                    plan_revision=_revision_text(plan_revision),
                    contract_hash=contract_hash,
                    diagnostic="finality blocked: " + ", ".join(failed),
                ))

            self._authorized = True
            event = self._new_event(
                event_type="world_contract.finalized",
                finality=EventFinality.FINAL,
                origin=EventOrigin.PIPELINE,
                payload={
                    "structural_gates_passed": True,
                    "parity_gate_passed": True,
                },
                plan_revision=self._binding.plan_revision,
                contract_hash=self._binding.contract_hash,
            )
            self._first_final_sequence = event.sequence
            return self._append(event)

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        finality: EventFinality | str = EventFinality.PROVISIONAL,
        plan_revision: str | int | None = None,
        contract_hash: str | None = None,
        origin: EventOrigin | str = EventOrigin.PIPELINE,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
        producer_event_id: str | None = None,
    ) -> FinalityDecision:
        """Classify and append an event exactly once.

        ``final`` is a request, not an authority claim. The request survives only
        when the active contract, revision/hash, gate authorization, ordering, and
        any object transform all agree.
        """

        if not event_type.strip():
            raise ValueError("event_type must not be empty")
        requested = EventFinality(finality)
        event_origin = EventOrigin(origin)
        policy = MismatchPolicy(mismatch_policy)
        body = _json_copy(dict(payload or {}))

        with self._lock:
            if producer_event_id:
                duplicate = self._producer_ids.get((event_origin, producer_event_id))
                if duplicate is not None:
                    return FinalityDecision(duplicate, EventDisposition.DUPLICATE)

            reason: str | None = None
            effective = requested
            revision = None if plan_revision is None else _revision_text(plan_revision)
            digest = contract_hash
            if requested is EventFinality.FINAL:
                reason = self._finality_error(revision, digest, body)
                if reason:
                    if policy is MismatchPolicy.REJECT:
                        raise EventRejected(reason)
                    effective = EventFinality.PROVISIONAL
                    body["requested_finality"] = EventFinality.FINAL.value
                    body["finality_diagnostic"] = reason
                else:
                    body = self._bind_solved_object(body)
            elif self._binding is not None and (revision is not None or digest is not None):
                reason = self._binding_mismatch(revision, digest, require_both=False)
                if reason:
                    body["finality_diagnostic"] = "stale provisional event: " + reason

            event = self._new_event(
                event_type=event_type,
                finality=effective,
                origin=event_origin,
                payload=body,
                plan_revision=revision,
                contract_hash=digest,
                producer_event_id=producer_event_id,
                diagnostic=reason,
            )
            stored = self._append(event)
            disposition = (
                EventDisposition.DOWNGRADED
                if effective is not requested else EventDisposition.ACCEPTED
            )
            return FinalityDecision(stored, disposition, reason)

    def publish_object(
        self,
        object_id: str,
        *,
        event_type: str = "object.published",
        payload: Mapping[str, Any] | None = None,
        final: bool = True,
        origin: EventOrigin | str = EventOrigin.PIPELINE,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
        producer_event_id: str | None = None,
    ) -> FinalityDecision:
        """Publish an object event populated from solved WorldContract values."""

        body = dict(payload or {})
        body["object_id"] = object_id
        binding = self._binding
        return self.emit(
            event_type,
            body,
            finality=EventFinality.FINAL if final else EventFinality.PROVISIONAL,
            plan_revision=binding.plan_revision if binding else None,
            contract_hash=binding.contract_hash if binding else None,
            origin=origin,
            mismatch_policy=mismatch_policy,
            producer_event_id=producer_event_id,
        )

    def ingest(
        self,
        data: Mapping[str, Any],
        *,
        origin: EventOrigin | str,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
    ) -> FinalityDecision:
        """Ingest an SSE/WS/sidecar/compiler envelope through the same authority check."""

        incoming_session = data.get("session_id")
        if incoming_session is not None and str(incoming_session) != self.session_id:
            raise EventRejected("event belongs to a different session")
        raw_payload = data.get("payload", {})
        if not isinstance(raw_payload, Mapping):
            raise ValueError("event payload must be an object")
        payload = dict(raw_payload)
        for key in (
            "object_id", "position", "rotation", "scale",
            "asset_binding", "material_intent",
        ):
            if key in data and key not in payload:
                payload[key] = data[key]
        return self.emit(
            str(data.get("event_type", data.get("type", "progress"))),
            payload,
            finality=str(data.get("finality", data.get("status", "provisional"))),
            plan_revision=data.get("plan_revision"),
            contract_hash=data.get("contract_hash"),
            origin=origin,
            mismatch_policy=mismatch_policy,
            producer_event_id=(
                None if data.get("producer_event_id", data.get("event_id")) is None
                else str(data.get("producer_event_id", data.get("event_id")))
            ),
        )

    def ingest_sidecar(
        self,
        data: Mapping[str, Any],
        *,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
    ) -> FinalityDecision:
        return self.ingest(data, origin=EventOrigin.SIDECAR, mismatch_policy=mismatch_policy)

    def ingest_compiler(
        self,
        data: Mapping[str, Any],
        *,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
    ) -> FinalityDecision:
        return self.ingest(data, origin=EventOrigin.COMPILER, mismatch_policy=mismatch_policy)

    def ingest_sse(
        self,
        data: Mapping[str, Any],
        *,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
    ) -> FinalityDecision:
        return self.ingest(data, origin=EventOrigin.SSE, mismatch_policy=mismatch_policy)

    def ingest_websocket(
        self,
        data: Mapping[str, Any],
        *,
        mismatch_policy: MismatchPolicy | str = MismatchPolicy.DOWNGRADE,
    ) -> FinalityDecision:
        return self.ingest(data, origin=EventOrigin.WEBSOCKET, mismatch_policy=mismatch_policy)

    def emit_progress(
        self,
        *,
        stage: str,
        objects_complete: int,
        objects_total: int,
        elapsed_seconds: float,
        eta_seconds: float | None,
        payload: Mapping[str, Any] | None = None,
    ) -> FinalityDecision:
        """Emit required stage/object/elapsed/ETA provisional progress."""

        if not stage.strip():
            raise ValueError("progress stage must not be empty")
        if objects_total < 0 or not 0 <= objects_complete <= objects_total:
            raise ValueError("progress object counts are invalid")
        if elapsed_seconds < 0 or (eta_seconds is not None and eta_seconds < 0):
            raise ValueError("progress timing values must be non-negative")
        body = dict(payload or {})
        body.update({
            "current_stage": stage,
            "objects_complete": objects_complete,
            "objects_total": objects_total,
            "elapsed_seconds": elapsed_seconds,
            "eta_seconds": eta_seconds,
        })
        return self.emit("pipeline.progress", body)

    def replay(
        self,
        after_event_id: str | int | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[PipelineEvent, ...]:
        """Replay stored events after an SSE Last-Event-ID/reconnect cursor."""

        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        with self._lock:
            start = 0
            if after_event_id is not None:
                if isinstance(after_event_id, int):
                    matching = [i for i, event in enumerate(self._events)
                                if event.sequence == after_event_id]
                else:
                    cursor = str(after_event_id)
                    matching = [i for i, event in enumerate(self._events)
                                if event.event_id == cursor]
                if not matching:
                    raise ReplayCursorError(f"unknown replay cursor: {after_event_id}")
                start = matching[0] + 1
            result = self._events[start:]
            if limit is not None:
                result = result[:limit]
            return tuple(result)

    def replay_sse(
        self,
        after_event_id: str | int | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[str, ...]:
        return tuple(event.to_sse() for event in self.replay(after_event_id, limit=limit))

    def replay_websocket(
        self,
        after_event_id: str | int | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(event.to_websocket() for event in self.replay(after_event_id, limit=limit))

    @staticmethod
    def encode_for_transport(event: PipelineEvent, transport: str) -> str | dict[str, Any]:
        normalized = transport.lower().replace("-", "_")
        if normalized == "sse":
            return event.to_sse()
        if normalized in {"websocket", "web_socket", "ws", "sidecar", "compiler"}:
            return event.to_websocket()
        raise ValueError(f"unsupported event transport: {transport}")

    def _finality_error(
        self,
        revision: str | None,
        digest: str | None,
        payload: Mapping[str, Any],
    ) -> str | None:
        reason = self._binding_mismatch(revision, digest)
        if reason:
            return reason
        if not self._authorized:
            return "finality has not been authorized by structural and parity gates"
        if self._contract_registration_sequence is None:
            return "verified contract must be registered before final events"
        next_sequence = len(self._events) + 1
        if next_sequence <= self._contract_registration_sequence:
            return "contract-before-final ordering violated"
        object_id = payload.get("object_id")
        if object_id is not None:
            if not str(object_id):
                return "final object event has an empty object identity"
            solved = self._binding.solved_objects.get(str(object_id))
            if solved is None:
                return f"object {object_id} is not present in the solved WorldContract"
            for key in ("position", "rotation", "scale", "asset_binding", "material_intent"):
                if key in payload and _json_copy(payload[key]) != _json_copy(solved[key]):
                    return f"final object event {key} does not match solved WorldContract"
        return None

    def _binding_mismatch(
        self,
        revision: str | int | None,
        digest: str | None,
        *,
        require_both: bool = True,
    ) -> str | None:
        if self._binding is None:
            return "no verified WorldContract is registered"
        if require_both and revision is None:
            return "final event is missing plan revision"
        if require_both and digest is None:
            return "final event is missing canonical hash"
        if revision is not None and _revision_text(revision) != self._binding.plan_revision:
            return (
                f"stale plan revision {_revision_text(revision)!r}; "
                f"active revision is {self._binding.plan_revision!r}"
            )
        if digest is not None and digest != self._binding.contract_hash:
            return "event canonical hash does not match active WorldContract"
        return None

    def _bind_solved_object(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = _json_copy(dict(payload))
        object_id = body.get("object_id")
        if object_id is not None:
            solved = self._binding.solved_objects[str(object_id)]
            for key in ("position", "rotation", "scale", "asset_binding", "material_intent"):
                body[key] = _json_copy(solved[key])
        return body

    def _new_event(
        self,
        *,
        event_type: str,
        finality: EventFinality,
        origin: EventOrigin,
        payload: Mapping[str, Any],
        plan_revision: str | None,
        contract_hash: str | None,
        producer_event_id: str | None = None,
        diagnostic: str | None = None,
    ) -> PipelineEvent:
        sequence = len(self._events) + 1
        return PipelineEvent(
            event_id=f"{self.session_id}:{sequence}",
            sequence=sequence,
            session_id=self.session_id,
            event_type=event_type,
            finality=finality,
            origin=origin,
            payload=_json_copy(dict(payload)),
            plan_revision=plan_revision,
            contract_hash=contract_hash,
            producer_event_id=producer_event_id,
            diagnostic=diagnostic,
        )

    def _append(self, event: PipelineEvent) -> PipelineEvent:
        expected = len(self._events) + 1
        if event.sequence != expected:
            raise EventJournalError(
                f"event sequence {event.sequence} is not contiguous; expected {expected}"
            )
        if event.finality is EventFinality.FINAL:
            if self._binding is None or self._contract_registration_sequence is None:
                raise EventJournalError("cannot append final event before contract registration")
            if event.plan_revision != self._binding.plan_revision:
                raise EventJournalError("final event revision is not the active contract revision")
            if event.contract_hash != self._binding.contract_hash:
                raise EventJournalError("final event hash is not the active contract hash")
            if event.sequence <= self._contract_registration_sequence:
                raise EventJournalError("contract-before-final ordering violated")
        if self.journal_path is not None:
            self._append_to_disk(event)
        self._events.append(event)
        if event.producer_event_id:
            self._producer_ids[(event.origin, event.producer_event_id)] = event
        return event

    def _append_to_disk(self, event: PipelineEvent) -> None:
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
            with self.journal_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise EventJournalError(f"failed to persist event journal: {exc}") from exc

    def _load_journal(self) -> None:
        if not self.journal_path.exists():
            return
        try:
            lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise EventJournalError(f"failed to read event journal: {exc}") from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = PipelineEvent.from_dict(json.loads(line))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise EventJournalError(
                    f"invalid event journal record at line {line_number}: {exc}"
                ) from exc
            expected = len(self._events) + 1
            if event.session_id != self.session_id:
                raise EventJournalError("journal event belongs to a different session")
            if event.sequence != expected or event.event_id != f"{self.session_id}:{expected}":
                raise EventJournalError("journal event ordering or identity is corrupt")
            self._rehydrate_authority(event)
            if event.finality is EventFinality.FINAL:
                reason = self._binding_mismatch(event.plan_revision, event.contract_hash)
                if reason or self._contract_registration_sequence is None:
                    raise EventJournalError(
                        "journal contains a final event without a preceding matching contract"
                    )
                if event.event_type != "world_contract.finalized" and not self._authorized:
                    raise EventJournalError(
                        "journal contains a final event before gate authorization"
                    )
            self._events.append(event)
            if event.producer_event_id:
                key = (event.origin, event.producer_event_id)
                if key in self._producer_ids:
                    raise EventJournalError("journal contains duplicate producer event identity")
                self._producer_ids[key] = event

    def _rehydrate_authority(self, event: PipelineEvent) -> None:
        if event.event_type == "world_contract.registered":
            self._binding = ContractBinding.from_dict(event.payload)
            self._authorized = False
            self._contract_registration_sequence = event.sequence
            self._first_final_sequence = None
        elif event.event_type == "world_contract.finalized":
            if self._binding_mismatch(event.plan_revision, event.contract_hash) is not None:
                raise EventJournalError("finalization event does not match registered contract")
            if not (
                event.payload.get("structural_gates_passed") is True
                and event.payload.get("parity_gate_passed") is True
            ):
                raise EventJournalError("finalization event lacks passing gate evidence")
            self._authorized = True
            self._first_final_sequence = event.sequence
        elif event.event_type == "publication.blocked":
            if self._binding_mismatch(
                event.plan_revision, event.contract_hash, require_both=False
            ) is None:
                self._authorized = False


# Descriptive alias used by orchestration code and older design notes.
EventLedger = EventSystem


__all__ = [
    "ContractBinding",
    "EventDisposition",
    "EventFinality",
    "EventJournalError",
    "EventLedger",
    "EventOrigin",
    "EventRejected",
    "EventSystem",
    "EventSystemError",
    "FinalityDecision",
    "InvalidContractBinding",
    "MismatchPolicy",
    "PipelineEvent",
    "ReplayCursorError",
]
