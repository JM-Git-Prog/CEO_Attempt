"""Tests for the MeshApprovalGate module.

Validates:
- Turntable preview generation (4 views at correct angles)
- Approve flow returns MeshApproval(approved=True)
- Reject flow records reason and increments retry_count
- Placeholder auto-approval via should_skip
- History tracking across approve/reject cycles
- Reset for retry clears state for next round

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5
"""

from __future__ import annotations

from pathlib import Path

import pytest

from unified_pipeline.mesh_approval import (
    MeshApprovalGate,
    TurntablePreview,
    TURNTABLE_ANGLES,
)
from unified_pipeline.models import MeshApproval


# ─── TurntablePreview ──────────────────────────────────────────────────────────


class TestTurntablePreview:
    def test_round_trip_serialization(self):
        preview = TurntablePreview(
            mesh_path="/assets/table.glb",
            preview_paths=[
                "/previews/table_turntable_000.png",
                "/previews/table_turntable_090.png",
                "/previews/table_turntable_180.png",
                "/previews/table_turntable_270.png",
            ],
            angles=TURNTABLE_ANGLES,
            generated_at=1234567890.0,
            output_dir="/previews",
        )
        d = preview.to_dict()
        restored = TurntablePreview.from_dict(d)
        assert restored.mesh_path == "/assets/table.glb"
        assert len(restored.preview_paths) == 4
        assert restored.angles == TURNTABLE_ANGLES
        assert restored.generated_at == 1234567890.0

    def test_from_dict_defaults(self):
        preview = TurntablePreview.from_dict({})
        assert preview.mesh_path == ""
        assert preview.preview_paths == []
        assert preview.angles == TURNTABLE_ANGLES


# ─── MeshApprovalGate: should_skip ────────────────────────────────────────────


class TestMeshApprovalGateShouldSkip:
    def test_placeholder_skips(self):
        """Req 11.5: Placeholder geometry auto-approves."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="chair_01",
            mesh_path="/assets/placeholder_chair.glb",
            generation_method="placeholder",
            face_count=12,
            vertex_count=8,
            is_placeholder=True,
        )
        assert gate.should_skip(mesh) is True

    def test_generated_mesh_does_not_skip(self):
        """Req 11.1: Generated meshes require approval."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="table_01",
            mesh_path="/assets/table.glb",
            generation_method="hunyuan3d",
            face_count=5000,
            vertex_count=2500,
            is_placeholder=False,
        )
        assert gate.should_skip(mesh) is False


# ─── MeshApprovalGate: Turntable Preview Generation ──────────────────────────


class TestTurntableGeneration:
    def test_generates_four_views(self):
        """Req 11.1: Turntable preview with 4 views at standard angles."""
        gate = MeshApprovalGate()
        output_dir = Path("/tmp/previews")
        preview = gate.generate_turntable("/assets/table.glb", output_dir)

        assert len(preview.preview_paths) == 4
        assert preview.angles == (0.0, 90.0, 180.0, 270.0)
        assert preview.mesh_path == "/assets/table.glb"
        assert preview.generated_at > 0

    def test_preview_paths_use_mesh_stem(self):
        """Preview filenames include the mesh stem and angle."""
        gate = MeshApprovalGate()
        output_dir = Path("/tmp/previews")
        preview = gate.generate_turntable("/assets/my_chair.glb", output_dir)

        assert "my_chair_turntable_000.png" in preview.preview_paths[0]
        assert "my_chair_turntable_090.png" in preview.preview_paths[1]
        assert "my_chair_turntable_180.png" in preview.preview_paths[2]
        assert "my_chair_turntable_270.png" in preview.preview_paths[3]

    def test_preview_paths_in_output_dir(self):
        """Preview images are placed in the specified output directory."""
        gate = MeshApprovalGate()
        output_dir = Path("/output/meshes/previews")
        preview = gate.generate_turntable("/assets/lamp.obj", output_dir)

        for path in preview.preview_paths:
            assert path.startswith(str(output_dir))


# ─── MeshApprovalGate: Present for Approval ───────────────────────────────────


class TestPresentForApproval:
    def test_present_non_placeholder_generates_preview(self):
        """Req 11.1: Non-placeholder mesh gets turntable preview."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="table_01",
            mesh_path="/assets/table.glb",
            generation_method="hunyuan3d",
            face_count=5000,
            vertex_count=2500,
            is_placeholder=False,
        )
        preview = gate.present_for_approval(mesh)

        assert preview is not None
        assert len(preview.preview_paths) == 4
        assert gate.current_mesh == mesh
        assert gate.current_preview == preview
        assert gate.is_pending

    def test_present_placeholder_auto_approves(self):
        """Req 11.5: Placeholder auto-approves without preview."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="chair_02",
            mesh_path="/assets/placeholder_chair.glb",
            generation_method="placeholder",
            face_count=12,
            vertex_count=8,
            is_placeholder=True,
        )
        preview = gate.present_for_approval(mesh)

        assert preview is None
        assert gate.is_approved
        assert not gate.is_pending
        assert len(gate.history) == 1
        assert gate.history[0]["decision"] == "auto_approved"


# ─── MeshApprovalGate: Approve ────────────────────────────────────────────────


class TestApproveFlow:
    def test_approve_returns_approved_mesh(self):
        """Req 11.2, 11.4: Approved mesh proceeds to materials."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="table_01",
            mesh_path="/assets/table.glb",
            generation_method="hunyuan3d",
            face_count=5000,
            vertex_count=2500,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh)
        result = gate.approve(mesh)

        assert result.approved is True
        assert result.rejection_reason == ""
        assert result.retry_count == 0
        assert result.object_id == "table_01"
        assert result.mesh_path == "/assets/table.glb"
        assert gate.is_approved

    def test_approve_records_in_history(self):
        """Approval decision is recorded in history."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="lamp_01",
            mesh_path="/assets/lamp.glb",
            generation_method="trellis2",
            face_count=3000,
            vertex_count=1500,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh)
        gate.approve(mesh)

        assert len(gate.history) == 1
        assert gate.history[0]["decision"] == "approved"
        assert gate.history[0]["object_id"] == "lamp_01"


