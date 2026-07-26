"""Tests for the deterministic auto-repair module (src.floor_plan.repair)."""

from __future__ import annotations

from src.floor_plan.models import FloorPlan, PlanValidationIssue, PlanValidationReport
from src.floor_plan.repair import RepairResult, repair_near_miss
from src.floor_plan.validator import validate_floor_plan


def _plan_with(items: list[dict], openings: list[dict] | None = None) -> FloorPlan:
    """Helper to build a test plan with given items and openings."""
    return FloorPlan.model_validate({
        "name": "Repair test room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": items,
        "openings": openings or [],
        "camera": {
            "x": 2.0, "y": 1.6, "z": -1.5,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })


def _item(item_id: str, x: float, z: float, **updates) -> dict:
    """Helper to build an item dict."""
    value = {
        "id": item_id,
        "name": item_id.replace("_", " ").title(),
        "category": "furniture",
        "mount": "floor",
        "x": x, "z": z,
        "width": 1.0, "depth": 1.0, "height": 1.0,
        "elevation": 0.0, "rotation_deg": 0.0,
        "fixed": False, "clearance_m": 0.0,
    }
    value.update(updates)
    return value


# ─────────────────────────────────────────────────────────────────────────────
# 1. test_repair_out_of_bounds_nudges_inward
# ─────────────────────────────────────────────────────────────────────────────

def test_repair_out_of_bounds_nudges_inward():
    """Item 0.15m outside the wall → repaired to be inside."""
    # Room is 6m wide, so half_w = 3.0.
    # Item width=1.0 → item center must be ≤ 2.5 to stay inside.
    # Place it at x=2.65 (0.15m past the valid range).
    plan = _plan_with([_item("desk", 2.65, 0.0)])
    report = validate_floor_plan(plan, tolerance="strict")

    # Confirm the item is out of bounds
    assert not report.valid
    assert any(b.code == "out_of_bounds" for b in report.blockers)

    result = repair_near_miss(plan, report, max_nudge_m=0.3)

    assert result.repaired
    assert len(result.repairs_applied) >= 1
    assert "desk" in result.repairs_applied[0].lower() or "Desk" in result.repairs_applied[0]
    assert len(result.remaining_blockers) == 0

    # Verify the repaired plan is valid
    final_report = validate_floor_plan(result.plan, tolerance="strict")
    assert final_report.valid


# ─────────────────────────────────────────────────────────────────────────────
# 2. test_repair_small_overlap_shifts_smaller_item
# ─────────────────────────────────────────────────────────────────────────────

def test_repair_small_overlap_shifts_smaller_item():
    """Two items overlap by ~0.08m → smaller one is shifted away."""
    # Sofa: width=2.0, center at x=0.0 → occupies [-1.0, 1.0]
    # Side table: width=0.5, center at x=1.17 → occupies [0.92, 1.42]
    # Overlap = 1.0 - 0.92 = 0.08m
    plan = _plan_with([
        _item("sofa", 0.0, 0.0, width=2.0, depth=1.0, fixed=True),
        _item("side_table", 1.17, 0.0, width=0.5, depth=0.5),
    ])
    report = validate_floor_plan(plan, tolerance="strict")

    # With strict mode, even small overlaps are blockers
    assert not report.valid
    assert any(b.code == "physical_overlap" for b in report.blockers)

    result = repair_near_miss(plan, report, max_nudge_m=0.3)

    assert result.repaired
    assert len(result.repairs_applied) >= 1
    assert "side_table" in result.repairs_applied[0].lower() or "Side Table" in result.repairs_applied[0]

    # The side table should have moved away from the sofa
    repaired_table = next(i for i in result.plan.items if i.id == "side_table")
    assert repaired_table.x > 1.17  # Moved further right (away from sofa center at 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. test_repair_opening_blocked_shifts_furniture
# ─────────────────────────────────────────────────────────────────────────────

def test_repair_opening_blocked_shifts_furniture():
    """Item blocking a door → shifted clear of the opening zone."""
    # Room: 6×5, half_d = 2.5
    # Door on south wall, width=0.9, inward = min(1.2, max(0.75, 0.9)) = 0.9
    # Opening volume spans z from -2.5 to -2.5 + 0.9 = -1.6
    # Place a chair at z=-1.75, depth=0.4: occupies [-1.95, -1.55]
    # The chair's north edge (-1.55) overlaps the volume's north edge (-1.6) — wait, -1.55 > -1.6
    # Actually: the opening volume occupies [-2.5, -1.6] in z.
    # Chair at z=-1.75, depth=0.4 occupies [-1.95, -1.55].
    # Intersection: chair south edge -1.95 < opening north edge -1.6 AND
    #   opening south edge -2.5 < chair north edge -1.55 → overlap!
    # To clear: chair south edge ≥ -1.6, so z ≥ -1.6 + 0.2 = -1.4
    # Shift needed: -1.4 - (-1.75) = 0.35 → too high for 0.3 max nudge
    # Let's use a barely-blocking position:
    # Chair at z=-1.8, depth=0.3 occupies [-1.95, -1.65].
    # overlap with [-2.5, -1.6]: south edge -1.95 < -1.6 and -2.5 < -1.65 → yes, overlaps
    # target_z = -2.5 + 0.9 + 0.15 + 0.1 = -1.35; shift = -1.35 - (-1.8) = 0.45 → still too much
    #
    # The issue is the inward depth for a 0.9m door is 0.9m, making the zone large.
    # Use a wider door with smaller blocking item, or increase max_nudge for this test.
    # Simplest: use max_nudge_m=0.5 for this test.
    plan = _plan_with(
        items=[_item("chair", 0.0, -2.1, width=0.5, depth=0.5)],
        openings=[{
            "id": "door_south",
            "kind": "door",
            "wall": "south",
            "offset": 0.0,
            "width": 0.9,
            "height": 2.1,
            "sill_height": 0.0,
        }],
    )
    report = validate_floor_plan(plan, tolerance="strict")

    assert not report.valid
    assert any(b.code == "opening_blocked" for b in report.blockers)

    result = repair_near_miss(plan, report, max_nudge_m=1.0)

    assert result.repaired
    assert len(result.repairs_applied) >= 1
    assert "chair" in result.repairs_applied[0].lower() or "Chair" in result.repairs_applied[0]

    # Chair should have been pushed north (away from south wall)
    repaired_chair = next(i for i in result.plan.items if i.id == "chair")
    assert repaired_chair.z > -2.1

    # Verify the repaired plan is valid
    final_report = validate_floor_plan(result.plan, tolerance="strict")
    assert final_report.valid


# ─────────────────────────────────────────────────────────────────────────────
# 4. test_repair_does_not_fix_structural_issues
# ─────────────────────────────────────────────────────────────────────────────

def test_repair_does_not_fix_structural_issues():
    """Duplicate IDs and structural issues → not repaired, returned as remaining_blockers."""
    # Create a report with non-repairable blockers
    plan = _plan_with([_item("desk", 0.0, 0.0)])
    report = PlanValidationReport(
        valid=False,
        blockers=[
            PlanValidationIssue(
                code="duplicate_stable_id",
                message="Duplicate stable ID: desk",
                item_ids=["desk"],
            ),
            PlanValidationIssue(
                code="non_finite_geometry",
                message="Invalid numeric geometry on desk",
                item_ids=["desk"],
            ),
        ],
    )

    result = repair_near_miss(plan, report, max_nudge_m=0.3)

    # No repairs should have been applied (these are unrepairable codes)
    assert not result.repaired
    assert len(result.repairs_applied) == 0
    # The remaining blockers should still be there
    assert len(result.remaining_blockers) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# 5. test_repair_caps_at_max_nudge
# ─────────────────────────────────────────────────────────────────────────────

def test_repair_caps_at_max_nudge():
    """Item WAY outside bounds → not fixed because nudge would exceed max."""
    # Room is 6m wide (half_w = 3.0). Item width=1.0 → valid center range ±2.5
    # Place item at x=4.0, which is 1.5m past the valid range. max_nudge_m=0.3 → too far.
    plan = _plan_with([_item("cabinet", 4.0, 0.0)])
    report = validate_floor_plan(plan, tolerance="strict")

    assert not report.valid
    assert any(b.code == "out_of_bounds" for b in report.blockers)

    result = repair_near_miss(plan, report, max_nudge_m=0.3)

    # Should NOT have been repaired — nudge too large
    assert not result.repaired
    assert len(result.repairs_applied) == 0
    assert any(b.code == "out_of_bounds" for b in result.remaining_blockers)


# ─────────────────────────────────────────────────────────────────────────────
# 6. test_repair_iterates_until_clean
# ─────────────────────────────────────────────────────────────────────────────

def test_repair_iterates_until_clean():
    """Plan with multiple issues → all fixed across iterations."""
    # Item 1: slightly out of bounds on the x-axis
    # Item 2: overlapping with item 3
    # Room: 6×5, half_w=3, half_d=2.5
    plan = _plan_with([
        # Slightly out of bounds (valid range for width=0.8 is ±2.6)
        _item("bookshelf", 2.75, 0.0, width=0.8, depth=0.4),
        # Two items with a small overlap
        _item("table", -1.0, -1.0, width=1.2, depth=0.8, fixed=True),
        _item("lamp", -0.35, -1.0, width=0.3, depth=0.3),
    ])
    report = validate_floor_plan(plan, tolerance="strict")

    # Should have at least one blocker (out_of_bounds)
    assert not report.valid
    blocker_codes = {b.code for b in report.blockers}
    assert "out_of_bounds" in blocker_codes

    result = repair_near_miss(plan, report, max_nudge_m=0.3, max_iterations=3)

    assert result.repaired
    assert len(result.repairs_applied) >= 1

    # Verify the final plan is valid
    final_report = validate_floor_plan(result.plan, tolerance="strict")
    assert final_report.valid, f"Remaining blockers: {[b.code for b in final_report.blockers]}"
