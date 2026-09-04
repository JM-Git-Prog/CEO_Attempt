"""The bridge: put what John built into the world he walks in.

2026-09-02. Until now a session's props landed in the warehouse and stopped
there. The world at :5173 reads its furniture from `worlds/<slug>/scene.json`,
and nothing had ever written to it from a session — so John could build a room
in V17, walk into the world, and find nothing he had made. `00-Vision-Product`
§6 calls this the compounding loop ("every room you finish makes the next one
faster"); it has been a document, not a program.

This module writes the placements. Three laws it obeys, all learned the hard way:

  * MERGE, NEVER CLOBBER. scene.json is shared state with other writers (the
    world's own editor, `place-garage-objects`). It is re-read from disk on every
    write and only this room's instances are replaced — same rule that exists
    because a parallel session once wiped site-log.json twice from stale memory.
  * ROOM-SCOPED. Every instance carries `room`, so a rebuild of the office can
    never disturb the diner. Rooms became data earlier today for exactly this.
  * ATOMIC. Written to a temp file and replaced, because the world hot-reloads
    scene.json the instant it changes and must never read a half-written file.

It never deletes another room's work, never touches the shell, and never spends.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

_DEFAULT_WORLDS = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"
    r"\CEO-3D-World\worlds"
)


def worlds_root() -> Path:
    raw = os.getenv("WORLDS_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_WORLDS


def scene_path(slug: str = "my-office") -> Path:
    return worlds_root() / slug / "scene.json"


def _read_scene(path: Path) -> dict:
    """Read the live file. A missing or unreadable scene is an empty one, never
    an exception — a broken read must not cost John the rooms already placed."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("instances"), list):
            return doc
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "instances": []}


def arrange(objects, room: str, centre, room_size=(2.4, 3.0)) -> list[dict]:
    """Lay a room's objects out from its centre — deterministic, not clever.

    A real solver belongs to the spatial stage; this exists so a finished prop
    APPEARS somewhere sensible instead of nowhere. The first object sits at the
    centre, the rest ring it just inside the walls, facing in.
    """
    width, depth = room_size
    cx, cz = float(centre[0]), float(centre[2] if len(centre) > 2 else centre[1])
    placed: list[dict] = []
    ring = [item for item in objects][1:]
    radius = max(0.6, min(width, depth) / 2 - 0.45)

    for index, item in enumerate(objects):
        name = str(item.get("name", "")).strip() if isinstance(item, dict) else str(item)
        asset = str(item.get("asset_id", "")) if isinstance(item, dict) else ""
        if not name or not asset:
            continue
        if index == 0:
            x, z, facing = cx, cz, 0.0
        else:
            step = 2 * math.pi * (index - 1) / max(1, len(ring))
            x = cx + radius * math.sin(step)
            z = cz + radius * math.cos(step)
            facing = math.atan2(cx - x, cz - z)  # turn to face the middle
        slug_name = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        placed.append({
            "instanceId": f"{room}-{slug_name}-{index}",
            "objectId": f"{room}-{slug_name}-{index}",
            "assetId": asset,
            "room": room,
            "physics": "static",
            "position": [round(x, 3), 0, round(z, 3)],
            "rotation": [0, round(facing, 6), 0],
            "scale": [1, 1, 1],
        })
    return placed


def place(instances: list[dict], room: str, slug: str = "my-office") -> dict:
    """Replace this room's instances in the world, leaving every other room alone."""
    path = scene_path(slug)
    if not path.parent.is_dir():
        return {"ok": False, "error": f"no world at {path.parent}"}

    scene = _read_scene(path)          # re-read live, never write from memory
    others = [
        item for item in scene["instances"]
        if isinstance(item, dict) and str(item.get("room", "")) != room
    ]
    replaced = len(scene["instances"]) - len(others)
    scene["instances"] = others + list(instances)
    scene.setdefault("version", 1)

    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    temporary.replace(path)            # atomic: the world may reload mid-write

    return {
        "ok": True,
        "scene": str(path),
        "room": room,
        "placed": len(instances),
        "replaced": replaced,
        "untouched": len(others),
    }
