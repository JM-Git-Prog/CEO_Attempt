"""Fail-closed structural publication gates for the unified world pipeline.

These gates run after relationship solving/canonicalization and before any
compiler. Compiler parity is intentionally excluded; it runs post-compile in
Task 7.4. Requirements: 20.1-20.10.
"""
from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from src.unified_pipeline.models import MetricPlan
from src.unified_pipeline.parametric_room import ParametricRoomResult
from src.world_contract import BodyMode, Wall, WorldContract, world_contract_from_json

MIN_CIRCULATION_CLEARANCE_M = 0.6
_EPSILON = 1e-7
_SHA256_LENGTH = 64
SEMANTIC_CATEGORIES = frozenset({
    "props", "architecture", "foliage", "hard-surface", "set-dressing"
})
STRUCTURAL_GATE_NAMES = (
    "provenance", "containment", "overlap_opening_circulation", "camera",
    "asset", "material", "geometry", "physics", "semantic",
)


class PublicationGateError(ValueError):
    """Raised when compilation/publication is attempted after a failed gate."""


@dataclass(frozen=True)
class ProvenanceNode:
    node_id: str
    kind: str
    sha256: str
    parent_id: str | None = None
    plan_revision: int = 0


@dataclass(frozen=True)
class AssetEvidence:
    """Verified final-mesh binding; normalization_count must be exactly one."""

    binding_id: str
    instance_id: str
    path: str
    sha256: str
    triangle_count: int
    normalization_count: int


@dataclass(frozen=True)
class MaterialEvidence:
    binding_id: str
    instance_id: str
    material_id: str
    verified: bool
    degraded: bool = False
    degradation_reason: str = ""


@dataclass(frozen=True)
class SemanticEvidence:
    binding_id: str
    instance_id: str
    stable_uuid: str
    semantic_label: str
    category: str


@dataclass(frozen=True)
class CollisionEvidence:
    binding_id: str
    instance_id: str
    geometry_node_id: str
    center_m: tuple[float, float, float]
    dimensions_m: tuple[float, float, float]
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class SettleEvidence:
    contract_hash: str
    plan_revision: int
    completed: bool
    total_unsettled: int = 0
    floating_instance_ids: tuple[str, ...] = ()
    interpenetrating_pairs: tuple[tuple[str, str], ...] = ()
    circulation_preserved: bool = True


