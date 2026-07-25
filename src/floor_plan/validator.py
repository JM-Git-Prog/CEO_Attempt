"""Deterministic bounds and circulation checks for model-authored plans."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

from src.floor_plan.geometry import (
    fit_center_inside,
    footprint_overlap_depth,
    footprints_intersect,
    inside_room,
)
from src.floor_plan.models import (
    FloorPlan,
    PlanValidationIssue,
    PlanValidationReport,
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_id(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return clean or fallback


def normalize_floor_plan(
    source: FloorPlan,
    description: str = "",
    *,
    strict: bool = False,
    infer_text_placement: bool = True,
) -> tuple[FloorPlan, list[str], PlanValidationReport]:
    """Normalize authored geometry and return deterministic validation evidence."""
    plan = source.model_copy(deep=True)
    warnings: list[str] = []
    if infer_text_placement:
        _apply_explicit_dimensions(plan, description, warnings)
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    opening_ids = {opening.id.lower() for opening in plan.openings}
    surfaces = {"floor", "flooring", "wall", "walls", "ceiling", "door", "doors", "window", "windows"}
    if strict:
        plan.items = [item for item in plan.items if _keep_strict_item(item, opening_ids)]
    else:
        plan.items = [
            item for item in plan.items
            if item.id.lower() not in opening_ids
            and not set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower())) & surfaces
        ]
    if infer_text_placement:
        plan.items = _expand_grouped_items(plan.items, warnings)
    seen: set[str] = set()
    for index, item in enumerate(plan.items):
        item.id = _safe_id(item.id, f"item_{index + 1}")
        if item.id in seen:
            item.id = f"{item.id}_{index + 1}"
        seen.add(item.id)
        item.rotation_deg %= 360
        words = set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower()))
        if strict and infer_text_placement:
            _normalize_mount(item, plan)
        elif strict:
            _apply_declared_mount(item, plan)
        else:
            item.width = min(item.width, plan.room.width)
            item.depth = min(item.depth, plan.room.depth)
            item.x = _clamp(item.x, -half_w + item.width / 2, half_w - item.width / 2)
            item.z = _clamp(item.z, -half_d + item.depth / 2, half_d - item.depth / 2)
            ceiling_fixture = bool(words & {"pendant", "chandelier", "ceiling", "hanging"})
            item.elevation = max(0.0, plan.room.height - item.height) if ceiling_fixture else 0.0
        if infer_text_placement and words & {"stool", "stools", "chair", "chairs", "table", "tables", "ottoman",
                   "cushion", "cushions", "beanbag", "bench", "benches", "seat", "seats",
                   "pouf", "pouffe", "footstool", "hassock",
                   "cabinet", "cabinets", "arcade", "machine", "pedestal"}:
            item.fixed = False
    for index, opening in enumerate(plan.openings):
        opening.id = _safe_id(opening.id, f"opening_{index + 1}")
        wall_length = plan.room.width if opening.wall in {"north", "south"} else plan.room.depth
        opening.width = min(opening.width, wall_length - 0.2)
        opening.offset = _clamp(
            opening.offset,
            -wall_length / 2 + opening.width / 2,
            wall_length / 2 - opening.width / 2,
        )
        if opening.kind == "door":
            opening.sill_height = 0.0
        else:
            opening.sill_height = _clamp(opening.sill_height, 0.0, plan.room.height - 0.2)
            opening.height = min(opening.height, plan.room.height - opening.sill_height)
    if infer_text_placement:
        _apply_description_layout(plan, description, warnings)
        _distribute_repeated_items(plan, warnings)
    if strict:
        _fit_items_inside(plan, warnings)
        _resolve_overlaps_bounded(plan, warnings)
    else:
        _resolve_overlaps_legacy(plan, warnings)
    plan.camera.x = _clamp(plan.camera.x, -half_w + 0.2, half_w - 0.2)
    plan.camera.z = _clamp(plan.camera.z, -half_d + 0.2, half_d - 0.2)
    plan.camera.y = _clamp(plan.camera.y, 1.2, plan.room.height - 0.2)
    if strict:
        _place_camera_clear_bounded(plan, warnings)
    else:
        _place_camera_clear(plan, warnings)
    view_length = math.sqrt(
        (plan.camera.target_x - plan.camera.x) ** 2
        + (plan.camera.target_y - plan.camera.y) ** 2
        + (plan.camera.target_z - plan.camera.z) ** 2
    )
    horizontal_view = math.hypot(
        plan.camera.target_x - plan.camera.x,
        plan.camera.target_z - plan.camera.z,
    )
    if view_length < 0.5 or horizontal_view < 1.0:
        plan.camera.target_x = 0.0
        plan.camera.target_y = min(1.2, plan.room.height / 2)
        plan.camera.target_z = 0.0
    report = validate_floor_plan(plan, warnings, strict=strict)
    if strict:
        warnings.extend(
            issue.message for issue in report.warnings
            if issue.message not in warnings
        )
        warnings = warnings[:20]
    else:
        warnings.extend(_overlap_warnings(plan))
    return plan, warnings, report


_SURFACE_OBJECT_TOKENS = {
    "beam", "beams", "rafter", "rafters", "fan", "light", "lamp", "pendant",
    "shelf", "shelves", "bookcase", "cabinet", "trim", "molding", "seat",
}
_FLOOR_STANDING_TOKENS = {
    "armchair", "chair", "stool", "table", "desk", "sofa", "bookcase",
    "bookshelf", "bookshelves", "cabinet", "dresser", "ottoman", "floorlamp",
}


def _keep_strict_item(item, opening_ids: set[str]) -> bool:
    """Filter only room surfaces/opening duplicates, never named ceiling architecture."""
    if item.id.lower() in opening_ids:
        return False
    words = set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower()))
    if words & _SURFACE_OBJECT_TOKENS:
        return True
    if words & {"door", "doors", "window", "windows"}:
        return False
    surface_words = words & {"floor", "flooring", "floorboards", "wall", "walls", "ceiling", "ceilings"}
    return not (surface_words and item.category == "architectural")


def _apply_declared_mount(item, plan: FloorPlan) -> None:
    """Apply only typed mount semantics, without inferring intent from text."""
    if item.mount == "ceiling":
        item.elevation = max(0.0, plan.room.height - item.height)
    elif item.mount == "floor":
        item.elevation = 0.0
    else:
        item.elevation = _clamp(item.elevation, 0.0, plan.room.height - item.height)


def _normalize_mount(item, plan: FloorPlan) -> None:
    text = f"{item.id} {item.name} {item.description}".lower()
    words = set(re.findall(r"[a-z]+", text))
    standing = bool(words & _FLOOR_STANDING_TOKENS) or "floor lamp" in text
    ceiling_cue = bool(words & {"beam", "beams", "rafter", "rafters", "pendant", "chandelier"})
    ceiling_cue = ceiling_cue or any(
        phrase in text for phrase in ("ceiling mounted", "ceiling-mounted", "ceiling light", "ceiling fan", "hanging light", "neon", "tube light", "track light")
    )
    if item.mount == "floor" and ceiling_cue and not standing:
        item.mount = "ceiling"
    if item.mount == "ceiling":
        # Clamp ceiling fixture height to reasonable range (most are 0.05-0.6m)
        if item.height > 0.8:
            item.height = min(0.5, max(0.1, item.height * 0.25))
        item.elevation = max(0.0, plan.room.height - item.height)
    elif item.mount == "floor":
        item.elevation = 0.0


def _fit_items_inside(plan: FloorPlan, warnings: list[str]) -> None:
    for item in plan.items:
        fitted = fit_center_inside(item, plan.room.width, plan.room.depth)
        if fitted is None:
            continue
        if abs(fitted[0] - item.x) > 1e-9 or abs(fitted[1] - item.z) > 1e-9:
            item.x, item.z = fitted
            warnings.append(f"Moved {item.name} inside the rotation-aware room boundary")


def _overlap_warnings(plan: FloorPlan) -> list[str]:
    warnings: list[str] = []
    for index, left in enumerate(plan.items):
        for right in plan.items[index + 1:]:
            dx = abs(left.x - right.x)
            dz = abs(left.z - right.z)
            overlap_x = dx < (left.width + right.width) / 2 - 0.03
            overlap_z = dz < (left.depth + right.depth) / 2 - 0.03
            vertical_overlap = left.elevation < right.elevation + right.height - 0.03 and right.elevation < left.elevation + left.height - 0.03
            if overlap_x and overlap_z and vertical_overlap and not (left.fixed and right.fixed):
                warnings.append(f"Check overlap: {left.name} / {right.name}")
    for item in plan.items:
        if not math.isfinite(item.x + item.z + item.width + item.depth):
            warnings.append(f"Invalid numeric value on {item.name}")
    return warnings[:12]


_COUNT_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_REPEATABLE = {"stools", "chairs", "lamps", "lights", "pendants", "tables"}


def _expand_grouped_items(items, warnings):
    expanded = []
    for item in items:
        words = re.findall(r"[a-z0-9]+", item.name.lower())
        first = words[0] if words else ""
        count = int(first) if first.isdigit() else _COUNT_WORDS.get(first, 1)
        if count <= 1 or count > 8 or not set(words) & _REPEATABLE:
            expanded.append(item)
            continue
        angle = math.radians(item.rotation_deg)
        along_x = item.width >= item.depth
        span = item.width if along_x else item.depth
        spacing = span / count
        footprint = max(0.12, min(spacing * 0.72, item.depth if along_x else item.width))
        base_id = re.sub(r"_(stools|chairs|lamps|lights|pendants|tables)$", lambda match: "_" + match.group(1).rstrip("s"), item.id)
        base_name = " ".join(item.name.split()[1:]).rstrip("s")
        for index in range(count):
            clone = item.model_copy(deep=True)
            offset = -span / 2 + spacing * (index + 0.5)
            local_x, local_z = (offset, 0.0) if along_x else (0.0, offset)
            clone.x = item.x + local_x * math.cos(angle) - local_z * math.sin(angle)
            clone.z = item.z + local_x * math.sin(angle) + local_z * math.cos(angle)
            clone.width = footprint
            clone.depth = footprint
            clone.id = f"{base_id}_{index + 1}"
            clone.name = f"{base_name} {index + 1}"
            expanded.append(clone)
    return expanded


def _distribute_repeated_items(plan: FloorPlan, warnings: list[str]) -> None:
    groups: dict[str, list] = {}
    for item in plan.items:
        key = re.sub(r"_\d+$", "", item.id)
        groups.setdefault(key, []).append(item)
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    for key, group in groups.items():
        if len(group) < 2:
            continue
        candidates = [item for item in plan.items if item not in group and item.fixed and item.elevation == 0]
        anchor = max(candidates, key=lambda item: item.width * item.depth, default=None)
        sample = group[0]
        ceiling_group = all(item.elevation > 0 for item in group)
        if anchor and anchor.width >= anchor.depth:
            available = max(sample.width, anchor.width - sample.width)
            spacing = min(max(sample.width + 0.25, 0.65), available / max(1, len(group) - 1))
            center = anchor.x
            if ceiling_group:
                z = anchor.z
            else:
                direction = -1 if anchor.z >= 0 else 1
                z = anchor.z + direction * (anchor.depth / 2 + sample.depth / 2 + 0.35)
            for index, item in enumerate(group):
                item.x = _clamp(center + (index - (len(group) - 1) / 2) * spacing, -half_w + item.width / 2, half_w - item.width / 2)
                item.z = _clamp(z, -half_d + item.depth / 2, half_d - item.depth / 2)
        elif anchor:
            available = max(sample.depth, anchor.depth - sample.depth)
            spacing = min(max(sample.depth + 0.25, 0.65), available / max(1, len(group) - 1))
            center = anchor.z
            if ceiling_group:
                x = anchor.x
            else:
                direction = -1 if anchor.x >= 0 else 1
                x = anchor.x + direction * (anchor.width / 2 + sample.width / 2 + 0.35)
            for index, item in enumerate(group):
                item.x = _clamp(x, -half_w + item.width / 2, half_w - item.width / 2)
                item.z = _clamp(center + (index - (len(group) - 1) / 2) * spacing, -half_d + item.depth / 2, half_d - item.depth / 2)
        else:
            spacing = max(sample.width * 1.7, 0.75)
            for index, item in enumerate(group):
                item.x = _clamp((index - (len(group) - 1) / 2) * spacing, -half_w + item.width / 2, half_w - item.width / 2)


@dataclass
class _CollisionVolume:
    id: str
    name: str
    x: float
    z: float
    width: float
    depth: float
    height: float
    elevation: float
    rotation_deg: float = 0.0
    fixed: bool = True
    mount: str = "opening"
    clearance_m: float = 0.0


def _opening_volumes(plan: FloorPlan) -> list[_CollisionVolume]:
    """Model door access and window recesses as real interior keep-clear volumes."""
    volumes: list[_CollisionVolume] = []
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    for opening in plan.openings:
        inward = min(1.2, max(0.75, opening.width)) if opening.kind == "door" else 0.18
        elevation = 0.0 if opening.kind == "door" else opening.sill_height
        if opening.wall == "north":
            x, z, width, depth = opening.offset, half_d - inward / 2, opening.width, inward
        elif opening.wall == "south":
            x, z, width, depth = opening.offset, -half_d + inward / 2, opening.width, inward
        elif opening.wall == "east":
            x, z, width, depth = half_w - inward / 2, opening.offset, inward, opening.width
        else:
            x, z, width, depth = -half_w + inward / 2, opening.offset, inward, opening.width
        volumes.append(_CollisionVolume(
            id=opening.id,
            name=f"{opening.kind.title()} {opening.id}",
            x=x,
            z=z,
            width=width,
            depth=depth,
            height=opening.height,
            elevation=elevation,
        ))
    return volumes


def _placement_candidates(item, plan: FloorPlan):
    """Yield a bounded, deterministic whole-room search nearest authored geometry first."""
    step = 0.2
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    rotations = tuple(dict.fromkeys((item.rotation_deg, (item.rotation_deg + 90.0) % 360.0)))
    candidates = [(0.0, item.x, item.z, item.rotation_deg)]
    x = -half_w + step / 2
    while x <= half_w - step / 2 + 1e-9 and len(candidates) < 50_000:
        z = -half_d + step / 2
        while z <= half_d - step / 2 + 1e-9 and len(candidates) < 50_000:
            for rotation in rotations:
                distance = (x - item.x) ** 2 + (z - item.z) ** 2
                rotation_cost = 0.0 if rotation == item.rotation_deg else 0.35
                candidates.append((distance + rotation_cost, x, z, rotation))
            z += step
        x += step
    for _, x, z, rotation in sorted(candidates):
        yield x, z, rotation


def _clearance_padding(volume) -> float:
    return min(0.4, max(0.0, getattr(volume, "clearance_m", 0.0)) / 2)


def _collides(item, obstacles: list, *, honor_clearance: bool) -> bool:
    for other in obstacles:
        left_padding = _clearance_padding(item) if honor_clearance else 0.0
        right_padding = _clearance_padding(other) if honor_clearance else 0.0
        if footprints_intersect(
            item,
            other,
            left_padding=left_padding,
            right_padding=right_padding,
            tolerance=0.0 if honor_clearance else 0.03,
        ):
            return True
    return False


def _try_place(item, plan: FloorPlan, obstacles: list, *, honor_clearance: bool) -> bool:
    original = (item.x, item.z, item.rotation_deg)
    for x, z, rotation in _placement_candidates(item, plan):
        item.x, item.z, item.rotation_deg = x, z, rotation
        if not inside_room(item, plan.room.width, plan.room.depth):
            continue
        if not _collides(item, obstacles, honor_clearance=honor_clearance):
            return True
    item.x, item.z, item.rotation_deg = original
    return False


def _resolve_overlaps_bounded(plan: FloorPlan, warnings: list[str]) -> None:
    """Resolve movable occupancy deterministically; fixed conflicts remain blockers."""
    opening_vols = _opening_volumes(plan)

    # Phase 0: Relocate fixed items that collide with opening volumes.
    # A "fixed" item placed by the description layout may still overlap a door
    # keep-clear zone (e.g. a long counter whose end clips a door swing).
    for item in plan.items:
        if not item.fixed or item.mount not in {"floor", "ceiling"}:
            continue
        if _collides(item, opening_vols, honor_clearance=False):
            if _try_place(item, plan, opening_vols, honor_clearance=False):
                warnings.append(
                    f"Shifted {item.name} to clear door/window opening"
                )

    movable = sorted(
        (
            item for item in plan.items
            if not item.fixed
        ),
        key=lambda item: (-item.width * item.depth, item.id),
    )
    placed = [
        item for item in plan.items
        if item.fixed
    ]
    placed.extend(opening_vols)
    for item in movable:
        needs_physical_move = (
            not inside_room(item, plan.room.width, plan.room.depth)
            or _collides(item, placed, honor_clearance=False)
        )
        needs_clearance_move = _collides(item, placed, honor_clearance=True)
        moved = False
        if needs_physical_move or needs_clearance_move:
            moved = _try_place(item, plan, placed, honor_clearance=True)
            if not moved:
                moved = _try_place(item, plan, placed, honor_clearance=False)
                if moved:
                    warnings.append(f"Placed {item.name} safely but full requested clearance was unavailable")
            elif moved:
                warnings.append(f"Moved {item.name} to resolve overlap and clearance constraints")
        placed.append(item)


def _camera_probe(plan: FloorPlan) -> _CollisionVolume:
    return _CollisionVolume(
        id="canon_camera",
        name="Canon camera",
        x=plan.camera.x,
        z=plan.camera.z,
        width=0.36,
        depth=0.36,
        height=plan.camera.y + 0.15,
        elevation=0.0,
        fixed=False,
        mount="camera",
    )


def _place_camera_clear_bounded(plan: FloorPlan, warnings: list[str]) -> None:
    obstacles = [*plan.items, *_opening_volumes(plan)]
    probe = _camera_probe(plan)
    if inside_room(probe, plan.room.width, plan.room.depth) and not _collides(
        probe, obstacles, honor_clearance=False
    ):
        return
    original = (plan.camera.x, plan.camera.z)
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    candidates = []
    step = 0.2
    x = -half_w + step
    while x <= half_w - step + 1e-9 and len(candidates) < 25_000:
        z = -half_d + step
        while z <= half_d - step + 1e-9 and len(candidates) < 25_000:
            candidates.append(((x - original[0]) ** 2 + (z - original[1]) ** 2, x, z))
            z += step
        x += step
    for _, x, z in sorted(candidates):
        plan.camera.x, plan.camera.z = x, z
        probe = _camera_probe(plan)
        if inside_room(probe, plan.room.width, plan.room.depth) and not _collides(
            probe, obstacles, honor_clearance=False
        ):
            warnings.append("Moved Canon camera to a collision-free footprint")
            return
    plan.camera.x, plan.camera.z = original


def validate_floor_plan(
    plan: FloorPlan,
    normalization_warnings: list[str] | None = None,
    *,
    tolerance: Literal["strict", "mvp"] | None = None,
    strict: bool = False,
) -> PlanValidationReport:
    """Return structured blockers from the same SAT model used for placement.

    Parameters
    ----------
    tolerance : "strict" | "mvp" | None
        Explicit validation mode.  When provided, takes precedence over *strict*.
    strict : bool
        Legacy flag.  Equivalent to ``tolerance="strict"`` when *tolerance* is None.

    MVP tolerance thresholds (non-critical → warning, not blocker):
      - Physical overlap ≤ 0.1 m
      - Clearance violation ≤ 0.15 m
      - Relationship offset ≤ 0.2 m (detected from clearance padding interactions)

    Structural impossibilities are ALWAYS rejected regardless of mode:
      - Non-finite geometry
      - Vertex outside room bounds
      - Zero-dimension room (caught by Pydantic model, but validated here too)
      - Missing dimensions (caught by Pydantic model)
      - Duplicate stable IDs
    """
    # --- Determine effective mode ---
    if tolerance is not None:
        effective_mode = tolerance
    elif strict:
        effective_mode = "strict"
    else:
        effective_mode = "mvp"

    # MVP thresholds
    MVP_OVERLAP_THRESHOLD = 0.1  # meters
    MVP_CLEARANCE_THRESHOLD = 0.15  # meters
    MVP_RELATIONSHIP_OFFSET_THRESHOLD = 0.2  # meters

    blockers: list[PlanValidationIssue] = []
    advisory: list[PlanValidationIssue] = []
    tolerance_warnings: list[dict] = []

    # --- Structural: duplicate stable IDs ---
    seen_ids: set[str] = set()
    for item_entry in plan.items:
        if item_entry.id in seen_ids:
            blockers.append(PlanValidationIssue(
                code="duplicate_stable_id",
                message=f"Duplicate stable ID: {item_entry.id}",
                item_ids=[item_entry.id],
            ))
        seen_ids.add(item_entry.id)

    # --- Structural: zero-dimension room ---
    if plan.room.width <= 0 or plan.room.depth <= 0 or plan.room.height <= 0:
        blockers.append(PlanValidationIssue(
            code="zero_dimension_room",
            message="Room has a zero or negative dimension",
            item_ids=[],
            details={
                "width": plan.room.width,
                "depth": plan.room.depth,
                "height": plan.room.height,
            },
        ))

    for index, left in enumerate(plan.items):
        if not math.isfinite(
            left.x + left.z + left.width + left.depth + left.height + left.elevation
        ):
            blockers.append(PlanValidationIssue(
                code="non_finite_geometry",
                message=f"Invalid numeric geometry on {left.name}",
                item_ids=[left.id],
            ))
            continue

        # Structural: vertex outside room bounds — always reject
        if not inside_room(left, plan.room.width, plan.room.depth):
            blockers.append(PlanValidationIssue(
                code="out_of_bounds",
                message=f"{left.name} extends beyond the rotation-aware room boundary",
                item_ids=[left.id],
                details={"mount": left.mount, "rotation_deg": left.rotation_deg},
            ))

        for right in plan.items[index + 1:]:
            physical = footprints_intersect(left, right)
            if physical:
                # Different mount types with minor vertical overlap are advisories, not blockers.
                mixed_mount = left.mount != right.mount and {left.mount, right.mount} != {"floor", "floor"}
                if mixed_mount:
                    if left.elevation >= right.elevation:
                        upper, lower = left, right
                    else:
                        upper, lower = right, left
                    lower_top = lower.elevation + lower.height
                    vertical_overlap = lower_top - upper.elevation
                    if vertical_overlap < 0.30:
                        advisory.append(PlanValidationIssue(
                            code="mixed_mount_clip",
                            message=(
                                f"Minor vertical clip ({vertical_overlap:.2f}m) between "
                                f"different mounts: {left.name} / {right.name}"
                            ),
                            item_ids=[left.id, right.id],
                            details={
                                "mounts": [left.mount, right.mount],
                                "vertical_overlap_m": round(vertical_overlap, 3),
                            },
                        ))
                        continue

                # --- MVP tolerance: measure overlap depth ---
                if effective_mode == "mvp":
                    overlap_depth = footprint_overlap_depth(left, right)
                    if overlap_depth <= MVP_OVERLAP_THRESHOLD:
                        # Non-critical: downgrade to warning
                        advisory.append(PlanValidationIssue(
                            code="physical_overlap",
                            message=(
                                f"Minor overlap ({overlap_depth:.3f}m ≤ {MVP_OVERLAP_THRESHOLD}m): "
                                f"{left.name} / {right.name} [MVP tolerated]"
                            ),
                            item_ids=[left.id, right.id],
                            details={
                                "fixed_pair": left.fixed and right.fixed,
                                "mounts": [left.mount, right.mount],
                                "overlap_m": round(overlap_depth, 4),
                                "mvp_tolerated": True,
                            },
                        ))
                        tolerance_warnings.append({
                            "warning_type": "overlap",
                            "affected_id": f"{left.id},{right.id}",
                            "measured_deviation": round(overlap_depth, 4),
                            "threshold": MVP_OVERLAP_THRESHOLD,
                        })
                        continue

                # Strict mode (or MVP with overlap > threshold): blocker
                blockers.append(PlanValidationIssue(
                    code="physical_overlap",
                    message=f"Unresolved overlap: {left.name} / {right.name}",
                    item_ids=[left.id, right.id],
                    details={
                        "fixed_pair": left.fixed and right.fixed,
                        "mounts": [left.mount, right.mount],
                    },
                ))
            elif footprints_intersect(
                left,
                right,
                left_padding=_clearance_padding(left),
                right_padding=_clearance_padding(right),
                tolerance=0.0,
            ):
                # Clearance conflict detected
                if effective_mode == "mvp":
                    # Measure the clearance violation depth
                    # The violation is the depth of intersection when padded
                    clearance_depth = footprint_overlap_depth(
                        left,
                        right,
                        left_padding=_clearance_padding(left),
                        right_padding=_clearance_padding(right),
                    )
                    if clearance_depth <= MVP_CLEARANCE_THRESHOLD:
                        # Non-critical: downgrade to warning
                        advisory.append(PlanValidationIssue(
                            code="clearance_conflict",
                            message=(
                                f"Minor clearance violation ({clearance_depth:.3f}m ≤ "
                                f"{MVP_CLEARANCE_THRESHOLD}m): {left.name} / {right.name} "
                                f"[MVP tolerated]"
                            ),
                            item_ids=[left.id, right.id],
                            details={
                                "clearance_violation_m": round(clearance_depth, 4),
                                "mvp_tolerated": True,
                            },
                        ))
                        tolerance_warnings.append({
                            "warning_type": "clearance",
                            "affected_id": f"{left.id},{right.id}",
                            "measured_deviation": round(clearance_depth, 4),
                            "threshold": MVP_CLEARANCE_THRESHOLD,
                        })
                        continue

                # Strict mode (or MVP with violation > threshold)
                advisory.append(PlanValidationIssue(
                    code="clearance_conflict",
                    message=f"Requested clearance is tight: {left.name} / {right.name}",
                    item_ids=[left.id, right.id],
                ))

    # --- Opening blocked checks (structural — always reject) ---
    for opening_volume in _opening_volumes(plan):
        for item_entry in plan.items:
            if footprints_intersect(item_entry, opening_volume):
                blockers.append(PlanValidationIssue(
                    code="opening_blocked",
                    message=f"{item_entry.name} obstructs {opening_volume.name}",
                    item_ids=[item_entry.id, opening_volume.id],
                    details={"opening_id": opening_volume.id},
                ))

    # --- Camera checks: skip entirely in MVP mode (MVP skips canon image generation) ---
    if effective_mode == "strict":
        camera = _camera_probe(plan)
        if not inside_room(camera, plan.room.width, plan.room.depth):
            blockers.append(PlanValidationIssue(
                code="camera_out_of_bounds",
                message="Canon camera footprint extends beyond the room boundary",
                item_ids=[],
            ))
        else:
            for obstacle in [*plan.items, *_opening_volumes(plan)]:
                if footprints_intersect(camera, obstacle):
                    blockers.append(PlanValidationIssue(
                        code="camera_inside_geometry",
                        message=f"Canon camera intersects {obstacle.name}",
                        item_ids=[] if obstacle.id == "canon_camera" else [obstacle.id],
                    ))
                    break

    advisory.extend(
        PlanValidationIssue(code="normalization", message=message)
        for message in dict.fromkeys(normalization_warnings or [])
    )
    return PlanValidationReport(
        valid=not blockers,
        blockers=blockers,
        warnings=advisory,
        tolerance_warnings=tolerance_warnings,
    )


def _resolve_overlaps_legacy(plan: FloorPlan, warnings: list[str]) -> None:
    """Iteratively nudge overlapping non-fixed items apart within room bounds."""
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    max_iterations = 20

    for _ in range(max_iterations):
        moved = False
        for i, left in enumerate(plan.items):
            for right in plan.items[i + 1:]:
                # Skip if no vertical overlap
                if left.elevation >= right.elevation + right.height - 0.03:
                    continue
                if right.elevation >= left.elevation + left.height - 0.03:
                    continue
                # Check horizontal overlap
                overlap_x = (left.width + right.width) / 2 - abs(left.x - right.x)
                overlap_z = (left.depth + right.depth) / 2 - abs(left.z - right.z)
                if overlap_x <= 0.03 or overlap_z <= 0.03:
                    continue
                # They overlap — nudge the non-fixed item (or the smaller one)
                if left.fixed and right.fixed:
                    continue
                mover = right if (left.fixed or left.width * left.depth >= right.width * right.depth) else left
                # Push along the axis with less overlap (cheaper to resolve)
                if overlap_x < overlap_z:
                    nudge = overlap_x + 0.1
                    direction = 1.0 if mover.x >= (left.x + right.x) / 2 else -1.0
                    mover.x = _clamp(mover.x + direction * nudge, -half_w + mover.width / 2, half_w - mover.width / 2)
                else:
                    nudge = overlap_z + 0.1
                    direction = 1.0 if mover.z >= (left.z + right.z) / 2 else -1.0
                    mover.z = _clamp(mover.z + direction * nudge, -half_d + mover.depth / 2, half_d - mover.depth / 2)
                moved = True
        if not moved:
            break


def _place_camera_clear(plan: FloorPlan, warnings: list[str]) -> None:
    camera_x, camera_z = plan.camera.x, plan.camera.z
    blocked = any(
        abs(camera_x - item.x) < item.width / 2 + 0.25
        and abs(camera_z - item.z) < item.depth / 2 + 0.25
        and item.elevation < 0.3
        for item in plan.items
    )
    if not blocked:
        return
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    candidates = [
        (-half_w + 0.45, -half_d + 0.45),
        (half_w - 0.45, -half_d + 0.45),
        (-half_w + 0.45, half_d - 0.45),
        (half_w - 0.45, half_d - 0.45),
    ]
    def clearance(candidate):
        distances = [
            (candidate[0] - item.x) ** 2 + (candidate[1] - item.z) ** 2
            for item in plan.items if item.elevation < plan.camera.y
        ]
        return min(distances) if distances else 999.0
    plan.camera.x, plan.camera.z = max(candidates, key=clearance)
    plan.camera.target_x = 0.0
    plan.camera.target_y = min(1.2, plan.room.height / 2)
    plan.camera.target_z = 0.0


def _apply_explicit_dimensions(plan: FloorPlan, description: str, warnings: list[str]) -> None:
    text = description.lower().replace("metres", "meters")
    pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s*wide.{0,80}?"
        r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s*deep.{0,80}?"
        r"(\d+(?:\.\d+)?)\s*(?:m|meters?)\s*(?:high|tall)",
        re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return
    width, depth, height = (float(value) for value in match.groups())
    plan.room.width = _clamp(width, 2.5, 30.0)
    plan.room.depth = _clamp(depth, 2.5, 30.0)
    plan.room.height = _clamp(height, 2.1, 8.0)


def _apply_description_layout(plan: FloorPlan, description: str, warnings: list[str]) -> None:
    text = description.lower()
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    counter = next((item for item in plan.items if "counter" in f"{item.id} {item.name}".lower()), None)
    if counter:
        counter.fixed = True
        if re.search(r"counter.{0,180}north wall|north wall.{0,180}counter", text, re.DOTALL):
            counter.rotation_deg = 0.0
            counter.x = 0.0
            counter.z = half_d - counter.depth / 2 - 0.25
        elif re.search(r"counter.{0,180}south wall|south wall.{0,180}counter", text, re.DOTALL):
            counter.rotation_deg = 0.0
            counter.x = 0.0
            counter.z = -half_d + counter.depth / 2 + 0.25
    for opening in plan.openings:
        if opening.kind == "door":
            if "door on the west wall" in text or "west-wall" in text:
                opening.wall = "west"
            if "northwest corner" in text and opening.wall in {"west", "east"}:
                opening.offset = half_d - opening.width / 2 - 0.2
            elif "southwest corner" in text and opening.wall in {"west", "east"}:
                opening.offset = -half_d + opening.width / 2 + 0.2
        elif opening.kind == "window":
            centered_south = bool(
                re.search(r"center(?:ed)?\s+(?:one\s+)?(?:large\s+)?(?:storefront\s+)?window\s+on\s+the\s+south\s+wall", text)
                or re.search(r"(?:storefront\s+)?window.{0,60}center(?:ed)?.{0,40}south\s+wall", text)
                or "south-wall storefront window" in text
            )
            if centered_south:
                opening.wall = "south"
                opening.offset = 0.0
                if "large" in text and "storefront window" in text:
                    opening.width = min(max(opening.width, plan.room.width * 0.6), plan.room.width - 0.4)
    corners = {
        "southeast corner": (half_w - 0.45, -half_d + 0.45),
        "southwest corner": (-half_w + 0.45, -half_d + 0.45),
        "northeast corner": (half_w - 0.45, half_d - 0.45),
        "northwest corner": (-half_w + 0.45, half_d - 0.45),
    }
    for phrase, (x, z) in corners.items():
        if f"camera at normal eye height in the {phrase}" in text or f"camera in the {phrase}" in text:
            plan.camera.x, plan.camera.z = x, z
            plan.camera.y = 1.6
            plan.camera.target_x = counter.x if counter else 0.0
            plan.camera.target_y = min(1.2, plan.room.height / 2)
            plan.camera.target_z = counter.z if counter else 0.0
            break
