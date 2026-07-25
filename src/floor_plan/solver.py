"""Constraint-based floor plan solver.

Converts relational spatial constraints from the LLM into deterministic
collision-free coordinates. The LLM's job is semantic reasoning (what goes
where in relation to what); the solver's job is geometry.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from src.floor_plan.models import FloorPlan, PlanItem, PlanOpening, PlanCamera, PlanRoom


@dataclass
class PlacedItem:
    """An item with resolved world coordinates."""
    id: str
    x: float
    z: float
    width: float
    depth: float
    height: float
    elevation: float
    rotation_deg: float = 0.0

    @property
    def half_w(self) -> float:
        return self.width / 2

    @property
    def half_d(self) -> float:
        return self.depth / 2

    def overlaps(self, other: "PlacedItem", margin: float = 0.05) -> bool:
        """AABB overlap check in XZ plane."""
        return (
            abs(self.x - other.x) < self.half_w + other.half_w - margin
            and abs(self.z - other.z) < self.half_d + other.half_d - margin
        )


def solve_plan(plan: FloorPlan) -> FloorPlan:
    """Recompute all item positions using constraint-based placement.
    
    Strategy:
    1. Place wall-anchored items (items near walls stay near walls)
    2. Place centered items at room center
    3. Place relative items (adjacent_to, south_of, above)
    4. Distribute repeated items evenly
    5. Final overlap resolution
    """
    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2
    
    # Classify items by their intended placement
    wall_items = []      # items that belong against a wall (counters, shelves, racks)
    center_items = []    # items that belong in the center (tables, islands)
    relative_items = []  # items relative to another (stools near table, lights above island)
    
    # Build a lookup for what items relate to
    item_map = {item.id: item for item in plan.items}
    
    for item in plan.items:
        text = f"{item.id} {item.name} {item.description}".lower()
        
        # Detect center items
        if any(word in text for word in ["island", "table", "center", "middle"]):
            if item.mount == "floor":
                center_items.append(item)
                continue
        
        # Detect wall items (large fixed things)
        if item.fixed or any(word in text for word in ["shelf", "rack", "counter", "bookcase", "cabinet", "workbench"]):
            if item.mount == "floor":
                wall_items.append(item)
                continue
        
        # Detect ceiling items that go above something
        if item.mount == "ceiling":
            relative_items.append(item)
            continue
        
        # Detect relative items (stools, chairs — they go near a table/counter)
        if any(word in text for word in ["stool", "chair", "bench", "cushion", "seat"]):
            relative_items.append(item)
            continue
        
        # Default: treat as center or relative depending on size
        if item.width * item.depth > 1.0:
            center_items.append(item)
        else:
            relative_items.append(item)
    
    placed: list[PlacedItem] = []
    
    # Compute opening keep-clear zones
    opening_zones = _compute_opening_zones(plan)
    
    # Step 1: Place wall items against their designated wall
    _place_wall_items(wall_items, plan, placed, opening_zones)
    
    # Step 2: Place center items at room center
    _place_center_items(center_items, plan, placed)
    
    # Step 3: Place relative items near their anchor
    _place_relative_items(relative_items, plan, placed, wall_items + center_items)
    
    # Step 4: Final overlap nudge
    _resolve_remaining_overlaps(placed, plan)
    
    # Write back positions
    placed_map = {p.id: p for p in placed}
    for item in plan.items:
        if item.id in placed_map:
            p = placed_map[item.id]
            item.x = p.x
            item.z = p.z
            item.rotation_deg = p.rotation_deg
    
    return plan


@dataclass
class _Zone:
    x: float
    z: float
    width: float
    depth: float


def _compute_opening_zones(plan: FloorPlan) -> list[_Zone]:
    """Compute keep-clear zones for doors and windows."""
    zones = []
    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2
    for opening in plan.openings:
        inward = 1.0 if opening.kind == "door" else 0.3
        if opening.wall == "north":
            zones.append(_Zone(opening.offset, half_d - inward / 2, opening.width + 0.4, inward))
        elif opening.wall == "south":
            zones.append(_Zone(opening.offset, -half_d + inward / 2, opening.width + 0.4, inward))
        elif opening.wall == "east":
            zones.append(_Zone(half_w - inward / 2, opening.offset, inward, opening.width + 0.4))
        else:
            zones.append(_Zone(-half_w + inward / 2, opening.offset, inward, opening.width + 0.4))
    return zones


def _in_zone(x: float, z: float, w: float, d: float, zones: list[_Zone]) -> bool:
    """Check if a placed item overlaps any keep-clear zone."""
    for zone in zones:
        if (abs(x - zone.x) < (w + zone.width) / 2
                and abs(z - zone.z) < (d + zone.depth) / 2):
            return True
    return False


def _place_wall_items(items: list[PlanItem], plan: FloorPlan, placed: list[PlacedItem], zones: list[_Zone]) -> None:
    """Place items against walls, distributed along the wall length."""
    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2
    
    # Determine which wall each item should go against
    for item in items:
        text = f"{item.id} {item.name} {item.description}".lower()
        
        # Try to detect wall from description or just use north (default for counters/shelves)
        wall = "north"  # default
        if "south" in text:
            wall = "south"
        elif "east" in text:
            wall = "east"
        elif "west" in text:
            wall = "west"
        elif "north" in text:
            wall = "north"
        
        # Position against the wall
        gap = 0.15  # gap between item and wall
        if wall == "north":
            item_x = 0.0  # centered on wall
            item_z = half_d - item.depth / 2 - gap
            rotation = 0.0
        elif wall == "south":
            item_x = 0.0
            item_z = -half_d + item.depth / 2 + gap
            rotation = 0.0
        elif wall == "east":
            item_x = half_w - item.depth / 2 - gap
            item_z = 0.0
            rotation = 90.0
        else:  # west
            item_x = -half_w + item.depth / 2 + gap
            item_z = 0.0
            rotation = 90.0
        
        # Check if this position conflicts with an opening zone
        if _in_zone(item_x, item_z, item.width, item.depth, zones):
            # Shift along the wall to avoid the opening
            if wall in ("north", "south"):
                # Try shifting left then right
                for offset in [item.width / 2 + 0.5, -(item.width / 2 + 0.5), item.width + 1.0, -(item.width + 1.0)]:
                    test_x = item_x + offset
                    if abs(test_x) + item.width / 2 < half_w and not _in_zone(test_x, item_z, item.width, item.depth, zones):
                        item_x = test_x
                        break
            else:
                for offset in [item.depth / 2 + 0.5, -(item.depth / 2 + 0.5)]:
                    test_z = item_z + offset
                    if abs(test_z) + item.depth / 2 < half_d and not _in_zone(item_x, test_z, item.width, item.depth, zones):
                        item_z = test_z
                        break
        
        p = PlacedItem(
            id=item.id, x=item_x, z=item_z,
            width=item.width, depth=item.depth,
            height=item.height, elevation=item.elevation,
            rotation_deg=rotation,
        )
        placed.append(p)


def _place_center_items(items: list[PlanItem], plan: FloorPlan, placed: list[PlacedItem]) -> None:
    """Place center items at room center, offset if multiple."""
    if not items:
        return
    
    if len(items) == 1:
        item = items[0]
        p = PlacedItem(
            id=item.id, x=0.0, z=0.0,
            width=item.width, depth=item.depth,
            height=item.height, elevation=item.elevation,
        )
        placed.append(p)
    else:
        # Distribute center items along the room's longer axis
        spacing = plan.room.width / (len(items) + 1)
        half_w = plan.room.width / 2
        for i, item in enumerate(items):
            x = -half_w + spacing * (i + 1)
            p = PlacedItem(
                id=item.id, x=x, z=0.0,
                width=item.width, depth=item.depth,
                height=item.height, elevation=item.elevation,
            )
            placed.append(p)


def _place_relative_items(
    items: list[PlanItem],
    plan: FloorPlan,
    placed: list[PlacedItem],
    anchors: list[PlanItem],
) -> None:
    """Place items relative to already-placed anchors."""
    placed_map = {p.id: p for p in placed}
    
    # Find the primary anchor (largest center/wall item)
    primary_anchor = None
    if placed:
        primary_anchor = max(placed, key=lambda p: p.width * p.depth)
    
    # Group relative items by type
    seating = [i for i in items if any(w in f"{i.id} {i.name}".lower() for w in ["stool", "chair", "cushion", "seat", "bench"])]
    ceiling = [i for i in items if i.mount == "ceiling"]
    other = [i for i in items if i not in seating and i not in ceiling]
    
    # Place seating: south side of primary anchor, evenly spaced
    if seating and primary_anchor:
        anchor = primary_anchor
        spacing = max(0.6, anchor.width / (len(seating) + 1)) if len(seating) > 1 else 0.0
        start_x = anchor.x - (len(seating) - 1) * spacing / 2
        for i, item in enumerate(seating):
            x = start_x + i * spacing
            z = anchor.z - anchor.half_d - item.depth / 2 - 0.3  # south of anchor
            p = PlacedItem(
                id=item.id, x=x, z=z,
                width=item.width, depth=item.depth,
                height=item.height, elevation=item.elevation,
            )
            placed.append(p)
    elif seating:
        # No anchor — place in a row centered
        spacing = 0.7
        start_x = -(len(seating) - 1) * spacing / 2
        for i, item in enumerate(seating):
            p = PlacedItem(
                id=item.id, x=start_x + i * spacing, z=-plan.room.depth / 4,
                width=item.width, depth=item.depth,
                height=item.height, elevation=item.elevation,
            )
            placed.append(p)
    
    # Place ceiling items: directly above the primary anchor, evenly spaced
    if ceiling and primary_anchor:
        anchor = primary_anchor
        spacing = max(0.5, anchor.width / (len(ceiling) + 1)) if len(ceiling) > 1 else 0.0
        start_x = anchor.x - (len(ceiling) - 1) * spacing / 2
        for i, item in enumerate(ceiling):
            x = start_x + i * spacing
            z = anchor.z
            elevation = plan.room.height - item.height
            p = PlacedItem(
                id=item.id, x=x, z=z,
                width=item.width, depth=item.depth,
                height=item.height, elevation=elevation,
            )
            placed.append(p)
    elif ceiling:
        # No anchor — center them
        spacing = 1.0
        start_x = -(len(ceiling) - 1) * spacing / 2
        for i, item in enumerate(ceiling):
            p = PlacedItem(
                id=item.id, x=start_x + i * spacing, z=0.0,
                width=item.width, depth=item.depth,
                height=item.height, elevation=plan.room.height - item.height,
            )
            placed.append(p)
    
    # Place other items in available space
    for item in other:
        # Find a free spot near the center
        best = _find_free_spot(item, plan, placed)
        placed.append(best)


def _find_free_spot(item: PlanItem, plan: FloorPlan, placed: list[PlacedItem]) -> PlacedItem:
    """Find the nearest collision-free position for an item, preferring center."""
    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2
    step = 0.3
    
    # Try center first, then spiral outward
    for radius in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]:
        if radius == 0.0:
            candidates = [(0.0, 0.0)]
        else:
            candidates = []
            for angle in range(0, 360, 30):
                x = radius * math.cos(math.radians(angle))
                z = radius * math.sin(math.radians(angle))
                candidates.append((x, z))
        
        for x, z in candidates:
            if abs(x) + item.width / 2 > half_w - 0.1:
                continue
            if abs(z) + item.depth / 2 > half_d - 0.1:
                continue
            candidate = PlacedItem(
                id=item.id, x=x, z=z,
                width=item.width, depth=item.depth,
                height=item.height, elevation=item.elevation,
            )
            if not any(candidate.overlaps(p) for p in placed):
                return candidate
    
    # Fallback: just place it wherever
    return PlacedItem(
        id=item.id, x=0.0, z=0.0,
        width=item.width, depth=item.depth,
        height=item.height, elevation=item.elevation,
    )


def _resolve_remaining_overlaps(placed: list[PlacedItem], plan: FloorPlan) -> None:
    """Nudge overlapping items apart."""
    half_w = plan.room.width / 2
    half_d = plan.room.depth / 2
    
    for _ in range(20):
        moved = False
        for i, a in enumerate(placed):
            for b in placed[i + 1:]:
                if a.elevation != b.elevation:
                    continue  # different heights don't collide
                if not a.overlaps(b, margin=0.0):
                    continue
                # Push the smaller one away
                mover = b if a.width * a.depth >= b.width * b.depth else a
                dx = mover.x - (a.x + b.x) / 2
                dz = mover.z - (a.z + b.z) / 2
                dist = math.sqrt(dx * dx + dz * dz) or 0.1
                nudge = 0.2
                mover.x += dx / dist * nudge
                mover.z += dz / dist * nudge
                # Clamp to room
                mover.x = max(-half_w + mover.half_w, min(half_w - mover.half_w, mover.x))
                mover.z = max(-half_d + mover.half_d, min(half_d - mover.half_d, mover.z))
                moved = True
        if not moved:
            break


def _resolve_overlaps_explicit(plan) -> None:
    """Final safety pass for solve_explicit_plan().

    Each item there is placed relative to its OWN single anchor (e.g. "stool,
    south of counter"), so two items with different anchors can land on top of
    each other and nothing catches it - the #1 measured failure reason
    ("physical_overlap", 68 hits in the 2026-07-24 exam, more than double the
    runner-up). This mirrors the spiral-search repair already proven in
    src/solver_repair.py (59/60 stress-test failures rescued), adapted to
    FloorPlanV11's PlanItem. Fixed/architectural items are never relocated.
    """
    half_w, half_d = plan.room.width / 2.0, plan.room.depth / 2.0
    items = plan.items
    radii = (0.15, 0.3, 0.5, 0.75, 1.0, 1.4, 1.9, 2.6)
    angle_steps = 12

    def footprint(item):
        rad = math.radians(item.rotation_deg)
        return (abs(item.width * math.cos(rad)) + abs(item.depth * math.sin(rad)),
                abs(item.width * math.sin(rad)) + abs(item.depth * math.cos(rad)))

    def clashes(item, other):
        if item.elevation != other.elevation:
            return False
        aw, ad = footprint(item)
        bw, bd = footprint(other)
        return (abs(item.x - other.x) < (aw + bw) / 2 - 0.03
                and abs(item.z - other.z) < (ad + bd) / 2 - 0.03)

    for _round in range(4):
        moved_any = False
        for i, item in enumerate(items):
            if getattr(item, "fixed", False):
                continue
            others = [o for j, o in enumerate(items) if j != i]
            if not any(clashes(item, o) for o in others):
                continue
            x0, z0 = item.x, item.z
            resolved = False
            for radius in radii:
                for step in range(angle_steps):
                    angle = 2.0 * math.pi * step / angle_steps
                    cx = x0 + radius * math.cos(angle)
                    cz = z0 + radius * math.sin(angle)
                    ew, ed = footprint(item)
                    if abs(cx) + ew / 2 > half_w - 0.02 or abs(cz) + ed / 2 > half_d - 0.02:
                        continue
                    item.x, item.z = cx, cz
                    if not any(clashes(item, o) for o in others):
                        resolved = moved_any = True
                        break
                    item.x, item.z = x0, z0
                if resolved:
                    break
        if not moved_any:
            break


def solve_explicit_plan(source):
    """Resolve a FloorPlanV11 only from persisted typed intent, never item text."""
    from src.floor_plan.models import FloorPlanV11

    if not isinstance(source, FloorPlanV11):
        raise TypeError("explicit Plan solving requires FloorPlanV11")
    plan = source.model_copy(deep=True)
    items = {item.id: item for item in plan.items}
    relations = {relation.subject_id: relation for relation in plan.relationships}
    visiting: set[str] = set()
    placed: set[str] = set()
    half_w, half_d = plan.room.width / 2.0, plan.room.depth / 2.0

    def distributed(anchor, item, parameters: dict[str, float], axis: str) -> float:
        index = parameters.get("distribution_index")
        count = parameters.get("distribution_count")
        if index is None or count is None or count <= 1:
            return anchor.x if axis == "x" else anchor.z
        anchor_span = anchor.width if axis == "x" else anchor.depth
        item_span = item.width if axis == "x" else item.depth
        span = parameters.get("distribution_span_m", max(0.0, anchor_span - item_span))
        return (
            (anchor.x if axis == "x" else anchor.z)
            - span / 2.0 + span * index / (count - 1.0)
        )

    def place(subject_id: str) -> None:
        if subject_id in placed:
            return
        if subject_id in visiting:
            raise ValueError("Plan relation cycle detected during solve")
        visiting.add(subject_id)
        relation = relations[subject_id]
        item = items[subject_id]
        target = None
        if relation.target_id is not None:
            place(relation.target_id)
            target = items[relation.target_id]
        p = relation.parameters_m
        requested_gap = p.get("gap_m", max(0.15, item.clearance_m))
        required_clearance = (
            item.clearance_m + target.clearance_m if target is not None else 0.0
        )
        gap = max(requested_gap, required_clearance)
        half_w, half_d = plan.room.width / 2.0, plan.room.depth / 2.0

        if relation.kind == "centered":
            item.x = p.get("x_offset_m", 0.0)
            item.z = p.get("z_offset_m", 0.0)
        elif relation.kind in {"against_wall", "near_corner"}:
            wall_gap = p.get("wall_gap_m", 0.05)
            along = p.get("along_offset_m", 0.0)
            if relation.wall == "north":
                item.rotation_deg = 0.0
                item.x, item.z = along, half_d - item.depth / 2.0 - wall_gap
            elif relation.wall == "south":
                item.rotation_deg = 0.0
                item.x, item.z = along, -half_d + item.depth / 2.0 + wall_gap
            elif relation.wall == "east":
                item.rotation_deg = 90.0
                item.x, item.z = half_w - item.depth / 2.0 - wall_gap, along
            else:
                item.rotation_deg = 90.0
                item.x, item.z = -half_w + item.depth / 2.0 + wall_gap, along
            if relation.kind == "near_corner" and "along_offset_m" not in p:
                sign = p.get("corner_sign", 1.0)
                if relation.wall in {"north", "south"}:
                    item.x = sign * (half_w - item.width / 2.0 - wall_gap)
                else:
                    item.z = sign * (half_d - item.width / 2.0 - wall_gap)
        elif relation.kind in {"adjacent_to", "east_of"}:
            item.x = target.x + target.width / 2.0 + item.width / 2.0 + gap
            item.z = distributed(target, item, p, "z")
        elif relation.kind == "west_of":
            item.x = target.x - target.width / 2.0 - item.width / 2.0 - gap
            item.z = distributed(target, item, p, "z")
        elif relation.kind == "north_of":
            item.x = distributed(target, item, p, "x")
            item.z = target.z + target.depth / 2.0 + item.depth / 2.0 + gap
        elif relation.kind == "south_of":
            item.x = distributed(target, item, p, "x")
            item.z = target.z - target.depth / 2.0 - item.depth / 2.0 - gap
        elif relation.kind == "above":
            item.x = distributed(target, item, p, "x")
            item.z = target.z
            item.elevation = (
                plan.room.height - item.height if item.mount == "ceiling"
                else target.elevation + target.height + gap
            )
        elif relation.kind == "facing":
            item.rotation_deg = math.degrees(
                math.atan2(target.x - item.x, item.z - target.z)
            ) % 360.0
        elif relation.kind == "around":
            index = p.get("distribution_index", 0.0)
            count = max(1.0, p.get("distribution_count", 1.0))
            radius = p.get(
                "radius_m",
                max(target.width, target.depth) / 2.0
                + max(item.width, item.depth) / 2.0 + gap,
            )
            angle = 2.0 * math.pi * index / count
            item.x = target.x + radius * math.cos(angle)
            item.z = target.z + radius * math.sin(angle)
        else:
            raise ValueError(f"unsupported explicit Plan relation: {relation.kind}")

        if item.mount == "floor":
            item.elevation = 0.0
        elif item.mount == "ceiling":
            item.elevation = plan.room.height - item.height

        # Clamp rotation-aware bounds inside room to prevent out-of-bounds blockers.
        rad = math.radians(item.rotation_deg)
        effective_w = abs(item.width * math.cos(rad)) + abs(item.depth * math.sin(rad))
        effective_d = abs(item.width * math.sin(rad)) + abs(item.depth * math.cos(rad))
        max_x = half_w - effective_w / 2.0
        max_z = half_d - effective_d / 2.0
        if max_x > 0:
            item.x = max(-max_x, min(max_x, item.x))
        if max_z > 0:
            item.z = max(-max_z, min(max_z, item.z))

        visiting.remove(subject_id)
        placed.add(subject_id)

    for identity in sorted(items):
        place(identity)

    _resolve_overlaps_explicit(plan)

    openings = {opening.id: opening for opening in plan.openings}
    for intent in plan.opening_intents:
        opening = openings[intent.opening_id]
        opening.wall = intent.wall
        if intent.placement == "centered":
            opening.offset = 0.0
        else:
            north = intent.corner in {"northwest", "northeast"}
            east = intent.corner in {"northeast", "southeast"}
            wall_length = plan.room.width if intent.wall in {"north", "south"} else plan.room.depth
            positive = east if intent.wall in {"north", "south"} else north
            magnitude = wall_length / 2.0 - opening.width / 2.0 - intent.margin_m
            opening.offset = magnitude if positive else -magnitude

            # Keep the opening as close to its typed corner as hard geometry permits.
            # This moves the opening, never a relation-owned fixed item.
            from src.floor_plan.geometry import footprints_intersect
            from src.floor_plan.validator import _opening_volumes

            direction = 1.0 if positive else -1.0
            for step in range(int(max(0.0, magnitude) / 0.05) + 1):
                candidate = direction * max(0.0, magnitude - step * 0.05)
                opening.offset = candidate
                volume = next(
                    value for value in _opening_volumes(plan) if value.id == opening.id
                )
                if not any(footprints_intersect(item, volume) for item in plan.items):
                    break

    camera = plan.camera_intent
    inset = camera.inset_m
    plan.camera.x = half_w - inset if camera.corner in {"northeast", "southeast"} else -half_w + inset
    plan.camera.z = half_d - inset if camera.corner in {"northwest", "northeast"} else -half_d + inset
    plan.camera.y = min(camera.eye_height_m, plan.room.height - 0.2)
    target = items[camera.target_id]
    plan.camera.target_x = target.x
    plan.camera.target_y = min(camera.target_height_m, plan.room.height)
    plan.camera.target_z = target.z
    plan.camera.fov_deg = camera.fov_deg
    return plan
