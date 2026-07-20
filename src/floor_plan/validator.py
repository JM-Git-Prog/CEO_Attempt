"""Deterministic bounds and circulation checks for model-authored plans."""

from __future__ import annotations

import math
import re

from src.floor_plan.models import FloorPlan


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_id(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    return clean or fallback


def normalize_floor_plan(source: FloorPlan, description: str = "") -> tuple[FloorPlan, list[str]]:
    """Return a safe copy and honor explicit metric/spatial user constraints."""
    plan = source.model_copy(deep=True)
    warnings: list[str] = []
    _apply_explicit_dimensions(plan, description, warnings)
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    opening_ids = {opening.id.lower() for opening in plan.openings}
    surfaces = {"floor", "flooring", "wall", "walls", "ceiling", "door", "doors", "window", "windows"}
    kept = []
    for item in plan.items:
        words = set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower()))
        if item.id.lower() in opening_ids or words & surfaces:
            continue
        else:
            kept.append(item)
    plan.items = kept
    plan.items = _expand_grouped_items(plan.items, warnings)
    seen: set[str] = set()
    for index, item in enumerate(plan.items):
        item.id = _safe_id(item.id, f"item_{index + 1}")
        if item.id in seen:
            item.id = f"{item.id}_{index + 1}"
        seen.add(item.id)
        item.width = min(item.width, plan.room.width)
        item.depth = min(item.depth, plan.room.depth)
        old = (item.x, item.z)
        item.x = _clamp(item.x, -half_w + item.width / 2, half_w - item.width / 2)
        item.z = _clamp(item.z, -half_d + item.depth / 2, half_d - item.depth / 2)
        item.rotation_deg %= 360
        words = set(re.findall(r"[a-z]+", f"{item.id} {item.name}".lower()))
        ceiling_fixture = bool(words & {"pendant", "chandelier", "ceiling", "hanging"})
        item.elevation = max(0.0, plan.room.height - item.height) if ceiling_fixture else 0.0
        if words & {"stool", "stools", "chair", "chairs", "table", "tables", "ottoman"}:
            item.fixed = False
        if old != (item.x, item.z):
            pass
    for index, opening in enumerate(plan.openings):
        opening.id = _safe_id(opening.id, f"opening_{index + 1}")
        wall_length = plan.room.width if opening.wall in {"north", "south"} else plan.room.depth
        opening.width = min(opening.width, wall_length - 0.2)
        opening.offset = _clamp(opening.offset, -wall_length / 2 + opening.width / 2, wall_length / 2 - opening.width / 2)
        if opening.kind == "door":
            opening.sill_height = 0.0
        else:
            opening.sill_height = _clamp(opening.sill_height, 0.0, plan.room.height - 0.2)
            opening.height = min(opening.height, plan.room.height - opening.sill_height)
    _apply_description_layout(plan, description, warnings)
    _distribute_repeated_items(plan, warnings)
    plan.camera.x = _clamp(plan.camera.x, -half_w + 0.2, half_w - 0.2)
    plan.camera.z = _clamp(plan.camera.z, -half_d + 0.2, half_d - 0.2)
    plan.camera.y = _clamp(plan.camera.y, 1.2, plan.room.height - 0.2)
    _place_camera_clear(plan, warnings)
    view_length = math.sqrt(
        (plan.camera.target_x - plan.camera.x) ** 2
        + (plan.camera.target_y - plan.camera.y) ** 2
        + (plan.camera.target_z - plan.camera.z) ** 2
    )
    horizontal_view = math.hypot(plan.camera.target_x - plan.camera.x, plan.camera.target_z - plan.camera.z)
    if view_length < 0.5 or horizontal_view < 1.0:
        plan.camera.target_x = 0.0
        plan.camera.target_y = min(1.2, plan.room.height / 2)
        plan.camera.target_z = 0.0
    warnings.extend(_overlap_warnings(plan))
    return plan, warnings


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
            if "window centered on the south wall" in text or "south-wall storefront window" in text:
                opening.wall = "south"
                opening.offset = 0.0
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
