"""V2 Task 2 — Texture meshes from the injected Canon at KNOWN positions.

Since the Canon was generated conditioned on our geometry, each object's 3D
position projects to a known 2D screen region in the Canon. We:
1. Project each object's 3D bounding box into the Canon's 2D screen space
2. Sample the dominant color from that region
3. Apply it to the mesh material (baseColorFactor)

This is accurate because positions are ground truth, not recovered — the Canon
was authored to match them.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SESSION_ID = "8df83612-1b81-4428-b711-7fbabc9536bb"
SESSION = Path(f"output/{SESSION_ID}")
ARTIFACTS = SESSION / "artifacts"


def project_point(point_3d, cam_pos, cam_target, fov_deg, aspect):
    """Project a 3D point to normalized screen coords [0,1]. Returns (sx, sy) or None if behind."""
    eye = np.array(cam_pos)
    target = np.array(cam_target)
    point = np.array(point_3d)

    forward = target - eye
    forward = forward / (np.linalg.norm(forward) + 1e-8)
    up = np.array([0.0, 1.0, 0.0])
    right = np.cross(forward, up)
    right = right / (np.linalg.norm(right) + 1e-8)
    cam_up = np.cross(right, forward)

    p_local = point - eye
    x = np.dot(p_local, right)
    y = np.dot(p_local, cam_up)
    z = np.dot(p_local, forward)

    if z <= 0.01:
        return None

    fov_rad = math.radians(fov_deg)
    tan_half = math.tan(fov_rad / 2)

    ndc_x = x / (z * tan_half * aspect)
    ndc_y = y / (z * tan_half)

    sx = (ndc_x + 1) / 2
    sy = (1 - ndc_y) / 2
    return (sx, sy)


def get_object_screen_bbox(obj, cam_pos, cam_target, fov, aspect, meshes_dir):
    """Project an object's 3D bounding box corners to 2D and return the screen bbox."""
    glb = meshes_dir / f"{obj['uuid']}.glb"
    if not glb.exists():
        return None

    try:
        loaded = trimesh.load(str(glb), force="scene", process=False)
    except Exception:
        return None

    # Get native bounds
    all_v = []
    for g in loaded.geometry.values():
        if hasattr(g, "vertices"):
            all_v.append(np.array(g.vertices))
    if not all_v:
        return None
    verts = np.vstack(all_v)
    vmin = verts.min(axis=0)
    vmax = verts.max(axis=0)

    scale = obj.get("scale", {})
    sx = scale.get("x", 1)
    sy = scale.get("y", 1)
    sz = scale.get("z", 1)
    pos = obj.get("position", {})
    px, py, pz = pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)

    # 8 corners of the scaled+translated bbox
    corners = []
    for cx in (vmin[0], vmax[0]):
        for cy in (vmin[1], vmax[1]):
            for cz in (vmin[2], vmax[2]):
                corners.append([cx * sx + px, cy * sy + py, cz * sz + pz])

    # Project all corners
    screen_pts = []
    for c in corners:
        p = project_point(c, cam_pos, cam_target, fov, aspect)
        if p is not None:
            screen_pts.append(p)

    if len(screen_pts) < 2:
        return None

    xs = [p[0] for p in screen_pts]
    ys = [p[1] for p in screen_pts]
    return (min(xs), min(ys), max(xs), max(ys))


