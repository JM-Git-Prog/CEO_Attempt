"""Plan-authoritative adapter for the existing V14 physics settle pass.

Settling may refine dynamic instance transforms only. The approved MetricPlan
continues to own room geometry, openings, circulation, and the camera binding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from src.photo_pipeline.models import PhotoPipelineConfig
from src.photo_pipeline.stages.physics_settle import PhysicsSettle, PhysicsSettleResult
from src.unified_pipeline.models import MetricPlan
from src.world_contract import BodyMode, Transform, Vector3, WorldContract, WorldInstance

MAX_SETTLE_ITERATIONS = 500
MAX_SETTLE_SECONDS = 5.0
PLAN_BOUNDS_MARGIN_M = 0.05
_EPSILON = 1e-6


class PhysicsSettleAuthorityError(ValueError):
    """Raised when settling would escape or mutate Plan-owned authority."""


@dataclass(frozen=True)
class SettleCorrection:
    instance_id: str
    delegated_position: tuple[float, float, float]
    final_position: tuple[float, float, float]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class UnifiedPhysicsSettleResult:
    settled_world_contract: WorldContract
    legacy_result: PhysicsSettleResult
    corrections: tuple[SettleCorrection, ...]
    plan_revision: int
    circulation_preserved: bool


@dataclass(frozen=True)
class _PlacedBox:
    instance_id: str
    position: tuple[float, float, float]
    half_extents: tuple[float, float, float]


class UnifiedPhysicsSettle:
    """Delegate simulation to V14, then enforce corrected Plan authority."""

    def __init__(self, settler: PhysicsSettle | None = None) -> None:
        self._settler = settler or PhysicsSettle()

    def settle(
        self,
        plan: MetricPlan,
        world_contract: WorldContract,
        *,
        approved_plan_revision: int,
    ) -> UnifiedPhysicsSettleResult:
        placements = _validate_authority(plan, world_contract, approved_plan_revision)
        original = world_contract
        legacy = self._settler.settle(
            world_contract,
            PhotoPipelineConfig(
                physics_settle_iterations=MAX_SETTLE_ITERATIONS,
                physics_settle_timeout_s=MAX_SETTLE_SECONDS,
            ),
        )
        if legacy.iterations_run > MAX_SETTLE_ITERATIONS:
            raise PhysicsSettleAuthorityError("legacy settle exceeded 500 iterations")
        if legacy.wall_time_s > MAX_SETTLE_SECONDS + 0.1:
            raise PhysicsSettleAuthorityError("legacy settle exceeded the 5 second deadline")
        _assert_non_transform_authority_unchanged(original, legacy.settled_world_contract)

        dynamic_ids = {
            intent.subject_id
            for intent in original.physics.intents
            if intent.body_mode == BodyMode.DYNAMIC
        }
        delegated = {item.id: item for item in legacy.settled_world_contract.instances}
        resolved: list[_PlacedBox] = []
        updated: list[WorldInstance] = []
        corrections: list[SettleCorrection] = []

        static_boxes = [
            _box_from_instance(item)
            for item in original.instances
            if item.id not in dynamic_ids
        ]
        for item in original.instances:
            if item.id not in dynamic_ids:
                updated.append(item)
                resolved.append(_box_from_instance(item))
                continue
            candidate = delegated[item.id]
            placement = placements[item.id]
            final_position, reasons = _resolve_dynamic(
                plan=plan,
                original=item,
                candidate=candidate,
                placement=placement,
                obstacles=tuple(static_boxes + resolved),
            )
            transform = Transform(
                position_m=Vector3(
                    x=final_position[0], y=final_position[1], z=final_position[2]
                ),
                rotation_deg=candidate.transform.rotation_deg,
                scale=item.transform.scale,
            )
            updated_item = item.model_copy(update={"transform": transform})
            updated.append(updated_item)
            resolved.append(_box_from_instance(updated_item))
            if reasons or final_position != _position(candidate):
                corrections.append(SettleCorrection(
                    instance_id=item.id,
                    delegated_position=_position(candidate),
                    final_position=final_position,
                    reasons=tuple(reasons),
                ))

        payload = original.model_dump()
        payload["instances"] = [item.model_dump() for item in updated]
        settled = WorldContract.model_validate(payload)
        _assert_non_transform_authority_unchanged(original, settled)
        _assert_no_interpenetration(settled)
        return UnifiedPhysicsSettleResult(
            settled_world_contract=settled,
            legacy_result=legacy,
            corrections=tuple(corrections),
            plan_revision=approved_plan_revision,
            circulation_preserved=True,
        )


def _validate_authority(
    plan: MetricPlan,
    contract: WorldContract,
    approved_revision: int,
) -> dict[str, dict]:
    if not plan.revisions:
        raise PhysicsSettleAuthorityError("settle requires a nonzero approved Plan revision")
    latest = max(revision.revision for revision in plan.revisions)
    if approved_revision <= 0 or approved_revision != latest:
        raise PhysicsSettleAuthorityError(
            "approved Plan revision must match the latest nonzero revision"
        )
    if contract.source.plan_revision != approved_revision:
        raise PhysicsSettleAuthorityError("WorldContract Plan revision mismatch")
    width, depth, height = plan.room_dimensions
    dimensions = contract.room.dimensions
    actual = (dimensions.width_m, dimensions.depth_m, dimensions.height_m)
    if not all(math.isclose(a, b, abs_tol=_EPSILON) for a, b in zip(actual, (width, depth, height))):
        raise PhysicsSettleAuthorityError("WorldContract room bounds differ from the Plan")

    placements = {str(item.get("id", "")): item for item in plan.object_placements}
    if "" in placements:
        raise PhysicsSettleAuthorityError("every Plan placement requires a stable id")
    dynamic_ids = {
        intent.subject_id
        for intent in contract.physics.intents
        if intent.body_mode == BodyMode.DYNAMIC
    }
    missing = sorted(dynamic_ids - placements.keys())
    if missing:
        raise PhysicsSettleAuthorityError(
            "dynamic instances missing authoritative Plan placements: " + ", ".join(missing)
        )
    instances = {item.id: item for item in contract.instances}
    for instance_id in dynamic_ids:
        item = instances[instance_id]
        placement = placements[instance_id]
        expected = (
            float(placement.get("width", 0.0)),
            float(placement.get("height", 0.0)),
            float(placement.get("depth", 0.0)),
        )
        actual_dims = (
            item.dimensions.width_m,
            item.dimensions.height_m,
            item.dimensions.depth_m,
        )
        if not all(math.isclose(a, b, abs_tol=_EPSILON) for a, b in zip(expected, actual_dims)):
            raise PhysicsSettleAuthorityError(f"instance {instance_id} dimensions differ from Plan")
    return placements


def _assert_non_transform_authority_unchanged(
    before: WorldContract, after: WorldContract
) -> None:
    before_data = before.model_dump(mode="json")
    after_data = after.model_dump(mode="json")
    before_instances = before_data.pop("instances")
    after_instances = after_data.pop("instances")
    if before_data != after_data:
        raise PhysicsSettleAuthorityError(
            "settle attempted to rewrite architecture, openings, camera, or contract policy"
        )
    if [item["id"] for item in before_instances] != [item["id"] for item in after_instances]:
        raise PhysicsSettleAuthorityError("settle attempted to rewrite stable instance identity")
    for first, second in zip(before_instances, after_instances):
        first = dict(first)
        second = dict(second)
        first.pop("transform")
        second.pop("transform")
        if first != second:
            raise PhysicsSettleAuthorityError(
                f"settle attempted to rewrite non-transform data for {first['id']}"
            )


def _position(item: WorldInstance) -> tuple[float, float, float]:
    value = item.transform.position_m
    return value.x, value.y, value.z


def _box_from_instance(item: WorldInstance) -> _PlacedBox:
    dimensions = (
        item.dimensions.width_m * item.transform.scale.x,
        item.dimensions.height_m * item.transform.scale.y,
        item.dimensions.depth_m * item.transform.scale.z,
    )
    rotation = item.transform.rotation_deg
    return _PlacedBox(
        instance_id=item.id,
        position=_position(item),
        half_extents=_rotated_half_extents(
            dimensions, (rotation.x, rotation.y, rotation.z)
        ),
    )


def _rotated_half_extents(
    dimensions: tuple[float, float, float],
    rotation_deg: tuple[float, float, float],
) -> tuple[float, float, float]:
    rx, ry, rz = (math.radians(value) for value in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    matrix = (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )
    half = tuple(value / 2.0 for value in dimensions)
    return tuple(
        sum(abs(matrix[row][column]) * half[column] for column in range(3))
        for row in range(3)
    )


def _resolve_dynamic(
    *,
    plan: MetricPlan,
    original: WorldInstance,
    candidate: WorldInstance,
    placement: dict,
    obstacles: Sequence[_PlacedBox],
) -> tuple[tuple[float, float, float], list[str]]:
    reasons: list[str] = []
    original_world = _position(original)
    delegated = _position(candidate)
    plan_origin = (float(placement["x"]), float(placement["y"]))
    plan_candidate = (
        plan_origin[0] + delegated[0] - original_world[0],
        plan_origin[1] + delegated[2] - original_world[2],
    )
    dimensions = (
        original.dimensions.width_m * original.transform.scale.x,
        original.dimensions.height_m * original.transform.scale.y,
        original.dimensions.depth_m * original.transform.scale.z,
    )
    rotation = candidate.transform.rotation_deg
    half = _rotated_half_extents(dimensions, (rotation.x, rotation.y, rotation.z))
    width, depth, height = plan.room_dimensions
    plan_x = _clamp(plan_candidate[0], half[0] + PLAN_BOUNDS_MARGIN_M, width - half[0] - PLAN_BOUNDS_MARGIN_M)
    plan_z = _clamp(plan_candidate[1], half[2] + PLAN_BOUNDS_MARGIN_M, depth - half[2] - PLAN_BOUNDS_MARGIN_M)
    if (plan_x, plan_z) != plan_candidate:
        reasons.append("clamped_to_plan_bounds")

    world_x = original_world[0] + plan_x - plan_origin[0]
    world_z = original_world[2] + plan_z - plan_origin[1]
    delegated_box = _PlacedBox(
        original.id, (world_x, delegated[1], world_z), half
    )
    if any(_boxes_interpenetrate(delegated_box, obstacle) for obstacle in obstacles):
        reasons.append("resolved_interpenetration")
    support_top = 0.0
    for obstacle in obstacles:
        if _horizontal_overlap((world_x, world_z), half, obstacle):
            obstacle_top = obstacle.position[1] + obstacle.half_extents[1]
            if obstacle_top <= delegated[1] + half[1] + _EPSILON:
                support_top = max(support_top, obstacle_top)
    world_y = support_top + half[1]
    ceiling_limit = height - half[1] - PLAN_BOUNDS_MARGIN_M
    if ceiling_limit < half[1]:
        raise PhysicsSettleAuthorityError(f"instance {original.id} cannot fit within Plan height")
    world_y = min(world_y, ceiling_limit)
    if not math.isclose(world_y, delegated[1], abs_tol=_EPSILON):
        reasons.append("resolved_floater_or_floor_penetration")

    baseline_conflicts = _circulation_conflicts(plan, plan_origin, (half[0], half[2]))
    position = (world_x, world_y, world_z)
    for _ in range(MAX_SETTLE_ITERATIONS):
        box = _PlacedBox(original.id, position, half)
        blockers = [item for item in obstacles if _boxes_interpenetrate(box, item)]
        plan_position = (
            plan_origin[0] + position[0] - original_world[0],
            plan_origin[1] + position[2] - original_world[2],
        )
        new_conflicts = _circulation_conflicts(plan, plan_position, (half[0], half[2]))
        if not blockers and new_conflicts.issubset(baseline_conflicts):
            return position, reasons
        options = _separation_options(box, blockers[0]) if blockers else []
        valid = []
        for x, z in options:
            px = plan_origin[0] + x - original_world[0]
            pz = plan_origin[1] + z - original_world[2]
            if not _inside_plan_bounds((px, pz), (half[0], half[2]), width, depth):
                continue
            if not _circulation_conflicts(plan, (px, pz), (half[0], half[2])).issubset(baseline_conflicts):
                continue
            valid.append((x, world_y, z))
        if not valid:
            break
        position = min(valid, key=lambda value: math.hypot(value[0] - position[0], value[2] - position[2]))
        if "resolved_interpenetration" not in reasons:
            reasons.append("resolved_interpenetration")

    baseline_y = half[1]
    baseline = (original_world[0], baseline_y, original_world[2])
    baseline_box = _PlacedBox(original.id, baseline, half)
    if not any(_boxes_interpenetrate(baseline_box, item) for item in obstacles):
        reasons.append("restored_plan_transform_for_circulation")
        return baseline, reasons
    raise PhysicsSettleAuthorityError(
        f"cannot resolve interpenetration for {original.id} without violating Plan authority"
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    if minimum > maximum:
        raise PhysicsSettleAuthorityError("object cannot fit inside authoritative Plan bounds")
    return min(maximum, max(minimum, value))


def _inside_plan_bounds(
    position: tuple[float, float],
    half: tuple[float, float],
    width: float,
    depth: float,
) -> bool:
    return (
        position[0] - half[0] >= PLAN_BOUNDS_MARGIN_M - _EPSILON
        and position[0] + half[0] <= width - PLAN_BOUNDS_MARGIN_M + _EPSILON
        and position[1] - half[1] >= PLAN_BOUNDS_MARGIN_M - _EPSILON
        and position[1] + half[1] <= depth - PLAN_BOUNDS_MARGIN_M + _EPSILON
    )


def _horizontal_overlap(
    center: tuple[float, float], half: tuple[float, float, float], other: _PlacedBox
) -> bool:
    return (
        abs(center[0] - other.position[0]) < half[0] + other.half_extents[0] - _EPSILON
        and abs(center[1] - other.position[2]) < half[2] + other.half_extents[2] - _EPSILON
    )


def _boxes_interpenetrate(first: _PlacedBox, second: _PlacedBox) -> bool:
    return all(
        abs(first.position[index] - second.position[index])
        < first.half_extents[index] + second.half_extents[index] - _EPSILON
        for index in range(3)
    )


def _separation_options(
    moving: _PlacedBox, blocker: _PlacedBox
) -> list[tuple[float, float]]:
    hx, _, hz = moving.half_extents
    bx, _, bz = blocker.half_extents
    x, _, z = blocker.position
    return [
        (x - bx - hx - _EPSILON, moving.position[2]),
        (x + bx + hx + _EPSILON, moving.position[2]),
        (moving.position[0], z - bz - hz - _EPSILON),
        (moving.position[0], z + bz + hz + _EPSILON),
    ]


def _assert_no_interpenetration(contract: WorldContract) -> None:
    dynamic_ids = {
        intent.subject_id
        for intent in contract.physics.intents
        if intent.body_mode == BodyMode.DYNAMIC
    }
    boxes = [_box_from_instance(item) for item in contract.instances]
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            if first.instance_id not in dynamic_ids and second.instance_id not in dynamic_ids:
                continue
            if _boxes_interpenetrate(first, second):
                raise PhysicsSettleAuthorityError(
                    f"settle left interpenetration between {first.instance_id} and {second.instance_id}"
                )


def _circulation_conflicts(
    plan: MetricPlan,
    position: tuple[float, float],
    half: tuple[float, float],
) -> set[int]:
    conflicts: set[int] = set()
    for index, path in enumerate(plan.circulation_paths):
        points = _path_points(plan, path)
        if len(points) < 2:
            continue
        clearance = max(0.6, float(path.get("min_width", path.get("width", 0.6)))) / 2.0
        for start, end in zip(points, points[1:]):
            if _segment_rectangle_distance(start, end, position, half) < clearance - _EPSILON:
                conflicts.add(index)
                break
    return conflicts


def _path_points(plan: MetricPlan, path: dict) -> tuple[tuple[float, float], ...]:
    raw_points = path.get("points")
    if raw_points:
        return tuple(point for value in raw_points if (point := _resolve_point(plan, value)) is not None)
    start = _resolve_point(plan, path.get("start", path.get("from")))
    end = _resolve_point(plan, path.get("end", path.get("to")))
    return tuple(point for point in (start, end) if point is not None)


def _resolve_point(plan: MetricPlan, value: object) -> tuple[float, float] | None:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    if isinstance(value, dict):
        if "x" in value and ("z" in value or "y" in value):
            return float(value["x"]), float(value.get("z", value.get("y")))
        return None
    if not isinstance(value, str):
        return None
    if value == "center":
        return plan.room_dimensions[0] / 2.0, plan.room_dimensions[1] / 2.0
    opening = next((item for item in plan.openings if item.get("id") == value), None)
    if opening is None:
        return None
    wall_id = opening.get("wall", opening.get("wall_id"))
    wall = next((item for item in plan.walls if item.get("id") == wall_id), None)
    if wall is None:
        return None
    start = wall.get("start", (0.0, 0.0))
    end = wall.get("end", start)
    parameter = float(opening.get("parameter", opening.get("position", 0.5)))
    return (
        float(start[0]) + (float(end[0]) - float(start[0])) * parameter,
        float(start[1]) + (float(end[1]) - float(start[1])) * parameter,
    )


def _segment_rectangle_distance(
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    half: tuple[float, float],
) -> float:
    minimum = (center[0] - half[0], center[1] - half[1])
    maximum = (center[0] + half[0], center[1] + half[1])
    if _segment_intersects_rectangle(start, end, minimum, maximum):
        return 0.0
    corners = (
        minimum,
        (minimum[0], maximum[1]),
        maximum,
        (maximum[0], minimum[1]),
    )
    return min(
        _point_rectangle_distance(start, minimum, maximum),
        _point_rectangle_distance(end, minimum, maximum),
        *(_point_segment_distance(corner, start, end) for corner in corners),
    )


def _segment_intersects_rectangle(
    start: tuple[float, float],
    end: tuple[float, float],
    minimum: tuple[float, float],
    maximum: tuple[float, float],
) -> bool:
    t_min, t_max = 0.0, 1.0
    for axis in range(2):
        delta = end[axis] - start[axis]
        if abs(delta) <= _EPSILON:
            if start[axis] < minimum[axis] or start[axis] > maximum[axis]:
                return False
            continue
        first = (minimum[axis] - start[axis]) / delta
        second = (maximum[axis] - start[axis]) / delta
        lower, upper = sorted((first, second))
        t_min, t_max = max(t_min, lower), min(t_max, upper)
        if t_min > t_max:
            return False
    return True


def _point_rectangle_distance(
    point: tuple[float, float],
    minimum: tuple[float, float],
    maximum: tuple[float, float],
) -> float:
    dx = max(minimum[0] - point[0], 0.0, point[0] - maximum[0])
    dz = max(minimum[1] - point[1], 0.0, point[1] - maximum[1])
    return math.hypot(dx, dz)


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dz = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dz * dz
    if length_squared <= _EPSILON:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz) / length_squared
    projection = min(1.0, max(0.0, projection))
    nearest = (start[0] + projection * dx, start[1] + projection * dz)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])
