"""Render Task 11.8.4a recliner evidence with a semantic, continuous-surface view contract.

This evidence-only renderer reads the immutable corrected GLB. It does not alter
geometry, materials, production code, or any service. Semantic cardinal views
are derived from the source alpha silhouette and recliner geometry instead of
assuming the generator's axes.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw, PngImagePlugin
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parents[5]
BUNDLE = Path(__file__).resolve().parent
EVIDENCE_DIR = BUNDLE.parent
PRIOR_ID = "3876cc8a-81a2-4bba-9da0-185ba59db002"
PRIOR_BUNDLE = EVIDENCE_DIR / f"task-11.8.4a-continuity-corrected-raw-crop-recliner-{PRIOR_ID}"
ARTIFACT = PRIOR_BUNDLE / "recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
PRIOR_PREVIEW = PRIOR_BUNDLE / "recliner-raw-crop_continuity-corrected-neutral-eight-panel.png"
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
OUTPUT = BUNDLE / "recliner-raw-crop_semantic-surface-neutral-eight-panel.png"
RECORD = BUNDLE / "render-record.json"

RECLINER_UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED_ARTIFACT_SHA256 = "4ca7009199ddcacf1eee2234423d8fcee2086e1b3b3ed7ecc78ca69916cedeaf"
EXPECTED_PRIOR_PREVIEW_SHA256 = "c6b41469032748ef02bf70136ec965eb9cb09d872a9013ca033609ed0d4a39cc"
EXPECTED_SOURCE_CROP_SHA256 = "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a"
PANEL = 420
HEADER = 72
BACKGROUND = np.array([222, 224, 226], dtype=np.uint8)
MAX_RENDER_VERTICES = 400_000
NORMAL_SMOOTH_SIGMA = 4.5
COLOR_SMOOTH_SIGMA = 2.5
CARDINAL_YAWS = (0, 90, 180, 270)
SOURCE_SEARCH_YAWS = tuple(range(0, 360, 45))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def one_geometry(path: Path) -> Any:
    scene = trimesh.load(str(path), force="scene", process=False)
    geometries = list(scene.geometry.values())
    if len(geometries) != 1:
        raise AssertionError(f"Expected exactly one geometry, found {len(geometries)}")
    return geometries[0]


def texture_vertex_colors(geometry: Any) -> np.ndarray:
    uv = np.asarray(getattr(geometry.visual, "uv", None), dtype=np.float64)
    texture = getattr(getattr(geometry.visual, "material", None), "baseColorTexture", None)
    if uv.shape != (len(geometry.vertices), 2) or not isinstance(texture, Image.Image):
        raise AssertionError("Immutable artifact lacks in-memory UV/base-color texture")
    image = np.asarray(texture.convert("RGB"), dtype=np.uint8)
    x = np.rint(np.clip(uv[:, 0], 0.0, 1.0) * (image.shape[1] - 1)).astype(np.int64)
    y = np.rint((1.0 - np.clip(uv[:, 1], 0.0, 1.0)) * (image.shape[0] - 1)).astype(np.int64)
    return image[y, x]


def rotate(values: np.ndarray, degrees: float) -> np.ndarray:
    angle = math.radians(degrees)
    matrix = np.array(
        [[math.cos(angle), 0.0, math.sin(angle)], [0.0, 1.0, 0.0], [-math.sin(angle), 0.0, math.cos(angle)]],
        dtype=np.float64,
    )
    return values @ matrix.T


def projected_samples(vertices: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    points = rotate(vertices, degrees)
    xy = points[:, :2]
    depth = points[:, 2]
    span = np.maximum(np.ptp(xy, axis=0), 1e-9)
    scale = 0.80 * PANEL / max(span)
    pixels = np.rint((xy - (xy.min(axis=0) + xy.max(axis=0)) / 2.0) * scale + PANEL / 2.0).astype(np.int32)
    pixels[:, 1] = PANEL - 1 - pixels[:, 1]
    valid = np.all((pixels >= 4) & (pixels < PANEL - 4), axis=1)
    return pixels[valid], depth[valid], np.flatnonzero(valid)


def surface_mask(vertices: np.ndarray, degrees: float) -> np.ndarray:
    pixels, _, _ = projected_samples(vertices, degrees)
    known = np.zeros((PANEL, PANEL), dtype=np.uint8)
    known[pixels[:, 1], pixels[:, 0]] = 255
    mask = cv2.dilate(known, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        raise AssertionError("Projected geometry produced no surface")
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == largest


def fitted_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    ys, xs = np.where(mask)
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1].astype(np.uint8)
    return cv2.resize(crop, size, interpolation=cv2.INTER_NEAREST).astype(bool)


def source_alpha_mask() -> np.ndarray:
    rgba = np.asarray(Image.open(SOURCE_CROP).convert("RGBA"), dtype=np.uint8)
    mask = rgba[:, :, 3] > 16
    ys, xs = np.where(mask)
    return mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def mask_iou(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.count_nonzero(first & second) / max(np.count_nonzero(first | second), 1))


def bilateral_symmetry(mask: np.ndarray) -> float:
    fitted = fitted_mask(mask, (256, 256))
    return mask_iou(fitted, np.fliplr(fitted))


def derive_view_contract(vertices: np.ndarray) -> dict[str, Any]:
    source = source_alpha_mask()
    source_size = (source.shape[1], source.shape[0])
    masks = {yaw: surface_mask(vertices, yaw) for yaw in SOURCE_SEARCH_YAWS}
    alignment = {yaw: mask_iou(fitted_mask(mask, source_size), source) for yaw, mask in masks.items()}
    source_oblique = max(SOURCE_SEARCH_YAWS, key=lambda yaw: (alignment[yaw], yaw))
    lower = (source_oblique // 90 * 90) % 360
    upper = (lower + 90) % 360
    adjacent = (lower, upper)
    geometry_cues = {}
    for yaw in adjacent:
        ys, xs = np.where(masks[yaw])
        width = int(xs.max() - xs.min() + 1)
        height = int(ys.max() - ys.min() + 1)
        symmetry = bilateral_symmetry(masks[yaw])
        geometry_cues[yaw] = {
            "silhouette_width_px": width,
            "silhouette_height_px": height,
            "bilateral_symmetry_iou": symmetry,
            "front_score": float((width / max(height, 1)) * symmetry),
        }
    front = max(adjacent, key=lambda yaw: (geometry_cues[yaw]["front_score"], alignment[yaw]))
    # The source is a front-right oblique. Choose the adjacent broad, symmetric
    # seat-facing view as front; cardinal handedness then follows around Y-up.
    right = (front + 90) % 360
    rear = (front + 180) % 360
    left = (front + 270) % 360
    semantic_yaws = {"front": front, "right": right, "rear": rear, "left": left}
    if len(set(semantic_yaws.values())) != 4:
        raise AssertionError("Semantic yaw derivation is not a permutation of cardinal views")
    return {
        "method": "source-alpha/geometry-derived-v1",
        "source_semantics": "Golden Room crop shows the recliner from a front-right oblique viewpoint",
        "source_search_yaws_degrees": list(SOURCE_SEARCH_YAWS),
        "source_silhouette_iou_by_yaw": {str(yaw): alignment[yaw] for yaw in SOURCE_SEARCH_YAWS},
        "best_source_oblique_yaw_degrees": source_oblique,
        "adjacent_cardinal_candidates_degrees": list(adjacent),
        "geometry_cues": {str(yaw): geometry_cues[yaw] for yaw in adjacent},
        "semantic_yaws_degrees": semantic_yaws,
        "generator_axes_assumed_semantic": False,
        "handedness": "Y-up; semantic right is +90 degrees from derived semantic front",
    }


def smooth_inside(values: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    weight = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigmaX=sigma, sigmaY=sigma)
    result = np.empty_like(values, dtype=np.float32)
    for channel in range(values.shape[2]):
        numerator = cv2.GaussianBlur(values[:, :, channel] * mask, (0, 0), sigmaX=sigma, sigmaY=sigma)
        result[:, :, channel] = numerator / np.maximum(weight, 1e-5)
    return result


def render_continuous_surface(
    vertices: np.ndarray,
    normals: np.ndarray,
    colors: np.ndarray,
    degrees: float,
    *,
    material: bool,
) -> tuple[Image.Image, np.ndarray]:
    pixels, depth, original = projected_samples(vertices, degrees)
    rotated_normals = rotate(normals[original], degrees)
    sampled_colors = colors[original]
    flat = pixels[:, 1] * PANEL + pixels[:, 0]
    zbuffer = np.full(PANEL * PANEL, -np.inf, dtype=np.float64)
    np.maximum.at(zbuffer, flat, depth)
    visible = depth >= zbuffer[flat] - 1e-9
    pixels = pixels[visible]
    flat = flat[visible]
    depth = depth[visible]
    rotated_normals = rotated_normals[visible]
    sampled_colors = sampled_colors[visible]

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
    normal_field = smooth_inside(normal_field, mask, NORMAL_SMOOTH_SIGMA)
    color_field = smooth_inside(color_field, mask, COLOR_SMOOTH_SIGMA)
    norm = np.linalg.norm(normal_field, axis=2, keepdims=True)
    normal_field = normal_field / np.maximum(norm, 1e-6)
    if float(np.median(normal_field[:, :, 2][mask])) < 0.0:
        normal_field *= -1.0

    key = np.array([-0.35, 0.65, 0.67], dtype=np.float32)
    key /= np.linalg.norm(key)
    fill = np.array([0.55, 0.35, 0.76], dtype=np.float32)
    fill /= np.linalg.norm(fill)
    key_term = np.maximum(np.sum(normal_field * key, axis=2), 0.0)
    fill_term = np.maximum(np.sum(normal_field * fill, axis=2), 0.0)
    rim = np.power(1.0 - np.clip(np.abs(normal_field[:, :, 2]), 0.0, 1.0), 2.0)
    dmin, dmax = float(depth_field[mask].min()), float(depth_field[mask].max())
    depth_norm = (depth_field - dmin) / max(dmax - dmin, 1e-6)
    lighting = np.clip(0.42 + 0.42 * key_term + 0.18 * fill_term + 0.10 * rim + 0.08 * depth_norm, 0.38, 1.12)

    if material:
        rgb = np.clip(color_field * lighting[:, :, None], 0, 255)
    else:
        neutral = np.array([174.0, 181.0, 188.0], dtype=np.float32)
        rgb = np.clip(neutral[None, None, :] * lighting[:, :, None], 0, 255)
    canvas = np.broadcast_to(BACKGROUND, (PANEL, PANEL, 3)).copy()
    canvas[mask] = rgb[mask].astype(np.uint8)
    contour = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)).astype(bool)
    canvas[contour] = np.clip(canvas[contour].astype(np.int16) - 28, 0, 255).astype(np.uint8)
    return Image.fromarray(canvas, mode="RGB"), mask


def stipple_score(panel: Image.Image, mask: np.ndarray) -> float:
    gray = np.asarray(panel.convert("L"), dtype=np.float32)
    interior = cv2.erode(mask.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    smooth = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.15, sigmaY=1.15)
    residual = np.abs(gray - smooth)
    return float(np.mean(residual[interior] > 4.0))


def main() -> None:
    expected = {
        ARTIFACT: EXPECTED_ARTIFACT_SHA256,
        PRIOR_PREVIEW: EXPECTED_PRIOR_PREVIEW_SHA256,
        SOURCE_CROP: EXPECTED_SOURCE_CROP_SHA256,
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256(path) != digest:
            raise AssertionError(f"Immutable input mismatch: {path}")

    geometry = one_geometry(ARTIFACT)
    vertices = np.asarray(geometry.vertices, dtype=np.float64)
    normals = np.asarray(geometry.vertex_normals, dtype=np.float64)
    colors = texture_vertex_colors(geometry)
    vertices = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2.0
    if len(vertices) > MAX_RENDER_VERTICES:
        indices = np.linspace(0, len(vertices) - 1, MAX_RENDER_VERTICES, dtype=np.int64)
        vertices, normals, colors = vertices[indices], normals[indices], colors[indices]

    contract = derive_view_contract(vertices)
    semantic_yaws = contract["semantic_yaws_degrees"]
    sheet = Image.new("RGB", (PANEL * 4, HEADER + PANEL * 2), (28, 30, 32))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 10), f"Task 11.8.4a semantic surface review | UUID {RECLINER_UUID}", fill=(250, 250, 250))
    draw.text((16, 34), "top: continuous neutral topology lighting | bottom: embedded durable material under the same neutral lights", fill=(205, 210, 215))
    panels: dict[str, Any] = {}
    for column, label in enumerate(("front", "right", "rear", "left")):
        yaw = int(semantic_yaws[label])
        geometry_panel, geometry_mask = render_continuous_surface(vertices, normals, colors, yaw, material=False)
        material_panel, material_mask = render_continuous_surface(vertices, normals, colors, yaw, material=True)
        x = column * PANEL
        sheet.paste(geometry_panel, (x, HEADER))
        sheet.paste(material_panel, (x, HEADER + PANEL))
        label_text = f"{label} | derived yaw {yaw} deg"
        ImageDraw.Draw(sheet).rectangle((x + 8, HEADER + 8, x + 180, HEADER + 28), fill=(245, 246, 247))
        ImageDraw.Draw(sheet).text((x + 12, HEADER + 12), label_text, fill=(24, 28, 32))
        ImageDraw.Draw(sheet).rectangle((x + 8, HEADER + PANEL + 8, x + 180, HEADER + PANEL + 28), fill=(245, 246, 247))
        ImageDraw.Draw(sheet).text((x + 12, HEADER + PANEL + 12), label_text, fill=(24, 28, 32))
        panels[label] = {
            "yaw_degrees": yaw,
            "geometry_surface_pixel_count": int(np.count_nonzero(geometry_mask)),
            "material_surface_pixel_count": int(np.count_nonzero(material_mask)),
            "geometry_stipple_score": stipple_score(geometry_panel, geometry_mask),
            "material_stipple_score": stipple_score(material_panel, material_mask),
        }

    contract_bytes = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("task", "11.8.4a")
    metadata.add_text("renderer", "continuous-normal-field-surface-v1")
    metadata.add_text("view_contract_sha256", hashlib.sha256(contract_bytes).hexdigest())
    metadata.add_text("semantic_yaws_degrees", json.dumps(semantic_yaws, sort_keys=True))
    sheet.save(OUTPUT, format="PNG", optimize=True, pnginfo=metadata)

    record = {
        "schema": "unified-world-pipeline.task-11.8.4a.semantic-surface-render.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "scope": "evidence renderer/view contract only; immutable corrected GLB and all prior evidence remain unchanged",
        "recliner_uuid": RECLINER_UUID,
        "source_lane": "raw_crop",
        "inputs": {relative(path): {"sha256": digest, "verified": sha256(path) == digest} for path, digest in expected.items()},
        "artifact_reused_without_modification": {"path": relative(ARTIFACT), "sha256": sha256(ARTIFACT)},
        "renderer": {
            "method": "continuous-normal-field-surface-v1",
            "description": "dense visible surface samples are interpolated into a continuous geometry-derived silhouette, then lit from smoothed vertex normals; no visible point splats or nearest-point dots",
            "sampled_vertices": int(len(vertices)),
            "neutral_background_rgb": BACKGROUND.tolist(),
            "neutral_key_fill_rim_lighting": True,
            "same_view_and_lighting_for_geometry_and_material_rows": True,
            "normal_smoothing_sigma_px": NORMAL_SMOOTH_SIGMA,
            "color_smoothing_sigma_px": COLOR_SMOOTH_SIGMA,
            "preview_size": [PANEL * 4, HEADER + PANEL * 2],
        },
        "view_contract": contract,
        "view_contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "panels": panels,
        "output": {"path": relative(OUTPUT), "sha256": sha256(OUTPUT), "bytes": OUTPUT.stat().st_size, "dimensions": list(sheet.size)},
        "preservation": {
            "glb_modified": False,
            "material_modified": False,
            "production_or_test_code_modified": False,
            "ui_or_service_or_session_or_model_modified": False,
        },
    }
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preview": relative(OUTPUT), "preview_sha256": sha256(OUTPUT), "view_contract": semantic_yaws, "render_record": relative(RECORD)}, indent=2))


if __name__ == "__main__":
    main()
