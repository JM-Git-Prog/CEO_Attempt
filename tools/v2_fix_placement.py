"""V2 Refine Loop — Fix Object Placement using depth map back-projection.

Uses the actual MiDaS depth map from the Canon photo to project each object's
bounding box centroid into 3D room coordinates. This gives accurate depth
positioning instead of guessed/flat layout.

Depth convention (MiDaS standard): 0=far, 255=near.
Camera model: pinhole with estimated FOV from the Canon perspective.
"""
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

SESSION = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
ARTIFACTS = SESSION / "artifacts"


def main():
    catalog = json.loads((ARTIFACTS / "catalog.json").read_text())
    scene = json.loads((ARTIFACTS / "scene.json").read_text())
    
    # Load depth map
    depth_img = Image.open(ARTIFACTS / "depth.png").convert("L")
    depth = np.array(depth_img).astype(np.float32)
    img_h, img_w = depth.shape
    
    room_w, room_d, room_h = scene["room_dimensions"]
    entries = catalog.get("entries", [])
    
    print(f"Room: {room_w}x{room_d}x{room_h}m")
    print(f"Depth map: {img_w}x{img_h}, convention: 0=far, 255=near")
    print(f"Objects: {len(entries)}")
    print()
    
    # Camera intrinsics estimate from the Canon photo
    # Assume ~60 degree horizontal FOV (typical for interior photos)
    fov_h_deg = 60.0
    fov_h_rad = math.radians(fov_h_deg)
    focal_length_px = (img_w / 2) / math.tan(fov_h_rad / 2)  # in pixels
    
    # Depth scaling: map [0-255] to metric depth [max_depth - min_depth]
    # 0 = far wall = max depth, 255 = near camera = min depth
    min_depth_m = 0.5   # closest object to camera
    max_depth_m = room_d  # far wall
    
    # Elevation categories
    hanging_keywords = ["chandelier", "pendant", "light", "lamp", "mirror", "frame"]
    floor_keywords = ["rug", "carpet", "mat", "ottoman", "pouf", "sofa", "chair", 
                      "sideboard", "cabinet", "dresser", "table", "bed", "headboard",
                      "pot", "ceramic", "plant"]
    wall_keywords = ["wall", "garden", "window", "arch"]
    
    for entry in entries:
        bbox = entry.get("bbox_in_best_view", [0, 0, img_w, img_h])
        x1, y1, x2, y2 = bbox
        
        # Clamp to image bounds
        x1 = max(0, min(x1, img_w - 1))
        y1 = max(0, min(y1, img_h - 1))
        x2 = max(x1 + 1, min(x2, img_w))
        y2 = max(y1 + 1, min(y2, img_h))
        
        # Centroid in pixel coordinates
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        
        # Sample depth at centroid (use median of patch for robustness)
        patch_r = 15
        px1 = max(0, int(cx) - patch_r)
        py1 = max(0, int(cy) - patch_r)
        px2 = min(img_w, int(cx) + patch_r)
        py2 = min(img_h, int(cy) + patch_r)
        depth_patch = depth[py1:py2, px1:px2]
        depth_val = np.median(depth_patch) if depth_patch.size > 0 else 128
        
        # Convert depth value to metric depth (0=far=max_depth, 255=near=min_depth)
        metric_depth = max_depth_m - (depth_val / 255.0) * (max_depth_m - min_depth_m)
        
        # Back-project centroid to 3D using pinhole model
        # X: pixel offset from center → world X
        room_x = (cx - img_w / 2) / focal_length_px * metric_depth
        
        # Z: depth axis (negative = into the room from camera)
        room_z = -(metric_depth - room_d / 2)  # center the room at z=0
        
        # Y: elevation based on object type
        name_lower = entry.get("name", "").lower()
        
        if any(kw in name_lower for kw in hanging_keywords):
            room_y = room_h * 0.75  # hanging near ceiling
        elif any(kw in name_lower for kw in wall_keywords):
            # Wall-mounted: use vertical position from image
            wall_y = (1.0 - cy / img_h) * room_h  # top of image = high on wall
            room_y = max(0.0, min(room_h, wall_y))
        elif any(kw in name_lower for kw in floor_keywords):
            room_y = 0.0  # sitting on floor
        else:
            # Use image Y position as hint
            if cy < img_h * 0.3:
                room_y = room_h * 0.6  # upper third = elevated
            elif cy < img_h * 0.6:
                room_y = 0.7  # middle = on a surface
            else:
                room_y = 0.0  # lower = on floor
        
        # Clamp X to room bounds
        room_x = max(-room_w / 2 + 0.3, min(room_w / 2 - 0.3, room_x))
        
        # Find matching object in scene.json and update position
        for obj in scene["objects"]:
            if obj["uuid"] == entry["uuid"]:
                obj["position"] = {
                    "x": round(float(room_x), 3),
                    "y": round(float(room_y), 3),
                    "z": round(float(room_z), 3),
                }
                break
        
        print(f"  {entry['name']:30s} depth={depth_val:3.0f} → ({room_x:+5.2f}, {room_y:4.2f}, {room_z:+5.2f})")
    
    # Camera: spawn at the near end of the room, looking forward
    scene["camera"]["position"] = {"x": 0.0, "y": 1.62, "z": room_d * 0.35}
    scene["camera"]["target"] = {"x": 0.0, "y": 1.2, "z": -room_d * 0.3}
    scene["navigation"]["spawn_position"] = {"x": 0.0, "y": 1.62, "z": room_d * 0.35}
    
    # Write updated scene
    (ARTIFACTS / "scene.json").write_text(json.dumps(scene, indent=2))
    print(f"\nScene updated with depth-projected placements.")
    print(f"URL: http://127.0.0.1:8000/?v=2.0&session={SESSION.name}")


if __name__ == "__main__":
    main()
