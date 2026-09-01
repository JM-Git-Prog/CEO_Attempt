"""Metric Plan Generator — constrained template selection and parameterization.

Converts a Brief's spatial requirements into a validated MetricPlan using
template-based generation. The LLM selects a template + parameters (not
free-form coordinate emission).

Requirements: 5.1, 5.2, 5.5, 5.6
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from src.orchestrator.llm import generate_json, LLMError
from src.unified_pipeline.models import Brief, MetricPlan, PlanRevision


# ─── Room Templates ────────────────────────────────────────────────────────────

ROOM_TEMPLATES: dict[str, dict[str, Any]] = {
    "kitchen": {
        "base_dimensions": (4.0, 3.5, 2.7),  # width, depth, ceiling_height
        "min_dimensions": (3.0, 3.0, 2.4),
        "max_dimensions": (5.0, 5.0, 3.0),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.2, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ],
        "keywords": ["kitchen", "kitchenette", "cooking", "breakfast", "diner"],
    },
    "living_room": {
        "base_dimensions": (5.0, 4.5, 2.7),
        "min_dimensions": (4.0, 3.5, 2.4),
        "max_dimensions": (8.0, 7.0, 3.2),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.3, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "east", "parameter": 0.5, "width": 1.5, "height": 1.5},
        ],
        "keywords": ["living", "lounge", "sitting", "family"],
    },
    "bedroom": {
        "base_dimensions": (4.0, 4.0, 2.7),
        "min_dimensions": (3.0, 3.0, 2.4),
        "max_dimensions": (6.0, 5.5, 3.0),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.2, "width": 0.8, "height": 2.1},
            {"type": "window", "wall": "east", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ],
        "keywords": ["bedroom", "sleeping", "rest", "nursery"],
    },
    "studio": {
        "base_dimensions": (5.5, 4.5, 2.9),
        "min_dimensions": (4.0, 4.0, 2.7),
        "max_dimensions": (7.0, 5.0, 3.2),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.35, "width": 1.0, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 2.0, "height": 1.6},
        ],
        "keywords": ["studio", "loft", "open plan", "open-plan", "creative", "art"],
    },
    "generic": {
        "base_dimensions": (4.0, 4.0, 2.7),
        "min_dimensions": (2.0, 2.0, 2.4),
        "max_dimensions": (10.0, 10.0, 4.0),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ],
        "keywords": [],
    },
}


# ─── LLM Prompt ────────────────────────────────────────────────────────────────

PLAN_GENERATION_SYSTEM = """\
You are an interior space planner. Given a Brief describing a room, select the best
template and parameterize it. You do NOT emit raw coordinates — you select from
templates and set parameters.

Available templates: kitchen, living_room, bedroom, studio, generic.

Return JSON:
{
  "template_id": "kitchen",
  "dimensions": {
    "width": 4.0,
    "depth": 3.5,
    "ceiling_height": 2.7
  },
  "openings": [
    {"type": "door|window", "wall": "north|south|east|west", "parameter": 0.0-1.0, "width": 0.8-2.0, "height": 1.0-2.5}
  ],
  "object_placements": [
    {"name": "object name", "x": 0.0-1.0, "y": 0.0-1.0, "rotation_deg": 0, "width": 0.5, "depth": 0.5, "height": 0.8}
  ],
  "circulation_paths": [
    {"from": "door_0", "to": "center", "min_width": 0.6}
  ]
}

