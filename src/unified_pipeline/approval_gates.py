"""Human approval gate infrastructure for the Unified World Pipeline.

Provides a generic ApprovalGate class and stage-specific gate functions
(blockout, canon, mesh) that block downstream processing until the user
approves or provides revision feedback.

Requirements: 7.3, 7.4, 7.5, 8.4, 8.7, 11.1, 11.2, 11.3
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from .models import BlockoutResult, SceneCanon, MeshApproval


# ─── Enums ─────────────────────────────────────────────────────────────────────


class ApprovalStatus(Enum):
    """Status of an approval gate."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ─── Data Records ──────────────────────────────────────────────────────────────


@dataclass
class ApprovalRecord:
    """Immutable record of one approval decision.

    Records what was presented, when, the decision, and any feedback.
    """

    gate_id: str
    stage: str
    timestamp: float
    decision: ApprovalStatus
    feedback: str = ""
    revision: int = 1
    presented_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "stage": self.stage,
            "timestamp": self.timestamp,
            "decision": self.decision.value,
            "feedback": self.feedback,
            "revision": self.revision,
            "presented_data": self.presented_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRecord:
        return cls(
            gate_id=data.get("gate_id", ""),
            stage=data.get("stage", ""),
            timestamp=data.get("timestamp", 0.0),
            decision=ApprovalStatus(data.get("decision", "pending")),
            feedback=data.get("feedback", ""),
            revision=data.get("revision", 1),
            presented_data=data.get("presented_data", {}),
        )


# ─── Generic Approval Gate ─────────────────────────────────────────────────────


class ApprovalGate:
    """Generic human approval gate — reusable for blockout, canon, mesh, etc.

    The gate blocks downstream processing while status is PENDING.
    Supports approve/reject/reset cycle for revision loops.
    """

    def __init__(self, gate_id: str, stage: str = "") -> None:
        self.gate_id: str = gate_id
        self.stage: str = stage or gate_id
        self._status: ApprovalStatus = ApprovalStatus.PENDING
        self._feedback: str = ""
        self._revision_count: int = 0
        self._records: list[ApprovalRecord] = []
        self._presented_at: float = 0.0
        self._presented_data: dict[str, Any] = {}
        self._event: asyncio.Event = asyncio.Event()

    # ─── Properties ────────────────────────────────────────────────────────

    @property
    def status(self) -> ApprovalStatus:
        """Current gate status."""
        return self._status

    @property
    def feedback(self) -> str:
        """Rejection feedback (empty if approved or pending)."""
        return self._feedback

    @property
    def revision_count(self) -> int:
        """Number of revision cycles completed."""
        return self._revision_count

    @property
    def records(self) -> list[ApprovalRecord]:
        """All approval records for this gate (full history)."""
        return list(self._records)

    # ─── Actions ───────────────────────────────────────────────────────────

    def present(self, data: dict[str, Any] | None = None) -> None:
        """Mark what is being presented for approval.

        Call this before waiting for user decision.
        """
        self._presented_at = time.time()
        self._presented_data = data or {}
        self._status = ApprovalStatus.PENDING
        self._feedback = ""
        self._event.clear()

    def approve(self) -> None:
        """User approves the current presentation.

        Sets status to APPROVED and unblocks any waiters.
        """
        self._status = ApprovalStatus.APPROVED
        self._feedback = ""
        self._records.append(
            ApprovalRecord(
                gate_id=self.gate_id,
                stage=self.stage,
                timestamp=time.time(),
                decision=ApprovalStatus.APPROVED,
                feedback="",
                revision=self._revision_count + 1,
                presented_data=self._presented_data,
            )
        )
        self._event.set()

    def reject(self, feedback: str) -> None:
        """User rejects with feedback, triggering a revision cycle.

        Sets status to REJECTED and unblocks any waiters. The orchestrator
        is responsible for reading the feedback and initiating a revision.
        """
        self._status = ApprovalStatus.REJECTED
        self._feedback = feedback
        self._revision_count += 1
        self._records.append(
            ApprovalRecord(
                gate_id=self.gate_id,
                stage=self.stage,
                timestamp=time.time(),
                decision=ApprovalStatus.REJECTED,
                feedback=feedback,
                revision=self._revision_count,
                presented_data=self._presented_data,
            )
        )
        self._event.set()

    def reset(self) -> None:
        """Reset to PENDING for the next revision round.

        Called after a rejection has been processed and a new revision
        is ready to be presented.
        """
        self._status = ApprovalStatus.PENDING
        self._feedback = ""
        self._event.clear()

    # ─── Queries ───────────────────────────────────────────────────────────

    def is_approved(self) -> bool:
        """True if the gate has been approved."""
        return self._status == ApprovalStatus.APPROVED

    def is_blocking(self) -> bool:
        """True while the gate is PENDING (blocks downstream)."""
        return self._status == ApprovalStatus.PENDING

    def is_rejected(self) -> bool:
        """True if the gate was rejected (needs revision)."""
        return self._status == ApprovalStatus.REJECTED

    # ─── Async Wait ────────────────────────────────────────────────────────

    async def wait_for_decision(self) -> ApprovalStatus:
        """Block until the user approves or rejects.

        Returns the decision status (APPROVED or REJECTED).
        """
        await self._event.wait()
        return self._status

    # ─── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "stage": self.stage,
            "status": self._status.value,
            "feedback": self._feedback,
            "revision_count": self._revision_count,
            "presented_at": self._presented_at,
            "presented_data": self._presented_data,
            "records": [r.to_dict() for r in self._records],
        }


# ─── Stage-Specific Gate Functions ─────────────────────────────────────────────


