"""Authority-safe unified adapter for the existing V14 physics classifier.

The approved normalized Metric Plan owns identity, category, dimensions, and
transforms. Neural/semantic evidence may supply only the material used by the
legacy density lookup; spatial or architectural claims are ignored and
reported on the result.

Requirements: 18.1-18.5, 31.1-31.5, 34.1
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

from src.photo_pipeline.stages.physics_classifier import PhysicsClassifier


class PhysicsAdapterError(ValueError):
    """Raised when authoritative Plan physics input is missing or invalid."""


STATIC_PLAN_CATEGORIES = frozenset(
    {
        "architecture",
        "architectural",
        "wall",
        "door",
        "built_in",
        "builtins",
        "countertop",
        "large_appliance",
    }
)

_SPATIAL_EVIDENCE_FIELDS = frozenset(
    {
        "object_id",
        "id",
        "uuid",
        "category",
        "dimensions",
        "dimensions_m",
        "width",
        "height",
        "depth",
        "position",
        "position_m",
        "rotation",
        "rotation_deg",
        "scale",
        "transform",
        "geometry",
        "is_architectural",
    }
)


def _normalized_category(category: str) -> str:
    return category.strip().lower().replace("-", "_").replace(" ", "_")


def _vector3(value: Any, field_name: str, *, positive: bool) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise PhysicsAdapterError(f"{field_name} must contain exactly three values")
    vector = tuple(float(component) for component in value)
    if not all(math.isfinite(component) for component in vector):
        raise PhysicsAdapterError(f"{field_name} values must be finite")
    if positive and not all(component > 0.0 for component in vector):
        raise PhysicsAdapterError(f"{field_name} values must be greater than zero")
    return vector  # type: ignore[return-value]


@dataclass(frozen=True)
class PlanPhysicsInput:
    """Minimal Plan-owned view required for physics classification."""

    plan_revision: int
    object_id: str
    category: str
    dimensions_m: tuple[float, float, float]
    position_m: tuple[float, float, float] | None = None
    rotation_deg: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.plan_revision <= 0:
            raise PhysicsAdapterError("approved Plan revision must be nonzero")
        try:
            UUID(self.object_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise PhysicsAdapterError("object_id must be a stable UUID") from exc
        if not self.category.strip():
            raise PhysicsAdapterError("Plan-owned category is required")
        object.__setattr__(
            self,
            "dimensions_m",
            _vector3(self.dimensions_m, "dimensions_m", positive=True),
        )
        if self.position_m is not None:
            object.__setattr__(
                self,
                "position_m",
                _vector3(self.position_m, "position_m", positive=False),
            )
        if self.rotation_deg is not None:
            object.__setattr__(
                self,
                "rotation_deg",
                _vector3(self.rotation_deg, "rotation_deg", positive=False),
            )

    @classmethod
    def from_plan_placement(
        cls,
        *,
        plan_revision: int,
        placement: Mapping[str, Any],
    ) -> "PlanPhysicsInput":
        """Create the narrow view from one approved Plan placement."""
        object_id = placement.get("object_id", placement.get("id"))
        category = placement.get("category")
        if object_id is None:
            raise PhysicsAdapterError("Plan placement is missing stable object UUID")
        if category is None:
            raise PhysicsAdapterError("Plan placement is missing Plan-owned category")

        dimensions = placement.get("dimensions_m", placement.get("dimensions"))
        if dimensions is None:
            required = ("width", "height", "depth")
            if not all(field in placement for field in required):
                raise PhysicsAdapterError("Plan placement is missing dimensions")
            dimensions = tuple(placement[field] for field in required)

        position = placement.get("position_m", placement.get("position"))
        rotation = placement.get("rotation_deg")
        if isinstance(rotation, (int, float)):
            rotation = (0.0, float(rotation), 0.0)
        elif rotation is None and "rotation" in placement:
            raw_rotation = placement["rotation"]
            rotation = (
                (0.0, float(raw_rotation), 0.0)
                if isinstance(raw_rotation, (int, float))
                else raw_rotation
            )

        return cls(
            plan_revision=plan_revision,
            object_id=str(object_id),
            category=str(category),
            dimensions_m=dimensions,
            position_m=position,
            rotation_deg=rotation,
        )


@dataclass(frozen=True)
class UnifiedPhysicsResult:
    """Physics intent bound to unchanged Plan authority and stable identity."""

    plan_revision: int
    object_id: str
    category: str
    dimensions_m: tuple[float, float, float]
    position_m: tuple[float, float, float] | None
    rotation_deg: tuple[float, float, float] | None
    material: str
    body_mode: str
    mass_kg: float
    estimated_mass_kg: float
    volume_m3: float
    material_density: float
    friction: float
    restitution: float
    can_topple: bool
    override_reason: str | None
    evidence_conflicts: tuple[str, ...] = ()


class UnifiedPhysicsClassifier:
    """Delegate density classification while enforcing the Plan boundary."""

    def __init__(self, classifier: PhysicsClassifier | None = None) -> None:
        self._classifier = classifier or PhysicsClassifier()

    def classify(
        self,
        plan_object: PlanPhysicsInput,
        neural_evidence: Mapping[str, Any] | None = None,
    ) -> UnifiedPhysicsResult:
        """Classify one Plan object; evidence can contribute material only."""
        evidence = neural_evidence or {}
        material_value = evidence.get("primary_material", evidence.get("material", "plastic"))
        material = str(material_value).strip().lower() or "plastic"
        conflicts = tuple(
            f"ignored neural authority claim: {field}"
            for field in sorted(_SPATIAL_EVIDENCE_FIELDS.intersection(evidence))
        )

        category = _normalized_category(plan_object.category)
        is_architectural = category in STATIC_PLAN_CATEGORIES
        legacy = self._classifier.classify(
            dimensions_m=plan_object.dimensions_m,
            material=material,
            is_architectural=is_architectural,
        )

        return UnifiedPhysicsResult(
            plan_revision=plan_object.plan_revision,
            object_id=plan_object.object_id,
            category=plan_object.category,
            dimensions_m=plan_object.dimensions_m,
            position_m=plan_object.position_m,
            rotation_deg=plan_object.rotation_deg,
            material=material,
            body_mode=legacy.body_mode,
            mass_kg=legacy.mass_kg,
            estimated_mass_kg=legacy.volume_m3 * legacy.material_density,
            volume_m3=legacy.volume_m3,
            material_density=legacy.material_density,
            friction=legacy.friction,
            restitution=legacy.restitution,
            can_topple=legacy.can_topple,
            override_reason=legacy.override_reason,
            evidence_conflicts=conflicts,
        )
