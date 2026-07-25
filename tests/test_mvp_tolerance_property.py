"""Property-based tests for MVP tolerance validation (Property 2).

**Validates: Requirements 2.2**

Property 2: MVP Tolerance — Non-Critical Acceptance vs Structural Rejection
- Property 2a: Plans with ONLY non-critical violations (overlaps ≤ 0.1m,
  clearance violations ≤ 0.15m) SHALL be accepted with tolerance_warnings.
- Property 2b: Plans with structural impossibilities (vertex outside bounds,
  zero-dimension room, duplicate IDs, non-finite geometry) SHALL be rejected
  regardless of any non-critical violations present.
"""

from __future__ import annotations

import math

from hypothesis import assume, given, settings, strategies as st

from src.floor_plan.models import FloorPlan, PlanValidationReport
from src.floor_plan.validator import validate_floor_plan


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

# Room dimensions respecting Pydantic constraints
room_width_st = st.floats(min_value=4.0, max_value=20.0, allow_nan=False, allow_infinity=False)
room_depth_st = st.floats(min_value=4.0, max_value=20.0, allow_nan=False, allow_infinity=False)
room_height_st = st.floats(min_value=2.5, max_value=6.0, allow_nan=False, allow_infinity=False)

# Item dimensions (valid Pydantic range: gt=0, le=20 for width/depth; gt=0, le=8 for height)
item_width_st = st.floats(min_value=0.3, max_value=2.0, allow_nan=False, allow_infinity=False)
item_depth_st = st.floats(min_value=0.3, max_value=2.0, allow_nan=False, allow_infinity=False)
item_height_st = st.floats(min_value=0.3, max_value=2.5, allow_nan=False, allow_infinity=False)

# Small controlled overlap: must be > 0.03m (geometry tolerance) and ≤ 0.1m (MVP threshold)
overlap_amount_st = st.floats(min_value=0.04, max_value=0.09, allow_nan=False, allow_infinity=False)


def _make_camera(room_width: float, room_depth: float) -> dict:
    """Create a camera safely within room bounds."""
    return {
        "x": room_width * 0.3,
        "y": 1.6,
        "z": -(room_depth * 0.3),
        "target_x": 0.0,
        "target_y": 1.1,
        "target_z": 0.0,
        "fov_deg": 55.0,
    }


def _make_item(item_id: str, x: float, z: float, width: float, depth: float,
               height: float = 1.0, clearance_m: float = 0.0) -> dict:
    """Create an item dict for FloorPlan construction."""
    return {
        "id": item_id,
        "name": item_id.replace("_", " ").title(),
        "category": "furniture",
        "mount": "floor",
        "x": x,
        "z": z,
        "width": width,
        "depth": depth,
        "height": height,
        "elevation": 0.0,
        "rotation_deg": 0.0,
        "fixed": False,
        "clearance_m": clearance_m,
        "description": "",
    }