def sample_region_color(canon_img, screen_bbox):
    """Sample the dominant (median non-dark) color from a screen bbox region."""
    w, h = canon_img.size
    # Clamp screen bbox to [0,1] first (huge flat planes can project far off-frame)
    sb = [max(0.0, min(1.0, v)) for v in screen_bbox]
    x1 = max(0, min(int(sb[0] * w), w - 1))
    y1 = max(0, min(int(sb[1] * h), h - 1))
    x2 = max(x1 + 1, min(int(sb[2] * w), w))
    y2 = max(y1 + 1, min(int(sb[3] * h), h))

    region = np.array(canon_img.crop((x1, y1, x2, y2)))
    if region.size == 0:
        return (128, 128, 128)

    pixels = region.reshape(-1, region.shape[-1])[:, :3]
    # Ignore very dark pixels (shadows) and very bright (blown highlights)
    brightness = pixels.mean(axis=1)
    mask = (brightness > 25) & (brightness < 245)
    if mask.sum() > 0:
        med = np.median(pixels[mask], axis=0).astype(int)
    else:
        med = np.median(pixels, axis=0).astype(int)
    return (int(med[0]), int(med[1]), int(med[2]))


def apply_color_to_mesh(glb_path, rgb):
    """Set the mesh's material baseColorFactor / face colors to rgb."""
    try:
        scene = trimesh.load(str(glb_path), force="scene", process=False)
        r, g, b = rgb
        modified = False
        for geom in scene.geometry.values():
            if not hasattr(geom, "visual"):
                continue
            v = geom.visual
            if v.kind == "texture" and hasattr(v, "material"):
                v.material.baseColorFactor = np.array([r, g, b, 255], dtype=np.uint8)
                modified = True
            elif v.kind == "vertex":
                geom.visual.vertex_colors = np.full((len(geom.vertices), 4), [r, g, b, 255], dtype=np.uint8)
                modified = True
            elif v.kind == "face":
                geom.visual.face_colors = np.full((len(geom.faces), 4), [r, g, b, 255], dtype=np.uint8)
                modified = True
            else:
                geom.visual = trimesh.visual.ColorVisuals(
                    mesh=geom,
                    face_colors=np.full((len(geom.faces), 4), [r, g, b, 255], dtype=np.uint8),
                )
                modified = True
        if modified:
            scene.export(str(glb_path), file_type="glb")
            return True
    except Exception as e:
        print(f"    apply failed: {e}")
    return False


def main():
    print("=" * 60)
    print("  TEXTURE MESHES FROM INJECTED CANON (known positions)")
    print("=" * 60)

    scene = json.loads((ARTIFACTS / "scene.json").read_text())
    meshes_dir = ARTIFACTS / "meshes"

    # Prefer the injected Canon (generated to match geometry), fall back to original
    canon_path = ARTIFACTS / "canon_injected.png"
    if not canon_path.exists():
        canon_path = ARTIFACTS / "canon.png"
    canon_img = Image.open(canon_path).convert("RGB")
    img_w, img_h = canon_img.size
    aspect = img_w / img_h
    print(f"Canon: {canon_path.name} ({img_w}x{img_h})")

    cam = scene["camera"]
    cam_pos = [cam["position"]["x"], cam["position"]["y"], cam["position"]["z"]]
    cam_target = [cam["target"]["x"], cam["target"]["y"], cam["target"]["z"]]
    fov = cam.get("fov", 70)

    print(f"Camera: {cam_pos} -> {cam_target}, FOV={fov}\n")

    textured = 0
    for obj in scene["objects"]:
        glb = meshes_dir / f"{obj['uuid']}.glb"
        if not glb.exists():
            continue

        screen_bbox = get_object_screen_bbox(obj, cam_pos, cam_target, fov, aspect, meshes_dir)
        if screen_bbox is None:
            print(f"  {obj['name'][:22]:22s} not visible in Canon — skip")
            continue

        rgb = sample_region_color(canon_img, screen_bbox)
        if apply_color_to_mesh(glb, rgb):
            textured += 1
            print(f"  {obj['name'][:22]:22s} screen=({screen_bbox[0]:.2f},{screen_bbox[1]:.2f}) -> RGB{rgb}")

    print(f"\nTextured {textured} meshes from the injected Canon.")
    print(f"Refresh: http://127.0.0.1:8000/?v=2.0&session={SESSION_ID}")


if __name__ == "__main__":
    main()
