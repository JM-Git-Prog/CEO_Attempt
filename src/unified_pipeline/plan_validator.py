"""Plan Validator — validates MetricPlan spatial correctness and auto-corrects.

Checks: room closure, opening validity, object non-overlap, circulation
clearance (≥0.6m between objects and walls), door swing clearance, and
dimensional plausibility. If validation fails, auto-corrects and creates
a new revision.

Requirements: 5.3, 5.4, 5.5
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any

from src.unified_pipeline.models import MetricPlan, PlanRevision


# ─── Validation Constants ──────────────────────────────────────────────────────

MIN_ROOM_WIDTH = 1.5       # meters — no room narrower than this (residential)
MAX_ROOM_HEIGHT = 6.0      # meters — no room taller than this (residential)
MIN_ROOM_HEIGHT = 2.1      # meters — minimum livable ceiling
MIN_OPENING_CORNER_DIST = 0.15  # meters — opening must be this far from corner
MIN_CIRCULATION_WIDTH = 0.6    # meters — minimum walkable path width
MIN_DOOR_SWING_CLEARANCE = 0.8  # meters — clearance for door to swing open
OBJECT_OVERLAP_TOLERANCE = 0.02  # meters — tolerance for overlap detection


# ─── Validation Result ─────────────────────────────────────────────────────────


@dataclass
class ValidationViolation:
    """One validation rule violation."""

    rule: str
    severity: str  # "error" or "warning"
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Complete validation result for a MetricPlan."""

    valid: bool
    violations: list[ValidationViolation] = field(default_factory=list)
    plan: MetricPlan | None = None  # corrected plan if auto-corrected

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning")


# ─── Helper Functions ──────────────────────────────────────────────────────────


