from __future__ import annotations

import json
from pathlib import Path

from src.floor_plan.geometry import footprints_intersect, inside_room
from src.floor_plan.models import FloorPlan
from src.floor_plan.validator import normalize_floor_plan


FIXTURE = Path(__file__).parent / "fixtures" / "attic_overlap_8cad78b6.json"
DESCRIPTION = (
    "A cozy attic study with sloped wooden ceilings, a small round window facing east, "
    "oak floorboards, a leather armchair, brass reading lamp, and shelves of old books "
    "lining the low walls."
)


def load_attic() -> FloorPlan:
    return FloorPlan.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))


def plan_with(items: list[dict], openings: list[dict] | None = None) -> FloorPlan:
    return FloorPlan.model_validate({
        "name": "Validation room",
        "room": {"width": 6.0, "depth": 5.0, "height": 3.0},
        "items": items,
        "openings": openings or [],
        "camera": {
            "x": 2.4, "y": 1.6, "z": -1.9,
            "target_x": 0.0, "target_y": 1.1, "target_z": 0.0,
        },
    })


def item(item_id: str, x: float, z: float, **updates) -> dict:
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


def test_reported_attic_session_is_preserved_repaired_and_reports_mixed_mount_clip():
    first, warnings, report = normalize_floor_plan(load_attic(), DESCRIPTION, strict=True)
    second, second_warnings, second_report = normalize_floor_plan(load_attic(), DESCRIPTION, strict=True)

    assert first.model_dump() == second.model_dump()
    assert warnings == second_warnings
    assert report.model_dump() == second_report.model_dump()
    assert {entry.id for entry in first.items} == {"stool_1", "lamp_1", "shelf_1", "beam_1"}
    assert next(entry for entry in first.items if entry.id == "beam_1").mount == "ceiling"
    assert next(entry for entry in first.items if entry.id == "shelf_1").mount == "floor"

    mixed_mount = next(
        issue for issue in report.warnings
        if set(issue.item_ids) == {"shelf_1", "beam_1"}
    )
    assert mixed_mount.code == "mixed_mount_clip"
    assert mixed_mount.details["mounts"] == ["floor", "ceiling"]
    assert all("stool_1" not in issue.item_ids for issue in report.blockers)
    assert report.valid is True


def test_ceiling_words_do_not_drop_floor_standing_or_architectural_items():
    source = plan_with([
        item(
            "room_ceiling", 0.0, 0.0,
            name="Sloped Wooden Ceiling", category="architectural", fixed=True,
        ),
        item(
            "beam_1", -1.8, 0.0,
            name="Exposed Ceiling Beam", category="architectural", fixed=True,
            width=0.3, depth=3.0, height=0.2,
        ),
        item(
            "bookcase_1", 1.8, 0.0,
            name="Floor-to-ceiling Bookcase", fixed=True,
            width=0.5, depth=1.2, height=2.7,
        ),
    ])

    plan, _, _ = normalize_floor_plan(source, strict=True)
    by_id = {entry.id: entry for entry in plan.items}
    assert "room_ceiling" not in by_id
    assert by_id["beam_1"].mount == "ceiling"
    assert by_id["beam_1"].elevation == 2.8
    assert by_id["bookcase_1"].mount == "floor"
    assert by_id["bookcase_1"].elevation == 0.0


def test_rotation_aware_bounds_and_whole_room_search_resolve_movable_items():
    source = plan_with([
        item("fixed_table", 0.0, 0.0, fixed=True, width=2.0, depth=1.0, rotation_deg=35.0),
        item("chair_1", 0.0, 0.0, width=1.1, depth=0.8, rotation_deg=47.0),
        item("chair_2", 0.0, 0.0, width=1.1, depth=0.8, rotation_deg=137.0),
        item("chair_3", 2.8, 2.3, width=1.1, depth=0.8, rotation_deg=47.0),
    ])

    plan, _, report = normalize_floor_plan(
        source, strict=True, infer_text_placement=False
    )
    assert report.valid
    assert all(inside_room(entry, plan.room.width, plan.room.depth) for entry in plan.items)
    for index, first in enumerate(plan.items):
        for second in plan.items[index + 1:]:
            assert not footprints_intersect(
                first,
                second,
                left_padding=first.clearance_m / 2,
                right_padding=second.clearance_m / 2,
            ), f"resolved items overlap: {first.id}, {second.id}"
