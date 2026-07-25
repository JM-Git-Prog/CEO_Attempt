"""Unit tests for MVP tolerance mode in validate_floor_plan().

Validates Requirements 2.1 and 2.2:
- MVP mode accepts plans with minor overlaps (≤0.1m), clearance violations (≤0.15m)
- MVP mode always rejects structural impossibilities (out_of_bounds, duplicate IDs)
- Camera checks are skipped in MVP mode
- Strict mode retains original behavior
"""

from __future__ import annotations

from src.floor_plan.models import FloorPlan, PlanValidationReport
from src.floor_plan.validator import validate_floor_plan


def _plan_with(items: list[dict], openings: list[dict] | None = None) -> FloorPlan:
    """Create a minimal plan for testing validation logic."""
    return FloorPlan.model_validate({
        "name": "Test room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": items,
        "openings": openings or [],
        "camera": {
            "x": 2.4, "y": 1.6, "z": -1.9,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })


def _item(item_id: str, x: float, z: float, **updates) -> dict:
    value = {
        "id": item_id,
        "name": item_id.replace("_", " ").title(),
        "category": "furniture",
        "mount": "floor",
        "x": x, "z": z,
        "width": 1.0, "depth": 1.0, "height": 1.0,
        "elevation": 0.0, "rotation_deg": 0.0,
        "fixed": False, "clearance_m": 0.2,
    }
    value.update(updates)
    return value


# --- MVP tolerance: minor overlap accepted ---


def test_mvp_accepts_minor_overlap_within_threshold():
    """Two items overlapping by 0.05m should be accepted in MVP mode."""
    # Place two items with slight overlap: centers 0.95m apart with 1.0m widths
    # overlap = (0.5 + 0.5) - 0.95 = 0.05m ≤ 0.1m threshold
    plan = _plan_with([
        _item("sofa", -0.475, 0.0, width=1.0, depth=1.0),
        _item("table", 0.475, 0.0, width=1.0, depth=1.0),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert report.valid, f"Expected valid but got blockers: {report.blockers}"
    assert len(report.tolerance_warnings) > 0
    assert report.tolerance_warnings[0]["warning_type"] == "overlap"
    assert report.tolerance_warnings[0]["measured_deviation"] <= 0.1


def test_mvp_rejects_large_overlap_beyond_threshold():
    """Two items overlapping by >0.1m should still be rejected in MVP mode."""
    # Place two items with significant overlap: centers 0.7m apart with 1.0m widths
    # overlap = (0.5 + 0.5) - 0.7 = 0.3m > 0.1m threshold
    plan = _plan_with([
        _item("sofa", -0.35, 0.0, width=1.0, depth=1.0),
        _item("table", 0.35, 0.0, width=1.0, depth=1.0),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert not report.valid
    overlap_blockers = [b for b in report.blockers if b.code == "physical_overlap"]
    assert len(overlap_blockers) == 1


def test_strict_rejects_any_overlap():
    """In strict mode, even minor overlaps are blockers."""
    # Same minor overlap that MVP accepts
    plan = _plan_with([
        _item("sofa", -0.475, 0.0, width=1.0, depth=1.0),
        _item("table", 0.475, 0.0, width=1.0, depth=1.0),
    ])

    report = validate_floor_plan(plan, tolerance="strict")
    assert not report.valid
    overlap_blockers = [b for b in report.blockers if b.code == "physical_overlap"]
    assert len(overlap_blockers) == 1


# --- MVP tolerance: clearance violations ---


def test_mvp_accepts_minor_clearance_violation():
    """Items with clearance padding overlap ≤0.15m should be warnings in MVP mode."""
    # Two items not physically overlapping but whose clearance zones intersect slightly
    # Items are 1.0m wide with 0.2m clearance each → clearance padding = 0.1m each
    # Physical gap = centers apart - widths/2 = 1.08 - 1.0 = 0.08m physical gap
    # With clearance: (0.5+0.1)+(0.5+0.1) - 1.08 = 1.2 - 1.08 = 0.12m clearance overlap
    # 0.12m ≤ 0.15m threshold
    plan = _plan_with([
        _item("sofa", -0.54, 0.0, width=1.0, depth=1.0, clearance_m=0.2),
        _item("table", 0.54, 0.0, width=1.0, depth=1.0, clearance_m=0.2),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert report.valid
    # Should have tolerance warnings for clearance
    clearance_warnings = [w for w in report.tolerance_warnings if w["warning_type"] == "clearance"]
    assert len(clearance_warnings) > 0
    assert clearance_warnings[0]["measured_deviation"] <= 0.15


# --- Structural impossibilities: ALWAYS rejected ---


def test_mvp_rejects_out_of_bounds():
    """Items with vertices outside room bounds are structural — always rejected."""
    # Room is 6.0 wide → half = 3.0. Item at x=2.9 with width=1.0 → edge at 3.4 > 3.0
    plan = _plan_with([
        _item("shelf", 2.9, 0.0, width=1.0, depth=0.5),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert not report.valid
    bounds_blockers = [b for b in report.blockers if b.code == "out_of_bounds"]
    assert len(bounds_blockers) == 1


def test_mvp_rejects_duplicate_stable_ids():
    """Duplicate stable IDs are structural — always rejected."""
    plan = _plan_with([
        _item("chair_1", -1.0, 0.0),
        _item("chair_1", 1.0, 0.0),  # duplicate ID
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert not report.valid
    dup_blockers = [b for b in report.blockers if b.code == "duplicate_stable_id"]
    assert len(dup_blockers) == 1


def test_mvp_rejects_non_finite_geometry():
    """Non-finite geometry is structural — always rejected."""
    plan = _plan_with([
        _item("chair", float("inf"), 0.0),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert not report.valid
    nf_blockers = [b for b in report.blockers if b.code == "non_finite_geometry"]
    assert len(nf_blockers) == 1


# --- Camera checks: skipped in MVP ---


def test_mvp_skips_camera_checks():
    """In MVP mode, camera validation is skipped entirely."""
    # Place camera outside room bounds — should still be valid in MVP mode
    plan = FloorPlan.model_validate({
        "name": "Test room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": [],
        "openings": [],
        "camera": {
            "x": 10.0, "y": 1.6, "z": 10.0,  # way outside bounds
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })

    report = validate_floor_plan(plan, tolerance="mvp")
    assert report.valid
    camera_blockers = [b for b in report.blockers if "camera" in b.code]
    assert len(camera_blockers) == 0


def test_strict_checks_camera():
    """In strict mode, camera out of bounds is a blocker."""
    plan = FloorPlan.model_validate({
        "name": "Test room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": [],
        "openings": [],
        "camera": {
            "x": 10.0, "y": 1.6, "z": 10.0,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })

    report = validate_floor_plan(plan, tolerance="strict")
    assert not report.valid
    camera_blockers = [b for b in report.blockers if "camera" in b.code]
    assert len(camera_blockers) > 0


# --- Default mode behavior ---


def test_default_tolerance_is_mvp_when_not_strict():
    """When no tolerance or strict is specified, default is MVP mode."""
    # Use case where camera is out of bounds — MVP should not fail
    plan = FloorPlan.model_validate({
        "name": "Test room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": [],
        "openings": [],
        "camera": {
            "x": 10.0, "y": 1.6, "z": 10.0,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })

    # Default (no tolerance, strict=False) → MVP mode
    report = validate_floor_plan(plan)
    assert report.valid


def test_strict_flag_backwards_compat():
    """Legacy strict=True flag should behave as tolerance='strict'."""
    plan = FloorPlan.model_validate({
        "name": "Test room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": [],
        "openings": [],
        "camera": {
            "x": 10.0, "y": 1.6, "z": 10.0,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })

    report = validate_floor_plan(plan, strict=True)
    assert not report.valid


# --- Tolerance warnings structure ---


def test_tolerance_warnings_have_correct_structure():
    """Tolerance warnings should have warning_type, affected_id, measured_deviation, threshold."""
    plan = _plan_with([
        _item("sofa", -0.475, 0.0, width=1.0, depth=1.0),
        _item("table", 0.475, 0.0, width=1.0, depth=1.0),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert report.valid
    assert len(report.tolerance_warnings) > 0

    warning = report.tolerance_warnings[0]
    assert "warning_type" in warning
    assert "affected_id" in warning
    assert "measured_deviation" in warning
    assert "threshold" in warning
    assert warning["warning_type"] in ("overlap", "clearance", "relationship_offset")
    assert isinstance(warning["measured_deviation"], float)
    assert isinstance(warning["threshold"], float)


def test_no_overlap_no_warnings():
    """A clean plan should produce no tolerance warnings."""
    plan = _plan_with([
        _item("sofa", -2.0, 0.0, width=1.0, depth=1.0),
        _item("table", 2.0, 0.0, width=1.0, depth=1.0),
    ])

    report = validate_floor_plan(plan, tolerance="mvp")
    assert report.valid
    assert len(report.tolerance_warnings) == 0
    assert len(report.blockers) == 0