def _compute_plan_hash(plan: MetricPlan) -> str:
    """Compute a deterministic hash of a plan."""
    data = json.dumps(plan.to_dict(), sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _get_wall_length(wall: dict[str, Any]) -> float:
    """Compute the length of a wall from start/end coordinates."""
    start = wall.get("start", (0, 0, 0))
    end = wall.get("end", (0, 0, 0))
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    return (dx**2 + dy**2) ** 0.5


def _objects_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Check if two object placements overlap (axis-aligned bounding box)."""
    ax, ay = a.get("x", 0), a.get("y", 0)
    aw, ad = a.get("width", 0.5), a.get("depth", 0.5)
    bx, by = b.get("x", 0), b.get("y", 0)
    bw, bd = b.get("width", 0.5), b.get("depth", 0.5)

    # AABB overlap test (centered on x, y)
    a_left = ax - aw / 2
    a_right = ax + aw / 2
    a_top = ay - ad / 2
    a_bottom = ay + ad / 2

    b_left = bx - bw / 2
    b_right = bx + bw / 2
    b_top = by - bd / 2
    b_bottom = by + bd / 2

    # Check for separation (with tolerance)
    if a_right <= b_left + OBJECT_OVERLAP_TOLERANCE:
        return False
    if a_left >= b_right - OBJECT_OVERLAP_TOLERANCE:
        return False
    if a_bottom <= b_top + OBJECT_OVERLAP_TOLERANCE:
        return False
    if a_top >= b_bottom - OBJECT_OVERLAP_TOLERANCE:
        return False

    return True


def _opening_corner_distance(opening: dict[str, Any], room_width: float, room_depth: float) -> float:
    """Compute distance of an opening from the nearest wall corner.

    The 'parameter' field is 0..1 along the wall. Distance to corner is
    min(parameter, 1-parameter) × wall_length.
    """
    wall = opening.get("wall", "north")
    param = opening.get("parameter", 0.5)
    opening_width = opening.get("width", 0.9)

    # Determine wall length based on orientation
    if wall in ("north", "south"):
        wall_length = room_width
    else:
        wall_length = room_depth

    # Distance from left/right edge of wall to center of opening
    center_pos = param * wall_length
    half_width = opening_width / 2

    dist_to_left = center_pos - half_width
    dist_to_right = wall_length - (center_pos + half_width)

    return min(dist_to_left, dist_to_right)


def _door_swing_position(opening: dict[str, Any], room_width: float, room_depth: float) -> tuple[float, float, float]:
    """Compute the door swing arc center and radius.

    Returns (center_x, center_y, swing_radius) for the door's swept area
    inside the room. The swing radius equals the door width.
    """
    wall = opening.get("wall", "north")
    param = opening.get("parameter", 0.5)
    door_width = opening.get("width", 0.9)

    # Position along wall
    if wall in ("north", "south"):
        wall_length = room_width
    else:
        wall_length = room_depth

    center_along_wall = param * wall_length

    # Door hinge is at one edge; the swing arc center is the hinge point.
    # Convention: hinge at left edge of opening, door swings inward.
    hinge_along_wall = center_along_wall - door_width / 2

    # Convert to room coordinates (origin at 0,0 = bottom-left corner)
    if wall == "north":
        cx, cy = hinge_along_wall, 0.0
    elif wall == "south":
        cx, cy = hinge_along_wall, room_depth
    elif wall == "east":
        cx, cy = room_width, hinge_along_wall
    else:  # west
        cx, cy = 0.0, hinge_along_wall

    return cx, cy, door_width


def _object_in_door_swing(obj: dict[str, Any], door_cx: float, door_cy: float, swing_radius: float) -> bool:
    """Check if an object's bounding box intersects the door swing arc.

    Uses a conservative approximation: checks if any corner of the object's
    AABB is within swing_radius of the door hinge, or if the object center is.
    """
    ox, oy = obj.get("x", 0), obj.get("y", 0)
    ow, od = obj.get("width", 0.5), obj.get("depth", 0.5)

    # Check closest point on AABB to the hinge
    closest_x = max(ox - ow / 2, min(door_cx, ox + ow / 2))
    closest_y = max(oy - od / 2, min(door_cy, oy + od / 2))

    dist = math.sqrt((closest_x - door_cx) ** 2 + (closest_y - door_cy) ** 2)
    return dist < swing_radius


def _gap_between_objects(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Compute the minimum gap between two object AABBs.

    Returns the minimum separating distance along either axis.
    If objects overlap, returns a negative value.
    """
    ax, ay = a.get("x", 0), a.get("y", 0)
    aw, ad = a.get("width", 0.5), a.get("depth", 0.5)
    bx, by = b.get("x", 0), b.get("y", 0)
    bw, bd = b.get("width", 0.5), b.get("depth", 0.5)

    # Gap along x axis
    gap_x = abs(ax - bx) - (aw + bw) / 2
    # Gap along y axis
    gap_y = abs(ay - by) - (ad + bd) / 2

    # If separated on one axis, the gap is the max of the separations
    # (they must overlap on BOTH axes to physically overlap)
    if gap_x >= 0 and gap_y >= 0:
        # Diagonal separation — use the smaller axis gap (the bottleneck)
        return min(gap_x, gap_y)
    elif gap_x >= 0:
        # Separated on x only — gap is the x separation
        return gap_x
    elif gap_y >= 0:
        # Separated on y only — gap is the y separation
        return gap_y
    else:
        # Overlapping on both axes
        return max(gap_x, gap_y)  # most negative = deepest overlap


# ─── PlanValidator ─────────────────────────────────────────────────────────────


class PlanValidator:
    """Validates a MetricPlan against spatial rules and auto-corrects violations.

    Validation rules (Requirement 5.3):
    - Room closure: all walls connect
    - Opening validity: not too close to corners (<0.3m), not on wall stubs
    - Object non-overlap
    - Circulation clearance: minimum 0.6m walkable paths
    - Door swing clearance
    - Dimensional plausibility: no room narrower than 1.5m or taller than 6m

    Auto-correction (Requirement 5.4):
    - If validation fails, correct automatically and create new revision

    Revision tracking (Requirement 5.5):
    - Every revision is traceable: number, what changed, why
    """

    def validate(self, plan: MetricPlan) -> ValidationResult:
        """Validate a MetricPlan. Returns ValidationResult with violations.

        If violations are found, auto-corrects and returns the corrected plan
        in result.plan.
        """
        violations = []

        # Check dimensional plausibility
        violations.extend(self._check_dimensions(plan))

        # Check room closure
        violations.extend(self._check_closure(plan))

        # Check opening validity
        violations.extend(self._check_openings(plan))

        # Check object non-overlap
        violations.extend(self._check_overlap(plan))

        # Check circulation clearance (walls and between objects)
        violations.extend(self._check_circulation(plan))

        # Check door swing clearance
        violations.extend(self._check_door_swing(plan))

        if not violations:
            return ValidationResult(valid=True, plan=plan)

        # Has violations — attempt auto-correction
        corrected = self._auto_correct(plan, violations)
        return ValidationResult(
            valid=False,
            violations=violations,
            plan=corrected,
        )

    def _check_dimensions(self, plan: MetricPlan) -> list[ValidationViolation]:
        """Check dimensional plausibility."""
        violations = []
        width, depth, height = plan.room_dimensions

        if width < MIN_ROOM_WIDTH:
            violations.append(ValidationViolation(
                rule="room_width_min",
                severity="error",
                message=f"Room width {width:.2f}m is below minimum {MIN_ROOM_WIDTH}m",
                details={"width": width, "min": MIN_ROOM_WIDTH},
            ))

        if depth < MIN_ROOM_WIDTH:
            violations.append(ValidationViolation(
                rule="room_depth_min",
                severity="error",
                message=f"Room depth {depth:.2f}m is below minimum {MIN_ROOM_WIDTH}m",
                details={"depth": depth, "min": MIN_ROOM_WIDTH},
            ))

        if height > MAX_ROOM_HEIGHT:
            violations.append(ValidationViolation(
                rule="room_height_max",
                severity="error",
                message=f"Room height {height:.2f}m exceeds maximum {MAX_ROOM_HEIGHT}m",
                details={"height": height, "max": MAX_ROOM_HEIGHT},
            ))

        if height < MIN_ROOM_HEIGHT:
            violations.append(ValidationViolation(
                rule="room_height_min",
                severity="error",
                message=f"Room height {height:.2f}m is below minimum {MIN_ROOM_HEIGHT}m",
                details={"height": height, "min": MIN_ROOM_HEIGHT},
            ))

        return violations

    def _check_closure(self, plan: MetricPlan) -> list[ValidationViolation]:
        """Check that all walls connect (room closure)."""
        violations = []
        walls = plan.walls

        if len(walls) < 3:
            violations.append(ValidationViolation(
                rule="room_closure",
                severity="error",
                message=f"Room has only {len(walls)} walls — minimum 3 for closure",
                details={"wall_count": len(walls)},
            ))
            return violations

        # Check that each wall's end connects to next wall's start
        for i in range(len(walls)):
            current = walls[i]
            next_wall = walls[(i + 1) % len(walls)]
            current_end = tuple(current.get("end", (0, 0, 0)))
            next_start = tuple(next_wall.get("start", (0, 0, 0)))

            # Allow small tolerance for floating point
            dist = sum((a - b) ** 2 for a, b in zip(current_end, next_start)) ** 0.5
            if dist > 0.01:
                violations.append(ValidationViolation(
                    rule="room_closure",
                    severity="error",
                    message=(
                        f"Wall '{current.get('id', i)}' end does not connect to "
                        f"wall '{next_wall.get('id', (i+1) % len(walls))}' start "
                        f"(gap={dist:.3f}m)"
                    ),
                    details={"wall_idx": i, "gap": dist},
                ))

        return violations

    def _check_openings(self, plan: MetricPlan) -> list[ValidationViolation]:
        """Check opening validity — not too close to corners."""
        violations = []
        width, depth, _height = plan.room_dimensions

        for i, opening in enumerate(plan.openings):
            corner_dist = _opening_corner_distance(opening, width, depth)
            if corner_dist < MIN_OPENING_CORNER_DIST:
                violations.append(ValidationViolation(
                    rule="opening_corner_distance",
                    severity="error",
                    message=(
                        f"Opening {i} ({opening.get('type', 'unknown')}) on wall "
                        f"'{opening.get('wall', '?')}' is {corner_dist:.2f}m from corner "
                        f"(minimum {MIN_OPENING_CORNER_DIST}m)"
                    ),
                    details={
                        "opening_idx": i,
                        "corner_distance": corner_dist,
                        "min_required": MIN_OPENING_CORNER_DIST,
                    },
                ))

        return violations

    def _check_overlap(self, plan: MetricPlan) -> list[ValidationViolation]:
        """Check object non-overlap."""
        violations = []
        placements = plan.object_placements

        for i in range(len(placements)):
            for j in range(i + 1, len(placements)):
                if _objects_overlap(placements[i], placements[j]):
                    violations.append(ValidationViolation(
                        rule="object_overlap",
                        severity="error",
                        message=(
                            f"Objects '{placements[i].get('name', i)}' and "
                            f"'{placements[j].get('name', j)}' overlap"
                        ),
                        details={
                            "object_a": placements[i].get("name", str(i)),
                            "object_b": placements[j].get("name", str(j)),
                        },
                    ))

        return violations

    def _check_circulation(self, plan: MetricPlan) -> list[ValidationViolation]:
        """Check circulation clearance (minimum 0.6m walkable paths).

        Checks both:
        - Object-to-wall clearance (at least one path to each wall)
        - Object-to-object clearance (adjacent objects must have ≥0.6m gap)
        """
        violations = []
        width, depth, _ = plan.room_dimensions
        placements = plan.object_placements

        # Check that each object has at least MIN_CIRCULATION_WIDTH clearance
        # from room edges
        for i, obj in enumerate(placements):
            x, y = obj.get("x", 0), obj.get("y", 0)
            ow, od = obj.get("width", 0.5), obj.get("depth", 0.5)

            # Distance to walls
            dist_left = x - ow / 2
            dist_right = width - (x + ow / 2)
            dist_top = y - od / 2
            dist_bottom = depth - (y + od / 2)

            min_wall_dist = min(dist_left, dist_right, dist_top, dist_bottom)
            if min_wall_dist < MIN_CIRCULATION_WIDTH:
                violations.append(ValidationViolation(
                    rule="circulation_clearance",
                    severity="warning",
                    message=(
                        f"Object '{obj.get('name', i)}' has only {min_wall_dist:.2f}m "
                        f"clearance to wall (minimum {MIN_CIRCULATION_WIDTH}m)"
                    ),
                    details={
                        "object_name": obj.get("name", str(i)),
                        "clearance": min_wall_dist,
                        "min_required": MIN_CIRCULATION_WIDTH,
                    },
                ))

        # Check inter-object circulation clearance
        for i in range(len(placements)):
            for j in range(i + 1, len(placements)):
                gap = _gap_between_objects(placements[i], placements[j])
                # Only flag if objects are close but not overlapping
                # (overlapping is caught by _check_overlap)
                if 0 <= gap < MIN_CIRCULATION_WIDTH:
                    violations.append(ValidationViolation(
                        rule="circulation_clearance",
                        severity="warning",
                        message=(
                            f"Objects '{placements[i].get('name', i)}' and "
                            f"'{placements[j].get('name', j)}' have only {gap:.2f}m "
                            f"gap (minimum {MIN_CIRCULATION_WIDTH}m for walkable path)"
                        ),
                        details={
                            "object_a": placements[i].get("name", str(i)),
                            "object_b": placements[j].get("name", str(j)),
                            "gap": gap,
                            "min_required": MIN_CIRCULATION_WIDTH,
                        },
                    ))

        return violations

    def _check_door_swing(self, plan: MetricPlan) -> list[ValidationViolation]:
        """Check that doors can fully swing open without hitting objects.

        For each door opening, computes the swing arc and checks that no
        object placement intersects it.
        """
        violations = []
        width, depth, _ = plan.room_dimensions
        placements = plan.object_placements

        for i, opening in enumerate(plan.openings):
            if opening.get("type") != "door":
                continue

            door_cx, door_cy, swing_radius = _door_swing_position(
                opening, width, depth
            )

            for obj in placements:
                if _object_in_door_swing(obj, door_cx, door_cy, swing_radius):
                    violations.append(ValidationViolation(
                        rule="door_swing_clearance",
                        severity="error",
                        message=(
                            f"Object '{obj.get('name', '?')}' is within door swing arc "
                            f"of door on '{opening.get('wall', '?')}' wall"
                        ),
                        details={
                            "opening_idx": i,
                            "opening_wall": opening.get("wall", "?"),
                            "object_name": obj.get("name", "unknown"),
                            "swing_radius": swing_radius,
                        },
                    ))

        return violations

    def _auto_correct(
        self, plan: MetricPlan, violations: list[ValidationViolation]
    ) -> MetricPlan:
        """Auto-correct a plan's violations and create a new revision.

        Requirement 5.4: auto-correct and create new revision number.
        Requirement 5.5: traceable revisions.
        """
        width, depth, height = plan.room_dimensions
        corrections: list[str] = []

        # Fix dimensional violations
        new_width, new_depth, new_height = width, depth, height
        for v in violations:
            if v.rule == "room_width_min":
                new_width = MIN_ROOM_WIDTH
                corrections.append(f"width {width:.2f}→{new_width:.2f}m")
            elif v.rule == "room_depth_min":
                new_depth = MIN_ROOM_WIDTH
                corrections.append(f"depth {depth:.2f}→{new_depth:.2f}m")
            elif v.rule == "room_height_max":
                new_height = MAX_ROOM_HEIGHT
                corrections.append(f"height {height:.2f}→{new_height:.2f}m")
            elif v.rule == "room_height_min":
                new_height = MIN_ROOM_HEIGHT
                corrections.append(f"height {height:.2f}→{new_height:.2f}m")

        # Fix opening corner distance
        new_openings = list(plan.openings)
        for v in violations:
            if v.rule == "opening_corner_distance":
                idx = v.details.get("opening_idx", 0)
                if idx < len(new_openings):
                    opening = dict(new_openings[idx])
                    # Move opening toward center of wall
                    opening["parameter"] = max(0.15, min(0.85, opening.get("parameter", 0.5)))
                    new_openings[idx] = opening
                    corrections.append(f"opening {idx} moved away from corner")

        # Fix overlapping objects — nudge apart
        new_placements = [dict(p) for p in plan.object_placements]
        for v in violations:
            if v.rule == "object_overlap":
                # Simple fix: nudge the second object
                name_b = v.details.get("object_b", "")
                for p in new_placements:
                    if p.get("name") == name_b:
                        p["x"] = p.get("x", 0) + 0.3
                        p["y"] = p.get("y", 0) + 0.3
                        corrections.append(f"nudged '{name_b}' to resolve overlap")
                        break

        # Fix door swing clearance — move objects out of swing arc
        for v in violations:
            if v.rule == "door_swing_clearance":
                obj_name = v.details.get("object_name", "")
                swing_radius = v.details.get("swing_radius", 0.9)
                opening_wall = v.details.get("opening_wall", "south")
                for p in new_placements:
                    if p.get("name") == obj_name:
                        # Move object away from the door wall
                        if opening_wall == "north":
                            p["y"] = p.get("y", 0) + swing_radius + 0.1
                        elif opening_wall == "south":
                            p["y"] = p.get("y", 0) - swing_radius - 0.1
                        elif opening_wall == "east":
                            p["x"] = p.get("x", 0) - swing_radius - 0.1
                        else:  # west
                            p["x"] = p.get("x", 0) + swing_radius + 0.1
                        corrections.append(
                            f"moved '{obj_name}' out of door swing arc"
                        )
                        break

        # Build walls for new dimensions
        from src.unified_pipeline.plan_generator import _build_walls_from_dimensions
        new_walls = _build_walls_from_dimensions(new_width, new_depth, new_height)

        # Determine next revision number
        current_rev = max((r.revision for r in plan.revisions), default=0)
        new_rev = current_rev + 1

        corrected_plan = MetricPlan(
            room_dimensions=(new_width, new_depth, new_height),
            walls=new_walls,
            openings=tuple(new_openings),
            object_placements=tuple(new_placements),
            circulation_paths=plan.circulation_paths,
            revisions=plan.revisions + (
                PlanRevision(
                    revision=new_rev,
                    changed="; ".join(corrections) if corrections else "auto-correction",
                    reason="Auto-corrected validation violations",
                    plan_hash="",
                ),
            ),
            template_id=plan.template_id,
        )

        # Compute hash for the corrected plan
        plan_hash = _compute_plan_hash(corrected_plan)
        final_revisions = corrected_plan.revisions[:-1] + (
            PlanRevision(
                revision=new_rev,
                changed=corrected_plan.revisions[-1].changed,
                reason=corrected_plan.revisions[-1].reason,
                plan_hash=plan_hash,
            ),
        )

        return MetricPlan(
            room_dimensions=corrected_plan.room_dimensions,
            walls=corrected_plan.walls,
            openings=corrected_plan.openings,
            object_placements=corrected_plan.object_placements,
            circulation_paths=corrected_plan.circulation_paths,
            revisions=final_revisions,
            template_id=corrected_plan.template_id,
        )
