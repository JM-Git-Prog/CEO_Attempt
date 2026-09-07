"""place_in_world.py — the bridge from a session into the world John walks in.

Written 2026-09-06 (dispatcher run for work order job-20260906-mtq2bfdt7son):
the module had been written on 2026-09-02 and never run. These pin the three
laws in its docstring against ONE REAL PLACEMENT — the four workshop props from
the warehouse shelf onto the Yard pad (app/src/modules/scene/Yard.tsx:
YARD_X=-22, YARD_Z=17, 6 x 4 m) in a copy of worlds/my-office/scene.json as it
stood that day — plus the fail-closed rule that was missing.

Run from CEO_Attempt:  python -m pytest tests/test_place_in_world.py
                  or:  python tests/test_place_in_world.py   (no pytest needed)
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `src.` imports when run directly
from src.unified_pipeline import place_in_world as piw  # noqa: E402

# worlds/my-office/scene.json as read 2026-09-06 (3 interrogation + 4 yard)
_SCENE = {
    "version": 1,
    "instances": [
        {"instanceId": "interrogation-table-0", "objectId": "interrogation-table-0",
         "assetId": "warehouse/workbench/0", "room": "interrogation", "physics": "static",
         "position": [-14, 0, 21], "rotation": [0, 1.5707963267948966, 0], "scale": [7.3, 7.3, 7.3]},
        {"instanceId": "interrogation-chair-suspect", "objectId": "interrogation-chair-suspect",
         "assetId": "warehouse/visitor-chair/0", "room": "interrogation", "physics": "static",
         "position": [-14, 0, 22], "rotation": [0, 3.141592653589793, 0], "scale": [1.38, 1.38, 1.38]},
        {"instanceId": "interrogation-chair-detective", "objectId": "interrogation-chair-detective",
         "assetId": "warehouse/visitor-chair/0", "room": "interrogation", "physics": "static",
         "position": [-14, 0, 20], "rotation": [0, 0, 0], "scale": [1.38, 1.38, 1.38]},
        {"instanceId": "yard-steel-interrogation-table", "objectId": "yard-steel-interrogation-table",
         "assetId": "warehouse/steel-interrogation-table/0", "room": "yard", "physics": "static",
         "position": [-23.6, 0, 17], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
    ],
    "metricScaleFactor": 1,
    "groundPlaneOffset": 0,
}

# the four workshop props — real shelf ids (worlds/warehouse/output/<slug>/0-*.glb)
_PROPS = [
    {"name": "Steel interrogation table", "asset_id": "warehouse/steel-interrogation-table/0"},
    {"name": "Metal interrogation chair", "asset_id": "warehouse/metal-interrogation-chair/0"},
    {"name": "Caged ceiling light", "asset_id": "warehouse/caged-ceiling-light/0"},
    {"name": "One-way mirror", "asset_id": "warehouse/one-way-mirror/0"},
]
_YARD_CENTRE, _YARD_SIZE = (-22, 0, 17), (6, 4)
_PAD_X, _PAD_Z = (-25, -19), (15, 19)

# mirror of app/vite.config.ts sanitizePlacementProject (lines 506-548): what the viewer keeps
_ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$", re.I)


def _vec3(v) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(
        isinstance(p, (int, float)) and math.isfinite(p) for p in v)


def _viewer_accepts(inst: dict) -> bool:
    return (isinstance(inst.get("instanceId"), str) and isinstance(inst.get("objectId"), str)
            and isinstance(inst.get("assetId"), str)
            and inst.get("physics") in ("rigidbody", "static", "ghost")
            and _vec3(inst.get("position")) and _vec3(inst.get("rotation")) and _vec3(inst.get("scale"))
            and bool(_ROOM_RE.match(inst.get("room", ""))))


def _seed(root: Path) -> Path:
    world = root / "my-office"
    world.mkdir(parents=True)
    path = world / "scene.json"
    path.write_text(json.dumps(_SCENE, indent=2), encoding="utf-8")
    os.environ["WORLDS_DIR"] = str(root)
    return path


def test_real_placement_merges_never_clobbers(tmp_path: Path) -> None:
    path = _seed(tmp_path)
    before = json.loads(path.read_text(encoding="utf-8"))
    interrogation_before = [i for i in before["instances"] if i["room"] == "interrogation"]

    inst = piw.arrange(_PROPS, "yard", _YARD_CENTRE, room_size=_YARD_SIZE)
    result = piw.place(inst, "yard", "my-office")
    assert result == {"ok": True, "scene": str(path), "room": "yard",
                      "placed": 4, "replaced": 1, "untouched": 3}

    after = json.loads(path.read_text(encoding="utf-8"))
    # room-scoped: the interrogation room is byte-for-byte what it was
    assert [i for i in after["instances"] if i["room"] == "interrogation"] == interrogation_before
    # the yard is exactly the new four
    assert [i for i in after["instances"] if i["room"] == "yard"] == inst
    # top-level scene fields survive the merge
    assert (after["version"], after["metricScaleFactor"], after["groundPlaneOffset"]) == (1, 1, 0)
    # atomic: no temp file left beside the scene
    assert not path.with_suffix(".json.tmp").exists()
    # the viewer would keep every instance
    assert all(_viewer_accepts(i) for i in after["instances"])
    # every prop stands on the Yard pad
    for i in inst:
        x, _, z = i["position"]
        assert _PAD_X[0] <= x <= _PAD_X[1] and _PAD_Z[0] <= z <= _PAD_Z[1], i["instanceId"]
    # a second identical run replaces the four and leaves the three
    assert piw.place(inst, "yard", "my-office")["replaced"] == 4


def test_absent_scene_is_created_but_corrupt_scene_is_refused(tmp_path: Path) -> None:
    path = _seed(tmp_path)
    inst = piw.arrange(_PROPS, "yard", _YARD_CENTRE, room_size=_YARD_SIZE)

    # absent: a first placement may create the file
    path.unlink()
    assert piw.place(inst, "yard", "my-office")["ok"] is True
    assert len(json.loads(path.read_text(encoding="utf-8"))["instances"]) == 4

    # corrupt (half-written by another writer): refuse, and leave the bytes alone
    path.write_text("{ half written", encoding="utf-8")
    result = piw.place(inst, "yard", "my-office")
    assert result["ok"] is False and "refusing" in result["error"]
    assert path.read_text(encoding="utf-8") == "{ half written"

    # parses but is not a scene (no instances list): same refusal
    path.write_text(json.dumps({"version": 1}), encoding="utf-8")
    assert piw.place(inst, "yard", "my-office")["ok"] is False
    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}

    # no such world folder: an error, never a new folder
    assert piw.place(inst, "yard", "no-such-world")["ok"] is False
    assert not (tmp_path / "no-such-world").exists()


if __name__ == "__main__":  # plain-python fallback (the sandbox has no pytest)
    for test in (test_real_placement_merges_never_clobbers,
                 test_absent_scene_is_created_but_corrupt_scene_is_refused):
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print("PASS", test.__name__)
