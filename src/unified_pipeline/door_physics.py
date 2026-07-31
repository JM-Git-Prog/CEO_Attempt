"""Plan-bound door hinge and interaction physics configuration.

Door leaves remain architectural/static for classification, while each hinge
receives an explicit positive interaction mass for constrained simulation.
All pivot geometry comes from an approved MetricPlan opening; Canon and depth
are neither accepted nor consulted. Requirements: 18.5, 18.6, 31.1-31.5, 34.1.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from src.unified_pipeline.models import MetricPlan


_ID_NAMESPACE = uuid.UUID("a261756f-ae8f-57f6-a2ad-fbc43345948f")
_EPSILON = 1e-9
_ALLOWED_PLAN_AUTHORITIES = {
    "approved_normalized_metric_plan",
    "metric_plan",
    "plan",
    "",
}
_DENSITY_KG_M3 = {
    "wood": 600.0,
    "metal": 7800.0,
    "glass": 2500.0,
    "fabric": 200.0,
    "ceramic": 2300.0,
    "plastic": 950.0,
}


class DoorPhysicsError(ValueError):
    """Raised when hinge configuration cannot be derived safely from the Plan."""


def _stable_id(kind: str, opening_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, f"{kind}:{opening_id}"))


@dataclass(frozen=True)
class HingePivot:
    """Wall-local pivot that avoids consumer-specific coordinate inference."""

    parent_wall_id: str
    wall_parameter: float
    elevation_m: float
    frame: str = "parent_wall_parameter"


@dataclass(frozen=True)
class HingeJointConfig:
    """Engine-neutral hinge joint configuration for one approved opening."""

    id: str
    joint_type: str
    anchor_body_id: str
    child_body_id: str
    axis: tuple[float, float, float]
    pivot: HingePivot
    lower_limit_deg: float
    upper_limit_deg: float
    interaction_mass_kg: float
    interaction_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["axis"] = list(self.axis)
        return data


@dataclass(frozen=True)
class DoorPhysicsConfig:
    """Static architectural classification plus explicit hinged interaction."""

    id: str
    opening_id: str
    parent_wall_id: str
    plan_revision: int
    plan_hash: str
    body_mode: str
    classification_mass_kg: float
    interaction_mass_kg: float
    mass_source: str
    friction: float
    restitution: float
    can_topple: bool
    is_architectural: bool
    hinge: HingeJointConfig
    spatial_authority: str = "approved_normalized_metric_plan"
    authority_claim: str = "derived_only"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["hinge"] = self.hinge.to_dict()
        return data


@dataclass(frozen=True)
class DoorPhysicsResult:
    """Immutable door configurations bound to one approved Plan revision."""

    plan_revision: int
    plan_hash: str
    doors: tuple[DoorPhysicsConfig, ...]
    spatial_authority: str = "approved_normalized_metric_plan"
    authority_claim: str = "derived_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "plan_hash": self.plan_hash,
            "doors": [door.to_dict() for door in self.doors],
            "spatial_authority": self.spatial_authority,
            "authority_claim": self.authority_claim,
        }


class DoorPhysicsConfigurator:
    """Create stable hinge contracts from approved Plan door openings only."""

    def __init__(
        self,
        *,
        default_interaction_mass_kg: float = 15.0,
        default_limits_deg: tuple[float, float] = (0.0, 90.0),
    ) -> None:
        self.default_interaction_mass_kg = _positive_finite(
            default_interaction_mass_kg, "default interaction mass"
        )
        self.default_limits_deg = _validated_limits(default_limits_deg)

    def configure(
        self,
        plan: MetricPlan,
        *,
        approved_plan_revision: int,
    ) -> DoorPhysicsResult:
        revision, plan_hash = _validate_approval(plan, approved_plan_revision)
        walls = _validated_walls(plan)
        doors: list[DoorPhysicsConfig] = []
        seen_opening_ids: set[str] = set()

        for index, opening in enumerate(plan.openings):
            if str(opening.get("type", "")).strip().lower() != "door":
                continue
            door = self._configure_door(
                opening, index=index, walls=walls,
                revision=revision, plan_hash=plan_hash,
            )
            if door.opening_id in seen_opening_ids:
                raise DoorPhysicsError("Approved door openings require unique stable IDs")
            seen_opening_ids.add(door.opening_id)
            doors.append(door)

        return DoorPhysicsResult(revision, plan_hash, tuple(doors))

    def _configure_door(
        self,
        opening: Mapping[str, Any],
        *,
        index: int,
        walls: Mapping[str, Mapping[str, Any]],
        revision: int,
        plan_hash: str,
    ) -> DoorPhysicsConfig:
        opening_id = str(opening.get("id", "")).strip()
        if not opening_id:
            raise DoorPhysicsError(
                f"Door opening {index} requires an explicit stable Plan opening ID"
            )
        _validate_authority(opening, opening_id)

        wall_id = str(opening.get("wall", "")).strip()
        if wall_id not in walls:
            raise DoorPhysicsError(
                f"Door opening '{opening_id}' references unknown parent wall '{wall_id}'"
            )
        wall_length = _wall_length(walls[wall_id], wall_id)
        parameter = _finite_field(opening, "parameter", opening_id)
        width = _positive_field(opening, "width", opening_id)
        height = _positive_field(opening, "height", opening_id)
        half_span = width / (2.0 * wall_length)
        if parameter - half_span < -_EPSILON or parameter + half_span > 1.0 + _EPSILON:
            raise DoorPhysicsError(
                f"Door opening '{opening_id}' lies outside its approved parent wall"
            )

        hinge_data = opening.get("hinge", {})
        if hinge_data is None:
            hinge_data = {}
        if not isinstance(hinge_data, Mapping):
            raise DoorPhysicsError(f"Door opening '{opening_id}' hinge must be a mapping")
        side = str(hinge_data.get("side", opening.get("hinge_side", "left"))).lower()
        if side not in {"left", "right"}:
            raise DoorPhysicsError(f"Door opening '{opening_id}' hinge side must be left or right")
        pivot_parameter = parameter + (half_span if side == "right" else -half_span)
        elevation = _nonnegative_finite(
            opening.get("base_elevation_m", opening.get("sill_height", 0.0)),
            f"Door opening '{opening_id}' base elevation",
        )
        wall_height = walls[wall_id].get("height")
        if wall_height is not None and elevation + height > _positive_finite(
            wall_height, f"Wall '{wall_id}' height"
        ) + _EPSILON:
            raise DoorPhysicsError(f"Door opening '{opening_id}' exceeds its parent wall height")

        axis = _validated_axis(
            hinge_data.get("axis", opening.get("hinge_axis", (0.0, 1.0, 0.0))),
            opening_id,
        )
        limits = _validated_limits(
            hinge_data.get(
                "limits_deg",
                opening.get("swing_limits_deg", self.default_limits_deg),
            ),
            opening_id=opening_id,
        )
        mass, mass_source = self._interaction_mass(opening, hinge_data, width, height)
        door_id = _stable_id("door-leaf", opening_id)
        hinge_id = _stable_id("door-hinge", opening_id)
        pivot = HingePivot(wall_id, pivot_parameter, elevation)
        hinge = HingeJointConfig(
            id=hinge_id,
            joint_type="hinge",
            anchor_body_id=f"wall:{wall_id}",
            child_body_id=door_id,
            axis=axis,
            pivot=pivot,
            lower_limit_deg=limits[0],
            upper_limit_deg=limits[1],
            interaction_mass_kg=mass,
        )
        return DoorPhysicsConfig(
            id=door_id,
            opening_id=opening_id,
            parent_wall_id=wall_id,
            plan_revision=revision,
            plan_hash=plan_hash,
            body_mode="STATIC",
            classification_mass_kg=0.0,
            interaction_mass_kg=mass,
            mass_source=mass_source,
            friction=0.6,
            restitution=0.1,
            can_topple=False,
            is_architectural=True,
            hinge=hinge,
        )

    def _interaction_mass(
        self,
        opening: Mapping[str, Any],
        hinge_data: Mapping[str, Any],
        width: float,
        height: float,
    ) -> tuple[float, str]:
        explicit = hinge_data.get(
            "mass_kg", opening.get("interaction_mass_kg", opening.get("mass_kg"))
        )
        if explicit is not None:
            return _positive_finite(explicit, "door interaction mass"), "plan_explicit"

        thickness = opening.get("leaf_thickness_m")
        if thickness is not None:
            thickness_m = _positive_finite(thickness, "door leaf thickness")
            material = str(opening.get("material", "wood")).strip().lower()
            density = opening.get("material_density_kg_m3")
            if density is None:
                if material not in _DENSITY_KG_M3:
                    raise DoorPhysicsError(
                        "Plan volume mass requires a known material or explicit density"
                    )
                density_kg_m3 = _DENSITY_KG_M3[material]
            else:
                density_kg_m3 = _positive_finite(density, "door material density")
            return width * height * thickness_m * density_kg_m3, "plan_volume_density"

        return self.default_interaction_mass_kg, "configured_default"


def _validate_approval(plan: MetricPlan, approved_revision: int) -> tuple[int, str]:
    if not plan.revisions:
        raise DoorPhysicsError("Door physics requires an approved nonzero Plan revision")
    latest = max(plan.revisions, key=lambda item: item.revision)
    if latest.revision <= 0 or approved_revision != latest.revision:
        raise DoorPhysicsError("Approved Plan revision must match the latest nonzero revision")
    if not latest.plan_hash:
        raise DoorPhysicsError("Approved Plan revision requires a provenance-bearing plan hash")
    return latest.revision, latest.plan_hash


def _validated_walls(plan: MetricPlan) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for wall in plan.walls:
        wall_id = str(wall.get("id", "")).strip()
        if not wall_id or wall_id in result:
            raise DoorPhysicsError("Approved walls require unique stable IDs")
        _wall_length(wall, wall_id)
        result[wall_id] = wall
    if not result:
        raise DoorPhysicsError("Door physics requires approved parent walls")
    return result


def _wall_length(wall: Mapping[str, Any], wall_id: str) -> float:
    try:
        start = tuple(float(value) for value in wall["start"])
        end = tuple(float(value) for value in wall["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DoorPhysicsError(f"Wall '{wall_id}' requires finite start/end coordinates") from exc
    if len(start) != 3 or len(end) != 3 or not all(math.isfinite(v) for v in start + end):
        raise DoorPhysicsError(f"Wall '{wall_id}' requires finite 3D start/end coordinates")
    length = math.dist(start, end)
    if length <= _EPSILON:
        raise DoorPhysicsError(f"Wall '{wall_id}' length must be positive")
    return length


def _validate_authority(opening: Mapping[str, Any], opening_id: str) -> None:
    for key in ("spatial_authority", "geometry_authority", "source_authority"):
        value = str(opening.get(key, "")).strip().lower()
        if value not in _ALLOWED_PLAN_AUTHORITIES:
            raise DoorPhysicsError(
                f"Door opening '{opening_id}' rejects non-Plan spatial authority '{value}'"
            )


def _finite_field(opening: Mapping[str, Any], field: str, opening_id: str) -> float:
    if field not in opening:
        raise DoorPhysicsError(f"Door opening '{opening_id}' lacks approved '{field}'")
    try:
        value = float(opening[field])
    except (TypeError, ValueError) as exc:
        raise DoorPhysicsError(f"Door opening '{opening_id}' has invalid '{field}'") from exc
    if not math.isfinite(value):
        raise DoorPhysicsError(f"Door opening '{opening_id}' has non-finite '{field}'")
    return value


def _positive_field(opening: Mapping[str, Any], field: str, opening_id: str) -> float:
    value = _finite_field(opening, field, opening_id)
    if value <= 0:
        raise DoorPhysicsError(f"Door opening '{opening_id}' requires positive '{field}'")
    return value


def _positive_finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DoorPhysicsError(f"{label} must be a positive finite number") from exc
    if not math.isfinite(result) or result <= 0:
        raise DoorPhysicsError(f"{label} must be a positive finite number")
    return result


def _nonnegative_finite(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DoorPhysicsError(f"{label} must be a nonnegative finite number") from exc
    if not math.isfinite(result) or result < 0:
        raise DoorPhysicsError(f"{label} must be a nonnegative finite number")
    return result


def _validated_axis(value: Any, opening_id: str) -> tuple[float, float, float]:
    try:
        axis = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise DoorPhysicsError(f"Door opening '{opening_id}' has an invalid hinge axis") from exc
    if len(axis) != 3 or not all(math.isfinite(component) for component in axis):
        raise DoorPhysicsError(f"Door opening '{opening_id}' hinge axis must be finite 3D")
    length = math.sqrt(sum(component * component for component in axis))
    if length <= _EPSILON:
        raise DoorPhysicsError(f"Door opening '{opening_id}' hinge axis cannot be zero")
    normalized = tuple(component / length for component in axis)
    if abs(normalized[0]) > _EPSILON or abs(normalized[2]) > _EPSILON:
        raise DoorPhysicsError(
            f"Door opening '{opening_id}' hinge axis must be vertical in Y-up contract space"
        )
    return normalized  # type: ignore[return-value]


def _validated_limits(
    value: Any,
    *,
    opening_id: str = "default",
) -> tuple[float, float]:
    try:
        limits = tuple(float(component) for component in value)
    except (TypeError, ValueError) as exc:
        raise DoorPhysicsError(f"Door opening '{opening_id}' has invalid swing limits") from exc
    if len(limits) != 2 or not all(math.isfinite(component) for component in limits):
        raise DoorPhysicsError(f"Door opening '{opening_id}' swing limits must be two finite values")
    lower, upper = limits
    if lower >= upper:
        raise DoorPhysicsError(f"Door opening '{opening_id}' swing lower limit must be below upper")
    if lower < -180.0 or upper > 180.0 or upper - lower > 180.0:
        raise DoorPhysicsError(
            f"Door opening '{opening_id}' swing limits must define at most 180 degrees within [-180, 180]"
        )
    return lower, upper


def configure_door_physics(
    plan: MetricPlan,
    *,
    approved_plan_revision: int,
    default_interaction_mass_kg: float = 15.0,
    default_limits_deg: tuple[float, float] = (0.0, 90.0),
) -> DoorPhysicsResult:
    """Convenience wrapper for one-shot door hinge configuration."""

    return DoorPhysicsConfigurator(
        default_interaction_mass_kg=default_interaction_mass_kg,
        default_limits_deg=default_limits_deg,
    ).configure(plan, approved_plan_revision=approved_plan_revision)


__all__ = [
    "DoorPhysicsConfig",
    "DoorPhysicsConfigurator",
    "DoorPhysicsError",
    "DoorPhysicsResult",
    "HingeJointConfig",
    "HingePivot",
    "configure_door_physics",
]