# ---------------------------------------------------------------------------
# Property 2a: Non-critical violations accepted with warnings
# ---------------------------------------------------------------------------


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    item_w=item_width_st,
    item_d=item_depth_st,
    item_h=item_height_st,
    overlap=overlap_amount_st,
)
@settings(max_examples=200)
def test_property_2a_noncritical_overlap_accepted(
    room_w: float,
    room_d: float,
    room_h: float,
    item_w: float,
    item_d: float,
    item_h: float,
    overlap: float,
):
    """Property 2a: Plans with only non-critical overlap (≤ 0.1m) SHALL pass.

    **Validates: Requirements 2.2**

    Strategy: Place two identical items side by side with a controlled overlap
    that is within the MVP threshold. Both items must remain inside room bounds.
    """
    # Calculate positions: items placed along x-axis with controlled overlap
    # item centers: left at -offset, right at +offset
    # overlap = (item_w/2 + item_w/2) - distance = item_w - distance
    # distance = item_w - overlap
    distance = item_w - overlap
    left_x = -(distance / 2)
    right_x = distance / 2

    # Ensure items stay within room bounds (half-width minus margin)
    half_room_w = room_w / 2
    half_room_d = room_d / 2
    margin = 0.05  # geometry margin used by inside_room

    # Items must not extend beyond room bounds
    left_edge = abs(left_x) + item_w / 2
    right_edge = abs(right_x) + item_w / 2
    depth_edge = item_d / 2

    assume(left_edge < half_room_w - margin)
    assume(right_edge < half_room_w - margin)
    assume(depth_edge < half_room_d - margin)

    plan = FloorPlan.model_validate({
        "name": "Property 2a test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": [
            _make_item("item_a", left_x, 0.0, item_w, item_d, item_h, clearance_m=0.0),
            _make_item("item_b", right_x, 0.0, item_w, item_d, item_h, clearance_m=0.0),
        ],
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    # Plan SHALL be accepted (valid == True)
    assert report.valid, (
        f"Plan with overlap={overlap:.4f}m should be accepted in MVP mode "
        f"but got blockers: {[b.code for b in report.blockers]}"
    )
    # SHALL produce tolerance_warnings (at minimum an overlap warning)
    assert len(report.tolerance_warnings) > 0, (
        f"Expected tolerance_warnings for overlap={overlap:.4f}m but got none"
    )
    # At least one warning must be the overlap we created
    overlap_warnings = [w for w in report.tolerance_warnings if w["warning_type"] == "overlap"]
    assert len(overlap_warnings) > 0, (
        f"Expected at least one overlap tolerance_warning but got: "
        f"{[w['warning_type'] for w in report.tolerance_warnings]}"
    )
    # Each overlap warning must respect the threshold
    for w in overlap_warnings:
        assert w["measured_deviation"] <= 0.1
        assert w["threshold"] == 0.1
    # All tolerance warnings must have correct structure
    for w in report.tolerance_warnings:
        assert "warning_type" in w
        assert "affected_id" in w
        assert "measured_deviation" in w
        assert "threshold" in w


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    item_w=st.floats(min_value=0.5, max_value=1.5, allow_nan=False, allow_infinity=False),
    item_d=st.floats(min_value=0.5, max_value=1.5, allow_nan=False, allow_infinity=False),
    clearance_violation=st.floats(min_value=0.01, max_value=0.14, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_property_2a_noncritical_clearance_accepted(
    room_w: float,
    room_d: float,
    room_h: float,
    item_w: float,
    item_d: float,
    clearance_violation: float,
):
    """Property 2a: Plans with only non-critical clearance violations (≤ 0.15m) SHALL pass.

    **Validates: Requirements 2.2**

    Strategy: Place two items that don't physically overlap but whose clearance
    zones intersect by a controlled amount within the MVP clearance threshold.
    """
    # Use a fixed clearance_m that produces predictable padding
    # _clearance_padding(item) = min(0.4, clearance_m / 2)
    # With clearance_m=0.4 → padding = 0.2 per item
    clearance_m = 0.4
    padding = clearance_m / 2  # = 0.2

    # Items placed along x-axis with a physical gap (no overlap) but clearance zone overlap
    # Physical separation = item_w (center-to-center distance where edges just touch)
    # With clearance padding, overlap = (item_w/2 + padding) + (item_w/2 + padding) - distance
    # We want: clearance_overlap = clearance_violation (which is ≤ 0.15m)
    # distance = item_w + 2*padding - clearance_violation
    distance = item_w + 2 * padding - clearance_violation

    # Ensure physical gap exists (no physical overlap)
    physical_gap = distance - item_w
    assume(physical_gap > 0.04)  # Must have clear physical separation (> tolerance 0.03)

    left_x = -(distance / 2)
    right_x = distance / 2

    # Ensure items stay within room bounds
    half_room_w = room_w / 2
    half_room_d = room_d / 2
    margin = 0.05

    max_edge = abs(right_x) + item_w / 2
    assume(max_edge < half_room_w - margin)
    assume(item_d / 2 < half_room_d - margin)

    plan = FloorPlan.model_validate({
        "name": "Property 2a clearance test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": [
            _make_item("item_a", left_x, 0.0, item_w, item_d, 1.0, clearance_m=clearance_m),
            _make_item("item_b", right_x, 0.0, item_w, item_d, 1.0, clearance_m=clearance_m),
        ],
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    # Plan SHALL be accepted
    assert report.valid, (
        f"Plan with clearance_violation={clearance_violation:.4f}m should be accepted "
        f"but got blockers: {[b.code for b in report.blockers]}"
    )


# ---------------------------------------------------------------------------
# Property 2b: Structural impossibilities ALWAYS rejected
# ---------------------------------------------------------------------------


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    item_w=item_width_st,
    item_d=item_depth_st,
)
@settings(max_examples=200)
def test_property_2b_out_of_bounds_rejected(
    room_w: float,
    room_d: float,
    room_h: float,
    item_w: float,
    item_d: float,
):
    """Property 2b: Items with vertices outside room bounds SHALL be rejected.

    **Validates: Requirements 2.2**

    Strategy: Place an item so its edge extends beyond the room boundary.
    """
    # Position item so its right edge is beyond room half-width
    half_room_w = room_w / 2
    # Item center at half_room_w so right edge is at half_room_w + item_w/2
    # This guarantees the item extends past the boundary
    out_of_bounds_x = half_room_w

    plan = FloorPlan.model_validate({
        "name": "Property 2b bounds test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": [
            _make_item("oob_item", out_of_bounds_x, 0.0, item_w, item_d, 1.0),
        ],
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    # SHALL be rejected regardless of MVP mode
    assert not report.valid, (
        f"Plan with item at x={out_of_bounds_x} (room half_w={half_room_w}, "
        f"item_w={item_w}) should be rejected for out_of_bounds"
    )
    assert any(b.code == "out_of_bounds" for b in report.blockers)


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    num_items=st.integers(min_value=2, max_value=5),
)
@settings(max_examples=200)
def test_property_2b_duplicate_ids_rejected(
    room_w: float,
    room_d: float,
    room_h: float,
    num_items: int,
):
    """Property 2b: Plans with duplicate stable IDs SHALL be rejected.

    **Validates: Requirements 2.2**

    Strategy: Generate multiple items sharing the same ID, placed safely
    within room bounds.
    """
    half_room_w = room_w / 2
    half_room_d = room_d / 2

    # Place items spaced apart within room bounds, all sharing same ID
    spacing = min(1.5, (room_w - 2.0) / (num_items + 1))
    items = []
    for i in range(num_items):
        x = -half_room_w + 1.0 + spacing * (i + 1)
        # Ensure within bounds
        x = max(-half_room_w + 1.0, min(half_room_w - 1.0, x))
        items.append(_make_item("duplicate_id", x, 0.0, 0.5, 0.5, 1.0))

    plan = FloorPlan.model_validate({
        "name": "Property 2b duplicate IDs test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": items,
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    # SHALL be rejected regardless of MVP mode
    assert not report.valid, (
        f"Plan with {num_items} items sharing same ID should be rejected "
        f"for duplicate_stable_id"
    )
    assert any(b.code == "duplicate_stable_id" for b in report.blockers)


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    non_finite_value=st.sampled_from([float("inf"), float("-inf"), float("nan")]),
    field=st.sampled_from(["x", "z", "width", "depth", "height", "elevation"]),
)
@settings(max_examples=200)
def test_property_2b_non_finite_geometry_rejected(
    room_w: float,
    room_d: float,
    room_h: float,
    non_finite_value: float,
    field: str,
):
    """Property 2b: Items with non-finite geometry SHALL be rejected.

    **Validates: Requirements 2.2**

    Strategy: Inject NaN/Inf into various geometry fields of a floor plan item.
    Must bypass Pydantic validation (which may catch some cases).
    """
    # Start with a valid item positioned safely inside bounds
    item_data = _make_item("bad_item", 0.0, 0.0, 1.0, 1.0, 1.0)

    # Inject non-finite value into the target field
    item_data[field] = non_finite_value

    # Some fields have Pydantic constraints that would reject non-finite values
    # during model construction. We need to handle this:
    # - width/depth have gt=0.0, le=20.0 → Inf rejected by Pydantic
    # - height has gt=0.0, le=8.0 → Inf rejected by Pydantic
    # - elevation has ge=0.0, le=8.0 → Inf rejected by Pydantic
    # - x, z have no bounds → NaN and Inf pass through Pydantic
    try:
        plan = FloorPlan.model_validate({
            "name": "Property 2b non-finite test",
            "room": {"width": room_w, "depth": room_d, "height": room_h},
            "items": [item_data],
            "openings": [],
            "camera": _make_camera(room_w, room_d),
        })
    except Exception:
        # Pydantic rejected the non-finite value before reaching the validator.
        # This is acceptable — the structural impossibility is caught at the model
        # layer. The property still holds: the plan cannot be accepted.
        return

    report = validate_floor_plan(plan, tolerance="mvp")

    # SHALL be rejected — non-finite geometry is a structural impossibility
    assert not report.valid, (
        f"Plan with {field}={non_finite_value} should be rejected for "
        f"non_finite_geometry or out_of_bounds"
    )
    # The blocker could be non_finite_geometry or out_of_bounds depending on field
    structural_codes = {"non_finite_geometry", "out_of_bounds"}
    assert any(b.code in structural_codes for b in report.blockers), (
        f"Expected structural blocker but got: {[b.code for b in report.blockers]}"
    )


@given(
    room_w=room_width_st,
    room_d=room_depth_st,
    room_h=room_height_st,
    overlap=overlap_amount_st,
)
@settings(max_examples=200)
def test_property_2b_structural_plus_noncritical_still_rejected(
    room_w: float,
    room_d: float,
    room_h: float,
    overlap: float,
):
    """Property 2b: Structural impossibilities reject even when non-critical violations coexist.

    **Validates: Requirements 2.2**

    Strategy: Create a plan with BOTH a non-critical overlap (would pass alone)
    AND a duplicate ID (structural impossibility). The plan SHALL still be rejected.
    """
    half_room_w = room_w / 2

    # Two items with minor overlap (non-critical — would pass MVP alone)
    item_w = 1.0
    distance = item_w - overlap
    left_x = -(distance / 2)
    right_x = distance / 2

    # Ensure items are within room bounds
    max_edge = abs(right_x) + item_w / 2
    assume(max_edge < half_room_w - 0.05)

    # Both items share the same ID → structural impossibility (duplicate_stable_id)
    plan = FloorPlan.model_validate({
        "name": "Property 2b combined test",
        "room": {"width": room_w, "depth": room_d, "height": room_h},
        "items": [
            _make_item("shared_id", left_x, 0.0, item_w, 1.0, 1.0),
            _make_item("shared_id", right_x, 0.0, item_w, 1.0, 1.0),
        ],
        "openings": [],
        "camera": _make_camera(room_w, room_d),
    })

    report = validate_floor_plan(plan, tolerance="mvp")

    # SHALL be rejected because of the structural impossibility
    assert not report.valid, (
        f"Plan with duplicate IDs + minor overlap={overlap:.4f}m "
        f"should still be rejected"
    )
    assert any(b.code == "duplicate_stable_id" for b in report.blockers)