async def await_blockout_approval(
    blockout: BlockoutResult,
    *,
    on_revision: Callable[[str, int], Awaitable[BlockoutResult]] | None = None,
) -> ApprovalGate:
    """Create and wait on a blockout approval gate.

    Blocks downstream (Canon generation) until the user approves the
    spatial layout. If rejected, triggers revision loop:
    feedback → new Plan revision → re-render → re-approve.

    Args:
        blockout: The current blockout result to present for approval.
        on_revision: Optional async callback invoked on rejection.
            Receives (feedback, revision_number) and returns a new
            BlockoutResult after re-planning and re-rendering.

    Returns:
        The ApprovalGate in APPROVED state (downstream can proceed).

    Requirements:
        7.3 — User approves or revises Blockout before Canon generation.
        7.4 — Revision loop: feedback → new Plan → re-render → re-approve.
        7.5 — No expensive generation before Blockout approval.
    """
    gate = ApprovalGate(gate_id="blockout", stage="plan_blockout")
    gate.present(
        {
            "image_path": blockout.image_path,
            "plan_revision": blockout.plan_revision,
            "camera_hash": blockout.camera_hash,
        }
    )

    while True:
        decision = await gate.wait_for_decision()

        if decision == ApprovalStatus.APPROVED:
            return gate

        # REJECTED — revision loop
        if on_revision is not None:
            new_blockout = await on_revision(
                gate.feedback, gate.revision_count
            )
            gate.reset()
            gate.present(
                {
                    "image_path": new_blockout.image_path,
                    "plan_revision": new_blockout.plan_revision,
                    "camera_hash": new_blockout.camera_hash,
                }
            )
        else:
            # No revision callback — return with rejected state for
            # the orchestrator to handle externally.
            return gate


async def await_canon_approval(
    canon: SceneCanon,
    *,
    on_revision: Callable[[str, int], Awaitable[SceneCanon]] | None = None,
) -> ApprovalGate:
    """Create and wait on a Scene Canon approval gate.

    Blocks mesh generation until the user approves the photorealistic
    reference image.

    Args:
        canon: The current Scene Canon result to present.
        on_revision: Optional async callback for regeneration on rejection.
            Receives (feedback, revision_number) and returns a new SceneCanon.

    Returns:
        The ApprovalGate in APPROVED state (downstream can proceed).

    Requirements:
        8.4 — User approves, rejects, or requests regeneration of Canon.
        8.7 — No mesh generation before Canon approval.
    """
    gate = ApprovalGate(gate_id="canon", stage="scene_canon")
    gate.present(
        {
            "image_path": canon.image_path,
            "plan_revision": canon.plan_revision,
            "camera_hash": canon.camera_hash,
            "canon_hash": canon.canon_hash,
            "object_verdicts": dict(canon.object_verdicts),
        }
    )

    while True:
        decision = await gate.wait_for_decision()

        if decision == ApprovalStatus.APPROVED:
            return gate

        # REJECTED — regeneration loop
        if on_revision is not None:
            new_canon = await on_revision(gate.feedback, gate.revision_count)
            gate.reset()
            gate.present(
                {
                    "image_path": new_canon.image_path,
                    "plan_revision": new_canon.plan_revision,
                    "camera_hash": new_canon.camera_hash,
                    "canon_hash": new_canon.canon_hash,
                    "object_verdicts": dict(new_canon.object_verdicts),
                }
            )
        else:
            return gate


async def await_mesh_approval(
    mesh: MeshApproval,
    *,
    on_revision: Callable[[str, int], Awaitable[MeshApproval]] | None = None,
) -> ApprovalGate:
    """Create and wait on a mesh shape approval gate.

    Blocks material application until the user approves mesh geometry.
    Placeholder meshes skip this gate (they are inherently approximate).

    Args:
        mesh: The current mesh approval record to present.
        on_revision: Optional async callback for regeneration on rejection.
            Receives (feedback, revision_number) and returns a new MeshApproval.

    Returns:
        The ApprovalGate in APPROVED state (downstream can proceed).

    Requirements:
        11.1 — Turntable preview presented to user.
        11.2 — User approves or rejects mesh shape.
        11.3 — Rejected meshes return to generation with reason.
        11.5 — Placeholders skip approval (inherently approximate).
    """
    # Placeholders auto-approve — they don't need human shape approval
    if mesh.is_placeholder:
        gate = ApprovalGate(gate_id="mesh", stage="mesh_shape")
        gate.present(
            {
                "object_id": mesh.object_id,
                "mesh_path": mesh.mesh_path,
                "is_placeholder": True,
            }
        )
        gate.approve()
        return gate

    gate = ApprovalGate(gate_id="mesh", stage="mesh_shape")
    gate.present(
        {
            "object_id": mesh.object_id,
            "mesh_path": mesh.mesh_path,
            "generation_method": mesh.generation_method,
            "face_count": mesh.face_count,
            "vertex_count": mesh.vertex_count,
        }
    )

    while True:
        decision = await gate.wait_for_decision()

        if decision == ApprovalStatus.APPROVED:
            return gate

        # REJECTED — regeneration loop
        if on_revision is not None:
            new_mesh = await on_revision(gate.feedback, gate.revision_count)
            if new_mesh.is_placeholder:
                # Fell through to placeholder — auto-approve
                gate.reset()
                gate.present(
                    {
                        "object_id": new_mesh.object_id,
                        "mesh_path": new_mesh.mesh_path,
                        "is_placeholder": True,
                    }
                )
                gate.approve()
                return gate
            gate.reset()
            gate.present(
                {
                    "object_id": new_mesh.object_id,
                    "mesh_path": new_mesh.mesh_path,
                    "generation_method": new_mesh.generation_method,
                    "face_count": new_mesh.face_count,
                    "vertex_count": new_mesh.vertex_count,
                }
            )
        else:
            return gate
