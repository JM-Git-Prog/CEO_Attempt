"""Re-place an existing session's objects via depth back-projection and rewrite
scene.json IN PLACE — reusing the GLBs already on disk (no GPU, no mesh regen).

Lets us validate the new depth_placement geometry in the browser without a full
Phase 4-5 rerun. Matches catalog entries to scene objects by uuid.

Usage: python tools/v2_replace_scene_positions.py <session_id>
"""
from __future__ import annotations
import json, sys
from pathlib import Path

from src.unified_pipeline.depth_placement import place_objects


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/v2_replace_scene_positions.py <session_id>")
        return 2
    sid = sys.argv[1]
    art = Path("output") / sid / "artifacts"
    scene_path = art / "scene.json"
    for p in (scene_path, art / "catalog.json", art / "capture_manifest.json"):
        if not p.is_file():
            print(f"missing: {p}")
            return 1

    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    catalog = json.loads((art / "catalog.json").read_text(encoding="utf-8"))
    manifest = json.loads((art / "capture_manifest.json").read_text(encoding="utf-8"))
    room = scene.get("room_dimensions") or manifest.get("room_dimensions", [5.0, 4.5, 2.7])

    placements = place_objects(catalog["entries"], manifest, room)

    patched = 0
    methods: dict[str, int] = {}
    for obj in scene.get("objects", []):
        p = placements.get(obj.get("uuid"))
        if p is None:
            continue
        obj["position"] = {"x": p.x, "y": p.y, "z": p.z}
        obj["placement_method"] = p.method
        obj["placement_confidence"] = p.confidence
        methods[p.method] = methods.get(p.method, 0) + 1
        patched += 1

    # Backup the original once, then overwrite.
    backup = art / "scene.pre_depth_placement.json"
    if not backup.exists():
        backup.write_text(json.dumps(scene, indent=2), encoding="utf-8")
    scene_path.write_text(json.dumps(scene, indent=2), encoding="utf-8")

    print(f"patched {patched}/{len(scene.get('objects', []))} object positions")
    print(f"methods: {methods}")
    origin = sum(1 for o in scene["objects"]
                 if abs(o["position"]["x"]) < 0.05 and abs(o["position"]["z"]) < 0.05)
    print(f"objects within 5cm of origin: {origin}")
    print(f"scene.json rewritten: {scene_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
