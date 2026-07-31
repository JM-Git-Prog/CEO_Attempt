"""Focused unit tests for Plan-bound door hinge configuration.

Validates Requirements 18.5, 18.6, 31.1-31.5, and 34.1.
"""

from __future__ import annotations

import pytest

from src.unified_pipeline.door_physics import (
    DoorPhysicsConfigurator,
    DoorPhysicsError,
    configure_door_physics,
)
from src.unified_pipeline.models import MetricPlan, PlanRevision


def _plan(
    door: dict | None = None,
    *,
    revision: int = 4,
    plan_hash: str = "approved-plan-hash-4",
) -> MetricPlan:
    opening = door or {
        "id": "door-south-entry",
        "type": "door",
        "wall": "south",
        "parameter": 0.5,
        "width": 0.9,
        "height": 2.1,
    }
    return MetricPlan(
        room_dimensions=(4.0, 3.0, 2.7),
        walls=(
            {"id": "south", "start": (0.0, 0.0, 0.0), "end": (4.0, 0.0, 0.0), "height": 2.7},
            {"id": "north", "start": (4.0, 0.0, 3.0), "end": (0.0, 0.0, 3.0), "height": 2.7},
        ),
        openings=(opening, {"id": "window-n", "type": "window", "wall": "north", "parameter": 0.5, "width": 1.0, "height": 1.0}),
        revisions=(PlanRevision(revision=revision, plan_hash=plan_hash, changed="approved"),),
        template_id="kitchen",
    )


def test_default_hinge_is_plan_bound_and_architectural_static() -> None:
    result = configure_door_physics(_plan(), approved_plan_revision=4)

    assert result.plan_revision == 4
    assert result.plan_hash == "approved-plan-hash-4"
    assert result.spatial_authority == "approved_normalized_metric_plan"
    assert len(result.doors) == 1
    door = result.doors[0]
    assert door.opening_id == "door-south-entry"
    assert door.body_mode == "STATIC"
    assert door.classification_mass_kg == 0.0
    assert door.interaction_mass_kg == 15.0
    assert door.mass_source == "configured_default"
    assert door.is_architectural is True
    assert door.can_topple is False


def test_hinge_has_explicit_axis_limits_and_wall_local_left_pivot() -> None:
    hinge = configure_door_physics(_plan(), approved_plan_revision=4).doors[0].hinge

    assert hinge.joint_type == "hinge"
    assert hinge.axis == (0.0, 1.0, 0.0)
    assert (hinge.lower_limit_deg, hinge.upper_limit_deg) == (0.0, 90.0)
    assert hinge.pivot.parent_wall_id == "south"
    assert hinge.pivot.frame == "parent_wall_parameter"
    assert hinge.pivot.wall_parameter == pytest.approx(0.5 - 0.9 / 8.0)
    assert hinge.pivot.elevation_m == 0.0
    assert hinge.interaction_enabled is True


def test_explicit_plan_hinge_configuration_is_preserved() -> None:
    door = {
        "id": "door-custom",
        "type": "door",
        "wall": "south",
        "parameter": 0.6,
        "width": 1.0,
        "height": 2.2,
        "base_elevation_m": 0.05,
        "hinge": {
            "side": "right",
            "axis": (0.0, -2.0, 0.0),
            "limits_deg": (-100.0, 5.0),
            "mass_kg": 18.5,
        },
    }
    configured = configure_door_physics(_plan(door), approved_plan_revision=4).doors[0]

    assert configured.mass_source == "plan_explicit"
    assert configured.interaction_mass_kg == 18.5
    assert configured.hinge.axis == (0.0, -1.0, 0.0)
    assert configured.hinge.pivot.wall_parameter == pytest.approx(0.6 + 1.0 / 8.0)
    assert configured.hinge.pivot.elevation_m == 0.05
    assert (configured.hinge.lower_limit_deg, configured.hinge.upper_limit_deg) == (-100.0, 5.0)


def test_plan_volume_density_assigns_interaction_mass_without_changing_static_classification() -> None:
    door = {
        "id": "door-oak",
        "type": "door",
        "wall": "south",
        "parameter": 0.5,
        "width": 0.9,
        "height": 2.1,
        "leaf_thickness_m": 0.04,
        "material": "wood",
    }
    configured = configure_door_physics(_plan(door), approved_plan_revision=4).doors[0]

    assert configured.interaction_mass_kg == pytest.approx(0.9 * 2.1 * 0.04 * 600.0)
    assert configured.mass_source == "plan_volume_density"
    assert configured.body_mode == "STATIC"
    assert configured.classification_mass_kg == 0.0