# ─── MeshApprovalGate: Reject ─────────────────────────────────────────────────


class TestRejectFlow:
    def test_reject_returns_mesh_with_reason(self):
        """Req 11.3: Rejected mesh has reason recorded."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="table_01",
            mesh_path="/assets/table.glb",
            generation_method="hunyuan3d",
            face_count=5000,
            vertex_count=2500,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh)
        result = gate.reject(mesh, reason="Shape looks nothing like a table")

        assert result.approved is False
        assert result.rejection_reason == "Shape looks nothing like a table"
        assert result.retry_count == 1
        assert gate.is_rejected

    def test_reject_increments_retry_count(self):
        """Req 11.3: Each rejection increments retry count."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="chair_01",
            mesh_path="/assets/chair.glb",
            generation_method="hunyuan3d",
            face_count=4000,
            vertex_count=2000,
            retry_count=2,  # Already been rejected twice
            is_placeholder=False,
        )
        gate.present_for_approval(mesh)
        result = gate.reject(mesh, reason="Still too blocky")

        assert result.retry_count == 3  # 2 + 1

    def test_reject_records_in_history(self):
        """Rejection with reason is recorded in history."""
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="vase_01",
            mesh_path="/assets/vase.glb",
            generation_method="trellis2",
            face_count=2000,
            vertex_count=1000,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh)
        gate.reject(mesh, reason="Missing handle")

        assert len(gate.history) == 1
        assert gate.history[0]["decision"] == "rejected"
        assert gate.history[0]["reason"] == "Missing handle"
        assert gate.history[0]["retry_count"] == 1


# ─── MeshApprovalGate: Full Reject → Retry → Approve Cycle ───────────────────


class TestFullRetryLoop:
    def test_reject_reset_approve_cycle(self):
        """Req 11.3, 11.4: Full reject → regenerate → approve cycle."""
        gate = MeshApprovalGate()

        # First attempt: rejected
        mesh_v1 = MeshApproval(
            object_id="table_01",
            mesh_path="/assets/table_v1.glb",
            generation_method="hunyuan3d",
            face_count=5000,
            vertex_count=2500,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh_v1)
        rejected = gate.reject(mesh_v1, reason="Legs are too short")
        assert rejected.retry_count == 1
        assert rejected.rejection_reason == "Legs are too short"

        # Reset for retry
        gate.reset_for_retry()
        assert gate.current_mesh is None
        assert gate.current_preview is None

        # Second attempt: approved
        mesh_v2 = MeshApproval(
            object_id="table_01",
            mesh_path="/assets/table_v2.glb",
            generation_method="hunyuan3d",
            face_count=5200,
            vertex_count=2600,
            retry_count=rejected.retry_count,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh_v2)
        approved = gate.approve(mesh_v2)

        assert approved.approved is True
        assert approved.retry_count == 1
        assert gate.is_approved
        assert len(gate.history) == 2
        assert gate.history[0]["decision"] == "rejected"
        assert gate.history[1]["decision"] == "approved"

    def test_multiple_rejections_before_approve(self):
        """Multiple rejection rounds track correctly."""
        gate = MeshApprovalGate()

        # Reject round 1
        mesh_v1 = MeshApproval(
            object_id="obj_01",
            mesh_path="/assets/obj_v1.glb",
            generation_method="hunyuan3d",
            face_count=3000,
            vertex_count=1500,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh_v1)
        r1 = gate.reject(mesh_v1, reason="Wrong proportions")
        assert r1.retry_count == 1
        gate.reset_for_retry()

        # Reject round 2
        mesh_v2 = MeshApproval(
            object_id="obj_01",
            mesh_path="/assets/obj_v2.glb",
            generation_method="trellis2",
            face_count=3500,
            vertex_count=1750,
            retry_count=1,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh_v2)
        r2 = gate.reject(mesh_v2, reason="Still not right")
        assert r2.retry_count == 2
        gate.reset_for_retry()

        # Approve round 3
        mesh_v3 = MeshApproval(
            object_id="obj_01",
            mesh_path="/assets/obj_v3.glb",
            generation_method="hunyuan3d",
            face_count=4000,
            vertex_count=2000,
            retry_count=2,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh_v3)
        final = gate.approve(mesh_v3)

        assert final.approved is True
        assert final.retry_count == 2
        assert len(gate.history) == 3


# ─── MeshApprovalGate: Serialization ──────────────────────────────────────────


class TestMeshApprovalGateSerialization:
    def test_to_dict_with_pending_mesh(self):
        gate = MeshApprovalGate()
        mesh = MeshApproval(
            object_id="obj_01",
            mesh_path="/assets/obj.glb",
            generation_method="hunyuan3d",
            face_count=5000,
            vertex_count=2500,
            is_placeholder=False,
        )
        gate.present_for_approval(mesh)
        d = gate.to_dict()

        assert d["gate"]["gate_id"] == "mesh"
        assert d["gate"]["stage"] == "mesh_shape"
        assert d["current_mesh"]["object_id"] == "obj_01"
        assert d["current_preview"] is not None
        assert len(d["current_preview"]["preview_paths"]) == 4

    def test_to_dict_empty_gate(self):
        gate = MeshApprovalGate()
        d = gate.to_dict()

        assert d["current_mesh"] is None
        assert d["current_preview"] is None
        assert d["history"] == []
