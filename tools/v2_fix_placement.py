"""V2 Refine Loop — Fix #1: Object Placement from Canon bounding boxes.

Reads the catalog (with 2D bounding boxes from vision detection) and the
Canon image dimensions. Projects bbox centroids into 3D room coordinates
using a simple perspective-to-floor-plane mapping. Rebuilds scene.json
with corrected positions.
"""
import json
import math
from pathlib import Path

SESSION = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
ARTIFACTS = SESSION / "artifacts"


def main():
    catalog = json.loads((ARTIFACTS / "catalog.json").read_text())
    scene = json.loads((ARTIFACTS / "scene.json").read_text())
    
    room_w, room_d, room_h = scene["room_dimensions"]
    entries = catalog.get("entries", [])
    
    print(f"Room: {room_w}x{room_d}x{room_h}m")
    print(f"Objects: {len(entries)}")
    
    # Get Canon image dimensions from the first entry's best view
    # The bboxes are in pixel coordinates of the Canon (typically 1024x1024 or similar)
    # We'll normalize to [0,1] then map to room coordinates
    
    # Find the max bbox coords to infer image size
    max_x = max((e.get("bbox_in_best_view", [0,0,0,0])[2] for e in entries), default=1024)
    max_y = max((e.get("bbox_in_best_view", [0,0,0,0])[3] for e in entries), default=1024)
    img_w = max(max_x, 1024)  # assume at least 1024
    img_h = max(max_y, 1024)
    
    print(f"Inferred image size: {img_w}x{img_h}")
    print()
    
    # Map each object's bbox centroid to room position
    # Strategy: 
    #   - X in image → X in room (left-right)
    #   - Y in image → Z in room (objects higher in image are further away)
    #   - Object size category → Y elevation
    
    elevation_map = {
        "large": 0.0,      # on the floor
        "medium": 0.0,     # on the floor
        "small": 0.7,      # on a surface
        "tiny": 0.85,      # on a surface/shelf
    }
    
    # Special categories that float
    hanging_keywords = ["chandelier", "pendant", "light", "lamp", "mirror"]
    floor_keywords = ["rug", "carpet", "mat", "ottoman", "pouf", "sofa", "chair", "sideboard", "cabinet", "dresser"]
    
    updated_objects = []
    
    for i, entry in enumerate(entries):
        bbox = entry.get("bbox_in_best_view", [0, 0, img_w, img_h])
        x1, y1, x2, y2 = bbox
        
        # Centroid in normalized coords [0, 1]
        cx = (x1 + x2) / 2 / img_w
        cy = (y1 + y2) / 2 / img_h
        
        # Map to room coordinates
        # X: image left→right = room -w/2 → +w/2
        room_x = (cx - 0.5) * room_w * 0.8  # 80% of room width to keep off walls
        
        # Z: image top→bottom = room far→near (perspective: top of image = far wall)
        room_z = (cy - 0.5) * room_d * 0.8  # top=far(-Z), bottom=near(+Z)
        
        # Y elevation based on type
        name_lower = entry.get("name", "").lower()
        size = entry.get("size_estimate", "medium")
        
        if any(kw in name_lower for kw in hanging_keywords):
            room_y = room_h * 0.75  # hanging from ceiling area
        elif any(kw in name_lower for kw in floor_keywords):
            room_y = 0.0  # on the floor
        else:
            room_y = elevation_map.get(size, 0.0)
        
        # Find matching object in scene.json
        scene_obj = None
        for obj in scene["objects"]:
            if obj["uuid"] == entry["uuid"]:
                scene_obj = obj
                break
        
        if scene_obj:
            scene_obj["position"] = {
                "x": round(room_x, 3),
                "y": round(room_y, 3),
                "z": round(room_z, 3),
            }
            print(f"  {entry['name'][:30]:30s} → ({room_x:.2f}, {room_y:.2f}, {room_z:.2f})")
    
    # Adjust camera to see the room from a good vantage
    scene["camera"]["position"] = {"x": 0.0, "y": 1.62, "z": room_d * 0.4}
    scene["camera"]["target"] = {"x": 0.0, "y": 1.0, "z": -room_d * 0.2}
    scene["navigation"]["spawn_position"] = {"x": 0.0, "y": 1.62, "z": room_d * 0.4}
    
    # Boost lighting
    scene["lighting"][0]["intensity"] = 0.7  # ambient
    
    # Write updated scene
    (ARTIFACTS / "scene.json").write_text(json.dumps(scene, indent=2))
    print(f"\nScene updated with bbox-derived placements.")
    print(f"URL: http://127.0.0.1:8000/?v=2.0&session={SESSION.name}")


if __name__ == "__main__":
    main()
