"""Deterministic V11 pre-approval camera composition qualification."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.camera_contract import camera_contract_for_plan, project_point
from src.floor_plan.models import FloorPlanV11, PlanCamera, PlanItem, PlanOpening


class FrozenEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)


class ProjectedCorner(FrozenEvidence):
    index: int
    screen_x: float | None
    screen_y: float | None
    depth: float | None
    inside: bool


class ProjectedInstanceBounds(FrozenEvidence):
    instance_id: str
    instance_kind: Literal["item", "opening"]
    minimum_x: float | None
    maximum_x: float | None
    minimum_y: float | None
    maximum_y: float | None
    minimum_depth: float | None
    fully_inside: bool
    corners: tuple[ProjectedCorner, ...]


class CandidateSummary(FrozenEvidence):
    index: int
    inset_m: float
    target_offset_m: tuple[float, float, float]
    covered_instances: int
    required_instances: int
    clipped_ids: tuple[str, ...]
    minimum_margin_px: float
    adjustment_cost: float


class CandidateEvidence(CandidateSummary):
    camera: PlanCamera
    projected_bounds: tuple[ProjectedInstanceBounds, ...]


class CompositionEvidence(FrozenEvidence):
    schema_version: Literal["composition-evidence/v1"] = "composition-evidence/v1"
    status: Literal["accepted", "rejected"]
    camera_corner: str
    vertical_fov_deg: float
    image_width: int
    image_height: int
    safe_margin_ratio: float
    required_ids: tuple[str, ...]
    candidate_count: int
    candidate_set_sha256: str
    selected: CandidateEvidence | None = None
    best_rejected: CandidateEvidence | None = None
    evidence_sha256: str = Field(min_length=64, max_length=64)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.model_dump(mode="json") if isinstance(item, BaseModel) else str(item),
    ).encode()


def _rotated_item_corners(item: PlanItem) -> tuple[tuple[float, float, float], ...]:
    angle = math.radians(item.rotation_deg)
    cosine, sine = math.cos(angle), math.sin(angle)
    points: list[tuple[float, float, float]] = []
    for local_x, local_z, y in itertools.product(
        (-item.width / 2.0, item.width / 2.0),
        (-item.depth / 2.0, item.depth / 2.0),
        (item.elevation, item.elevation + item.height),
    ):
        points.append((
            item.x + local_x * cosine - local_z * sine,
            y,
            item.z + local_x * sine + local_z * cosine,
        ))
    return tuple(points)


def _opening_corners(plan: FloorPlanV11, opening: PlanOpening) -> tuple[tuple[float, float, float], ...]:
    half_width, half_depth = plan.room.width / 2.0, plan.room.depth / 2.0
    y_values = (opening.sill_height, opening.sill_height + opening.height)
    if opening.wall in {"north", "south"}:
        z = half_depth if opening.wall == "north" else -half_depth
        return tuple(
            (opening.offset + along, y, z)
            for along, y in itertools.product((-opening.width / 2.0, opening.width / 2.0), y_values)
        )
    x = half_width if opening.wall == "east" else -half_width
    return tuple(
        (x, y, opening.offset + along)
        for along, y in itertools.product((-opening.width / 2.0, opening.width / 2.0), y_values)
    )


def _project_bounds(
    contract,
    instance_id: str,
    instance_kind: Literal["item", "opening"],
    points: tuple[tuple[float, float, float], ...],
    margin_ratio: float,
) -> ProjectedInstanceBounds:
    margin_x = contract.image_width * margin_ratio
    margin_y = contract.image_height * margin_ratio
    corners: list[ProjectedCorner] = []
    finite: list[tuple[float, float, float]] = []
    for index, point in enumerate(points):
        projected = project_point(contract, point)
        if projected is None or not all(math.isfinite(value) for value in projected):
            corners.append(ProjectedCorner(index=index, screen_x=None, screen_y=None, depth=None, inside=False))
            continue
        x, y, depth = projected
        inside = (
            margin_x <= x <= contract.image_width - margin_x
            and margin_y <= y <= contract.image_height - margin_y
        )
        finite.append((x, y, depth))
        corners.append(ProjectedCorner(
            index=index, screen_x=round(x, 6), screen_y=round(y, 6),
            depth=round(depth, 6), inside=inside,
        ))
    return ProjectedInstanceBounds(
        instance_id=instance_id,
        instance_kind=instance_kind,
        minimum_x=round(min(value[0] for value in finite), 6) if finite else None,
        maximum_x=round(max(value[0] for value in finite), 6) if finite else None,
        minimum_y=round(min(value[1] for value in finite), 6) if finite else None,
        maximum_y=round(max(value[1] for value in finite), 6) if finite else None,
        minimum_depth=round(min(value[2] for value in finite), 6) if finite else None,
        fully_inside=len(finite) == len(points) and all(value.inside for value in corners),
        corners=tuple(corners),
    )


def _candidate_camera(
    plan: FloorPlanV11,
    inset_m: float,
    target_offset: tuple[float, float, float],
    fov_deg: float,
) -> PlanCamera:
    intent = plan.camera_intent
    half_width, half_depth = plan.room.width / 2.0, plan.room.depth / 2.0
    east = intent.corner in {"northeast", "southeast"}
    north = intent.corner in {"northwest", "northeast"}
    target = next(item for item in plan.items if item.id == intent.target_id)
    return PlanCamera(
        x=(half_width - inset_m) if east else (-half_width + inset_m),
        y=min(intent.eye_height_m, plan.room.height - 0.2),
        z=(half_depth - inset_m) if north else (-half_depth + inset_m),
        target_x=target.x + target_offset[0],
        target_y=min(plan.room.height, max(0.0, intent.target_height_m + target_offset[1])),
        target_z=target.z + target_offset[2],
        fov_deg=fov_deg,
    )


def _minimum_margin(bounds: tuple[ProjectedInstanceBounds, ...], width: int, height: int) -> float:
    values: list[float] = []
    for instance in bounds:
        for corner in instance.corners:
            if corner.screen_x is None or corner.screen_y is None:
                return -1_000_000.0
            values.extend((corner.screen_x, width - corner.screen_x, corner.screen_y, height - corner.screen_y))
    return min(values, default=-1_000_000.0)


def qualify_v11_composition(
    plan: FloorPlanV11,
    policy: dict | None = None,
) -> tuple[FloorPlanV11, CompositionEvidence]:
    """Select one bounded camera candidate without mutating Plan geometry.

    FOV: the intent FOV is tried first with the full candidate grid; only if no
    candidate is accepted does the ladder widen FOV in small policy-bounded steps
    (default +3/+5/+7 deg, capped at 62). Geometry is never mutated.
    """
    settings = policy or {}
    width = int(settings.get("image_width", 1024))
    height = int(settings.get("image_height", 768))
    margin = float(settings.get("safe_margin_ratio", 0.03))
    inset_offsets = tuple(float(value) for value in settings.get(
        "inset_offsets_m", (0.0, -0.1, 0.1, -0.2, 0.2)
    ))
    x_offsets = tuple(float(value) for value in settings.get(
        "target_x_offsets_m", (0.0, -0.4, 0.4, -0.8, 0.8, -1.2, 1.2)
    ))
    y_offsets = tuple(float(value) for value in settings.get(
        "target_y_offsets_m", (0.0, -0.3, 0.3, -0.6, 0.6, 0.9)
    ))
    z_offsets = tuple(float(value) for value in settings.get(
        "target_z_offsets_m", (0.0, -0.4, 0.4, -0.8, 0.8, -1.2, 1.2)
    ))
    require_openings = bool(settings.get("require_openings", False))
    required: list[tuple[str, Literal["item", "opening"], tuple[tuple[float, float, float], ...]]] = [
        (item.id, "item", _rotated_item_corners(item)) for item in sorted(plan.items, key=lambda value: value.id)
    ]
    if require_openings:
        required.extend(
            (opening.id, "opening", _opening_corners(plan, opening))
            for opening in sorted(plan.openings, key=lambda value: value.id)
        )
    required_ids = tuple(value[0] for value in required)
    summaries: list[CandidateSummary] = []
    detailed: list[CandidateEvidence] = []
    minimum_inset = float(settings.get("minimum_inset_m", 0.22))
    maximum_inset = min(plan.room.width, plan.room.depth) / 2.0 - 0.05
    fov_offsets = tuple(float(value) for value in settings.get(
        "fov_offsets_deg", (0.0, 3.0, 5.0, 7.0)
    ))
    maximum_fov = float(settings.get("maximum_fov_deg", 62.0))

    selected: CandidateEvidence | None = None
    index = 0
    tried_fovs: list[float] = []
    for fov_offset in fov_offsets:
        fov = min(plan.camera_intent.fov_deg + fov_offset, maximum_fov)
        if fov in tried_fovs:
            continue
        tried_fovs.append(fov)
        for values in itertools.product(inset_offsets, x_offsets, y_offsets, z_offsets):
            inset_delta, offset_x, offset_y, offset_z = values
            inset = min(maximum_inset, max(minimum_inset, plan.camera_intent.inset_m + inset_delta))
            target_offset = (offset_x, offset_y, offset_z)
            camera = _candidate_camera(plan, inset, target_offset, fov)
            candidate_plan = plan.model_copy(update={"camera": camera})
            contract = camera_contract_for_plan(candidate_plan, width=width, height=height)
            bounds = tuple(
                _project_bounds(contract, instance_id, kind, points, margin)
                for instance_id, kind, points in required
            )
            clipped = tuple(value.instance_id for value in bounds if not value.fully_inside)
            adjustment = abs(inset_delta) + abs(offset_x) + abs(offset_y) + abs(offset_z)
            base = {
                "index": index,
                "inset_m": round(inset, 6),
                "target_offset_m": target_offset,
                "covered_instances": len(required) - len(clipped),
                "required_instances": len(required),
                "clipped_ids": clipped,
                "minimum_margin_px": round(_minimum_margin(bounds, width, height), 6),
                "adjustment_cost": round(adjustment, 6),
            }
            summaries.append(CandidateSummary(**base))
            detailed.append(CandidateEvidence(**base, camera=camera, projected_bounds=bounds))
            index += 1
        accepted = [value for value in detailed if not value.clipped_ids]
        selected = max(
            accepted,
            key=lambda value: (value.minimum_margin_px, -value.adjustment_cost, -value.index),
            default=None,
        )
        if selected is not None:
            break

    best_rejected = None if selected else max(
        detailed,
        key=lambda value: (
            value.covered_instances, value.minimum_margin_px,
            -value.adjustment_cost, -value.index,
        ),
        default=None,
    )
    summary_hash = hashlib.sha256(_canonical(tuple(summaries))).hexdigest()
    evidence_payload = {
        "schema_version": "composition-evidence/v1",
        "status": "accepted" if selected else "rejected",
        "camera_corner": plan.camera_intent.corner,
        "vertical_fov_deg": plan.camera_intent.fov_deg,
        "image_width": width,
        "image_height": height,
        "safe_margin_ratio": margin,
        "required_ids": required_ids,
        "candidate_count": len(summaries),
        "candidate_set_sha256": summary_hash,
        "selected": selected,
        "best_rejected": best_rejected,
    }
    evidence_hash = hashlib.sha256(_canonical(evidence_payload)).hexdigest()
    evidence = CompositionEvidence(**evidence_payload, evidence_sha256=evidence_hash)
    if selected is None:
        return plan.model_copy(deep=True), evidence
    return plan.model_copy(deep=True, update={"camera": selected.camera}), evidence
