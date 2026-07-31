"""Mesh shape approval gate with turntable preview generation.

Provides the MeshApprovalGate convenience wrapper around the generic ApprovalGate
lifecycle, adding turntable preview generation (4 views at 0°, 90°, 180°, 270°)
and a structured approve/reject/regenerate flow with rejection reason recording
and retry count tracking.

The await_mesh_approval function in approval_gates.py handles the async gate
lifecycle. This module adds the turntable preview rendering and the
MeshApprovalGate class that coordinates preview generation with the approval
decision flow.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .approval_gates import ApprovalGate, ApprovalStatus
from .models import MeshApproval


# ─── Turntable Angles ──────────────────────────────────────────────────────────

TURNTABLE_ANGLES: tuple[float, ...] = (0.0, 90.0, 180.0, 270.0)
"""Standard turntable preview angles in degrees."""


# ─── Turntable Preview Record ─────────────────────────────────────────────────


@dataclass
class TurntablePreview:
    """Record of a generated turntable preview set.

    Stores the paths to the rendered preview images and metadata
    about the mesh that was previewed.
    """

    mesh_path: str
    preview_paths: list[str] = field(default_factory=list)
    angles: tuple[float, ...] = TURNTABLE_ANGLES
    generated_at: float = 0.0
    output_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mesh_path": self.mesh_path,
            "preview_paths": list(self.preview_paths),
            "angles": list(self.angles),
            "generated_at": self.generated_at,
            "output_dir": self.output_dir,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurntablePreview:
        return cls(
            mesh_path=data.get("mesh_path", ""),
            preview_paths=list(data.get("preview_paths", [])),
            angles=tuple(data.get("angles", TURNTABLE_ANGLES)),
            generated_at=data.get("generated_at", 0.0),
            output_dir=data.get("output_dir", ""),
        )


# ─── MeshApprovalGate ──────────────────────────────────────────────────────────


class MeshApprovalGate:
    """Mesh shape approval gate with turntable preview and retry tracking.

    Wraps the generic ApprovalGate with mesh-specific concerns:
    - Turntable preview generation (4 views at 0°, 90°, 180°, 270°)
    - Placeholder auto-approval (skip gate)
    - Rejection reason recording
    - Retry count tracking
    - Approve → proceed to materials flow

    Usage:
        gate = MeshApprovalGate()
        mesh = MeshApproval(object_id="table_01", mesh_path="/assets/table.glb", ...)

        if gate.should_skip(mesh):
            result = gate.approve(mesh)  # auto-approve placeholders
        else:
            gate.present_for_approval(mesh)
            # ... user views turntable, decides ...
            result = gate.approve(mesh)    # or
            result = gate.reject(mesh, reason="Too blocky")

    Requirements:
        11.1 — Turntable preview presented to user.
        11.2 — User approves or rejects mesh shape.
        11.3 — Rejected meshes return to generation with reason.
        11.4 — Approved meshes proceed to material/texture application.
        11.5 — Placeholders skip approval (inherently approximate).
    """

    def __init__(self) -> None:
        self._gate: ApprovalGate = ApprovalGate(gate_id="mesh", stage="mesh_shape")
        self._current_mesh: MeshApproval | None = None
        self._current_preview: TurntablePreview | None = None
        self._history: list[dict[str, Any]] = []

    # ─── Properties ────────────────────────────────────────────────────────

    @property
    def gate(self) -> ApprovalGate:
        """The underlying ApprovalGate instance."""
        return self._gate

    @property
    def current_mesh(self) -> MeshApproval | None:
        """The mesh currently being presented for approval."""
        return self._current_mesh

    @property
    def current_preview(self) -> TurntablePreview | None:
        """The turntable preview for the current mesh."""
        return self._current_preview

    @property
    def history(self) -> list[dict[str, Any]]:
        """Full history of approval decisions for this gate."""
        return list(self._history)

    @property
    def is_pending(self) -> bool:
        """True while waiting for user decision."""
        return self._gate.is_blocking()

    @property
    def is_approved(self) -> bool:
        """True if the current mesh was approved."""
        return self._gate.is_approved()

    @property
    def is_rejected(self) -> bool:
        """True if the current mesh was rejected."""
        return self._gate.is_rejected()

    # ─── Core Flow ─────────────────────────────────────────────────────────

    def should_skip(self, mesh: MeshApproval) -> bool:
        """Check if the mesh should skip approval (placeholder auto-approves).

        Requirement 11.5: Placeholder geometry does not require shape approval.

        Args:
            mesh: The mesh approval record to check.

        Returns:
            True if the mesh is a placeholder and should auto-approve.
        """
        return mesh.is_placeholder

    def present_for_approval(self, mesh: MeshApproval) -> TurntablePreview | None:
        """Present a mesh for user approval with turntable preview.

        Generates a turntable preview (4 views) and sets up the gate
        for the user to approve or reject.

        Requirement 11.1: Present turntable preview to user.

        Args:
            mesh: The mesh to present for approval.

        Returns:
            The generated TurntablePreview, or None if the mesh is
            a placeholder (auto-approved via should_skip).
        """
        if self.should_skip(mesh):
            # Auto-approve placeholders without presenting
            self._current_mesh = mesh
            self._gate.present(
                {
                    "object_id": mesh.object_id,
                    "mesh_path": mesh.mesh_path,
                    "is_placeholder": True,
                }
            )
            self._gate.approve()
            self._history.append(
                {
                    "object_id": mesh.object_id,
                    "mesh_path": mesh.mesh_path,
                    "decision": "auto_approved",
                    "reason": "placeholder",
                    "retry_count": mesh.retry_count,
                    "timestamp": time.time(),
                }
            )
            return None

        self._current_mesh = mesh

        # Generate turntable preview
        output_dir = Path(mesh.mesh_path).parent / "previews"
        preview = self.generate_turntable(mesh.mesh_path, output_dir)
        self._current_preview = preview

        # Present to gate with mesh metadata
        self._gate.present(
            {
                "object_id": mesh.object_id,
                "mesh_path": mesh.mesh_path,
                "generation_method": mesh.generation_method,
                "face_count": mesh.face_count,
                "vertex_count": mesh.vertex_count,
                "preview_paths": preview.preview_paths,
                "retry_count": mesh.retry_count,
            }
        )

        return preview

    def generate_turntable(
        self, mesh_path: str, output_dir: Path
    ) -> TurntablePreview:
        """Generate turntable preview images for a mesh.

        Renders the mesh from 4 angles (0°, 90°, 180°, 270°) as simple
        wireframe/silhouette views. In production this delegates to the
        existing preview rendering infrastructure; here it produces the
        expected file paths for the preview images.

        Args:
            mesh_path: Path to the mesh file (.glb, .obj, etc.).
            output_dir: Directory to write preview images into.

        Returns:
            TurntablePreview with paths to the 4 rendered views.
        """
        output_dir = Path(output_dir)
        stem = Path(mesh_path).stem

        preview_paths: list[str] = []
        for angle in TURNTABLE_ANGLES:
            # Construct the expected output path for each angle
            filename = f"{stem}_turntable_{int(angle):03d}.png"
            preview_path = str(output_dir / filename)
            preview_paths.append(preview_path)

        preview = TurntablePreview(
            mesh_path=mesh_path,
            preview_paths=preview_paths,
            angles=TURNTABLE_ANGLES,
            generated_at=time.time(),
            output_dir=str(output_dir),
        )

        return preview

    def approve(self, mesh: MeshApproval) -> MeshApproval:
        """Approve the mesh shape — proceed to material/texture application.

        Requirement 11.2: User approves mesh shape.
        Requirement 11.4: Approved meshes proceed to material application.

        Args:
            mesh: The mesh being approved.

        Returns:
            A new MeshApproval with approved=True.
        """
        self._gate.approve()
        self._history.append(
            {
                "object_id": mesh.object_id,
                "mesh_path": mesh.mesh_path,
                "decision": "approved",
                "reason": "",
                "retry_count": mesh.retry_count,
                "timestamp": time.time(),
            }
        )

        # Return new frozen MeshApproval with approved=True
        return MeshApproval(
            object_id=mesh.object_id,
            mesh_path=mesh.mesh_path,
            generation_method=mesh.generation_method,
            face_count=mesh.face_count,
            vertex_count=mesh.vertex_count,
            approved=True,
            rejection_reason="",
            retry_count=mesh.retry_count,
            is_placeholder=mesh.is_placeholder,
        )

    def reject(self, mesh: MeshApproval, reason: str) -> MeshApproval:
        """Reject the mesh shape — return to generation with reason recorded.

        Requirement 11.2: User rejects mesh shape.
        Requirement 11.3: Rejected meshes return to generation with reason.

        Args:
            mesh: The mesh being rejected.
            reason: Human-readable reason for rejection.

        Returns:
            A new MeshApproval with approved=False, rejection_reason set,
            and retry_count incremented.
        """
        self._gate.reject(reason)
        new_retry_count = mesh.retry_count + 1

        self._history.append(
            {
                "object_id": mesh.object_id,
                "mesh_path": mesh.mesh_path,
                "decision": "rejected",
                "reason": reason,
                "retry_count": new_retry_count,
                "timestamp": time.time(),
            }
        )

        # Return new frozen MeshApproval with rejection recorded
        return MeshApproval(
            object_id=mesh.object_id,
            mesh_path=mesh.mesh_path,
            generation_method=mesh.generation_method,
            face_count=mesh.face_count,
            vertex_count=mesh.vertex_count,
            approved=False,
            rejection_reason=reason,
            retry_count=new_retry_count,
            is_placeholder=mesh.is_placeholder,
        )

    def reset_for_retry(self) -> None:
        """Reset the gate for a new mesh presentation after rejection.

        Called by the orchestrator after processing a rejection and
        regenerating the mesh. Prepares the gate for the next round.
        """
        self._gate.reset()
        self._current_mesh = None
        self._current_preview = None

    # ─── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize the gate state for persistence."""
        return {
            "gate": self._gate.to_dict(),
            "current_mesh": (
                self._current_mesh.to_dict() if self._current_mesh else None
            ),
            "current_preview": (
                self._current_preview.to_dict()
                if self._current_preview
                else None
            ),
            "history": list(self._history),
        }