@dataclass(frozen=True)
class GateDiagnostic:
    code: str
    message: str
    offending_node: str = ""
    offending_binding: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "offending_node": self.offending_node,
            "offending_binding": self.offending_binding,
        }


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool
    plan_revision: int
    canonical_hash: str
    diagnostics: tuple[GateDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "plan_revision": self.plan_revision,
            "canonical_hash": self.canonical_hash,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass(frozen=True)
class CompilationGateToken:
    """Proof that every pre-compile structural gate passed for one contract."""

    plan_revision: int
    canonical_hash: str
    report_hash: str


@dataclass(frozen=True)
class StructuralGateReport:
    plan_revision: int
    canonical_hash: str
    results: tuple[GateResult, ...]
    parity_deferred: bool = True

    @property
    def passed(self) -> bool:
        return (
            tuple(item.gate for item in self.results) == STRUCTURAL_GATE_NAMES
            and all(item.passed for item in self.results)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "plan_revision": self.plan_revision,
            "canonical_hash": self.canonical_hash,
            "parity_deferred_to_task_7_4": self.parity_deferred,
            "passed": self.passed,
            "results": [item.to_dict() for item in self.results],
        }

    def require_compilation_ready(self) -> CompilationGateToken:
        if not self.passed:
            failures = [
                diagnostic
                for result in self.results if not result.passed
                for diagnostic in result.diagnostics
            ]
            summary = "; ".join(
                f"{item.code}: {item.message}" for item in failures[:5]
            ) or "structural gate report is incomplete"
            raise PublicationGateError(f"compilation blocked: {summary}")
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return CompilationGateToken(
            self.plan_revision,
            self.canonical_hash,
            hashlib.sha256(encoded).hexdigest(),
        )


@dataclass(frozen=True)
class StructuralGateContext:
    contract: WorldContract
    plan: MetricPlan
    provenance: tuple[ProvenanceNode, ...]
    assets: tuple[AssetEvidence, ...]
    materials: tuple[MaterialEvidence, ...]
    semantics: tuple[SemanticEvidence, ...]
    collisions: tuple[CollisionEvidence, ...]
    settle: SettleEvidence
    room: ParametricRoomResult | None = None
    allowed_overlap_pairs: frozenset[frozenset[str]] = field(default_factory=frozenset)


def _diagnostic(
    code: str, message: str, node: str = "", binding: str = ""
) -> GateDiagnostic:
    return GateDiagnostic(code, message, node, binding)


def _is_sha256(value: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(contract: WorldContract) -> str:
    return contract.content_hash()


def _revision(context: StructuralGateContext) -> int:
    return context.contract.source.plan_revision


def _bounds(
    context: StructuralGateContext,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    if context.room is not None:
        return (
            context.room.navigable_bounds.minimum_m,
            context.room.navigable_bounds.maximum_m,
        )
    dimensions = context.contract.room.dimensions
    return (0.0, 0.0, 0.0), (
        dimensions.width_m, dimensions.height_m, dimensions.depth_m
    )


def _vector(value: object) -> tuple[float, float, float]:
    return (float(value.x), float(value.y), float(value.z))  # type: ignore[attr-defined]


def _rotation_aware_half_extents(
    dimensions: tuple[float, float, float],
    rotation_deg: tuple[float, float, float],
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> tuple[float, float, float]:
    """Return the world AABB half-extents of a scaled Euler-rotated box."""
    rx, ry, rz = (math.radians(value) for value in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    # Rz * Ry * Rx; absolute rotation maps local half-extents to world AABB.
    matrix = (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )
    local = tuple(
        abs(float(size) * float(factor)) / 2.0
        for size, factor in zip(dimensions, scale)
    )
    return tuple(
        sum(abs(matrix[row][column]) * local[column] for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _instance_box(instance: object) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
]:
    transform = instance.transform  # type: ignore[attr-defined]
    dimensions = instance.dimensions  # type: ignore[attr-defined]
    center = _vector(transform.position_m)
    half = _rotation_aware_half_extents(
        (dimensions.width_m, dimensions.height_m, dimensions.depth_m),
        _vector(transform.rotation_deg),
        _vector(transform.scale),
    )
    return center, half


def _inside(
    center: Sequence[float], half: Sequence[float],
    minimum: Sequence[float], maximum: Sequence[float],
) -> bool:
    return all(
        center[axis] - half[axis] >= minimum[axis] - _EPSILON
        and center[axis] + half[axis] <= maximum[axis] + _EPSILON
        for axis in range(3)
    )


def _boxes_overlap(
    first: tuple[Sequence[float], Sequence[float]],
    second: tuple[Sequence[float], Sequence[float]],
) -> bool:
    return all(
        abs(first[0][axis] - second[0][axis])
        < first[1][axis] + second[1][axis] - _EPSILON
        for axis in range(3)
    )


def _point_in_box(
    point: Sequence[float], box: tuple[Sequence[float], Sequence[float]]
) -> bool:
    return all(
        box[0][axis] - box[1][axis] - _EPSILON <= point[axis]
        <= box[0][axis] + box[1][axis] + _EPSILON
        for axis in range(3)
    )


def _path_points(plan: MetricPlan, path: Mapping[str, object]) -> tuple[
    tuple[float, float], tuple[float, float]
] | None:
    width, depth, _ = plan.room_dimensions

    def resolve(value: object) -> tuple[float, float] | None:
        if value == "center":
            return width / 2.0, depth / 2.0
        if isinstance(value, (tuple, list)) and len(value) >= 2:
            return float(value[0]), float(value[1])
        if isinstance(value, str):
            opening = next(
                (item for item in plan.openings if str(item.get("id", "")) == value),
                None,
            )
            if opening is not None:
                parameter = float(opening.get("parameter", 0.5))
                wall = str(opening.get("wall", ""))
                return {
                    "north": (parameter * width, 0.0),
                    "south": ((1.0 - parameter) * width, depth),
                    "east": (width, parameter * depth),
                    "west": (0.0, (1.0 - parameter) * depth),
                }.get(wall)
        return None

    start = resolve(path.get("start", path.get("from")))
    end = resolve(path.get("end", path.get("to")))
    return (start, end) if start is not None and end is not None else None


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dz = end[0] - start[0], end[1] - start[1]
    length_sq = dx * dx + dz * dz
    if length_sq <= _EPSILON:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    amount = max(0.0, min(1.0, (
        (point[0] - start[0]) * dx + (point[1] - start[1]) * dz
    ) / length_sq))
    closest = start[0] + amount * dx, start[1] + amount * dz
    return math.hypot(point[0] - closest[0], point[1] - closest[1])


def _segment_rectangle_distance(
    start: tuple[float, float], end: tuple[float, float],
    center: tuple[float, float], half: tuple[float, float],
) -> float:
    # Conservative and deterministic: endpoint/corner distances plus segment
    # sampling. Rotation has already been folded into the AABB half-extents.
    minimum = center[0] - half[0], center[1] - half[1]
    maximum = center[0] + half[0], center[1] + half[1]
    for index in range(65):
        amount = index / 64.0
        point = (
            start[0] + (end[0] - start[0]) * amount,
            start[1] + (end[1] - start[1]) * amount,
        )
        dx = max(minimum[0] - point[0], 0.0, point[0] - maximum[0])
        dz = max(minimum[1] - point[1], 0.0, point[1] - maximum[1])
        if dx == 0.0 and dz == 0.0:
            return 0.0
    corners = (
        minimum, (minimum[0], maximum[1]), maximum, (maximum[0], minimum[1])
    )
    return min(_point_segment_distance(corner, start, end) for corner in corners)


def _provenance_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    revision, canonical_hash = _revision(context), _canonical_hash(context.contract)
    if revision <= 0:
        failures.append(_diagnostic(
            "provenance.zero_revision", "approved Plan revision must be nonzero",
            context.contract.source.session_id, "source.plan_revision",
        ))
    nodes = {item.node_id: item for item in context.provenance}
    if len(nodes) != len(context.provenance):
        failures.append(_diagnostic(
            "provenance.duplicate_node", "provenance node IDs must be unique"
        ))
        return failures
    candidates = [item for item in nodes.values() if item.kind == "world_contract"]
    if len(candidates) != 1:
        failures.append(_diagnostic(
            "provenance.contract_node", "exactly one world_contract provenance node is required"
        ))
        return failures
    node = candidates[0]
    if node.sha256 != canonical_hash:
        failures.append(_diagnostic(
            "provenance.contract_hash", "provenance contract hash does not match canonical contract",
            node.node_id, node.sha256,
        ))
    expected = ("world_contract", "approved_plan", "intent", "evidence")
    visited: set[str] = set()
    for expected_kind in expected:
        if node.node_id in visited:
            failures.append(_diagnostic(
                "provenance.cycle", "provenance chain contains a cycle", node.node_id
            ))
            break
        visited.add(node.node_id)
        if node.kind != expected_kind:
            failures.append(_diagnostic(
                "provenance.broken_chain",
                f"expected {expected_kind} node, found {node.kind}", node.node_id,
            ))
        if not _is_sha256(node.sha256):
            failures.append(_diagnostic(
                "provenance.invalid_hash", "provenance node requires a SHA-256 digest",
                node.node_id, node.sha256,
            ))
        if expected_kind in {"world_contract", "approved_plan"} and node.plan_revision != revision:
            failures.append(_diagnostic(
                "provenance.revision_mismatch",
                f"node revision {node.plan_revision} does not match contract revision {revision}",
                node.node_id,
            ))
        if expected_kind == "evidence":
            if node.parent_id is not None:
                failures.append(_diagnostic(
                    "provenance.evidence_parent", "root evidence must not have a parent",
                    node.node_id, node.parent_id,
                ))
            break
        if not node.parent_id or node.parent_id not in nodes:
            failures.append(_diagnostic(
                "provenance.missing_parent", "provenance chain has a missing parent",
                node.node_id, node.parent_id or "",
            ))
            break
        node = nodes[node.parent_id]
    return failures


def _containment_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    minimum, maximum = _bounds(context)
    if any(not math.isfinite(value) for value in (*minimum, *maximum)) or any(
        minimum[index] >= maximum[index] for index in range(3)
    ):
        return [_diagnostic(
            "containment.invalid_bounds", "navigable room bounds are invalid",
            context.contract.room.id, "navigable_bounds",
        )]
    for instance in context.contract.instances:
        center, half = _instance_box(instance)
        if not _inside(center, half, minimum, maximum):
            failures.append(_diagnostic(
                "containment.object_extent",
                "rotation-aware object extent leaves navigable room bounds",
                instance.id, instance.id,
            ))
    for collision in context.collisions:
        half = _rotation_aware_half_extents(
            collision.dimensions_m, collision.rotation_deg
        )
        if not _inside(collision.center_m, half, minimum, maximum):
            failures.append(_diagnostic(
                "containment.collision_extent",
                "rotation-aware collision extent leaves navigable room bounds",
                collision.instance_id, collision.binding_id,
            ))
    camera = _vector(context.contract.camera.position_m)
    if not _inside(camera, (0.0, 0.0, 0.0), minimum, maximum):
        failures.append(_diagnostic(
            "containment.camera", "camera origin is outside navigable room bounds",
            context.contract.camera.id, context.contract.source.camera_contract_hash,
        ))
    return failures


def _opening_box(
    context: StructuralGateContext, opening: object
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    minimum, maximum = _bounds(context)
    mid_x = (minimum[0] + maximum[0]) / 2.0
    mid_z = (minimum[2] + maximum[2]) / 2.0
    offset = float(opening.offset_m)  # type: ignore[attr-defined]
    width = float(opening.width_m)  # type: ignore[attr-defined]
    height = float(opening.height_m)  # type: ignore[attr-defined]
    sill = float(opening.sill_height_m)  # type: ignore[attr-defined]
    thickness = 0.05
    wall = opening.wall  # type: ignore[attr-defined]
    if wall in {Wall.NORTH, Wall.SOUTH}:
        center = (
            mid_x + offset,
            sill + height / 2.0,
            minimum[2] if wall == Wall.NORTH else maximum[2],
        )
        half = width / 2.0, height / 2.0, thickness
    else:
        center = (
            maximum[0] if wall == Wall.EAST else minimum[0],
            sill + height / 2.0,
            mid_z + offset,
        )
        half = thickness, height / 2.0, width / 2.0
    return center, half


def _overlap_opening_circulation_gate(
    context: StructuralGateContext,
) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    instances = tuple(context.contract.instances)
    boxes = {item.id: _instance_box(item) for item in instances}
    for index, first in enumerate(instances):
        for second in instances[index + 1:]:
            pair = frozenset((first.id, second.id))
            if pair not in context.allowed_overlap_pairs and _boxes_overlap(
                boxes[first.id], boxes[second.id]
            ):
                failures.append(_diagnostic(
                    "overlap.forbidden_solids", "final object solids overlap",
                    first.id, f"{first.id}<->{second.id}",
                ))
    wall_ids = {str(item.get("id", "")) for item in context.plan.walls}
    contract_openings = {item.id: item for item in context.contract.openings}
    for raw in context.plan.openings:
        opening_id = str(raw.get("id", ""))
        host = str(raw.get("wall", ""))
        if not opening_id or opening_id not in contract_openings:
            failures.append(_diagnostic(
                "opening.missing_binding", "approved Plan opening is absent from contract",
                opening_id or "<unnamed>", host,
            ))
            continue
        if host not in wall_ids:
            failures.append(_diagnostic(
                "opening.invalid_host", "opening host wall is not part of the closed room",
                opening_id, host,
            ))
    for opening in context.contract.openings:
        portal = _opening_box(context, opening)
        for instance in instances:
            if _boxes_overlap(portal, boxes[instance.id]):
                failures.append(_diagnostic(
                    "opening.occluded", "object solid occludes a required opening",
                    instance.id, opening.id,
                ))
    for index, raw in enumerate(context.plan.circulation_paths):
        path = dict(raw)
        clearance = float(path.get("min_width", path.get("clearance_m", 0.0)))
        binding = str(path.get("id", f"circulation:{index}"))
        if not math.isfinite(clearance) or clearance < MIN_CIRCULATION_CLEARANCE_M:
            failures.append(_diagnostic(
                "circulation.minimum_clearance",
                f"required clearance is {clearance!r}m; minimum is 0.6m",
                binding, binding,
            ))
            continue
        points = _path_points(context.plan, path)
        if points is None:
            failures.append(_diagnostic(
                "circulation.invalid_path", "circulation path endpoints cannot be resolved",
                binding, binding,
            ))
            continue
        for instance in instances:
            center, half = boxes[instance.id]
            distance = _segment_rectangle_distance(
                points[0], points[1], (center[0], center[2]), (half[0], half[2])
            )
            if distance < clearance / 2.0 - _EPSILON:
                failures.append(_diagnostic(
                    "circulation.occluded",
                    f"object leaves less than {clearance:.3f}m required path width",
                    instance.id, binding,
                ))
    return failures


def _camera_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    camera = context.contract.camera
    origin, target = _vector(camera.position_m), _vector(camera.target_m)
    minimum, maximum = _bounds(context)
    values = (*origin, *target, *_vector(camera.up), camera.near_plane_m, camera.far_plane_m)
    if not all(math.isfinite(value) for value in values):
        failures.append(_diagnostic(
            "camera.nonfinite", "camera projection contains non-finite values",
            camera.id, context.contract.source.camera_contract_hash,
        ))
        return failures
    if camera.near_plane_m <= 0.0 or camera.far_plane_m <= camera.near_plane_m:
        failures.append(_diagnostic(
            "camera.frustum", "camera near/far planes are invalid",
            camera.id, context.contract.source.camera_contract_hash,
        ))
    if not _inside(origin, (0.0, 0.0, 0.0), minimum, maximum):
        failures.append(_diagnostic(
            "camera.not_navigable", "camera origin is not in navigable interior space",
            camera.id, "navigable_bounds",
        ))
    if not _inside(target, (0.0, 0.0, 0.0), minimum, maximum):
        failures.append(_diagnostic(
            "camera.target_outside", "camera does not observe a solved interior target",
            camera.id, "camera.target_m",
        ))
    focus_distance = math.dist(origin, target)
    if not camera.near_plane_m < focus_distance < camera.far_plane_m:
        failures.append(_diagnostic(
            "camera.target_clipped", "solved interior target is outside the camera frustum range",
            camera.id, "camera.near_far",
        ))
    for collision in context.collisions:
        box = (
            collision.center_m,
            _rotation_aware_half_extents(collision.dimensions_m, collision.rotation_deg),
        )
        if _point_in_box(origin, box):
            failures.append(_diagnostic(
                "camera.inside_collision", "camera origin is inside collision geometry",
                camera.id, collision.binding_id,
            ))
    return failures


def _asset_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    records: dict[str, AssetEvidence] = {}
    for item in context.assets:
        if item.instance_id in records:
            failures.append(_diagnostic(
                "asset.duplicate_binding", "instance has more than one final asset binding",
                item.instance_id, item.binding_id,
            ))
        records[item.instance_id] = item
    required = {
        item.id for item in context.contract.instances
        if item.geometry_strategy in {"generated", "asset"}
    }
    for instance_id in sorted(required):
        item = records.get(instance_id)
        if item is None:
            failures.append(_diagnostic(
                "asset.missing_binding", "final mesh lacks approved asset evidence",
                instance_id, instance_id,
            ))
            continue
        path = Path(item.path).expanduser()
        if not path.is_file():
            failures.append(_diagnostic(
                "asset.invalid_path", "approved mesh path is not a regular file",
                instance_id, item.binding_id,
            ))
        elif not _is_sha256(item.sha256) or _file_sha256(path) != item.sha256:
            failures.append(_diagnostic(
                "asset.sha256_mismatch", "approved mesh SHA-256 does not match file bytes",
                instance_id, item.binding_id,
            ))
        if isinstance(item.triangle_count, bool) or item.triangle_count <= 0:
            failures.append(_diagnostic(
                "asset.triangle_count", "final mesh triangle count must be positive",
                instance_id, item.binding_id,
            ))
        if item.normalization_count != 1:
            failures.append(_diagnostic(
                "asset.normalization_count",
                f"asset normalization count is {item.normalization_count}; expected exactly one",
                instance_id, item.binding_id,
            ))
    extras = sorted(set(records) - {item.id for item in context.contract.instances})
    for instance_id in extras:
        failures.append(_diagnostic(
            "asset.orphan_binding", "asset evidence references no contract instance",
            instance_id, records[instance_id].binding_id,
        ))
    return failures


def _material_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    records: dict[str, MaterialEvidence] = {}
    contract_materials = {item.id for item in context.contract.materials}
    for item in context.materials:
        if item.instance_id in records:
            failures.append(_diagnostic(
                "material.duplicate_binding", "instance has multiple material evidence records",
                item.instance_id, item.binding_id,
            ))
        records[item.instance_id] = item
    for instance in context.contract.instances:
        item = records.get(instance.id)
        if item is None:
            failures.append(_diagnostic(
                "material.missing_binding", "final object lacks material evidence",
                instance.id, instance.material_id,
            ))
            continue
        if item.material_id != instance.material_id or item.material_id not in contract_materials:
            failures.append(_diagnostic(
                "material.binding_mismatch", "material evidence does not bind the contract material",
                instance.id, item.binding_id,
            ))
        if item.verified == item.degraded:
            failures.append(_diagnostic(
                "material.dishonest_state",
                "material must be exactly one of verified or honestly degraded",
                instance.id, item.binding_id,
            ))
        if item.degraded and not item.degradation_reason.strip():
            failures.append(_diagnostic(
                "material.missing_degradation_reason",
                "degraded material requires a focused degradation reason",
                instance.id, item.binding_id,
            ))
    return failures


def _geometry_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    walls = tuple(context.plan.walls)
    if len(walls) < 3:
        failures.append(_diagnostic(
            "geometry.room_closure", "room requires at least three connected walls",
            context.contract.room.id, "plan.walls",
        ))
    else:
        endpoints: list[tuple[float, float, float]] = []
        edges: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
        for wall in walls:
            try:
                start = tuple(float(value) for value in wall["start"])
                end = tuple(float(value) for value in wall["end"])
            except (KeyError, TypeError, ValueError):
                failures.append(_diagnostic(
                    "geometry.wall_endpoint", "wall has invalid endpoints",
                    str(wall.get("id", "<unnamed>")), "plan.walls",
                ))
                continue
            if len(start) != 3 or len(end) != 3 or math.dist(start, end) <= _EPSILON:
                failures.append(_diagnostic(
                    "geometry.wall_endpoint", "wall endpoints are degenerate",
                    str(wall.get("id", "<unnamed>")), "plan.walls",
                ))
                continue
            endpoints.extend((start, end))
            edges.append((start, end))
        if edges:
            for endpoint in endpoints:
                degree = sum(
                    int(math.dist(endpoint, start) <= _EPSILON)
                    + int(math.dist(endpoint, end) <= _EPSILON)
                    for start, end in edges
                )
                if degree != 2:
                    failures.append(_diagnostic(
                        "geometry.room_closure", "wall endpoint does not have degree two",
                        repr(endpoint), "plan.walls",
                    ))
                    break
            connected = {edges[0][0], edges[0][1]}
            changed = True
            while changed:
                changed = False
                for start, end in edges:
                    if start in connected or end in connected:
                        before = len(connected)
                        connected.update((start, end))
                        changed = changed or len(connected) != before
            if any(start not in connected or end not in connected for start, end in edges):
                failures.append(_diagnostic(
                    "geometry.disconnected_walls", "room wall graph is disconnected",
                    context.contract.room.id, "plan.walls",
                ))
    if not context.plan.revisions:
        failures.append(_diagnostic(
            "geometry.missing_revision", "geometry has no approved Plan revision",
            context.contract.room.id, "plan.revisions",
        ))
    else:
        latest = context.plan.revisions[-1]
        if latest.revision <= 0 or latest.revision != _revision(context):
            failures.append(_diagnostic(
                "geometry.revision_mismatch", "Plan and WorldContract revisions differ",
                context.contract.room.id, str(latest.revision),
            ))
    if context.room is not None:
        visible = {item.stable_id: item for item in context.room.elements}
        for collision in context.room.collision:
            element = visible.get(collision.geometry_id)
            if element is None or (
                collision.position_upbge != element.position_upbge
                or collision.dimensions_upbge != element.dimensions_upbge
            ):
                failures.append(_diagnostic(
                    "geometry.architectural_collision_mismatch",
                    "architectural collision does not match visible Plan geometry",
                    collision.geometry_id, collision.stable_id,
                ))
        if context.room.plan_revision != _revision(context):
            failures.append(_diagnostic(
                "geometry.room_revision", "parametric room binds a different Plan revision",
                context.contract.room.id, str(context.room.plan_revision),
            ))
    return failures


def _physics_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    canonical_hash = _canonical_hash(context.contract)
    settle = context.settle
    if settle.contract_hash != canonical_hash:
        failures.append(_diagnostic(
            "physics.settle_hash", "settle evidence binds a different WorldContract",
            context.contract.room.id, settle.contract_hash,
        ))
    if settle.plan_revision != _revision(context):
        failures.append(_diagnostic(
            "physics.settle_revision", "settle evidence binds a different Plan revision",
            context.contract.room.id, str(settle.plan_revision),
        ))
    if (
        not settle.completed or settle.total_unsettled != 0
        or settle.floating_instance_ids or settle.interpenetrating_pairs
    ):
        offending = (
            settle.floating_instance_ids[0]
            if settle.floating_instance_ids else
            (settle.interpenetrating_pairs[0][0] if settle.interpenetrating_pairs else "")
        )
        failures.append(_diagnostic(
            "physics.unsettled",
            "physics settle is incomplete, floating, or interpenetrating",
            offending, "settle_evidence",
        ))
    if not settle.circulation_preserved:
        failures.append(_diagnostic(
            "physics.circulation_regression", "settle invalidated required circulation",
            context.contract.room.id, "settle_evidence",
        ))
    collision_by_instance = {item.instance_id: item for item in context.collisions}
    if len(collision_by_instance) != len(context.collisions):
        failures.append(_diagnostic(
            "physics.duplicate_collision", "instance has duplicate collision authorities"
        ))
    intents = {item.subject_id: item for item in context.contract.physics.intents}
    for instance in context.contract.instances:
        collision = collision_by_instance.get(instance.id)
        if collision is None:
            failures.append(_diagnostic(
                "physics.missing_collision", "final visible object lacks collision evidence",
                instance.id, instance.physics_intent_id,
            ))
            continue
        dimensions = instance.dimensions
        scale = instance.transform.scale
        expected_dimensions = (
            dimensions.width_m * scale.x,
            dimensions.height_m * scale.y,
            dimensions.depth_m * scale.z,
        )
        expected_center = _vector(instance.transform.position_m)
        expected_rotation = _vector(instance.transform.rotation_deg)
        if (
            collision.geometry_node_id != instance.id
            or any(abs(a - b) > _EPSILON for a, b in zip(collision.center_m, expected_center))
            or any(abs(a - b) > _EPSILON for a, b in zip(collision.dimensions_m, expected_dimensions))
            or any(abs(a - b) > _EPSILON for a, b in zip(collision.rotation_deg, expected_rotation))
        ):
            failures.append(_diagnostic(
                "physics.collision_geometry_mismatch",
                "collision transform/extents do not match visible geometry",
                instance.id, collision.binding_id,
            ))
        if instance.id not in intents or intents[instance.id].id != instance.physics_intent_id:
            failures.append(_diagnostic(
                "physics.intent_binding", "instance physics intent is missing or mismatched",
                instance.id, instance.physics_intent_id,
            ))
        elif intents[instance.id].body_mode == BodyMode.DYNAMIC and intents[instance.id].mass_kg <= 0:
            failures.append(_diagnostic(
                "physics.dynamic_mass", "dynamic instance requires positive mass",
                instance.id, instance.physics_intent_id,
            ))
    return failures


def _semantic_gate(context: StructuralGateContext) -> list[GateDiagnostic]:
    failures: list[GateDiagnostic] = []
    records: dict[str, SemanticEvidence] = {}
    allowed_for_contract_category = {
        "furniture": {"props", "hard-surface"},
        "fixture": {"architecture", "hard-surface", "props"},
        "architectural": {"architecture"},
        "decor": {"props", "foliage", "set-dressing"},
    }
    for item in context.semantics:
        if item.instance_id in records:
            failures.append(_diagnostic(
                "semantic.duplicate_binding", "instance has multiple semantic authorities",
                item.instance_id, item.binding_id,
            ))
        records[item.instance_id] = item
    for instance in context.contract.instances:
        item = records.get(instance.id)
        if item is None:
            failures.append(_diagnostic(
                "semantic.missing_label", "object lacks semantic evidence",
                instance.id, instance.id,
            ))
            continue
        try:
            stable = str(uuid.UUID(item.stable_uuid))
        except (ValueError, AttributeError, TypeError):
            stable = ""
        if stable != instance.id or item.instance_id != instance.id:
            failures.append(_diagnostic(
                "semantic.unstable_uuid", "semantic binding does not preserve the object UUID",
                instance.id, item.binding_id,
            ))
        if not item.semantic_label.strip():
            failures.append(_diagnostic(
                "semantic.empty_label", "semantic label must be non-empty",
                instance.id, item.binding_id,
            ))
        if (
            item.category not in SEMANTIC_CATEGORIES
            or item.category not in allowed_for_contract_category[instance.category]
        ):
            failures.append(_diagnostic(
                "semantic.invalid_category",
                "semantic category is outside taxonomy or conflicts with contract category",
                instance.id, item.binding_id,
            ))
    first = _canonical_hash(context.contract)
    second = _canonical_hash(context.contract)
    try:
        reconstructed = world_contract_from_json(context.contract.canonical_bytes())
        round_trip = _canonical_hash(reconstructed)
    except Exception as exc:
        failures.append(_diagnostic(
            "semantic.canonical_roundtrip", f"canonical contract cannot round-trip: {exc}",
            context.contract.room.id, first,
        ))
    else:
        if first != second or first != round_trip:
            failures.append(_diagnostic(
                "semantic.unstable_hash", "WorldContract hash is unstable across serialization",
                context.contract.room.id, first,
            ))
    return failures


_GATE_FUNCTIONS: tuple[
    tuple[str, Callable[[StructuralGateContext], list[GateDiagnostic]]], ...
] = (
    ("provenance", _provenance_gate),
    ("containment", _containment_gate),
    ("overlap_opening_circulation", _overlap_opening_circulation_gate),
    ("camera", _camera_gate),
    ("asset", _asset_gate),
    ("material", _material_gate),
    ("geometry", _geometry_gate),
    ("physics", _physics_gate),
    ("semantic", _semantic_gate),
)


class StructuralPublicationGates:
    """Evaluate all pre-compilation structural gates without short-circuiting."""

    def evaluate(self, context: StructuralGateContext) -> StructuralGateReport:
        canonical_hash = _canonical_hash(context.contract)
        revision = _revision(context)
        results: list[GateResult] = []
        for name, validator in _GATE_FUNCTIONS:
            try:
                diagnostics = tuple(validator(context))
            except Exception as exc:  # A validator fault must fail closed.
                diagnostics = (_diagnostic(
                    f"{name}.validator_error",
                    f"gate could not establish safety: {type(exc).__name__}: {exc}",
                    context.contract.room.id,
                    name,
                ),)
            results.append(GateResult(
                gate=name,
                passed=not diagnostics,
                plan_revision=revision,
                canonical_hash=canonical_hash,
                diagnostics=diagnostics,
            ))
        return StructuralGateReport(
            plan_revision=revision,
            canonical_hash=canonical_hash,
            results=tuple(results),
            parity_deferred=True,
        )


def validate_before_compilation(
    context: StructuralGateContext,
) -> StructuralGateReport:
    """Run every structural gate and return the complete recorded report."""
    return StructuralPublicationGates().evaluate(context)


def authorize_compilation(context: StructuralGateContext) -> CompilationGateToken:
    """Fail closed unless every structural gate passes for this exact contract.

    Parity is not represented by this token. Task 7.4 must separately validate
    parity after compilation and before final publication.
    """
    return validate_before_compilation(context).require_compilation_ready()


__all__ = [
    "AssetEvidence", "CollisionEvidence", "CompilationGateToken",
    "GateDiagnostic", "GateResult", "MaterialEvidence",
    "MIN_CIRCULATION_CLEARANCE_M", "ProvenanceNode", "PublicationGateError",
    "SemanticEvidence", "SettleEvidence", "StructuralGateContext",
    "StructuralGateReport", "StructuralPublicationGates",
    "authorize_compilation", "validate_before_compilation",
]
