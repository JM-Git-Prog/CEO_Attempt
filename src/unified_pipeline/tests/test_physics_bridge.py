"""Focused tests for the authority-safe unified physics adapter.

Validates Requirements 18.1-18.5, 31.1-31.5, and 34.1.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from src.photo_pipeline.models_v14 import PhysicsClassification
from src.unified_pipeline.physics_bridge import (
    PhysicsAdapterError,
    PlanPhysicsInput,
    STATIC_PLAN_CATEGORIES,
    UnifiedPhysicsClassifier,
)


def _plan_object(
    *,
    category: str = "props",
    dimensions: tuple[float, float, float] = (0.2, 0.2, 0.2),
) -> PlanPhysicsInput:
    return PlanPhysicsInput(
        plan_revision=3,
        object_id=str(uuid4()),
        category=category,
        dimensions_m=dimensions,
        position_m=(1.0, 0.5, 2.0),
        rotation_deg=(0.0, 45.0, 0.0),
    )


def test_factory_requires_and_preserves_plan_owned_fields() -> None:
    object_id = str(uuid4())
    placement = {
        "id": object_id,
        "category": "props",
        "width": 0.4,
        "height": 0.8,
        "depth": 0.3,
        "position": [1.0, 0.4, 2.0],
        "rotation_deg": 90.0,
    }

    result = PlanPhysicsInput.from_plan_placement(
        plan_revision=7,
        placement=placement,
    )

    assert result.plan_revision == 7
    assert result.object_id == object_id
    assert result.category == "props"
    assert result.dimensions_m == (0.4, 0.8, 0.3)
    assert result.position_m == (1.0, 0.4, 2.0)
    assert result.rotation_deg == (0.0, 90.0, 0.0)


@pytest.mark.parametrize(
    ("placement", "message"),
    [
        ({"category": "props", "dimensions": [1, 1, 1]}, "stable object UUID"),
        ({"id": str(uuid4()), "dimensions": [1, 1, 1]}, "Plan-owned category"),
        ({"id": str(uuid4()), "category": "props"}, "dimensions"),
    ],
)
def test_factory_fails_closed_when_plan_authority_is_incomplete(
    placement: dict[str, object], message: str
) -> None:
    with pytest.raises(PhysicsAdapterError, match=message):
        PlanPhysicsInput.from_plan_placement(plan_revision=1, placement=placement)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"plan_revision": 0},
        {"object_id": "not-a-uuid"},
        {"category": ""},
        {"dimensions_m": (1.0, 0.0, 1.0)},
        {"dimensions_m": (1.0, float("nan"), 1.0)},
    ],
)
def test_plan_input_rejects_invalid_authoritative_values(
    kwargs: dict[str, object]
) -> None:
    values: dict[str, object] = {
        "plan_revision": 1,
        "object_id": str(uuid4()),
        "category": "props",
        "dimensions_m": (1.0, 1.0, 1.0),
    }
    values.update(kwargs)
    with pytest.raises(PhysicsAdapterError):
        PlanPhysicsInput(**values)  # type: ignore[arg-type]


def test_plan_input_is_immutable() -> None:
    plan_object = _plan_object()
    with pytest.raises(FrozenInstanceError):
        plan_object.category = "architecture"  # type: ignore[misc]


def test_exactly_25kg_is_dynamic_with_required_defaults() -> None:
    # 0.125 m³ × fabric density 200 kg/m³ = exactly 25 kg.
    result = UnifiedPhysicsClassifier().classify(
        _plan_object(dimensions=(0.5, 0.5, 0.5)),
        {"primary_material": "fabric"},
    )

    assert result.body_mode == "DYNAMIC"
    assert result.mass_kg == pytest.approx(25.0)
    assert result.estimated_mass_kg == pytest.approx(25.0)
    assert result.friction == 0.5
    assert result.restitution == 0.2
    assert result.can_topple is True


def test_over_25kg_is_static_with_required_defaults() -> None:
    result = UnifiedPhysicsClassifier().classify(
        _plan_object(dimensions=(1.0, 1.0, 1.0)),
        {"primary_material": "wood"},
    )

    assert result.body_mode == "STATIC"
    assert result.mass_kg == 0.0
    assert result.estimated_mass_kg == 600.0
    assert result.friction == 0.6
    assert result.restitution == 0.1
    assert result.can_topple is False
    assert result.override_reason is None


def test_unknown_material_preserves_legacy_default_density() -> None:
    result = UnifiedPhysicsClassifier().classify(
        _plan_object(dimensions=(0.1, 0.1, 0.1)),
        {"primary_material": "stone"},
    )

    assert result.material_density == 950.0
    assert result.estimated_mass_kg == pytest.approx(0.95)
    assert result.body_mode == "DYNAMIC"


@pytest.mark.parametrize("category", sorted(STATIC_PLAN_CATEGORIES))
def test_every_architectural_plan_category_forces_static(category: str) -> None:
    result = UnifiedPhysicsClassifier().classify(
        _plan_object(category=category, dimensions=(0.01, 0.01, 0.01)),
        {"primary_material": "fabric", "is_architectural": False},
    )

    assert result.body_mode == "STATIC"
    assert result.mass_kg == 0.0
    assert result.can_topple is False
    assert result.override_reason == "architectural_function"
    assert "ignored neural authority claim: is_architectural" in result.evidence_conflicts


def test_neural_architectural_claim_cannot_override_plan_category() -> None:
    result = UnifiedPhysicsClassifier().classify(
        _plan_object(category="props", dimensions=(0.1, 0.1, 0.1)),
        {"primary_material": "fabric", "is_architectural": True},
    )

    assert result.body_mode == "DYNAMIC"
    assert result.override_reason is None


def test_neural_evidence_cannot_rewrite_identity_geometry_or_transform() -> None:
    plan_object = _plan_object(dimensions=(0.1, 0.2, 0.3))
    foreign_uuid = str(uuid4())
    evidence = {
        "primary_material": "wood",
        "object_id": foreign_uuid,
        "category": "architecture",
        "dimensions_m": (9.0, 9.0, 9.0),
        "position_m": (9.0, 9.0, 9.0),
        "rotation_deg": (90.0, 90.0, 90.0),
        "geometry": "neural-mesh.glb",
    }

    result = UnifiedPhysicsClassifier().classify(plan_object, evidence)

    assert result.object_id == plan_object.object_id
    assert result.category == plan_object.category
    assert result.dimensions_m == plan_object.dimensions_m
    assert result.position_m == plan_object.position_m
    assert result.rotation_deg == plan_object.rotation_deg
    assert result.volume_m3 == pytest.approx(0.006)
    assert len(result.evidence_conflicts) == 6


def test_adapter_delegates_once_to_existing_classifier() -> None:
    class RecordingClassifier:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[float, float, float], str, bool]] = []

        def classify(
            self,
            dimensions_m: tuple[float, float, float],
            material: str,
            is_architectural: bool,
        ) -> PhysicsClassification:
            self.calls.append((dimensions_m, material, is_architectural))
            return PhysicsClassification(
                body_mode="DYNAMIC",
                mass_kg=1.0,
                volume_m3=0.001,
                material_density=1000.0,
                friction=0.5,
                restitution=0.2,
                can_topple=True,
                override_reason=None,
            )

    legacy = RecordingClassifier()
    plan_object = _plan_object(dimensions=(0.1, 0.1, 0.1))
    result = UnifiedPhysicsClassifier(classifier=legacy).classify(
        plan_object,
        {"primary_material": "glass"},
    )

    assert legacy.calls == [((0.1, 0.1, 0.1), "glass", False)]
    assert result.object_id == plan_object.object_id
    assert UUID(result.object_id) == UUID(plan_object.object_id)
