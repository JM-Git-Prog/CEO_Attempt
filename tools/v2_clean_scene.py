"""Clean the polluted scene.json — keep only objects with real meshes at valid positions."""
import json
import os
from pathlib import Path

sess = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb/artifacts")
scene = json.loads((sess / "scene.json").read_text())

# Meshes that actually exist on disk
mesh_files = set(f[:-4] for f in os.listdir(sess / "meshes") if f.endswith(".glb"))

room_w, room_d, room_h = scene["room_dimensions"]

# Load catalog for the canonical 21 objects
catalog = json.loads((sess / "catalog.json").read_text())
catalog_uuids = {e["uuid"] for e in catalog.get("entries", [])}

kept = []
seen = set()
for obj in scene["objects"]:
    uuid = obj["uuid"]
    # Only keep original catalog objects (not runaway gen- objects)
    if uuid not in catalog_uuids:
        continue
    if uuid in seen:
        continue
    # Mesh must exist
    if uuid not in mesh_files:
        continue
    seen.add(uuid)
    kept.append(obj)

print(f"Before: {len(scene['objects'])} objects")
print(f"After: {len(kept)} objects (catalog-only, mesh exists, deduped)")

scene["objects"] = kept

# Reset room to a reasonable size and camera to see the whole room
scene["room_dimensions"] = [5.0, 6.0, 3.0]
scene["camera"] = {
    "position": {"x": 0.0, "y": 1.5, "z": 2.6},
    "target": {"x": 0.0, "y": 1.0, "z": -2.0},
    "fov": 70,
    "near": 0.05,
    "far": 100.0,
}
scene["navigation"]["spawn_position"] = {"x": 0.0, "y": 1.5, "z": 2.6}

(sess / "scene.json").write_text(json.dumps(scene, indent=2))
print("Scene cleaned. Room 5x6x3, camera at z=2.6 FOV=70.")

# Report object positions
for o in kept:
    p = o["position"]
    print(f"  {o['name'][:25]:25s} ({p['x']:+.1f}, {p['y']:.1f}, {p['z']:+.1f})")
