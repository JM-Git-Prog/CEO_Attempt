"""V2 Refine Loop — Colorize meshes from Canon photo colors.

For each object, samples the average color from its bounding box region
in the Canon photo and applies it as the mesh's baseColorFactor.
This gives approximate color without full texture mapping.
"""
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh


SESSION = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
ARTIFACTS = SESSION / "artifacts"


def get_crop_color(canon_img, bbox):
    """Get average color from the bbox region of the Canon image."""
    x1, y1, x2, y2 = bbox
    # Clamp to image bounds
    x1 = max(0, min(x1, canon_img.width - 1))
    y1 = max(0, min(y1, canon_img.height - 1))
    x2 = max(x1 + 1, min(x2, canon_img.width))
    y2 = max(y1 + 1, min(y2, canon_img.height))
    
    crop = canon_img.crop((x1, y1, x2, y2))
    arr = np.array(crop)
    # Average color (ignore very dark pixels which are likely shadows)
    mask = arr.mean(axis=2) > 30  # not too dark
    if mask.sum() > 0:
        avg = arr[mask].mean(axis=0).astype(int)
    else:
        avg = arr.mean(axis=(0, 1)).astype(int)
    return tuple(avg[:3])


def colorize_glb(glb_path, color_rgb):
    """Set the baseColorFactor of a GLB's material to the given RGB color."""
    try:
        scene = trimesh.load(str(glb_path), force="scene", process=False)
        modified = False
        r, g, b = color_rgb
        
        for name, geom in scene.geometry.items():
            if not hasattr(geom, "visual"):
                continue
            visual = geom.visual
            if visual.kind == "texture" and hasattr(visual, "material"):
                visual.material.baseColorFactor = np.array([r, g, b, 255], dtype=np.uint8)
                modified = True
            elif visual.kind == "vertex":
                geom.visual.vertex_colors = np.full(
                    (len(geom.vertices), 4), [r, g, b, 255], dtype=np.uint8
                )
                modified = True
            elif visual.kind == "face":
                geom.visual.face_colors = np.full(
                    (len(geom.faces), 4), [r, g, b, 255], dtype=np.uint8
                )
                modified = True
            else:
                # Force face colors on anything else
                geom.visual = trimesh.visual.ColorVisuals(
                    mesh=geom,
                    face_colors=np.full((len(geom.faces), 4), [r, g, b, 255], dtype=np.uint8)
                )
                modified = True
        
        if modified:
            scene.export(str(glb_path), file_type="glb")
            return True
    except Exception as e:
        print(f"    Error: {e}")
    return False


def main():
    catalog = json.loads((ARTIFACTS / "catalog.json").read_text())
    canon_path = ARTIFACTS / "canon.png"
    
    if not canon_path.exists():
        print("ERROR: Canon image not found")
        return
    
    canon_img = Image.open(canon_path).convert("RGB")
    print(f"Canon: {canon_img.width}x{canon_img.height}")
    
    entries = catalog.get("entries", [])
    colorized = 0
    
    for entry in entries:
        bbox = entry.get("bbox_in_best_view", [0, 0, canon_img.width, canon_img.height])
        color = get_crop_color(canon_img, bbox)
        
        glb_path = ARTIFACTS / "meshes" / f"{entry['uuid']}.glb"
        if not glb_path.exists():
            continue
        
        print(f"  {entry['name']:30s} -> RGB({color[0]:3d}, {color[1]:3d}, {color[2]:3d})", end="")
        
        if colorize_glb(glb_path, color):
            print(" OK")
            colorized += 1
        else:
            print(" SKIP")
    
    print(f"\nColorized {colorized}/{len(entries)} meshes from Canon photo.")
    print(f"Refresh: http://127.0.0.1:8000/?v=2.0&session={SESSION.name}")


if __name__ == "__main__":
    main()
