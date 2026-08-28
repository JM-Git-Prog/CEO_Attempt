"""V2 Camera Calibration Loop — find exact camera params that reproduce the Canon's projection.

Uses the catalog bboxes (known pixel positions in Canon) and depth-projected 3D positions
to solve for the camera FOV, position, and orientation that makes the pyrender output
match the Canon's object layout exactly.

Method: render the scene, project known 3D points back to 2D, compare against their
known Canon pixel positions, adjust camera params to minimize the reprojection error.
Iterate until error < threshold.
"""
import json
import math
import numpy as np
from pathlib import Path
from PIL import Image

SESSION = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
ARTIFACTS = SESSION / "artifacts"


def load_reference_points():
    """Load known 2D→3D correspondences from catalog + scene."""
    catalog = json.loads((ARTIFACTS / "catalog.json").read_text())
    scene = json.loads((ARTIFACTS / "scene.json").read_text())
    depth = np.array(Image.open(ARTIFACTS / "depth.png").convert("L")).astype(np.float32)
    
    canon = Image.open(ARTIFACTS / "canon.png")
    img_w, img_h = canon.size
    
    # Build UUID→position map from scene
    pos_map = {}
    for obj in scene["objects"]:
        pos_map[obj["uuid"]] = obj["position"]
    
    # Correspondences: (pixel_x, pixel_y) → (world_x, world_y, world_z)
    points_2d = []
    points_3d = []
    
    for entry in catalog.get("entries", []):
        uuid = entry["uuid"]
        if uuid not in pos_map:
            continue
        bbox = entry.get("bbox_in_best_view", [0, 0, img_w, img_h])
        # 2D: centroid in normalized coords [0,1]
        cx = (bbox[0] + bbox[2]) / 2 / img_w
        cy = (bbox[1] + bbox[3]) / 2 / img_h
        # 3D: position from scene
        p = pos_map[uuid]
        points_2d.append((cx, cy))
        points_3d.append((p["x"], p["y"], p["z"]))
    
    return points_2d, points_3d, img_w, img_h


def project_point(point_3d, cam_pos, cam_target, fov_deg, aspect):
    """Project a 3D point to normalized 2D screen coords [0,1] using pinhole model."""
    eye = np.array(cam_pos)
    target = np.array(cam_target)
    point = np.array(point_3d)
    
    # Camera basis vectors
    forward = target - eye
    forward = forward / (np.linalg.norm(forward) + 1e-8)
    up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, up)
    right = right / (np.linalg.norm(right) + 1e-8)
    cam_up = np.cross(right, forward)
    
    # Point in camera space
    p_local = point - eye
    x = np.dot(p_local, right)
    y = np.dot(p_local, cam_up)
    z = np.dot(p_local, forward)
    
    if z <= 0:
        return None  # behind camera
    
    # Perspective projection
    fov_rad = math.radians(fov_deg)
    tan_half_fov = math.tan(fov_rad / 2)
    
    # NDC coordinates [-1, 1]
    ndc_x = x / (z * tan_half_fov * aspect)
    ndc_y = y / (z * tan_half_fov)
    
    # To screen [0, 1] (flip Y because screen Y goes down)
    screen_x = (ndc_x + 1) / 2
    screen_y = (1 - ndc_y) / 2
    
    return (screen_x, screen_y)


def compute_reprojection_error(cam_pos, cam_target, fov_deg, points_2d, points_3d, aspect):
    """Mean reprojection error in normalized screen coords."""
    errors = []
    for p2d, p3d in zip(points_2d, points_3d):
        projected = project_point(p3d, cam_pos, cam_target, fov_deg, aspect)
        if projected is None:
            errors.append(1.0)  # penalty for behind-camera points
        else:
            dx = projected[0] - p2d[0]
            dy = projected[1] - p2d[1]
            errors.append(math.sqrt(dx*dx + dy*dy))
    return np.mean(errors) if errors else 1.0


def calibrate():
    """Iteratively adjust camera params to minimize reprojection error."""
    points_2d, points_3d, img_w, img_h = load_reference_points()
    aspect = img_w / img_h
    
    print(f"Reference points: {len(points_2d)} correspondences")
    print(f"Image: {img_w}x{img_h}, aspect={aspect:.3f}")
    
    # Load current scene for room dims
    scene = json.loads((ARTIFACTS / "scene.json").read_text())
    room_w, room_d, room_h = scene["room_dimensions"]
    
    # Start with current camera
    best_pos = [0.0, 1.5, room_d * 0.48]
    best_target = [0.0, 0.8, -room_d * 0.4]
    best_fov = 70.0
    best_error = compute_reprojection_error(best_pos, best_target, best_fov, points_2d, points_3d, aspect)
    
    print(f"\nInitial: FOV={best_fov:.0f}, pos=({best_pos[0]:.2f}, {best_pos[1]:.2f}, {best_pos[2]:.2f}), error={best_error:.4f}")
    
    # Grid search over FOV and camera Z position
    for fov in range(50, 100, 5):
        for z_frac in [0.3, 0.35, 0.4, 0.45, 0.48, 0.5, 0.55, 0.6]:
            for y_pos in [1.2, 1.4, 1.5, 1.6, 1.8]:
                for target_z_frac in [-0.5, -0.4, -0.3, -0.2, -0.1, 0.0]:
                    pos = [0.0, y_pos, room_d * z_frac]
                    target = [0.0, 0.8, room_d * target_z_frac]
                    error = compute_reprojection_error(pos, target, fov, points_2d, points_3d, aspect)
                    if error < best_error:
                        best_error = error
                        best_pos = pos
                        best_target = target
                        best_fov = fov
    
    print(f"\nBest: FOV={best_fov:.0f}, pos=({best_pos[0]:.2f}, {best_pos[1]:.2f}, {best_pos[2]:.2f})")
    print(f"  target=({best_target[0]:.2f}, {best_target[1]:.2f}, {best_target[2]:.2f})")
    print(f"  reprojection error={best_error:.4f}")
    
    # Apply to scene.json
    scene["camera"] = {
        "position": {"x": best_pos[0], "y": best_pos[1], "z": best_pos[2]},
        "target": {"x": best_target[0], "y": best_target[1], "z": best_target[2]},
        "fov": best_fov,
        "near": 0.05,
        "far": 100.0,
    }
    scene["navigation"]["spawn_position"] = {
        "x": best_pos[0], "y": best_pos[1], "z": best_pos[2]
    }
    
    (ARTIFACTS / "scene.json").write_text(json.dumps(scene, indent=2))
    print(f"\nCamera calibrated and saved.")
    print(f"Refresh: http://127.0.0.1:8000/?v=2.0&session={SESSION.name}")


if __name__ == "__main__":
    calibrate()