Rules:
- Dimensions must be within template min/max bounds
- Object x,y are normalized 0..1 (fraction of room width/depth)
- Every room needs at least one door and one window
- Leave 0.6m minimum circulation clearance between furniture
- Opening parameter is position along wall (0=left corner, 1=right corner)
- Keep openings at least 0.3m from corners (parameter 0.05-0.95)
"""


# ─── Template Selection ────────────────────────────────────────────────────────


def select_template(brief: Brief) -> str:
    """Select the best room template based on Brief content.

    Uses keyword matching on room_purpose and object names.
    Requirement 5.1: constrained template selection.
    """
    purpose_lower = brief.room_purpose.lower()
    object_names_lower = " ".join(
        obj.name.lower() for obj in brief.object_manifest
    )
    combined = f"{purpose_lower} {object_names_lower}"

    best_template = "generic"
    best_score = 0

    for template_id, template in ROOM_TEMPLATES.items():
        if template_id == "generic":
            continue
        score = sum(1 for kw in template["keywords"] if kw in combined)
        if score > best_score:
            best_score = score
            best_template = template_id

    return best_template


# ─── Plan Generation ───────────────────────────────────────────────────────────


def _compute_plan_hash(plan: MetricPlan) -> str:
    """Compute a deterministic hash of a plan for revision tracking."""
    data = json.dumps(plan.to_dict(), sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _build_walls_from_dimensions(
    width: float, depth: float, ceiling_height: float
) -> tuple[dict[str, Any], ...]:
    """Build 4 walls from room dimensions."""
    return (
        {"id": "north", "start": (0, 0, 0), "end": (width, 0, 0), "height": ceiling_height},
        {"id": "east", "start": (width, 0, 0), "end": (width, depth, 0), "height": ceiling_height},
        {"id": "south", "start": (width, depth, 0), "end": (0, depth, 0), "height": ceiling_height},
        {"id": "west", "start": (0, depth, 0), "end": (0, 0, 0), "height": ceiling_height},
    )


def _denormalize_placements(
    placements: list[dict[str, Any]], width: float, depth: float
) -> tuple[dict[str, Any], ...]:
    """Convert normalized (0..1) placements to absolute coordinates."""
    result = []
    for p in placements:
        result.append({
            "id": p.get("id", p.get("object_id", "")),
            "name": p.get("name", "object"),
            "x": p.get("x", 0.5) * width,
            "y": p.get("y", 0.5) * depth,
            "rotation_deg": p.get("rotation_deg", 0),
            "width": p.get("width", 0.5),
            "depth": p.get("depth", 0.5),
            "height": p.get("height", 0.8),
        })
    return tuple(result)


# Real-world furniture footprints in metres: (width, depth, height).
#
# Keyed on the Brief's OWN object names. This is a static table, not an
# observation: the canon image and the depth pass still provide zero
# coordinates and zero scale, so the spatial-authority rule documented in
# _deterministic_placements is unchanged. Without this every object was
# emitted as an identical 0.5 x 0.5 x 0.8 box, which turned "a table and two
# chairs" into three matching cubes in a row.
_FURNITURE_DIMENSIONS: dict[str, tuple[float, float, float]] = {
    "table": (1.40, 0.80, 0.75),
    "dining table": (1.60, 0.90, 0.75),
    "coffee table": (1.10, 0.60, 0.45),
    "desk": (1.40, 0.70, 0.75),
    "chair": (0.50, 0.55, 0.90),
    "armchair": (0.80, 0.80, 0.85),
    "stool": (0.40, 0.40, 0.65),
    "bench": (1.20, 0.40, 0.45),
    "sofa": (2.00, 0.90, 0.85),
    "couch": (2.00, 0.90, 0.85),
    "bed": (1.60, 2.00, 0.55),
    "bookshelf": (0.90, 0.35, 1.80),
    "cabinet": (1.00, 0.45, 0.90),
    "lamp": (0.35, 0.35, 1.55),
    "rug": (2.00, 1.40, 0.02),
}

_DEFAULT_FURNITURE_DIMS: tuple[float, float, float] = (0.5, 0.5, 0.8)

# An anchor is a surface people sit at; seats are what tuck around it.
_SEATING_ANCHORS: tuple[str, ...] = ("dining table", "table", "desk")
_SEATING_NAMES: tuple[str, ...] = ("chair", "armchair", "stool", "bench")

# Inward-facing rotations, matching the convention in _perimeter_placements:
# an object on the north side faces 180, south faces 0, east 270, west 90.
_SEAT_SIDES: tuple[str, ...] = ("north", "south", "east", "west")

# PlanValidator.MIN_CIRCULATION_WIDTH — every pair of objects, and every object
# and wall, must keep this much walkable space. Duplicated as a literal rather
# than imported because plan_validator imports from this module.
_SEAT_CIRCULATION = 0.6
_SEAT_WALL_CLEARANCE = 0.6

# PlanValidator tests `gap < MIN_CIRCULATION_WIDTH`, so a seat placed at exactly
# 0.6m fails on floating point alone: 1.75 - 1.15 evaluates to 0.5999999999999999.
# Clear the boundary by the validator's own overlap tolerance rather than sitting
# on it. Placements therefore aim for 0.62m and land safely above the minimum.
_PLACEMENT_EPSILON = 0.02
_SEAT_TUCK = _SEAT_CIRCULATION + _PLACEMENT_EPSILON


def _seat_side_order(
    openings: tuple[dict[str, Any], ...] = (),
) -> tuple[str, ...]:
    """Order the seat sides so the door's wall is used last.

    A seat parked in front of a door fails PlanValidator's door-swing check:
    measured 2026-08-31, a south seat sat 0.585m from a south door needing
    MIN_DOOR_SWING_CLEARANCE (0.8m). Seating across the axis PERPENDICULAR to
    the door keeps both seats out of the swing while still placing them
    opposite each other across the table, which is what a person would do.
    """
    door = next(
        (item for item in openings
         if str(item.get("type", item.get("kind", ""))) == "door"),
        None,
    )
    wall = str(door.get("wall", "south")) if door else "south"
    if wall in {"north", "south"}:
        return ("east", "west", "north", "south")
    return ("north", "south", "east", "west")


def _seating_footprint(
    anchor: Any,
    seats: list[Any],
    openings: tuple[dict[str, Any], ...] = (),
) -> tuple[float, float]:
    """Minimum room (width, depth) that a table-and-seats group actually needs.

    A real dining set cannot satisfy a uniform 0.6m circulation rule inside the
    4x4 template: the depth budget alone is 0.6 wall + 0.55 seat + 0.6 + 0.80
    table + 0.6 + 0.55 seat + 0.6 wall = 4.3m. The room therefore grows to fit
    its furniture, which the templates already allow (max 10x10), rather than
    the furniture shrinking into identical boxes to fit the room.
    """
    anchor_w, anchor_d, _ = _furniture_dims(anchor.name)
    seat_total = sum(obj.count for obj in seats)
    if seat_total <= 0:
        return (0.0, 0.0)

    # Count how many seats land on each axis, using the SAME side order the
    # placer uses -- otherwise the room is sized for one layout and filled
    # with another.
    order = _seat_side_order(openings)
    depth_sides = sum(
        1 for index in range(min(seat_total, 4))
        if order[index] in {"north", "south"}
    )
    width_sides = sum(
        1 for index in range(min(seat_total, 4))
        if order[index] in {"east", "west"}
    )
    seat_depth = max(_furniture_dims(obj.name)[1] for obj in seats)

    # _SEAT_TUCK, not _SEAT_CIRCULATION: the placer tucks seats at 0.62m, so
    # sizing the room at 0.60m leaves them 0.58m from the wall and fails the
    # clearance check by exactly the epsilon. Measured, not guessed.
    band = _SEAT_TUCK + seat_depth
    margin = 2.0 * (_SEAT_WALL_CLEARANCE + _PLACEMENT_EPSILON)
    needed_w = margin + anchor_w + width_sides * band
    needed_d = margin + anchor_d + depth_sides * band
    return (needed_w, needed_d)


def _grid_footprint(objects: list[Any]) -> tuple[float, float]:
    """Minimum room (width, depth) for objects laid out on the circulation grid.

    Cells are spaced for the largest real footprint, so a sofa no longer lands
    on a grid sized for 0.5m cubes.
    """
    total = sum(obj.count for obj in objects)
    if total <= 0:
        return (0.0, 0.0)
    span = max(
        max(_furniture_dims(obj.name)[0], _furniture_dims(obj.name)[1])
        for obj in objects
    )
    columns = 1
    while columns * columns < total:
        columns += 1
    rows = -(-total // columns)
    margin = 2.0 * (_SEAT_WALL_CLEARANCE + span / 2.0)
    step = span + _SEAT_CIRCULATION
    return (margin + (columns - 1) * step, margin + (rows - 1) * step)


def _seating_group(
    objects: list[Any],
) -> tuple[Any | None, list[Any]]:
    """Split a table-style anchor and its seats out of free-standing furniture."""
    anchor = next(
        (obj for obj in objects
         if _normalized_name(obj.name) in _SEATING_ANCHORS),
        None,
    )
    seats = [
        obj for obj in objects
        if _normalized_name(obj.name) in _SEATING_NAMES
    ]
    return (anchor, seats)


def _normalized_name(name: object) -> str:
    """Casefold a Brief object name to its lookup key."""
    return " ".join(str(name).casefold().replace("-", " ").split())


def _furniture_dims(name: object) -> tuple[float, float, float]:
    """Real-world footprint for a Brief object name.

    Falls back to the trailing noun ("round dining table" -> "table") and then
    to the original generic box, so unknown objects behave exactly as before.
    """
    key = _normalized_name(name)
    if key in _FURNITURE_DIMENSIONS:
        return _FURNITURE_DIMENSIONS[key]
    tail = key.rsplit(" ", 1)[-1] if " " in key else key
    return _FURNITURE_DIMENSIONS.get(tail, _DEFAULT_FURNITURE_DIMS)


def _seating_placements(
    anchor: Any,
    seats: list[Any],
    width: float,
    depth: float,
    openings: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """Place a table at room centre with its seats tucked around it, facing in.

    Sides are consumed north, south, east, west so two chairs land across the
    table from each other rather than side by side. Positions derive only from
    template dimensions and the static footprint table.
    """
    anchor_w, anchor_d, anchor_h = _furniture_dims(anchor.name)
    centre_x, centre_y = width / 2.0, depth / 2.0

    placements: list[dict[str, Any]] = [{
        "id": anchor.id,
        "name": anchor.name,
        "x": centre_x,
        "y": centre_y,
        "rotation_deg": 0,
        "width": anchor_w,
        "depth": anchor_d,
        "height": anchor_h,
        "is_architectural": False,
    }]

    tuck = _SEAT_TUCK  # the validator's minimum walkable gap, plus epsilon
    seat_instances = [
        (obj, instance_index)
        for obj in seats
        for instance_index in range(obj.count)
    ]

    for index, (obj, instance_index) in enumerate(seat_instances):
        seat_w, seat_d, seat_h = _furniture_dims(obj.name)
        sides = _seat_side_order(openings)
        side = sides[index % len(sides)]
        # Seats beyond the first four shift along their side rather than stack.
        shift = (index // len(sides)) * (seat_w + 0.15)
        offset_y = anchor_d / 2.0 + tuck + seat_d / 2.0
        offset_x = anchor_w / 2.0 + tuck + seat_d / 2.0

        if side == "north":
            x, y, rotation = centre_x + shift, centre_y - offset_y, 180
        elif side == "south":
            x, y, rotation = centre_x + shift, centre_y + offset_y, 0
        elif side == "east":
            x, y, rotation = centre_x + offset_x, centre_y + shift, 270
        else:
            x, y, rotation = centre_x - offset_x, centre_y + shift, 90

        # Keep every seat inside the room with its own half-span of clearance.
        margin_x, margin_y = seat_w / 2.0 + 0.05, seat_d / 2.0 + 0.05
        x = min(max(x, margin_x), width - margin_x)
        y = min(max(y, margin_y), depth - margin_y)

        placements.append({
            "id": (
                obj.id if obj.count == 1
                else f"{obj.id}-{instance_index + 1}"
            ),
            "name": obj.name,
            "x": x,
            "y": y,
            "rotation_deg": rotation,
            "width": seat_w,
            "depth": seat_d,
            "height": seat_h,
            "is_architectural": False,
        })

    return placements


def _deterministic_placements(
    brief: Brief,
    width: float,
    depth: float,
    openings: tuple[dict[str, Any], ...] = (),
) -> tuple[dict[str, Any], ...]:
    """Place Brief instances deterministically.

    Placement is split by object nature so that circulation capacity is only
    charged against free-standing furniture:

    - True openings (door/window/opening) are represented by Plan opening
      records, never by placements.
    - Architectural, wall-hosted fixtures (``is_architectural`` — counters,
      cabinets, sinks, stoves, refrigerators) are placed against the room
      perimeter, parameterized along a wall and facing inward. They do not
      consume a center-floor circulation cell (Req 17: architectural elements
      are parameterized along their parent wall).
    - Free-standing furniture is placed on the bounded center-floor grid that
      preserves 0.6m circulation clearance (Req 5.3).

    Positions derive only from template dimensions and Brief identity; semantic
    observations never provide coordinates or scale.
    """
    opening_names = {"door", "window", "opening"}
    placeable = [
        obj for obj in brief.object_manifest
        if " ".join(obj.name.casefold().replace("-", " ").split())
        not in opening_names
    ]
    if not placeable:
        return ()

    # Split perimeter (wall-hosted architectural) fixtures from free-standing
    # furniture. Only free-standing objects charge against circulation capacity.
    perimeter_objects = [obj for obj in placeable if obj.is_architectural]
    freestanding_objects = [obj for obj in placeable if not obj.is_architectural]
    freestanding_total = sum(obj.count for obj in freestanding_objects)

    object_span = 0.5
    edge_clearance = _SEAT_WALL_CLEARANCE + _PLACEMENT_EPSILON
    minimum_gap = _SEAT_CIRCULATION + _PLACEMENT_EPSILON

    placements: list[dict[str, Any]] = []

    # ── Seating cluster: a table and its seats are placed as one group ──────────
    # Without this the grid scatters a table and its chairs into unrelated cells,
    # which reads as three loose boxes rather than a place you would sit down.
    cluster_box: tuple[float, float, float, float] | None = None
    anchor, seats = _seating_group(freestanding_objects)
    if anchor is not None and seats:
        cluster = _seating_placements(anchor, seats, width, depth, openings)
        placements.extend(cluster)
        # Footprint the cluster occupies, so grid cells can steer clear of it.
        cluster_box = (
            min(p["x"] - p["width"] / 2.0 for p in cluster),
            min(p["y"] - p["depth"] / 2.0 for p in cluster),
            max(p["x"] + p["width"] / 2.0 for p in cluster),
            max(p["y"] + p["depth"] / 2.0 for p in cluster),
        )
        clustered = {id(anchor), *(id(obj) for obj in seats)}
        freestanding_objects = [
            obj for obj in freestanding_objects if id(obj) not in clustered
        ]
        freestanding_total = sum(obj.count for obj in freestanding_objects)

    # Space grid cells for the largest real footprint still going on the grid.
    # Emitting real sizes onto a grid spaced for 0.5m cubes would overlap.
    if freestanding_objects:
        object_span = max(
            [object_span]
            + [
                max(_furniture_dims(obj.name)[0], _furniture_dims(obj.name)[1])
                for obj in freestanding_objects
            ]
        )

    # ── Free-standing furniture: bounded center-floor circulation grid ──────────
    if freestanding_total > 0:
        def axis_capacity(span: float) -> int:
            center_span = span - 2.0 * (edge_clearance + object_span / 2.0)
            if center_span < -1e-9:
                return 0
            return 1 + max(0, int(center_span // (object_span + minimum_gap)))

        max_columns = axis_capacity(width)
        max_rows = axis_capacity(depth)
        if (
            max_columns <= 0
            or max_rows <= 0
            or freestanding_total > max_columns * max_rows
        ):
            raise ValueError(
                "template cannot place all required free-standing objects "
                "with 0.6m circulation"
            )

        columns = min(max_columns, freestanding_total)
        rows = (freestanding_total + columns - 1) // columns
        if cluster_box is not None:
            # A lone grid cell sits dead centre, which is inside the seating
            # group's exclusion zone however large the room grows. Force a
            # 2-wide grid so cells land off-centre where there is room.
            columns = min(max_columns, max(columns, 2))
            rows = min(max_rows, max(rows, 2))

        def axis_centers(span: float, count: int) -> tuple[float, ...]:
            margin = edge_clearance + object_span / 2.0
            if count == 1:
                return (span / 2.0,)
            step = (span - 2.0 * margin) / (count - 1)
            return tuple(margin + index * step for index in range(count))

        x_centers = axis_centers(width, columns)
        y_centers = axis_centers(depth, rows)
        # Consume cells farthest from the actual template door hinge first so a
        # partially filled grid leaves the swing's most constrained cell empty.
        door = next(
            (
                item for item in openings
                if item.get("type", item.get("kind")) == "door"
            ),
            {"wall": "south", "parameter": 0.5, "width": 0.9},
        )
        wall = str(door.get("wall", "south"))
        parameter = float(door.get("parameter", 0.5))
        door_width = float(door.get("width", 0.9))
        wall_length = width if wall in {"north", "south"} else depth
        hinge = parameter * wall_length - door_width / 2.0
        if wall == "north":
            hinge_xy = (hinge, 0.0)
        elif wall == "south":
            hinge_xy = (hinge, depth)
        elif wall == "east":
            hinge_xy = (width, hinge)
        else:
            hinge_xy = (0.0, hinge)

        cells = [(x, y) for y in y_centers for x in x_centers]
        if cluster_box is not None:
            # Drop any cell whose footprint would crowd the seating group.
            reach = object_span / 2.0 + minimum_gap
            left, top, right, bottom = cluster_box
            cells = [
                cell for cell in cells
                if not (
                    left - reach < cell[0] < right + reach
                    and top - reach < cell[1] < bottom + reach
                )
            ]
            if len(cells) < freestanding_total:
                raise ValueError(
                    "template cannot place all required free-standing objects "
                    "clear of the seating group with 0.6m circulation"
                )
        cells.sort(
            key=lambda cell: (
                -((cell[0] - hinge_xy[0]) ** 2 + (cell[1] - hinge_xy[1]) ** 2),
                cell[1],
                cell[0],
            )
        )

        index = 0
        for obj in freestanding_objects:
            for instance_index in range(obj.count):
                x, y = cells[index]
                instance_id = (
                    obj.id if obj.count == 1
                    else f"{obj.id}-{instance_index + 1}"
                )
                grid_w, grid_d, grid_h = _furniture_dims(obj.name)
                placements.append({
                    "id": instance_id,
                    "name": obj.name,
                    "x": x,
                    "y": y,
                    "rotation_deg": 0,
                    # Real footprint for the emitted box; the grid still spaces
                    # cells by object_span so circulation capacity is unchanged.
                    "width": grid_w,
                    "depth": grid_d,
                    "height": grid_h,
                    "is_architectural": False,
                })
                index += 1

    # ── Wall-hosted architectural fixtures: perimeter placement ─────────────────
    if perimeter_objects:
        placements.extend(
            _perimeter_placements(
                perimeter_objects, width, depth, object_span, openings
            )
        )

    return tuple(placements)


# Perimeter walls in deterministic order; each entry defines how a fixture at
# parameter t (0..1 along the wall) maps to a center position and inward-facing
# rotation. Fixtures sit half a span off the wall so they rest against it.
_PERIMETER_WALLS: tuple[str, ...] = ("north", "east", "south", "west")


def _perimeter_placements(
    objects: list[Any],
    width: float,
    depth: float,
    object_span: float,
    openings: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """Place wall-hosted architectural fixtures along the room perimeter.

    Fixtures are distributed across walls in deterministic order, seated against
    the wall (half a span inward) and rotated to face the room interior. They do
    not consume center-floor circulation capacity. This mirrors Req 17: derived,
    parameterized-along-wall placement rather than hand-placed coordinates.
    """
    offset = object_span / 2.0
    edge = object_span / 2.0 + 0.05  # keep off the exact corner

    def wall_span(wall: str) -> float:
        return width if wall in {"north", "south"} else depth

    def place_on_wall(wall: str, t: float) -> tuple[float, float, int]:
        span = wall_span(wall)
        # position along the wall, clamped off the corners
        along = edge + t * max(0.0, span - 2.0 * edge)
        if wall == "north":
            return (along, offset, 180)
        if wall == "south":
            return (along, depth - offset, 0)
        if wall == "east":
            return (width - offset, along, 270)
        return (offset, along, 90)  # west

    # Count how many fixture instances land on each wall so we can distribute
    # them evenly along that wall.
    instances: list[Any] = []
    for obj in objects:
        for instance_index in range(obj.count):
            instances.append((obj, instance_index))

    # Assign instances to walls round-robin in deterministic order.
    per_wall: dict[str, list[Any]] = {w: [] for w in _PERIMETER_WALLS}
    for i, item in enumerate(instances):
        wall = _PERIMETER_WALLS[i % len(_PERIMETER_WALLS)]
        per_wall[wall].append(item)

    placements: list[dict[str, Any]] = []
    for wall in _PERIMETER_WALLS:
        wall_items = per_wall[wall]
        n = len(wall_items)
        for slot, (obj, instance_index) in enumerate(wall_items):
            t = 0.5 if n == 1 else slot / (n - 1)
            x, y, rot = place_on_wall(wall, t)
            instance_id = (
                obj.id if obj.count == 1
                else f"{obj.id}-{instance_index + 1}"
            )
            placements.append({
                "id": instance_id,
                "name": obj.name,
                "x": x,
                "y": y,
                "rotation_deg": rot,
                "width": object_span,
                "depth": object_span,
                "height": 0.8,
                "is_architectural": True,
            })
    return placements


def _normalize_openings(raw_openings: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Normalize openings from various LLM response formats into consistent format.

    Handles both our expected format and alternative formats (e.g., mock LLM).
    Each opening must have: type, wall, parameter (0..1), width, height.
    """
    result = []
    for o in raw_openings:
        if not isinstance(o, dict):
            continue
        # Determine type
        opening_type = o.get("type", o.get("kind", ""))
        if opening_type not in ("door", "window"):
            continue
        # Determine wall
        wall = o.get("wall", "south")
        if wall not in ("north", "south", "east", "west"):
            continue
        # Determine parameter (0..1 along wall)
        parameter = o.get("parameter", None)
        if parameter is None:
            # Try to derive from offset if available
            parameter = 0.5  # default center
        # Clamp parameter to 0..1
        parameter = max(0.0, min(1.0, float(parameter)))
        # Width and height
        width = float(o.get("width", 0.9))
        height = float(o.get("height", 2.1 if opening_type == "door" else 1.2))

        result.append({
            "type": opening_type,
            "wall": wall,
            "parameter": parameter,
            "width": width,
            "height": height,
        })
    return tuple(result) if result else ()


