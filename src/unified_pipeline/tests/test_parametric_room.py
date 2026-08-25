"""Focused Task 5.1 tests for the authoritative parametric room adapter."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.unified_pipeline.approval_gates import ApprovalGate
from src.unified_pipeline.camera_contract import CameraContract
from src.unified_pipeline.depth_bridge import (
    CameraAnchoredSimilarity,
    DepthEvidence,
    DepthEvidenceProvenance,
)
from src.unified_pipeline.mesh_shading import audit_glb_shading
from src.unified_pipeline.models import MetricPlan, PlanRevision
from src.unified_pipeline.parametric_room import (
    PLAN_AUTHORITY,
    AuthorityClaim,
    AuthorityConflictError,
    DepthDerivedMesh,
    DepthReferenceError,
    PlanBindingError,
    build_authoritative_parametric_room,
)
from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
from src.unified_pipeline.plan_validator import _compute_plan_hash


def _camera() -> CameraContract:
    return CameraContract(
        position=(0.0, 1.6, -1.2),
        target=(0.0, 1.1, 0.0),
    )


def _plan(*, width: float = 4.0, depth: float = 3.5) -> MetricPlan:
    base = MetricPlan(
        room_dimensions=(width, depth, 2.7),
        walls=_build_walls_from_dimensions(width, depth, 2.7),
        openings=(
            {"id": "entry", "type": "door", "wall": "south", "parameter": 0.5,
             "width": 0.9, "height": 2.1},
            {"id": "rain_window", "type": "window", "wall": "east", "parameter": 0.6,
             "width": 1.2, "height": 1.1, "sill_height": 0.9},
        ),
        template_id="kitchen",
    )
    revision = PlanRevision(
        revision=3,
        changed="approved normalized kitchenette",
        reason="blockout approval",
        plan_hash=_compute_plan_hash(base),
    )
    return replace(base, revisions=(revision,))


def _approval(plan: MetricPlan, camera: CameraContract) -> ApprovalGate:
    gate = ApprovalGate("blockout", "plan_blockout")
    gate.present({
        "plan_revision": plan.revisions[-1].revision,
        "camera_hash": camera.compute_hash(),
    })
    gate.approve()
    return gate


def _depth_evidence(tmp_path: Path, camera: CameraContract) -> DepthEvidence:
    depth_path = tmp_path / "depth.npy"
    normal_path = tmp_path / "normal.npy"
    depth_path.write_bytes(b"depth")
    normal_path.write_bytes(b"normal")
    return DepthEvidence(
        depth_map_path=str(depth_path),
        normal_map_path=str(normal_path),
        valid_pixel_ratio=0.95,
        depth_range_m=(0.5, 5.0),
        provenance=DepthEvidenceProvenance(
            session_id="task-5-1",
            source_image_path=str(tmp_path / "canon.png"),
            source_image_sha256="a" * 64,
            source_resolution=(1024, 768),
            depth_artifact_sha256="b" * 64,
        ),
        alignment=CameraAnchoredSimilarity(
            camera_hash=camera.compute_hash(),
            uniform_scale=1.25,
            translation_to_fit_m=(0.1, 0.0, -0.2),
        ),
        evidence_kind="aligned_appearance_reference",
    )


def test_builds_compiler_room_and_binds_every_authoritative_output() -> None:
    plan, camera = _plan(), _camera()

    room = build_authoritative_parametric_room(
        plan, camera, _approval(plan, camera)
    )

    assert room.spatial_authority == PLAN_AUTHORITY
    assert room.plan_revision == 3
    assert room.plan_hash == plan.revisions[-1].plan_hash
    assert room.camera_hash == camera.compute_hash()
    assert len(room.compiler_input_hash) == 64
    assert {item.role for item in room.elements} >= {
        "floor", "ceiling", "wall_segment"
    }
    assert {item.stable_id for item in room.openings} == {
        "entry", "rain_window"
    }
    assert {item.geometry_id for item in room.collision} == {
        item.stable_id for item in room.elements
    }
    assert all(item.body_mode == "STATIC" for item in room.collision)
    bindings = [item.binding for item in room.elements]
    bindings += [item.binding for item in room.openings]
    bindings += [item.binding for item in room.collision]
    bindings.append(room.navigable_bounds.binding)
    assert all(binding.plan_revision == 3 for binding in bindings)
    assert all(binding.plan_hash == room.plan_hash for binding in bindings)
    assert all(binding.camera_hash == room.camera_hash for binding in bindings)
    assert room.navigable_bounds.minimum_m == pytest.approx((-1.95, 0.0, -1.70))
    assert room.navigable_bounds.maximum_m == pytest.approx((1.95, 2.7, 1.70))


def test_compiler_wall_segments_leave_real_noncolliding_opening_gaps() -> None:
    plan, camera = _plan(), _camera()
    room = build_authoritative_parametric_room(
        plan, camera, _approval(plan, camera)
    )
    walls = [item for item in room.elements if item.role == "wall_segment"]

    assert walls
    assert all(not opening.collision_enabled for opening in room.openings)
    for opening in room.openings:
        horizontal_axis = 0 if opening.wall in {"north", "south"} else 1
        for segment in [
            item for item in walls if dict(item.metadata)["wall"] == opening.wall
        ]:
            inside_horizontal = (
                abs(opening.position_upbge[horizontal_axis] - segment.position_upbge[horizontal_axis])
                < segment.dimensions_upbge[horizontal_axis] / 2.0
            )
            inside_vertical = (
                abs(opening.position_upbge[2] - segment.position_upbge[2])
                < segment.dimensions_upbge[2] / 2.0
            )
            assert not (inside_horizontal and inside_vertical)


def test_south_door_and_north_window_apertures_have_no_architecture_collider() -> None:
    original, camera = _plan(), _camera()
    base = replace(
        original,
        openings=(
            {"id": "south_door", "type": "door", "wall": "south", "parameter": 0.3,
             "width": 0.9, "height": 2.1},
            {"id": "north_window", "type": "window", "wall": "north", "parameter": 0.65,
             "width": 1.2, "height": 1.1, "sill_height": 0.9},
        ),
        revisions=(),
    )
    plan = replace(base, revisions=(PlanRevision(
        revision=3,
        changed="south door and north window",
        reason="aperture collision regression",
        plan_hash=_compute_plan_hash(base),
    ),))
    room = build_authoritative_parametric_room(plan, camera, _approval(plan, camera))
    collision_by_geometry = {item.geometry_id: item for item in room.collision}

    assert {item.stable_id for item in room.openings} == {"south_door", "north_window"}
    assert not ({"south_door", "north_window"} & set(collision_by_geometry))
    for opening in room.openings:
        opening_center = (
            opening.position_upbge[0], opening.position_upbge[2], opening.position_upbge[1]
        )
        opening_half = (
            opening.dimensions_upbge[0] / 2.0,
            opening.dimensions_upbge[2] / 2.0,
            opening.dimensions_upbge[1] / 2.0,
        )
        blockers = []
        for collider in room.collision:
            if "wall" not in collider.geometry_id:
                continue
            center = (
                collider.position_upbge[0], collider.position_upbge[2], collider.position_upbge[1]
            )
            half = (
                collider.dimensions_upbge[0] / 2.0,
                collider.dimensions_upbge[2] / 2.0,
                collider.dimensions_upbge[1] / 2.0,
            )
            if all(
                abs(opening_center[index] - center[index])
                < opening_half[index] + half[index] - 1e-7
                for index in range(3)
            ):
                blockers.append(collider.geometry_id)
        assert blockers == []


def test_accepts_only_aligned_noncolliding_depth_appearance_mesh(tmp_path: Path) -> None:
    plan, camera = _plan(), _camera()
    mesh = tmp_path / "depth-reference.glb"
    mesh.write_bytes(b"optional depth appearance")
    depth = DepthDerivedMesh(
        mesh_path=str(mesh), evidence=_depth_evidence(tmp_path, camera)
    )

    room = build_authoritative_parametric_room(
        plan, camera, _approval(plan, camera), depth_mesh=depth
    )

    reference = room.depth_reference
    assert reference is not None
    assert reference.label == "optional_aligned_depth_appearance_reference"
    assert reference.optional is True
    assert reference.collision_enabled is False
    assert reference.spatial_authority is False
    assert reference.authority_claims == ()
    assert len(reference.mesh_sha256) == 64
    assert reference.alignment["camera_hash"] == camera.compute_hash()


def test_rejects_depth_mesh_aligned_to_another_camera(tmp_path: Path) -> None:
    plan, camera = _plan(), _camera()
    other = CameraContract(position=(0.2, 1.6, -1.2), target=(0.0, 1.1, 0.0))
    mesh = tmp_path / "depth-reference.glb"
    mesh.write_bytes(b"mesh")
    depth = DepthDerivedMesh(
        mesh_path=str(mesh), evidence=_depth_evidence(tmp_path, other)
    )

    with pytest.raises(DepthReferenceError, match="camera hash"):
        build_authoritative_parametric_room(
            plan, camera, _approval(plan, camera), depth_mesh=depth
        )


@pytest.mark.parametrize("scope", ["architecture", "collision", "navigation_geometry"])
def test_fails_closed_when_another_source_claims_spatial_authority(scope: str) -> None:
    plan, camera = _plan(), _camera()

    with pytest.raises(AuthorityConflictError, match="more than one source"):
        build_authoritative_parametric_room(
            plan,
            camera,
            _approval(plan, camera),
            authority_claims=(AuthorityClaim("depth_mesh", (scope,)),),
        )


def test_rejects_unapproved_stale_or_mutated_plan() -> None:
    plan, camera = _plan(), _camera()
    pending = ApprovalGate("blockout", "plan_blockout")
    pending.present({"plan_revision": 3, "camera_hash": camera.compute_hash()})
    with pytest.raises(PlanBindingError, match="approval"):
        build_authoritative_parametric_room(plan, camera, pending)

    stale = ApprovalGate("blockout", "plan_blockout")
    stale.present({"plan_revision": 2, "camera_hash": camera.compute_hash()})
    stale.approve()
    with pytest.raises(PlanBindingError, match="different Plan revision"):
        build_authoritative_parametric_room(plan, camera, stale)

    mutated = replace(plan, room_dimensions=(5.0, 3.5, 2.7))
    with pytest.raises(PlanBindingError, match="hash does not bind"):
        build_authoritative_parametric_room(
            mutated, camera, _approval(mutated, camera)
        )


def test_rejects_noncanonical_walls_even_when_room_is_closed() -> None:
    plan, camera = _plan(), _camera()
    shifted = tuple(
        {**wall, "start": tuple(value + 1.0 for value in wall["start"]),
         "end": tuple(value + 1.0 for value in wall["end"])}
        for wall in plan.walls
    )
    changed = replace(plan, walls=shifted, revisions=())
    changed = replace(changed, revisions=(PlanRevision(
        revision=4,
        changed="shifted",
        reason="test",
        plan_hash=_compute_plan_hash(changed),
    ),))

    with pytest.raises(PlanBindingError, match="not normalized"):
        build_authoritative_parametric_room(
            changed, camera, _approval(changed, camera)
        )


def test_exports_plan_only_render_shell_with_matching_open_collision(tmp_path: Path) -> None:
    from src.unified_pipeline.parametric_room import export_authoritative_room_glb

    plan, camera = _plan(), _camera()
    room = build_authoritative_parametric_room(
        plan, camera, _approval(plan, camera)
    )

    evidence = export_authoritative_room_glb(room, tmp_path / "room.glb")

    assert Path(evidence["path"]).is_file()
    assert len(evidence["sha256"]) == 64
    assert evidence["face_count"] > 0
    assert evidence["vertex_count"] > 0
    assert evidence["element_ids"] == evidence["collision_ids"]
    assert evidence["depth_geometry_used"] is False
    assert evidence["normalization_count"] == 0
    assert evidence["shading_authority"] == "explicit-exported-vertex-normals"
    assert evidence["material_metallic_factor"] == 0.0
    audit = audit_glb_shading(evidence["path"], expected_sha256=evidence["sha256"])
    assert audit.shading_model == "smooth"
    assert audit.primitives_with_normals == audit.primitive_count
    import trimesh
    loaded = trimesh.load(evidence["path"], force="scene", process=False)
    assert all(
        float(geometry.visual.material.metallicFactor) == 0.0
        for geometry in loaded.geometry.values()
    )
    assert {item["kind"] for item in evidence["opening_checks"]} == {"door", "window"}
    assert all(item["visual_clear"] and item["collision_clear"] for item in evidence["opening_checks"])
