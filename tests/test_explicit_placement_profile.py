from __future__ import annotations

from src.floor_plan.models import FloorPlan
from src.floor_plan.validator import normalize_floor_plan


def _source() -> FloorPlan:
    return FloorPlan.model_validate({
        "name": "Profile room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": [{
            "id": "counter_1", "name": "Service Counter", "category": "furniture",
            "mount": "floor", "x": 1.0, "z": 0.0, "width": 1.5, "depth": 0.6,
            "height": 1.0, "elevation": 0.0, "rotation_deg": 0.0,
            "fixed": True, "clearance_m": 0.2,
        }],
        "openings": [],
        "camera": {
            "x": 2.4, "y": 1.6, "z": -1.9,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })


def test_explicit_profile_bypasses_keyword_movement_while_retained_mode_is_stable():
    description = "Place the service counter against the north wall."
    retained, _, _ = normalize_floor_plan(
        _source(), description, strict=True, infer_text_placement=True
    )
    explicit, _, _ = normalize_floor_plan(
        _source(), description, strict=True, infer_text_placement=False
    )
    historical_default, _, _ = normalize_floor_plan(_source(), description, strict=True)

    assert historical_default == retained
    assert retained.items[0].x == 0.0
    assert retained.items[0].z > 0.0
    assert explicit.items[0].x == 1.0
    assert explicit.items[0].z == 0.0
    assert explicit.items[0].fixed is True