class MetricPlanGenerator:
    """Generates a MetricPlan from a Brief using constrained template selection.

    The LLM selects template + parameters, NOT free-form coordinates.
    Includes revision tracking and auto-correction on validation failure.

    Requirements: 5.1, 5.2, 5.5, 5.6
    """

    def __init__(self, model: Optional[str] = None, timeout: float = 30.0):
        self._model = model
        self._timeout = timeout

    def generate_deterministic(self, brief: Brief) -> MetricPlan:
        """Generate from the constrained template without invoking an LLM.

        This is the Canon-first bridge entry point: durable Brief intent selects
        the template and deterministic solver rules own every spatial value.
        """
        template_id = select_template(brief)
        return self._fallback_generate(
            brief, template_id, ROOM_TEMPLATES[template_id]
        )

    async def generate(self, brief: Brief) -> MetricPlan:
        """Generate a MetricPlan from a Brief.

        Requirement 5.1: constrained template selection and parameterization.
        Requirement 5.2: defines room dimensions, walls, openings, placements, circulation.
        Requirement 5.5: revision tracking with provenance.
        Requirement 5.6: relative parameterization (fixtures reference parent wall).
        """
        template_id = select_template(brief)
        template = ROOM_TEMPLATES[template_id]

        # Try LLM-based parameterization
        try:
            plan = await self._llm_generate(brief, template_id, template)
        except (LLMError, TimeoutError, Exception):
            # Fallback: use template defaults
            plan = self._fallback_generate(brief, template_id, template)

        return plan

    async def _llm_generate(
        self, brief: Brief, template_id: str, template: dict[str, Any]
    ) -> MetricPlan:
        """Use LLM to parameterize the template."""
        user_prompt = (
            f"Room purpose: {brief.room_purpose}\n"
            f"Template: {template_id}\n"
            f"Objects needed:\n"
            + "\n".join(
                f"  - {obj.name} (x{obj.count}, role={obj.role})"
                for obj in brief.object_manifest
            )
            + f"\n\nTemplate bounds:\n"
            f"  min: {template['min_dimensions']}\n"
            f"  max: {template['max_dimensions']}\n"
            f"  base: {template['base_dimensions']}\n"
            f"\nGenerate the plan parameters."
        )

        result = await generate_json(
            system=PLAN_GENERATION_SYSTEM,
            user=user_prompt,
            model=self._model,
            timeout_seconds=self._timeout,
        )

        # Parse LLM response into MetricPlan
        dims = result.get("dimensions", {})
        width = float(dims.get("width", template["base_dimensions"][0]))
        depth = float(dims.get("depth", template["base_dimensions"][1]))
        ceiling = float(dims.get("ceiling_height", template["base_dimensions"][2]))

        # Clamp to template bounds
        min_d = template["min_dimensions"]
        max_d = template["max_dimensions"]
        width = max(min_d[0], min(max_d[0], width))
        depth = max(min_d[1], min(max_d[1], depth))
        ceiling = max(min_d[2], min(max_d[2], ceiling))

        walls = _build_walls_from_dimensions(width, depth, ceiling)

        # Parse openings — validate they have the expected structure
        raw_openings = result.get("openings", None)
        if raw_openings and isinstance(raw_openings, list):
            openings = _normalize_openings(raw_openings)
            if not openings:
                openings = tuple(template["default_openings"])
        else:
            openings = tuple(template["default_openings"])

        # Ensure we have at least one opening (fallback to template)
        if not openings:
            openings = tuple(template["default_openings"])

        raw_placements = result.get("object_placements", [])
        placements = _denormalize_placements(raw_placements, width, depth)
        if not placements:
            placements = _deterministic_placements(
                brief, width, depth, openings
            )
        circulation = tuple(result.get("circulation_paths", [])) or (
            {"from": "door_0", "to": "center", "min_width": 0.6},
        )

        plan = MetricPlan(
            room_dimensions=(width, depth, ceiling),
            walls=walls,
            openings=openings,
            object_placements=placements,
            circulation_paths=circulation,
            revisions=(),
            template_id=template_id,
        )

        # Compute and bind hash in revision
        plan_hash = _compute_plan_hash(plan)
        revision = PlanRevision(
            revision=1,
            changed="initial generation",
            reason=f"Generated from Brief using template '{template_id}'",
            plan_hash=plan_hash,
        )
        plan = MetricPlan(
            room_dimensions=plan.room_dimensions,
            walls=plan.walls,
            openings=plan.openings,
            object_placements=plan.object_placements,
            circulation_paths=plan.circulation_paths,
            revisions=(revision,),
            template_id=template_id,
        )

        return plan

    def _select_template(self, brief: Brief) -> dict[str, Any]:
        """Select the best template dict from the library.

        Returns the template dictionary from ROOM_TEMPLATES.
        """
        template_id = select_template(brief)
        return ROOM_TEMPLATES[template_id]

    def _parameterize(
        self, brief: Brief, template: dict[str, Any]
    ) -> MetricPlan:
        """Parameterize a template into a MetricPlan using defaults.

        This is the synchronous path used when LLM is not available.
        """
        template_id = next(
            (k for k, v in ROOM_TEMPLATES.items() if v is template), "generic"
        )
        return self._fallback_generate(brief, template_id, template)

    def revise(
        self,
        plan: MetricPlan,
        changed: str,
        reason: str,
        **updates: Any,
    ) -> MetricPlan:
        """Create a new revision of an existing plan.

        Requirement 5.5: Every Plan revision SHALL be traceable — revision number,
        what changed, why. Plan-owned relationships are revisioned and hashed with
        the spatial values they constrain.
        """
        current_rev = max((r.revision for r in plan.revisions), default=0)
        new_rev_num = current_rev + 1

        new_dims = updates.get("room_dimensions", plan.room_dimensions)
        new_walls = updates.get("walls", plan.walls)
        new_openings = updates.get("openings", plan.openings)
        new_placements = updates.get("object_placements", plan.object_placements)
        new_circulation = updates.get("circulation_paths", plan.circulation_paths)
        new_relationships = updates.get("relationships", plan.relationships)

        updated = MetricPlan(
            room_dimensions=tuple(new_dims),
            walls=tuple(new_walls),
            openings=tuple(new_openings),
            object_placements=tuple(new_placements),
            circulation_paths=tuple(new_circulation),
            relationships=tuple(new_relationships),
            revisions=(),
            template_id=plan.template_id,
        )
        plan_hash = _compute_plan_hash(updated)
        new_revision = PlanRevision(
            revision=new_rev_num,
            changed=changed,
            reason=reason,
            plan_hash=plan_hash,
        )

        return MetricPlan(
            room_dimensions=updated.room_dimensions,
            walls=updated.walls,
            openings=updated.openings,
            object_placements=updated.object_placements,
            circulation_paths=updated.circulation_paths,
            relationships=updated.relationships,
            revisions=plan.revisions + (new_revision,),
            template_id=updated.template_id,
        )

    def _fallback_generate(
        self, brief: Brief, template_id: str, template: dict[str, Any]
    ) -> MetricPlan:
        """Generate a plan from template defaults when LLM fails.

        Uses template base dimensions and default openings, placing objects
        in a simple grid layout.
        """
        width, depth, ceiling = template["base_dimensions"]
        # Needed by the sizing below: the seat side order depends on which wall
        # carries the door, so the openings must be known before placement.
        openings = tuple(template["default_openings"])

        # Grow the room to fit a table-and-seats group rather than shrinking the
        # furniture to fit the template (see _seating_footprint). Clamped to the
        # template's own maximum, so the room stays within its declared bounds.
        freestanding = [
            obj for obj in brief.object_manifest if not obj.is_architectural
        ]
        anchor, seats = _seating_group(freestanding)
        max_w, max_d, _ = template["max_dimensions"]

        if anchor is not None and seats:
            needed_w, needed_d = _seating_footprint(anchor, seats, openings)
            width = min(max(width, needed_w), max_w)
            depth = min(max(depth, needed_d), max_d)
            clustered = {id(anchor), *(id(obj) for obj in seats)}
            freestanding = [
                obj for obj in freestanding if id(obj) not in clustered
            ]

        # Anything left goes on the circulation grid, which needs its own room.
        if freestanding:
            grid_w, grid_d = _grid_footprint(freestanding)
            if anchor is not None and seats:
                # The grid must also clear the seating group, not share its space.
                grid_w += _seating_footprint(anchor, seats, openings)[0]
            width = min(max(width, grid_w), max_w)
            depth = min(max(depth, grid_d), max_d)

        # Deterministic placement preserves every requested Plan instance;
        # true openings remain represented by opening records.
        #
        # The sizing above gets close, but a room holding BOTH a seating group
        # and grid furniture also has to clear the group's exclusion zone, whose
        # geometry is easier to test than to predict. Grow and retry, bounded by
        # the template maximum, and let the final failure surface rather than
        # silently emitting a plan that cannot validate.
        while True:
            try:
                placements = _deterministic_placements(
                    brief, width, depth, openings
                )
                break
            except ValueError:
                if width >= max_w and depth >= max_d:
                    raise
                width = min(width + _SEAT_CIRCULATION, max_w)
                depth = min(depth + _SEAT_CIRCULATION, max_d)

        walls = _build_walls_from_dimensions(width, depth, ceiling)

        circulation = (
            {"from": "door_0", "to": "center", "min_width": 0.6},
        )

        plan = MetricPlan(
            room_dimensions=(width, depth, ceiling),
            walls=walls,
            openings=openings,
            object_placements=tuple(placements),
            circulation_paths=circulation,
            revisions=(),
            template_id=template_id,
        )

        plan_hash = _compute_plan_hash(plan)
        revision = PlanRevision(
            revision=1,
            changed="initial generation (fallback)",
            reason=f"Fallback generation using template '{template_id}' defaults",
            plan_hash=plan_hash,
        )
        plan = MetricPlan(
            room_dimensions=plan.room_dimensions,
            walls=plan.walls,
            openings=plan.openings,
            object_placements=plan.object_placements,
            circulation_paths=plan.circulation_paths,
            revisions=(revision,),
            template_id=template_id,
        )

        return plan
