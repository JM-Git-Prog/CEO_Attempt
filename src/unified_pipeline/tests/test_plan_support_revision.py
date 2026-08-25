"""Focused Task 11.8 Slice J regressions for Plan-owned support repair."""
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from src.unified_pipeline.approval_gates import ApprovalGate, ApprovalStatus
from src.unified_pipeline.assembler import DEFAULT_PLAYER_RADIUS_M
from src.unified_pipeline.blockout_renderer import BlockoutRenderer, load_blockout_visibility
from src.unified_pipeline.canon_first_authority import derive_camera_from_plan
from src.unified_pipeline.models import MetricPlan, PlanRevision
from src.unified_pipeline.plan_generator import MetricPlanGenerator, _build_walls_from_dimensions
from src.unified_pipeline.plan_validator import PlanValidator
from src.unified_pipeline.strict_real_assets import settle_classified_bodies
from src.unified_pipeline.strict_real_handlers import _plan_relationship_bindings

COUNTER_ID = "8c6119a5-f7b9-4eca-a30e-cb039aad9c71"
COFFEE_ID = "a4566944-5603-48e2-a0d0-ffc47dc8d225"


def _revision_2() -> MetricPlan:
    placements = (
        {"id": "e307026a-2a6b-47e8-a2a9-42b8dc7904e0", "name": "round table", "x": 3.15, "y": 0.85, "width": 0.5, "height": 0.8, "depth": 0.5, "rotation_deg": 0},
        {"id": "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53-1", "name": "two chairs", "x": 2.0, "y": 0.85, "width": 0.5, "height": 0.8, "depth": 0.5, "rotation_deg": 0},
        {"id": "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53-2", "name": "two chairs", "x": 3.15, "y": 2.65, "width": 0.5, "height": 0.8, "depth": 0.5, "rotation_deg": 0},
        {"id": COUNTER_ID, "name": "counter", "x": 0.85, "y": 0.85, "width": 0.5, "height": 0.8, "depth": 0.5, "rotation_deg": 0, "is_architectural": True},
        {"id": COFFEE_ID, "name": "coffee maker", "x": 2.0, "y": 2.65, "width": 0.5, "height": 0.8, "depth": 0.5, "rotation_deg": 0, "is_architectural": False},
    )
    return MetricPlan(
        room_dimensions=(4.0, 3.5, 2.7),
        walls=_build_walls_from_dimensions(4.0, 3.5, 2.7),
        openings=(
            {"type": "door", "wall": "south", "parameter": 0.2, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ),
        object_placements=placements,
        circulation_paths=({"from": "door_0", "to": "center", "min_width": 0.6},),
        revisions=(
            PlanRevision(revision=1, changed="initial generation (fallback)", reason="test", plan_hash="rev1"),
            PlanRevision(revision=2, changed="camera_contract_and_blockout_framing", reason="test", plan_hash="rev2"),
        ),
        template_id="kitchen",
    )


def _revision_3() -> MetricPlan:
    prior = _revision_2()
    placements = []
    for item in prior.object_placements:
        updated = dict(item)
        if item["id"] == COFFEE_ID:
            updated.update({"x": 0.85, "y": 0.85, "elevation": 0.8})
        placements.append(updated)
    return MetricPlanGenerator().revise(
        prior,
        changed="counter_supports_coffee_maker",
        reason="Revision 2 rejected: coffee maker was floor-level and away from counter",
        object_placements=tuple(placements),
        relationships=({
            "relationship_type": "support",
            "source_id": COUNTER_ID,
            "target_id": COFFEE_ID,
            "authority": "metric_plan",
            "semantic": "counter supports coffee maker",
        },),
    )


def test_revision_3_uses_rejection_revision_and_explicit_plan_support() -> None:
    prior = _revision_2()
    gate = ApprovalGate("slice-j-blockout", "plan_blockout")
    gate.present({"plan_revision": 2, "plan_hash": prior.revisions[-1].plan_hash})
    gate.reject("coffee maker must be explicitly supported by the counter")

    revised = _revision_3()
    assert revised.revisions[-1].revision == 3
    assert revised.revisions[-1].changed == "counter_supports_coffee_maker"
    assert revised.revisions[-1].plan_hash not in {"", prior.revisions[-1].plan_hash}
    assert prior.relationships == ()
    assert revised.room_dimensions == prior.room_dimensions
    assert revised.openings == prior.openings
    assert revised.circulation_paths == prior.circulation_paths
    assert revised.relationships == ({
        "relationship_type": "support",
        "source_id": COUNTER_ID,
        "target_id": COFFEE_ID,
        "authority": "metric_plan",
        "semantic": "counter supports coffee maker",
    },)
    assert PlanValidator().validate(revised).valid is True
    assert [record.decision for record in gate.records] == [ApprovalStatus.REJECTED]


def test_revision_3_camera_blockout_and_approval_are_new_and_revision_bound(tmp_path: Path) -> None:
    prior = _revision_2()
    revised = _revision_3()
    prior_camera = derive_camera_from_plan(prior, raster_width=1024, raster_height=768)
    camera = derive_camera_from_plan(revised, raster_width=1024, raster_height=768)

    assert camera is not prior_camera
    assert camera.compute_hash() == prior_camera.compute_hash()  # same approved framing, freshly derived
    with pytest.raises(FrozenInstanceError):
        camera.vfov = 70.0  # type: ignore[misc]

    result = BlockoutRenderer(tmp_path).render(revised, camera, session_id="slice-j")
    visibility = load_blockout_visibility(Path(result.image_path))
    assert result.plan_revision == 3
    assert result.camera_hash == camera.compute_hash()
    assert visibility["plan_revision"] == 3
    assert visibility["camera_sha256"] == camera.compute_hash()
    assert visibility["fully_green"] is True
    assert visibility["elements"][COUNTER_ID]["geometry_visible"] is True
    assert visibility["elements"][COFFEE_ID]["geometry_visible"] is True
    assert visibility["elements"][COUNTER_ID]["projected_center_px"] != visibility["elements"][COFFEE_ID]["projected_center_px"]

    gate = ApprovalGate("slice-j-blockout", "plan_blockout")
    gate.present({
        "plan_revision": 2,
        "camera_hash": prior_camera.compute_hash(),
        "blockout": "retained-revision-2-evidence",
    })
    gate.reject("coffee maker support defect")
    gate.reset()
    gate.present({
        "plan_revision": 3,
        "plan_hash": revised.revisions[-1].plan_hash,
        "camera_hash": camera.compute_hash(),
        "blockout": result.image_path,
    })
    gate.approve()
    approvals = [record for record in gate.records if record.decision == ApprovalStatus.APPROVED]
    assert len(approvals) == 1
    assert approvals[0].presented_data["plan_revision"] == 3
    assert gate.records[0].presented_data["plan_revision"] == 2
    assert gate.records[0].decision == ApprovalStatus.REJECTED


def test_support_authority_fails_closed_and_static_physics_preserves_plan_transforms() -> None:
    revised = _revision_3()
    relation = dict(revised.relationships[0])
    relation["authority"] = "depth_evidence"
    invalid_authority = replace(revised, relationships=(relation,))
    result = PlanValidator().validate(invalid_authority)
    assert result.valid is False
    assert any(item.rule == "plan_relationship" for item in result.violations)

    placements = {str(item["id"]): item for item in revised.object_placements if item["id"] in {COUNTER_ID, COFFEE_ID}}
    bodies = [{
        "object_id": object_id,
        "body_mode": "STATIC",
        "mass_kg": 0.0,
        "friction": 0.6,
        "restitution": 0.1,
        "collision_dimensions_m": [placement["width"], placement["height"], placement["depth"]],
    } for object_id, placement in placements.items()]
    settled = settle_classified_bodies(
        bodies=bodies,
        placements=placements,
        room_dimensions=revised.room_dimensions,
    )
    transforms = {item["object_id"]: item for item in settled["transforms"]}
    assert transforms[COUNTER_ID]["position"] == pytest.approx([-1.15, 0.0, -0.9])
    assert transforms[COFFEE_ID]["position"] == pytest.approx([-1.15, 0.8, -0.9])
    assert transforms[COUNTER_ID]["settle_method"] == "static approved-Plan anchor preservation"
    assert transforms[COFFEE_ID]["settle_method"] == "static approved-Plan anchor preservation"


def test_strict_real_binding_preserves_plan_support_authority() -> None:
    revised = _revision_3()

    bindings = _plan_relationship_bindings(
        revised,
        {str(item["id"]) for item in revised.object_placements},
    )

    assert len(bindings) == 1
    assert bindings[0].source_id == COUNTER_ID
    assert bindings[0].target_id == COFFEE_ID
    assert bindings[0].relationship_type == "support"
    assert json.loads(bindings[0].metadata) == {
        "authority": "metric_plan",
        "semantic": "counter supports coffee maker",
    }


def test_metric_plan_round_trip_keeps_relationships_and_old_documents_default_empty() -> None:
    revised = _revision_3()
    assert MetricPlan.from_dict(revised.to_dict()) == revised
    legacy = revised.to_dict()
    legacy.pop("relationships")
    assert MetricPlan.from_dict(legacy).relationships == ()


TABLE_ID = "e307026a-2a6b-47e8-a2a9-42b8dc7904e0"
CHAIR_1_ID = "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53-1"
CHAIR_2_ID = "ebd3ce47-a92a-4b8c-a2f4-843cbd24bc53-2"


def _rotated_plan_aabb(item: dict[str, object]) -> tuple[float, float, float, float]:
    angle = math.radians(float(item.get("rotation_deg", 0.0)))
    cosine, sine = abs(math.cos(angle)), abs(math.sin(angle))
    half_x = (float(item["width"]) * cosine + float(item["depth"]) * sine) / 2.0
    half_y = (float(item["width"]) * sine + float(item["depth"]) * cosine) / 2.0
    x, y = float(item["x"]), float(item["y"])
    return x - half_x, x + half_x, y - half_y, y + half_y


def _aabbs_overlap(left: tuple[float, ...], right: tuple[float, ...]) -> bool:
    return (
        left[0] < right[1] - 1e-9
        and right[0] < left[1] - 1e-9
        and left[2] < right[3] - 1e-9
        and right[2] < left[3] - 1e-9
    )


def _player_path(
    plan: MetricPlan,
    target: tuple[float, float],
) -> list[tuple[float, float]]:
    """Mirror Browser v8's 0.25 m player box on its exact 0.05 m probe grid."""
    step = 0.05
    start = (2.0, 1.75)
    obstacles = [_rotated_plan_aabb(dict(item)) for item in plan.object_placements]

    def can_occupy(point: tuple[float, float]) -> bool:
        x, y = point
        if (
            x - DEFAULT_PLAYER_RADIUS_M < 0.05 - 1e-9
            or x + DEFAULT_PLAYER_RADIUS_M > plan.room_dimensions[0] - 0.05 + 1e-9
            or y - DEFAULT_PLAYER_RADIUS_M < 0.05 - 1e-9
            or y + DEFAULT_PLAYER_RADIUS_M > plan.room_dimensions[1] - 0.05 + 1e-9
        ):
            return False
        return not any(
            bounds[0] - DEFAULT_PLAYER_RADIUS_M + 1e-9 < x < bounds[1] + DEFAULT_PLAYER_RADIUS_M - 1e-9
            and bounds[2] - DEFAULT_PLAYER_RADIUS_M + 1e-9 < y < bounds[3] + DEFAULT_PLAYER_RADIUS_M - 1e-9
            for bounds in obstacles
        )

    grid = lambda value: round(value / step)
    start_key = (grid(start[0]), grid(start[1]))
    target_key = (grid(target[0]), grid(target[1]))
    queue = deque([start_key])
    previous: dict[tuple[int, int], tuple[int, int] | None] = {start_key: None}
    while queue:
        current = queue.popleft()
        if current == target_key:
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            candidate = current[0] + dx, current[1] + dy
            if candidate in previous:
                continue
            if can_occupy((candidate[0] * step, candidate[1] * step)):
                previous[candidate] = current
                queue.append(candidate)
    if target_key not in previous:
        return []
    reverse: list[tuple[int, int]] = []
    cursor: tuple[int, int] | None = target_key
    while cursor is not None:
        reverse.append(cursor)
        cursor = previous[cursor]
    return [(x * step, y * step) for x, y in reversed(reverse)]


def _revision_4() -> MetricPlan:
    prior = _revision_3()
    placements = (
        {"id": TABLE_ID, "name": "round table", "x": 2.8, "y": 2.55, "width": 1.0, "height": 0.75, "depth": 1.0, "rotation_deg": 0, "is_architectural": False},
        {"id": CHAIR_1_ID, "name": "chair", "x": 2.8, "y": 1.75, "width": 0.55, "height": 0.85, "depth": 0.55, "rotation_deg": 0, "is_architectural": False},
        {"id": CHAIR_2_ID, "name": "chair", "x": 3.6, "y": 2.55, "width": 0.55, "height": 0.85, "depth": 0.55, "rotation_deg": 90, "is_architectural": False},
        {"id": COUNTER_ID, "name": "counter", "x": 0.85, "y": 2.1, "width": 1.6, "height": 0.9, "depth": 0.6, "rotation_deg": 0, "is_architectural": True},
        {"id": COFFEE_ID, "name": "coffee maker", "x": 0.85, "y": 2.1, "width": 0.35, "height": 0.42, "depth": 0.35, "elevation": 0.9, "rotation_deg": 0, "is_architectural": False},
    )
    return MetricPlanGenerator().revise(
        prior,
        changed="realistic_world_extents_upright_chairs_two_clear_paths_safe_framing",
        reason=(
            "Revision 3 rejected: final world used generic 0.5m extents, chair-2 visual evidence "
            "was invalid, and both player-radius paths plus safe spawn/framing required revalidation"
        ),
        object_placements=placements,
        circulation_paths=({
            "id": "door-to-center",
            "from": "door_0",
            "to": "center",
            "min_width": 0.6,
            "geometry_authority": "metric_plan",
        },),
    )


def test_revision_4_formal_reject_revise_reapprove_has_one_new_approval() -> None:
    prior = _revision_3()
    gate = ApprovalGate("slice-n-blockout", "plan_blockout")
    gate.present({"plan_revision": 3, "plan_hash": prior.revisions[-1].plan_hash})
    gate.reject("generic extents and invalid chair-2 cannot publish")
    gate.reset()

    revised = _revision_4()
    gate.present({"plan_revision": 4, "plan_hash": revised.revisions[-1].plan_hash})
    gate.approve()

    assert revised.revisions[-1].revision == 4
    assert revised.revisions[-1].plan_hash not in {"", prior.revisions[-1].plan_hash}
    assert revised.room_dimensions == prior.room_dimensions
    assert revised.openings == prior.openings
    assert tuple(
        revised.circulation_paths[0][key] for key in ("from", "to", "min_width")
    ) == tuple(prior.circulation_paths[0][key] for key in ("from", "to", "min_width"))
    assert [record.decision for record in gate.records] == [
        ApprovalStatus.REJECTED,
        ApprovalStatus.APPROVED,
    ]
    assert len([record for record in gate.records if record.decision == ApprovalStatus.APPROVED]) == 1


def test_revision_4_has_realistic_extents_upright_distinct_chairs_and_support_contact() -> None:
    revised = _revision_4()
    by_id = {str(item["id"]): item for item in revised.object_placements}

    assert (by_id[TABLE_ID]["width"], by_id[TABLE_ID]["height"], by_id[TABLE_ID]["depth"]) == (1.0, 0.75, 1.0)
    assert (by_id[COUNTER_ID]["width"], by_id[COUNTER_ID]["height"], by_id[COUNTER_ID]["depth"]) == (1.6, 0.9, 0.6)
    assert (by_id[COFFEE_ID]["width"], by_id[COFFEE_ID]["height"], by_id[COFFEE_ID]["depth"]) == (0.35, 0.42, 0.35)
    assert by_id[COFFEE_ID]["elevation"] == pytest.approx(
        by_id[COUNTER_ID].get("elevation", 0.0) + by_id[COUNTER_ID]["height"]
    )
    assert by_id[CHAIR_1_ID]["rotation_deg"] == 0
    assert by_id[CHAIR_2_ID]["rotation_deg"] == 90
    assert by_id[CHAIR_1_ID]["y"] != by_id[CHAIR_2_ID]["y"]
    validation = PlanValidator().validate(revised)
    assert validation.valid is True
    assert not [
        item for item in validation.violations
        if item.rule == "circulation_clearance"
    ], "revision 4 must keep the south-door-to-center path physically clear"


def test_revision_4_rotated_aabbs_and_actual_player_radius_keep_both_paths_clear() -> None:
    revised = _revision_4()
    boxes = {
        str(item["id"]): _rotated_plan_aabb(dict(item))
        for item in revised.object_placements
    }

    assert DEFAULT_PLAYER_RADIUS_M == pytest.approx(0.25)
    assert boxes[TABLE_ID] == pytest.approx((2.3, 3.3, 2.05, 3.05))
    assert boxes[CHAIR_1_ID] == pytest.approx((2.525, 3.075, 1.475, 2.025))
    assert boxes[CHAIR_2_ID] == pytest.approx((3.325, 3.875, 2.275, 2.825))
    assert boxes[COUNTER_ID] == pytest.approx((0.05, 1.65, 1.8, 2.4))
    assert boxes[COFFEE_ID] == pytest.approx((0.675, 1.025, 1.925, 2.275))

    ids = [TABLE_ID, CHAIR_1_ID, CHAIR_2_ID, COUNTER_ID, COFFEE_ID]
    assert not [
        (left, right)
        for index, left in enumerate(ids)
        for right in ids[index + 1:]
        if {left, right} != {COUNTER_ID, COFFEE_ID}
        and _aabbs_overlap(boxes[left], boxes[right])
    ]
    assert boxes[TABLE_ID][0] - DEFAULT_PLAYER_RADIUS_M - 2.0 == pytest.approx(0.05)

    center_path = _player_path(revised, (2.0, 2.35))
    door_path = _player_path(revised, (0.8, 0.30))
    assert center_path[0] == pytest.approx((2.0, 1.75))
    assert center_path[-1] == pytest.approx((2.0, 2.35))
    assert door_path[0] == pytest.approx((2.0, 1.75))
    assert door_path[-1] == pytest.approx((0.8, 0.30))


def test_revision_4_blockout_framing_keeps_all_assets_and_openings_visible(tmp_path: Path) -> None:
    revised = _revision_4()
    camera = derive_camera_from_plan(revised, raster_width=1024, raster_height=768)
    result = BlockoutRenderer(tmp_path).render(revised, camera, session_id="slice-n")
    visibility = load_blockout_visibility(Path(result.image_path))

    assert result.plan_revision == 4
    assert result.camera_hash == camera.compute_hash()
    assert visibility["fully_green"] is True
    assert visibility["all_required_visible"] is True
    assert set(revised.object_placements[i]["id"] for i in range(5)).issubset(visibility["elements"])