def test_ids_are_stable_across_reconfiguration_and_unrelated_plan_revision() -> None:
    first = configure_door_physics(_plan(), approved_plan_revision=4).doors[0]
    revised = configure_door_physics(
        _plan(revision=5, plan_hash="approved-plan-hash-5"),
        approved_plan_revision=5,
    ).doors[0]

    assert first.id == revised.id
    assert first.hinge.id == revised.hinge.id
    assert revised.plan_revision == 5
    assert revised.plan_hash == "approved-plan-hash-5"
    assert first.hinge.child_body_id == first.id
    assert first.hinge.anchor_body_id == "wall:south"


def test_serialization_contains_explicit_identity_authority_and_hinge_mass() -> None:
    payload = configure_door_physics(_plan(), approved_plan_revision=4).to_dict()

    assert payload["authority_claim"] == "derived_only"
    door = payload["doors"][0]
    assert door["opening_id"] == "door-south-entry"
    assert door["hinge"]["pivot"]["frame"] == "parent_wall_parameter"
    assert door["hinge"]["axis"] == [0.0, 1.0, 0.0]
    assert door["hinge"]["interaction_mass_kg"] == door["interaction_mass_kg"]


@pytest.mark.parametrize(
    ("plan", "approved_revision", "message"),
    [
        (MetricPlan(), 1, "nonzero Plan revision"),
        (_plan(), 3, "match the latest"),
        (_plan(plan_hash=""), 4, "plan hash"),
    ],
)
def test_rejects_unapproved_stale_or_unhashed_plan(
    plan: MetricPlan, approved_revision: int, message: str
) -> None:
    with pytest.raises(DoorPhysicsError, match=message):
        configure_door_physics(plan, approved_plan_revision=approved_revision)


def test_rejects_missing_or_duplicate_stable_opening_ids() -> None:
    missing = {
        "type": "door", "wall": "south", "parameter": 0.5,
        "width": 0.9, "height": 2.1,
    }
    with pytest.raises(DoorPhysicsError, match="explicit stable Plan opening ID"):
        configure_door_physics(_plan(missing), approved_plan_revision=4)

    valid = dict(_plan().openings[0])
    duplicate_plan = _plan()
    duplicate_plan = MetricPlan(
        room_dimensions=duplicate_plan.room_dimensions,
        walls=duplicate_plan.walls,
        openings=(valid, dict(valid)),
        revisions=duplicate_plan.revisions,
    )
    with pytest.raises(DoorPhysicsError, match="unique stable IDs"):
        configure_door_physics(duplicate_plan, approved_plan_revision=4)


def test_rejects_non_plan_spatial_authority_without_reading_evidence_geometry() -> None:
    door = dict(_plan().openings[0])
    door.update({"geometry_authority": "depth", "depth_width": 1.4, "canon_height": 2.4})

    with pytest.raises(DoorPhysicsError, match="non-Plan spatial authority 'depth'"):
        configure_door_physics(_plan(door), approved_plan_revision=4)


def test_rejects_invalid_parent_geometry_axis_limits_and_mass() -> None:
    base = dict(_plan().openings[0])
    cases = [
        ({**base, "wall": "missing"}, "unknown parent wall"),
        ({**base, "parameter": 0.02}, "outside its approved parent wall"),
        ({**base, "hinge_axis": (1.0, 0.0, 0.0)}, "vertical in Y-up"),
        ({**base, "swing_limits_deg": (90.0, 0.0)}, "lower limit"),
        ({**base, "interaction_mass_kg": 0.0}, "positive finite"),
    ]

    for door, message in cases:
        with pytest.raises(DoorPhysicsError, match=message):
            configure_door_physics(_plan(door), approved_plan_revision=4)


def test_windows_are_ignored_and_empty_door_set_is_valid() -> None:
    plan = _plan()
    no_doors = MetricPlan(
        room_dimensions=plan.room_dimensions,
        walls=plan.walls,
        openings=(plan.openings[1],),
        revisions=plan.revisions,
    )

    result = DoorPhysicsConfigurator().configure(no_doors, approved_plan_revision=4)

    assert result.doors == ()
    assert result.plan_revision == 4
