"""Quick check of depth map convention and sample values."""
from PIL import Image
import numpy as np
import json
from pathlib import Path

session = Path("output/8df83612-1b81-4428-b711-7fbabc9536bb")
depth = np.array(Image.open(session / "artifacts/depth.png").convert("L")).astype(np.float32)
catalog = json.loads((session / "artifacts/catalog.json").read_text())

print(f"Depth map shape: {depth.shape}, range [{depth.min():.0f}-{depth.max():.0f}]")

for entry in catalog.get("entries", [])[:8]:
    bbox = entry.get("bbox_in_best_view", [0, 0, 1024, 768])
    cx = int((bbox[0] + bbox[2]) / 2)
    cy = int((bbox[1] + bbox[3]) / 2)
    cx = min(cx, depth.shape[1] - 1)
    cy = min(cy, depth.shape[0] - 1)
    patch = depth[max(0, cy - 10):cy + 10, max(0, cx - 10):cx + 10]
    d_avg = patch.mean() if patch.size > 0 else 0
    print(f"  {entry['name']:30s} center=({cx:4d},{cy:4d}) depth={d_avg:.0f}")

floor_depth = depth[-50:, :].mean()
ceiling_depth = depth[:50, :].mean()
center_depth = depth[300:500, 400:600].mean()
print(f"\nFloor (bottom rows): {floor_depth:.0f}")
print(f"Ceiling (top rows): {ceiling_depth:.0f}")
print(f"Center: {center_depth:.0f}")
print(f"Convention: {'0=near, 255=far (MiDaS inverted)' if floor_depth < ceiling_depth else '0=far, 255=near (MiDaS standard)'}")
