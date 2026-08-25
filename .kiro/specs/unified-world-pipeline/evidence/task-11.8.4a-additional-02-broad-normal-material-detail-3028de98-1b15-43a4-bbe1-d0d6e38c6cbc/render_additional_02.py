"""Task 11.8.4a additional-02 renderer.

One focused hypothesis: replace additional-01 emboss-like depth-detail lighting with
a very broad low-pass of real visible vertex normals while restoring low-pass embedded
base-color variation. Geometry, materials, semantic views, and thresholds are unchanged.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, PngImagePlugin
from scipy.ndimage import distance_transform_edt

BUNDLE = Path(__file__).resolve().parent
EVIDENCE_DIR = BUNDLE.parent
PARENT_PATH = EVIDENCE_DIR / "task-11.8.4a-additional-01-depth-derived-normal-6e97d166-7dca-4c75-bbe1-1dd7bfc4a15f" / "render_additional_01.py"
OUTPUT = BUNDLE / "recliner-raw-crop_additional-02-broad-normal-material-detail-eight-panel.png"
RECORD = BUNDLE / "render-record.json"
ATTEMPT = "additional-02"
METHOD = "broad-normal-lowpass-material-detail-v1"
HYPOTHESIS = "Replace the emboss-like depth-detail field with a 14-pixel masked low-pass of real visible vertex normals and a 1.6-pixel material-color low-pass, preserving the same semantic yaws, silhouette rasterization, neutral lights, and unchanged anti-stipple threshold."
NORMAL_SIGMA = 14.0
COLOR_SIGMA = 1.6
DEPTH_SIGMA = 10.0


def load_parent():
    spec = importlib.util.spec_from_file_location("additional_01_parent", PARENT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load additional-01 renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parent = load_parent()
base = parent.base
PANEL = parent.PANEL
ARTIFACT = parent.ARTIFACT
EXPECTED_ARTIFACT_SHA256 = parent.EXPECTED_ARTIFACT_SHA256
MAX_RENDER_VERTICES = parent.MAX_RENDER_VERTICES
one_geometry = parent.one_geometry
surface_mask = parent.surface_mask
mask_iou = parent.mask_iou
derive_view_contract = parent.derive_view_contract


def render_continuous_surface(vertices: np.ndarray, normals: np.ndarray, colors: np.ndarray, degrees: float, *, material: bool):
    pixels, depth, original = base.projected_samples(vertices, degrees)
    rotated_normals = base.rotate(normals[original], degrees)
    sampled_colors = colors[original]
    flat = pixels[:, 1] * PANEL + pixels[:, 0]
    zbuffer = np.full(PANEL * PANEL, -np.inf, dtype=np.float64)
    np.maximum.at(zbuffer, flat, depth)
    visible = depth >= zbuffer[flat] - 1e-9
    pixels, depth = pixels[visible], depth[visible]
    rotated_normals, sampled_colors = rotated_normals[visible], sampled_colors[visible]
    sparse_normals = np.zeros((PANEL, PANEL, 3), dtype=np.float32)
    sparse_colors = np.zeros((PANEL, PANEL, 3), dtype=np.float32)
    sparse_depth = np.zeros((PANEL, PANEL), dtype=np.float32)
    known = np.zeros((PANEL, PANEL), dtype=np.uint8)
    sparse_normals[pixels[:, 1], pixels[:, 0]] = rotated_normals
    sparse_colors[pixels[:, 1], pixels[:, 0]] = sampled_colors
    sparse_depth[pixels[:, 1], pixels[:, 0]] = depth
    known[pixels[:, 1], pixels[:, 0]] = 1
    mask = surface_mask(vertices, degrees)
    _, nearest = distance_transform_edt(known == 0, return_indices=True)
    normal_field = sparse_normals[nearest[0], nearest[1]]
    color_field = sparse_colors[nearest[0], nearest[1]]
    depth_field = sparse_depth[nearest[0], nearest[1]]
    normal_field = base.smooth_inside(normal_field, mask, NORMAL_SIGMA)
    normal_field /= np.maximum(np.linalg.norm(normal_field, axis=2, keepdims=True), 1e-6)
    if float(np.median(normal_field[:, :, 2][mask])) < 0:
        normal_field *= -1
    dmin, dmax = float(depth_field[mask].min()), float(depth_field[mask].max())
    depth_norm = (depth_field - dmin) / max(dmax - dmin, 1e-6)
    depth_broad = parent.masked_gaussian(depth_norm, mask, DEPTH_SIGMA)
    key = np.array([-0.35, 0.65, 0.67], dtype=np.float32); key /= np.linalg.norm(key)
    fill = np.array([0.55, 0.35, 0.76], dtype=np.float32); fill /= np.linalg.norm(fill)
    key_term = np.maximum(np.sum(normal_field * key, axis=2), 0.0)
    fill_term = np.maximum(np.sum(normal_field * fill, axis=2), 0.0)
    rim = np.power(1.0 - np.clip(np.abs(normal_field[:, :, 2]), 0.0, 1.0), 2.0)
    lighting = np.clip(0.44 + 0.40 * key_term + 0.16 * fill_term + 0.08 * rim + 0.08 * depth_broad, 0.40, 1.10)
    lighting = parent.masked_gaussian(lighting, mask, 2.0)
    if material:
        channels = [parent.masked_gaussian(color_field[:, :, c], mask, COLOR_SIGMA) for c in range(3)]
        rgb = np.clip(np.dstack(channels) * lighting[:, :, None], 0, 255)
    else:
        rgb = np.clip(np.array([174.0, 181.0, 188.0], dtype=np.float32)[None, None, :] * lighting[:, :, None], 0, 255)
    canvas = np.broadcast_to(base.BACKGROUND, (PANEL, PANEL, 3)).copy()
    canvas[mask] = rgb[mask].astype(np.uint8)
    contour = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)).astype(bool)
    canvas[contour] = np.clip(canvas[contour].astype(np.int16) - 28, 0, 255).astype(np.uint8)
    return Image.fromarray(canvas, mode="RGB"), mask


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parent.BUNDLE = BUNDLE
    parent.OUTPUT = OUTPUT
    parent.RECORD = RECORD
    parent.ATTEMPT = ATTEMPT
    parent.HYPOTHESIS = HYPOTHESIS
    parent.render_continuous_surface = render_continuous_surface
    parent.main()
    image = Image.open(OUTPUT).convert("RGB")
    contract = json.loads(RECORD.read_text(encoding="utf-8"))["view_contract"]
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("task", "11.8.4a")
    metadata.add_text("attempt", ATTEMPT)
    metadata.add_text("renderer", METHOD)
    metadata.add_text("view_contract_sha256", hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
    metadata.add_text("semantic_yaws_degrees", json.dumps(contract["semantic_yaws_degrees"], sort_keys=True))
    image.save(OUTPUT, format="PNG", optimize=True, pnginfo=metadata)
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    record["attempt"] = ATTEMPT
    record["hypothesis"] = HYPOTHESIS
    record["renderer"] = {"method": METHOD, "normal_smoothing_sigma_px": NORMAL_SIGMA, "color_smoothing_sigma_px": COLOR_SIGMA, "depth_smoothing_sigma_px": DEPTH_SIGMA, "same_semantic_views_and_lighting_for_rows": True}
    record["output"].update({"path": parent.relative(OUTPUT), "sha256": sha256(OUTPUT), "bytes": OUTPUT.stat().st_size})
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"attempt": ATTEMPT, "preview": parent.relative(OUTPUT), "preview_sha256": sha256(OUTPUT), "metrics": record["panels"]}, indent=2))


if __name__ == "__main__":
    main()
