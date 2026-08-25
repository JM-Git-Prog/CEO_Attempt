"""Task 11.8.4a additional-01: continuous depth-derived neutral surface evidence.

One focused hypothesis only: replace noisy interpolated vertex-normal lighting with
normals derived from a masked, broadly smoothed visible-depth field. The immutable
GLB, embedded materials, semantic view contract, panel layout, and gate thresholds
remain unchanged.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, PngImagePlugin
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[5]
BUNDLE = Path(__file__).resolve().parent
EVIDENCE_DIR = BUNDLE.parent
BASE_BUNDLE = EVIDENCE_DIR / "task-11.8.4a-semantic-surface-recliner-cf5fd0f5-0ec5-4985-aa11-bc72dbd48637"
BASE_RENDERER_PATH = BASE_BUNDLE / "render_semantic_surface_evidence.py"
BASE_RECORD_PATH = BASE_BUNDLE / "render-record.json"
OUTPUT = BUNDLE / "recliner-raw-crop_additional-01-depth-derived-normal-eight-panel.png"
RECORD = BUNDLE / "render-record.json"
ATTEMPT = "additional-01"
HYPOTHESIS = "Derive neutral topology normals from a masked, broadly smoothed visible-depth field instead of interpolated generator vertex normals; retain the same silhouette, semantic yaws, neutral lights, material colors, and anti-stipple threshold."
DEPTH_SMOOTH_SIGMA = 9.0
DEPTH_DETAIL_SIGMA = 3.5
COLOR_SMOOTH_SIGMA = 4.0


def load_base():
    spec = importlib.util.spec_from_file_location("task_11_8_4a_base_renderer", BASE_RENDERER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load immutable base renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = load_base()
PANEL = base.PANEL
HEADER = base.HEADER
BACKGROUND = base.BACKGROUND
ARTIFACT = base.ARTIFACT
SOURCE_CROP = base.SOURCE_CROP
RECLINER_UUID = base.RECLINER_UUID
EXPECTED_ARTIFACT_SHA256 = base.EXPECTED_ARTIFACT_SHA256
EXPECTED_SOURCE_CROP_SHA256 = base.EXPECTED_SOURCE_CROP_SHA256
surface_mask = base.surface_mask
mask_iou = base.mask_iou
one_geometry = base.one_geometry
derive_view_contract = base.derive_view_contract
MAX_RENDER_VERTICES = base.MAX_RENDER_VERTICES


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def masked_gaussian(values: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    weight = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigmaX=sigma, sigmaY=sigma)
    numerator = cv2.GaussianBlur(values.astype(np.float32) * mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
    return numerator / np.maximum(weight, 1e-5)


def render_continuous_surface(vertices: np.ndarray, normals: np.ndarray, colors: np.ndarray, degrees: float, *, material: bool) -> tuple[Image.Image, np.ndarray]:
    pixels, depth, original = base.projected_samples(vertices, degrees)
    sampled_colors = colors[original]
    flat = pixels[:, 1] * PANEL + pixels[:, 0]
    zbuffer = np.full(PANEL * PANEL, -np.inf, dtype=np.float64)
    np.maximum.at(zbuffer, flat, depth)
    visible = depth >= zbuffer[flat] - 1e-9
    pixels, depth, sampled_colors = pixels[visible], depth[visible], sampled_colors[visible]

    sparse_depth = np.zeros((PANEL, PANEL), dtype=np.float32)
    sparse_colors = np.zeros((PANEL, PANEL, 3), dtype=np.float32)
    known = np.zeros((PANEL, PANEL), dtype=np.uint8)
    sparse_depth[pixels[:, 1], pixels[:, 0]] = depth
    sparse_colors[pixels[:, 1], pixels[:, 0]] = sampled_colors
    known[pixels[:, 1], pixels[:, 0]] = 1

    mask = surface_mask(vertices, degrees)
    _, nearest = distance_transform_edt(known == 0, return_indices=True)
    depth_field = sparse_depth[nearest[0], nearest[1]]
    color_field = sparse_colors[nearest[0], nearest[1]]
    dmin, dmax = float(depth_field[mask].min()), float(depth_field[mask].max())
    depth_norm = (depth_field - dmin) / max(dmax - dmin, 1e-6)
    depth_broad = masked_gaussian(depth_norm, mask, DEPTH_SMOOTH_SIGMA)
    depth_detail = masked_gaussian(depth_norm, mask, DEPTH_DETAIL_SIGMA)

    gx = cv2.Sobel(depth_broad, cv2.CV_32F, 1, 0, ksize=5) / 24.0
    gy = cv2.Sobel(depth_broad, cv2.CV_32F, 0, 1, ksize=5) / 24.0
    normal_field = np.dstack((-5.0 * gx, 5.0 * gy, np.ones_like(gx)))
    normal_field /= np.maximum(np.linalg.norm(normal_field, axis=2, keepdims=True), 1e-6)

    key = np.array([-0.35, 0.65, 0.67], dtype=np.float32)
    key /= np.linalg.norm(key)
    fill = np.array([0.55, 0.35, 0.76], dtype=np.float32)
    fill /= np.linalg.norm(fill)
    key_term = np.maximum(np.sum(normal_field * key, axis=2), 0.0)
    fill_term = np.maximum(np.sum(normal_field * fill, axis=2), 0.0)
    rim = np.power(1.0 - np.clip(normal_field[:, :, 2], 0.0, 1.0), 2.0)
    broad_detail = np.clip((depth_detail - depth_broad) * 2.0, -0.12, 0.12)
    lighting = np.clip(0.48 + 0.34 * key_term + 0.14 * fill_term + 0.08 * rim + 0.12 * depth_broad + broad_detail, 0.42, 1.08)
    lighting = masked_gaussian(lighting, mask, 1.6)

    if material:
        channels = [masked_gaussian(color_field[:, :, c], mask, COLOR_SMOOTH_SIGMA) for c in range(3)]
        color_smooth = np.dstack(channels)
        rgb = np.clip(color_smooth * lighting[:, :, None], 0, 255)
    else:
        neutral = np.array([174.0, 181.0, 188.0], dtype=np.float32)
        rgb = np.clip(neutral[None, None, :] * lighting[:, :, None], 0, 255)
    canvas = np.broadcast_to(BACKGROUND, (PANEL, PANEL, 3)).copy()
    canvas[mask] = rgb[mask].astype(np.uint8)
    contour = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)).astype(bool)
    canvas[contour] = np.clip(canvas[contour].astype(np.int16) - 28, 0, 255).astype(np.uint8)
    return Image.fromarray(canvas, mode="RGB"), mask


def main() -> None:
    expected = {ARTIFACT: EXPECTED_ARTIFACT_SHA256, SOURCE_CROP: EXPECTED_SOURCE_CROP_SHA256}
    for path, digest in expected.items():
        if not path.is_file() or sha256(path) != digest:
            raise AssertionError(f"Immutable input mismatch: {path}")
    geometry = one_geometry(ARTIFACT)
    vertices = np.asarray(geometry.vertices, dtype=np.float64)
    normals = np.asarray(geometry.vertex_normals, dtype=np.float64)
    colors = base.texture_vertex_colors(geometry)
    vertices = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    if len(vertices) > MAX_RENDER_VERTICES:
        indices = np.linspace(0, len(vertices) - 1, MAX_RENDER_VERTICES, dtype=np.int64)
        vertices, normals, colors = vertices[indices], normals[indices], colors[indices]
    contract = derive_view_contract(vertices)
    semantic_yaws = contract["semantic_yaws_degrees"]
    sheet = Image.new("RGB", (PANEL * 4, HEADER + PANEL * 2), (28, 30, 32))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 10), f"Task 11.8.4a {ATTEMPT} depth-derived surface | UUID {RECLINER_UUID}", fill=(250, 250, 250))
    draw.text((16, 34), "top: neutral topology | bottom: embedded durable material | same semantic views and neutral lights", fill=(205, 210, 215))
    panels: dict[str, Any] = {}
    for column, label in enumerate(("front", "right", "rear", "left")):
        yaw = int(semantic_yaws[label])
        geometry_panel, geometry_mask = render_continuous_surface(vertices, normals, colors, yaw, material=False)
        material_panel, material_mask = render_continuous_surface(vertices, normals, colors, yaw, material=True)
        x = column * PANEL
        sheet.paste(geometry_panel, (x, HEADER))
        sheet.paste(material_panel, (x, HEADER + PANEL))
        label_text = f"{label} | derived yaw {yaw} deg"
        for y in (HEADER, HEADER + PANEL):
            ImageDraw.Draw(sheet).rectangle((x + 8, y + 8, x + 180, y + 28), fill=(245, 246, 247))
            ImageDraw.Draw(sheet).text((x + 12, y + 12), label_text, fill=(24, 28, 32))
        panels[label] = {
            "yaw_degrees": yaw,
            "geometry_surface_pixel_count": int(np.count_nonzero(geometry_mask)),
            "material_surface_pixel_count": int(np.count_nonzero(material_mask)),
            "geometry_stipple_score": base.stipple_score(geometry_panel, geometry_mask),
            "material_stipple_score": base.stipple_score(material_panel, material_mask),
        }
    contract_bytes = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("task", "11.8.4a")
    metadata.add_text("attempt", ATTEMPT)
    metadata.add_text("renderer", "masked-depth-derived-normal-surface-v1")
    metadata.add_text("view_contract_sha256", hashlib.sha256(contract_bytes).hexdigest())
    metadata.add_text("semantic_yaws_degrees", json.dumps(semantic_yaws, sort_keys=True))
    sheet.save(OUTPUT, format="PNG", optimize=True, pnginfo=metadata)
    baseline = json.loads(BASE_RECORD_PATH.read_text(encoding="utf-8"))
    record = {
        "schema": "unified-world-pipeline.task-11.8.4a.additional-render.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "attempt": ATTEMPT,
        "hypothesis": HYPOTHESIS,
        "scope": "evidence renderer/view/lighting/rasterization only; immutable GLB/material and prior evidence unchanged",
        "recliner_uuid": RECLINER_UUID,
        "source_lane": "raw_crop",
        "artifact": {"path": relative(ARTIFACT), "sha256": sha256(ARTIFACT), "modified": False},
        "renderer": {
            "method": "masked-depth-derived-normal-surface-v1",
            "depth_smoothing_sigma_px": DEPTH_SMOOTH_SIGMA,
            "depth_detail_sigma_px": DEPTH_DETAIL_SIGMA,
            "color_smoothing_sigma_px": COLOR_SMOOTH_SIGMA,
            "sampled_vertices": int(len(vertices)),
            "same_semantic_views_and_lighting_for_rows": True,
        },
        "view_contract": contract,
        "panels": panels,
        "before_geometry_stipple_score_by_panel": {k: baseline["panels"][k]["geometry_stipple_score"] for k in panels},
        "output": {"path": relative(OUTPUT), "sha256": sha256(OUTPUT), "bytes": OUTPUT.stat().st_size, "dimensions": list(sheet.size)},
        "preservation": {"glb_modified": False, "material_modified": False, "production_test_ui_service_session_model_modified": False},
    }
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"attempt": ATTEMPT, "preview": relative(OUTPUT), "preview_sha256": sha256(OUTPUT), "metrics": panels}, indent=2))


if __name__ == "__main__":
    main()
