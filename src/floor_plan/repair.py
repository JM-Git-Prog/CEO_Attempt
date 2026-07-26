"""
Deterministic auto-repair for near-miss floor plans.

Inspired by LL3M's debug-loop pattern: instead of throwing away a plan
that fails validation by a small margin, mechanically fix it and re-validate.
Zero LLM tokens spent. Pure math.

Handles:
- Items slightly out of bounds → nudge inward
- Small overlaps between items → shift the lighter/smaller item
- Opening blocked by furniture → shift furniture away from opening zone
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from src.floor_plan.geometry import (
    fit_center_inside,
    footprint_overlap_depth,
    footprints_intersect,
    inside_room,
)
from src.floor_plan.models import (
    FloorPlan,
    PlanItem,
    PlanValidationIssue,
    PlanValidationReport,
)
from src.floor_plan.validator import _opening_volumes, validate_floor_plan


@dataclass
class RepairResult:
    """Result of an auto-repair attempt."""

    repaired: bool  # True if repairs were applied
    plan: FloorPlan  # The repaired (or original) plan
    repairs_applied: list[str] = field(default_factory=list)  # Human-readable list of what was fixed
    remaining_blockers: list[PlanValidationIssue] = field(default_factory=list)  # Issues that couldn't be fixed


# Issue codes we know how to fix deterministically
_REPAIRABLE_CODES = frozenset({"out_of_bounds", "physical_overlap", "opening_blocked"})


def _find_item(plan: FloorPlan, item_id: str) -> PlanItem | None:
    """Find an item in the plan by ID."""
    for item in plan.items:
        if item.id == item_id:
            return item
    return None


def _item_footprint_area(item: PlanItem) -> float:
    """Compute footprint area (width × depth) for comparison."""
    return item.width * item.depth


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _repair_out_of_bounds(
    plan: FloorPlan, issue: PlanValidationIssue, max_nudge_m: float
) -> str | None:
    """Nudge an out-of-bounds item inward by the minimum amount.

    Uses fit_center_inside to find the nearest valid center position.
    Returns a human-readable description of the fix, or None if unfixable.
    """
    if not issue.item_ids:
        return None
    item = _find_item(plan, issue.item_ids[0])
    if item is None:
        return None

    # Use the geometry helper to find the nearest valid center
    result = fit_center_inside(item, plan.room.width, plan.room.depth)
    if result is None:
        # Item is too large for the room — can't fix
        return None

    new_x, new_z = result
    dx = abs(new_x - item.x)
    dz = abs(new_z - item.z)
    total_nudge = math.hypot(dx, dz)

    if total_nudge > max_nudge_m:
        # Nudge exceeds maximum — don't repair
        return None

    if total_nudge < 1e-6:
        # Already inside (within tolerance) — nothing to do
        return None

    old_x, old_z = item.x, item.z
    item.x, item.z = new_x, new_z
    return (
        f"Nudged {item.name} ({item.id}) inward by {total_nudge:.3f}m "
        f"(from [{old_x:.3f}, {old_z:.3f}] to [{new_x:.3f}, {new_z:.3f}])"
    )


def _repair_physical_overlap(
    plan: FloorPlan, issue: PlanValidationIssue, max_nudge_m: float
) -> str | None:
    """Shift the smaller/lighter item away from the larger one.

    Direction: move smaller item's center away from larger item's center.
    Amount: the overlap depth, capped at max_nudge_m.
    Returns a human-readable description of the fix, or None if unfixable.
    """
    if len(issue.item_ids) < 2:
        return None
    left = _find_item(plan, issue.item_ids[0])
    right = _find_item(plan, issue.item_ids[1])
    if left is None or right is None:
        return None

    # Both fixed — can't move either
    if left.fixed and right.fixed:
        return None

    # Determine which to move (smaller footprint, or non-fixed)
    if left.fixed:
        mover, anchor = right, left
    elif right.fixed:
        mover, anchor = left, right
    elif _item_footprint_area(left) <= _item_footprint_area(right):
        mover, anchor = left, right
    else:
        mover, anchor = right, left

    # Compute overlap depth
    overlap = footprint_overlap_depth(left, right)
    if overlap <= 0.0:
        return None  # No overlap (possibly already resolved)
    if overlap > max_nudge_m:
        return None  # Too large to fix

    # Direction: move mover away from anchor
    dx = mover.x - anchor.x
    dz = mover.z - anchor.z
    dist = math.hypot(dx, dz)
    if dist < 1e-6:
        # Coincident centers — push along x-axis
        dx, dz, dist = 1.0, 0.0, 1.0

    # Normalize direction and apply overlap + small margin
    shift = overlap + 0.02  # 2cm margin
    shift = min(shift, max_nudge_m)
    nx, nz = dx / dist, dz / dist

    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2
    new_x = _clamp(mover.x + nx * shift, -half_w + mover.width / 2, half_w - mover.width / 2)
    new_z = _clamp(mover.z + nz * shift, -half_d + mover.depth / 2, half_d - mover.depth / 2)

    old_x, old_z = mover.x, mover.z
    mover.x, mover.z = new_x, new_z
    actual_shift = math.hypot(new_x - old_x, new_z - old_z)
    return (
        f"Shifted {mover.name} ({mover.id}) by {actual_shift:.3f}m away from "
        f"{anchor.name} ({anchor.id}) to resolve {overlap:.3f}m overlap"
    )


def _repair_opening_blocked(
    plan: FloorPlan, issue: PlanValidationIssue, max_nudge_m: float
) -> str | None:
    """Shift a furniture item away from a blocked opening.

    Identifies the blocking item and the opening volume, then shifts the item
    perpendicular to the wall the opening is on.
    Returns a human-readable description of the fix, or None if unfixable.
    """
    if len(issue.item_ids) < 2:
        return None

    # item_ids[0] is the blocking item, item_ids[1] is the opening volume id
    blocker = _find_item(plan, issue.item_ids[0])
    if blocker is None:
        return None
    if blocker.fixed:
        return None

    # Find the opening that is blocked
    opening_id = issue.item_ids[1]
    opening = None
    for op in plan.openings:
        if op.id == opening_id:
            opening = op
            break
    if opening is None:
        # Try to get it from details
        details_id = issue.details.get("opening_id")
        if details_id:
            for op in plan.openings:
                if op.id == details_id:
                    opening = op
                    break
    if opening is None:
        return None

    # Determine shift direction: perpendicular to the wall, toward room center
    # Plus a margin of opening.width/2 + 0.1m
    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2

    # Opening inward depth (same logic as _opening_volumes)
    inward = min(1.2, max(0.75, opening.width)) if opening.kind == "door" else 0.18

    if opening.wall == "north":
        # Opening is on north wall (z = +half_d side); push item south (decrease z)
        target_z = half_d - inward - blocker.depth / 2 - 0.1
        shift = blocker.z - target_z
        if shift <= 0:
            return None  # Already clear
        if shift > max_nudge_m:
            return None
        old_z = blocker.z
        blocker.z = _clamp(target_z, -half_d + blocker.depth / 2, half_d - blocker.depth / 2)
        return (
            f"Shifted {blocker.name} ({blocker.id}) south by {old_z - blocker.z:.3f}m "
            f"to clear {opening.kind} {opening.id}"
        )
    elif opening.wall == "south":
        # Opening is on south wall (z = -half_d side); push item north (increase z)
        target_z = -half_d + inward + blocker.depth / 2 + 0.1
        shift = target_z - blocker.z
        if shift <= 0:
            return None
        if shift > max_nudge_m:
            return None
        old_z = blocker.z
        blocker.z = _clamp(target_z, -half_d + blocker.depth / 2, half_d - blocker.depth / 2)
        return (
            f"Shifted {blocker.name} ({blocker.id}) north by {blocker.z - old_z:.3f}m "
            f"to clear {opening.kind} {opening.id}"
        )
    elif opening.wall == "east":
        # Opening on east wall (x = +half_w side); push item west (decrease x)
        target_x = half_w - inward - blocker.width / 2 - 0.1
        shift = blocker.x - target_x
        if shift <= 0:
            return None
        if shift > max_nudge_m:
            return None
        old_x = blocker.x
        blocker.x = _clamp(target_x, -half_w + blocker.width / 2, half_w - blocker.width / 2)
        return (
            f"Shifted {blocker.name} ({blocker.id}) west by {old_x - blocker.x:.3f}m "
            f"to clear {opening.kind} {opening.id}"
        )
    else:  # west
        # Opening on west wall (x = -half_w side); push item east (increase x)
        target_x = -half_w + inward + blocker.width / 2 + 0.1
        shift = target_x - blocker.x
        if shift <= 0:
            return None
        if shift > max_nudge_m:
            return None
        old_x = blocker.x
        blocker.x = _clamp(target_x, -half_w + blocker.width / 2, half_w - blocker.width / 2)
        return (
            f"Shifted {blocker.name} ({blocker.id}) east by {blocker.x - old_x:.3f}m "
            f"to clear {opening.kind} {opening.id}"
        )


def repair_near_miss(
    plan: FloorPlan,
    report: PlanValidationReport,
    *,
    max_nudge_m: float = 0.3,
    max_iterations: int = 3,
) -> RepairResult:
    """Attempt to mechanically repair a near-miss plan.

    Only repairs issues where the fix is unambiguous and bounded:
    - out_of_bounds: nudge item inward by the minimum amount to clear the wall
    - physical_overlap: shift the smaller/lighter item away from the larger one
    - opening_blocked: shift the blocking item away from the opening zone

    Does NOT attempt to fix:
    - duplicate_stable_id (requires semantic understanding)
    - zero_dimension_room (requires human intent)
    - non_finite_geometry (data corruption)

    Parameters:
        plan: The floor plan to repair (will be deep-copied)
        report: Validation report with blockers to fix
        max_nudge_m: Maximum distance to nudge any single item per repair (default 0.3m)
        max_iterations: Maximum repair → revalidate cycles (default 3)

    Returns:
        RepairResult with the repaired plan (or original if no repairs possible)
    """
    # Deep-copy the plan so we don't mutate the original
    working_plan = plan.model_copy(deep=True)
    all_repairs: list[str] = []
    current_report = report

    for _iteration in range(max_iterations):
        # Check if there are any repairable blockers
        repairable = [b for b in current_report.blockers if b.code in _REPAIRABLE_CODES]
        if not repairable:
            break

        iteration_repairs: list[str] = []
        for blocker in repairable:
            repair_desc: str | None = None
            if blocker.code == "out_of_bounds":
                repair_desc = _repair_out_of_bounds(working_plan, blocker, max_nudge_m)
            elif blocker.code == "physical_overlap":
                repair_desc = _repair_physical_overlap(working_plan, blocker, max_nudge_m)
            elif blocker.code == "opening_blocked":
                repair_desc = _repair_opening_blocked(working_plan, blocker, max_nudge_m)

            if repair_desc:
                iteration_repairs.append(repair_desc)

        if not iteration_repairs:
            # No repairs were possible this iteration — stop
            break

        all_repairs.extend(iteration_repairs)

        # Re-validate after this round of repairs
        current_report = validate_floor_plan(working_plan, tolerance="mvp")

        if current_report.valid:
            break

    remaining = [b for b in current_report.blockers]
    return RepairResult(
        repaired=len(all_repairs) > 0,
        plan=working_plan,
        repairs_applied=all_repairs,
        remaining_blockers=remaining,
    )
