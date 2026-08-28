"""Fix Compare camera to match the Canon photographer's viewpoint exactly."""
import json
from pathlib import Path

scene_path = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb/artifacts/scene.json")
scene = json.loads(scene_path.read_text())

room_w, room_d, room_h = scene["room_dimensions"]

# The Canon photographer stood at the near end of the room.
# The depth projection placed objects relative to this camera.
# Camera MUST match the projection origin or objects appear shifted.
cam_z = room_d * 0.45  # near the south wall

scene["camera"] = {
    "position": {"x": 0.0, "y": 1.5, "z": cam_z},
    "target": {"x": 0.0, "y": 0.8, "z": -room_d * 0.3},
    "fov": 60,
    "near": 0.05,
    "far": 100.0,
}
scene["navigation"]["spawn_position"] = {"x": 0.0, "y": 1.5, "z": cam_z}

# Check visibility
print(f"Camera at (0, 1.5, {cam_z:.1f}) looking at (0, 0.8, {-room_d*0.3:.1f})")
visible = sum(1 for o in scene["objects"] if o["position"]["z"] < cam_z)
print(f"{visible}/{len(scene['objects'])} objects in front of camera")

scene_path.write_text(json.dumps(scene, indent=2))
print("Camera fixed.")
