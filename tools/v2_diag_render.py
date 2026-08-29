"""Diagnose why objects don't appear in the depth render."""
import json
import numpy as np
import trimesh
from pathlib import Path

sess = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb/artifacts")
scene_data = json.loads((sess / "scene.json").read_text())
meshes_dir = sess / "meshes"

cam = scene_data["camera"]
cam_pos = np.array([cam["position"]["x"], cam["position"]["y"], cam["position"]["z"]])
cam_tgt = np.array([cam["target"]["x"], cam["target"]["y"], cam["target"]["z"]])
print(f"Camera: {cam_pos} -> {cam_tgt}")
print()

for obj in scene_data["objects"][:10]:
    glb = meshes_dir / f"{obj['uuid']}.glb"
    if not glb.exists():
        print(f"  {obj['name']:20s} NO MESH FILE")
        continue
    loaded = trimesh.load(str(glb), force="scene", process=False)
    # Combined bounds
    all_v = []
    for g in loaded.geometry.values():
        if hasattr(g, "vertices"):
            all_v.append(np.array(g.vertices))
    if not all_v:
        print(f"  {obj['name']:20s} NO VERTICES")
        continue
    verts = np.vstack(all_v)
    native_size = verts.max(axis=0) - verts.min(axis=0)
    scale = obj.get("scale", {})
    sx, sy, sz = scale.get("x", 1), scale.get("y", 1), scale.get("z", 1)
    scaled_size = native_size * np.array([sx, sy, sz])
    pos = obj["position"]
    print(f"  {obj['name'][:20]:20s} native={native_size.round(2)} scale=({sx},{sy},{sz}) -> world_size={scaled_size.round(2)} pos=({pos['x']:.1f},{pos['y']:.1f},{pos['z']:.1f})")
