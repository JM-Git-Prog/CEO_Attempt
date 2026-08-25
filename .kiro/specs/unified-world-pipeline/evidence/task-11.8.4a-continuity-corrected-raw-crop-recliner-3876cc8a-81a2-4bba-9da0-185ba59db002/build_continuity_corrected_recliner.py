"""Build a bounded Task 11.8.4a visual-continuity correction.

The immutable raw-crop mesh is copied. A seamless upholstery-only map is
computed deterministically from opaque pixels in the hash-bound raw crop, then
passed through the unchanged approved local MaterialProcessor Pass 1 and Pass 2
paths. No model, service, session, production code, or spatial authority is used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter

BUNDLE_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from src.photo_pipeline.stages.material_processor import MaterialProcessor

EVIDENCE_DIR = BUNDLE_DIR.parent
SOURCE_BUNDLE = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a"
SOURCE_GLB = SOURCE_BUNDLE / "objects" / "recliner-raw-crop_hunyuan3d.glb"
SOURCE_NEUTRAL = SOURCE_BUNDLE / "lane-raw-crop-neutral.png"
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
SOURCE_IMAGE = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4-01-canon_00002_.png")
MIRROR_IMAGE = Path(r"C:\Users\JohnM\ComfyUI-Shared\input\danny-v4-01-canon_00002_.png")
WORKFLOW_UI = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.ui.json")
WORKFLOW_API = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\workflows\danny-v4.1-items.api.json")
PRIOR_GATE = EVIDENCE_DIR / "task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json"
REJECTED_EVIDENCE = EVIDENCE_DIR / "task-11.8.4a-remediated-raw-crop-recliner-aa1347b1-9a3e-45f6-af16-571c7e03dde8.json"
REJECTED_BUNDLE = EVIDENCE_DIR / "task-11.8.4a-remediated-raw-crop-recliner-aa1347b1-9a3e-45f6-af16-571c7e03dde8"
REJECTED_ARTIFACT = REJECTED_BUNDLE / "recliner-raw-crop_durable-fabric-pbr.glb"
REJECTED_PREVIEW = REJECTED_BUNDLE / "recliner-raw-crop_durable-fabric-pbr-neutral-eight-panel.png"
VISUAL_REJECTION = EVIDENCE_DIR / "task-11.8.4a-visual-rejection-b1cbf2d1-1a25-478c-8ddf-3a4f5bfd4780.json"
PROCESSOR_PATH = ROOT / "src" / "photo_pipeline" / "stages" / "material_processor.py"

DERIVED_TEXTURE = BUNDLE_DIR / "recliner-raw-crop_seamless-upholstery-source-map.png"
OUTPUT_GLB = BUNDLE_DIR / "recliner-raw-crop_continuity-corrected-fabric-pbr.glb"
OUTPUT_PREVIEW = BUNDLE_DIR / "recliner-raw-crop_continuity-corrected-neutral-eight-panel.png"
BUILD_RECORD = BUNDLE_DIR / "build-record.json"

RECLINER_UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED_HASHES = {
    SOURCE_GLB: "970d3b92c8d25f27b088de9696c5762255b72a7e7b7af1180ef8f946fa70ad06",
    SOURCE_NEUTRAL: "8f52b50c172cefbeaa6ec19f59495ca27eb88c8a4bf0986c513e6bd62c2444b3",
    SOURCE_CROP: "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a",
    SOURCE_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    MIRROR_IMAGE: "dbbaa35c9aafd64de2735a29da8eea5a1852e08805a5746563f6f2d45100a3b6",
    WORKFLOW_UI: "0b5ccde89d6fb9ac5a25ab91f45a5da2dac9c5be9932d62a1e3e04812b261196",
    WORKFLOW_API: "362dea52c21418717e919d9ea942f74a9016dd38088ec618660c21f74f2f37af",
    PRIOR_GATE: "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
    REJECTED_EVIDENCE: "b0fc2b37f5b2c97b815552ee004f13228507ec272559ef04e45d67175859c3fa",
    REJECTED_ARTIFACT: "181ad41bfde7b1a807cb8c2c89c5a3ce977618b8b3092252d3abe5c05b07e7b2",
    REJECTED_PREVIEW: "37776fac4fa6634ee31f39d195b87d571de94ffe7e1be7d00f5dd758d97794a6",
}

PANEL = 420
HEADER = 72
ANGLES = (("front", 0), ("right", 90), ("rear", 180), ("left", 270))
MAX_RENDER_VERTICES = 300_000
BACKGROUND = np.array([232, 232, 232], dtype=np.uint8)
VISUAL_THRESHOLDS = {
    "projected_subject_leakage_correlation_max": 0.20,
    "rendered_coverage_min": 0.995,
    "internal_hole_ratio_max": 0.010,
    "small_component_ratio_max": 0.005,
    "palette_outlier_ratio_max": 0.080,
    "false_surface_edge_density_max": 0.160,
    "brown_palette_inlier_ratio_min": 0.900,
    "cross_view_median_delta_e_max": 18.0,
}


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


def verify_inputs() -> None:
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise AssertionError(f"Required immutable input missing: {path}")
        observed = sha256(path)
        if observed != expected:
            raise AssertionError(f"Immutable input hash mismatch for {path}: {observed} != {expected}")
    for path in (DERIVED_TEXTURE, OUTPUT_GLB, OUTPUT_PREVIEW, BUILD_RECORD):
        if path.exists():
            raise AssertionError(f"Refusing to overwrite immutable output: {path}")


def one_geometry(path: Path) -> Any:
    scene = trimesh.load(str(path), force="scene", process=False)
    geometries = list(scene.geometry.values())
    if len(geometries) != 1:
        raise AssertionError(f"Expected one geometry in {path}, got {len(geometries)}")
    return geometries[0]


def geometry_snapshot(path: Path) -> dict[str, Any]:
    geometry = one_geometry(path)
    return {
        "vertices": np.asarray(geometry.vertices, dtype=np.float64),
        "faces": np.asarray(geometry.faces, dtype=np.int64),
        "extents": np.asarray(geometry.extents, dtype=np.float64),
    }


def raw_crop_pixels() -> tuple[Image.Image, np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    rgba = Image.open(SOURCE_CROP).convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    visible = alpha >= 128
    if not np.any(visible):
        raise AssertionError("Raw crop has no opaque recliner pixels")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise AssertionError("Raw crop alpha bbox is empty")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    return rgba, rgb, visible, bbox


def make_seamless_upholstery_map() -> dict[str, Any]:
    """Create a low-frequency periodic fabric map with no object silhouette.

    Every color is derived from opaque raw-crop recliner pixels. Dark hardware
    and extreme highlights are excluded by robust luminance bounds; spatial
    chair structure is intentionally discarded before approved projection.
    """
    _, rgb, visible, bbox = raw_crop_pixels()
    pixels = rgb[visible].astype(np.float32)
    luminance = pixels @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    low, high = np.percentile(luminance, [12, 88])
    brown = (pixels[:, 0] >= pixels[:, 2] * 0.92) & (pixels[:, 0] >= pixels[:, 1] * 0.90)
    selected = pixels[(luminance >= low) & (luminance <= high) & brown]
    if len(selected) < 500:
        raise AssertionError(f"Insufficient source upholstery pixels: {len(selected)}")

    median = np.median(selected, axis=0)
    p10 = np.percentile(selected, 10, axis=0)
    p90 = np.percentile(selected, 90, axis=0)
    rng = np.random.default_rng(1184)
    sampled = selected[rng.integers(0, len(selected), size=256 * 256)].reshape(256, 256, 3)
    smooth = gaussian_filter(sampled, sigma=(11.0, 11.0, 0.0), mode="wrap")
    # Keep source variation subtle enough to remain upholstery, not projected imagery.
    smooth = median[None, None, :] + 0.32 * (smooth - median[None, None, :])
    smooth = np.clip(smooth, p10[None, None, :], p90[None, None, :])
    tile = np.rint(smooth).astype(np.uint8)
    texture = np.tile(tile, (4, 4, 1))
    Image.fromarray(texture, mode="RGB").save(DERIVED_TEXTURE, format="PNG", optimize=True)
    return {
        "method": "opaque raw-crop pixels -> robust upholstery palette -> deterministic periodic sampling -> wrap Gaussian smoothing -> 0.32 source variation; no spatial source structure retained",
        "source_alpha_bbox": list(bbox),
        "opaque_source_pixel_count": int(np.count_nonzero(visible)),
        "selected_upholstery_pixel_count": int(len(selected)),
        "luminance_percentile_bounds": [float(low), float(high)],
        "median_rgb": [float(value) for value in median],
        "p10_rgb": [float(value) for value in p10],
        "p90_rgb": [float(value) for value in p90],
        "deterministic_seed": 1184,
        "periodic_tile_size": [256, 256],
        "output_size": [1024, 1024],
        "output_sha256": sha256(DERIVED_TEXTURE),
        "source_only_no_model_or_inference": True,
    }


def texture_vertex_colors(geometry: Any) -> np.ndarray:
    uv = getattr(geometry.visual, "uv", None)
    material = getattr(geometry.visual, "material", None)
    texture = getattr(material, "baseColorTexture", None)
    if uv is None or not isinstance(texture, Image.Image):
        raise AssertionError("Artifact lacks in-memory UV/baseColorTexture")
    uv_array = np.asarray(uv, dtype=np.float64)
    if uv_array.shape != (len(geometry.vertices), 2):
        raise AssertionError(f"UV shape mismatch: {uv_array.shape}")
    image = np.asarray(texture.convert("RGB"), dtype=np.uint8)
    x = np.rint(np.clip(uv_array[:, 0], 0.0, 1.0) * (image.shape[1] - 1)).astype(np.int64)
    y = np.rint((1.0 - np.clip(uv_array[:, 1], 0.0, 1.0)) * (image.shape[0] - 1)).astype(np.int64)
    return image[y, x]


def render_surface(vertices: np.ndarray, degrees: float, colors: np.ndarray | None) -> tuple[Image.Image, np.ndarray]:
    angle = math.radians(degrees)
    rotation = np.array([[math.cos(angle), 0.0, math.sin(angle)], [0.0, 1.0, 0.0], [-math.sin(angle), 0.0, math.cos(angle)]])
    points = vertices @ rotation.T
    xy = points[:, :2]
    depth = points[:, 2]
    span = np.maximum(np.ptp(xy, axis=0), 1e-9)
    scale = 0.82 * PANEL / max(span)
    pixels = np.rint((xy - (xy.min(axis=0) + xy.max(axis=0)) / 2) * scale + PANEL / 2).astype(np.int32)
    pixels[:, 1] = PANEL - 1 - pixels[:, 1]
    valid = np.all((pixels >= 3) & (pixels < PANEL - 3), axis=1)
    pixels, depth = pixels[valid], depth[valid]
    colors = None if colors is None else colors[valid]

    flat = pixels[:, 1] * PANEL + pixels[:, 0]
    zbuffer = np.full(PANEL * PANEL, -np.inf, dtype=np.float64)
    np.maximum.at(zbuffer, flat, depth)
    visible = depth >= zbuffer[flat] - 1e-12
    pixels, depth, flat = pixels[visible], depth[visible], flat[visible]
    colors = None if colors is None else colors[visible]

    dmin, dmax = float(depth.min()), float(depth.max())
    light = 0.76 + 0.24 * (depth - dmin) / max(dmax - dmin, 1e-9)
    if colors is None:
        values = np.clip(80 + 110 * light, 0, 255).astype(np.uint8)
        rendered = np.column_stack((values, values, values))
    else:
        rendered = np.clip(colors.astype(np.float32) * light[:, None], 0, 255).astype(np.uint8)

    sparse = np.zeros((PANEL, PANEL, 3), dtype=np.uint8)
    known = np.zeros((PANEL, PANEL), dtype=np.uint8)
    sparse[pixels[:, 1], pixels[:, 0]] = rendered
    known[pixels[:, 1], pixels[:, 0]] = 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    silhouette = cv2.dilate(known, kernel, iterations=1)
    silhouette = cv2.morphologyEx(silhouette, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, nearest = distance_transform_edt(known == 0, return_indices=True)
    filled = sparse[nearest[0], nearest[1]]
    image = np.full((PANEL, PANEL, 3), BACKGROUND, dtype=np.uint8)
    image[silhouette.astype(bool)] = filled[silhouette.astype(bool)]
    return Image.fromarray(image, mode="RGB"), silhouette.astype(bool)


def source_subject_reference(size: tuple[int, int]) -> Image.Image:
    rgba, rgb, visible, bbox = raw_crop_pixels()
    median = np.median(rgb[visible], axis=0).astype(np.uint8)
    crop = rgba.crop(bbox)
    padding = round(min(size) * 0.0625)
    scale = min((size[0] - 2 * padding) / crop.width, (size[1] - 2 * padding) / crop.height)
    resized = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, tuple(int(value) for value in median) + (255,))
    canvas.alpha_composite(resized, ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2))
    return canvas.convert("RGB")


def projected_subject_leakage(texture: Image.Image) -> float:
    reference = np.asarray(source_subject_reference(texture.size).convert("L"), dtype=np.float32)
    observed = np.asarray(texture.convert("L"), dtype=np.float32)

    def highpass(value: np.ndarray) -> np.ndarray:
        return value - cv2.GaussianBlur(value, (0, 0), sigmaX=8.0, sigmaY=8.0)

    observed_hp = highpass(observed).ravel()
    scores = []
    for candidate in (reference, np.flipud(reference), np.fliplr(reference)):
        candidate_hp = highpass(candidate).ravel()
        denom = float(np.linalg.norm(observed_hp) * np.linalg.norm(candidate_hp))
        scores.append(0.0 if denom == 0.0 else abs(float(np.dot(observed_hp, candidate_hp) / denom)))
    return max(scores)


def panel_metrics(geometry_image: Image.Image, material_image: Image.Image) -> dict[str, float]:
    geom = np.asarray(geometry_image.convert("RGB"), dtype=np.uint8)
    material = np.asarray(material_image.convert("RGB"), dtype=np.uint8)
    geom_mask = np.max(np.abs(geom.astype(np.int16) - BACKGROUND.astype(np.int16)), axis=2) > 3
    material_mask = np.max(np.abs(material.astype(np.int16) - BACKGROUND.astype(np.int16)), axis=2) > 3
    coverage = float(np.count_nonzero(geom_mask & material_mask) / max(np.count_nonzero(geom_mask), 1))
    closed = cv2.morphologyEx(material_mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(bool)
    hole_ratio = float(np.count_nonzero(closed & ~material_mask) / max(np.count_nonzero(closed), 1))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(material_mask.astype(np.uint8), connectivity=8)
    small = sum(int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, count) if stats[index, cv2.CC_STAT_AREA] < 50)
    small_ratio = float(small / max(np.count_nonzero(material_mask), 1))

    interior = cv2.erode(material_mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    values = material[interior]
    lab = cv2.cvtColor(material, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab_values = lab[interior]
    center = np.median(lab_values, axis=0)
    delta = np.linalg.norm(lab_values - center, axis=1)
    outlier_ratio = float(np.mean(delta > 28.0))
    gray = cv2.cvtColor(material, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 45, 110) > 0
    edge_density = float(np.count_nonzero(edges & interior) / max(np.count_nonzero(interior), 1))
    hsv_values = cv2.cvtColor(material, cv2.COLOR_RGB2HSV)[interior]
    brown = ((hsv_values[:, 0] <= 35) | (hsv_values[:, 0] >= 170)) & (hsv_values[:, 1] >= 12)
    brown_ratio = float(np.mean(brown))
    return {
        "rendered_coverage": coverage,
        "internal_hole_ratio": hole_ratio,
        "small_component_ratio": small_ratio,
        "palette_outlier_ratio": outlier_ratio,
        "false_surface_edge_density": edge_density,
        "brown_palette_inlier_ratio": brown_ratio,
        "median_lab_l": float(center[0]),
        "median_lab_a": float(center[1]),
        "median_lab_b": float(center[2]),
        "sampled_material_pixels": int(len(values)),
    }


def assess_artifact_visual(path: Path, *, write_preview: Path | None = None) -> dict[str, Any]:
    geometry = one_geometry(path)
    vertices = np.asarray(geometry.vertices, dtype=np.float64)
    colors = texture_vertex_colors(geometry)
    vertices = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    if len(vertices) > MAX_RENDER_VERTICES:
        indices = np.linspace(0, len(vertices) - 1, MAX_RENDER_VERTICES, dtype=np.int64)
        vertices, colors = vertices[indices], colors[indices]
    texture = getattr(geometry.visual.material, "baseColorTexture")
    leakage = projected_subject_leakage(texture)

    sheet = Image.new("RGB", (PANEL * 4, HEADER + PANEL * 2), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    draw.text((16, 12), f"Task 11.8.4a continuity review | UUID {RECLINER_UUID}", fill=(255, 255, 255))
    draw.text((16, 36), "top: continuous geometry silhouette | bottom: embedded source-derived upholstery material", fill=(210, 210, 210))
    per_view: dict[str, dict[str, float]] = {}
    medians = []
    for index, (label, degrees) in enumerate(ANGLES):
        geometry_panel, _ = render_surface(vertices, degrees, None)
        material_panel, _ = render_surface(vertices, degrees, colors)
        metrics = panel_metrics(geometry_panel, material_panel)
        per_view[label] = metrics
        medians.append([metrics["median_lab_l"], metrics["median_lab_a"], metrics["median_lab_b"]])
        x = index * PANEL
        sheet.paste(geometry_panel, (x, HEADER))
        sheet.paste(material_panel, (x, HEADER + PANEL))
        ImageDraw.Draw(sheet).text((x + 12, HEADER + 12), f"{label} geometry", fill=(20, 20, 20))
        ImageDraw.Draw(sheet).text((x + 12, HEADER + PANEL + 12), f"{label} material", fill=(20, 20, 20))
    medians_array = np.asarray(medians, dtype=np.float32)
    cross_delta = max(float(np.linalg.norm(a - b)) for a in medians_array for b in medians_array)
    checks = {
        "projected_subject_leakage": leakage <= VISUAL_THRESHOLDS["projected_subject_leakage_correlation_max"],
        "rendered_surface_coverage": all(value["rendered_coverage"] >= VISUAL_THRESHOLDS["rendered_coverage_min"] for value in per_view.values()),
        "no_speckled_or_holed_coverage": all(value["internal_hole_ratio"] <= VISUAL_THRESHOLDS["internal_hole_ratio_max"] and value["small_component_ratio"] <= VISUAL_THRESHOLDS["small_component_ratio_max"] for value in per_view.values()),
        "no_false_surface_edges": all(value["false_surface_edge_density"] <= VISUAL_THRESHOLDS["false_surface_edge_density_max"] for value in per_view.values()),
        "bounded_palette_outliers": all(value["palette_outlier_ratio"] <= VISUAL_THRESHOLDS["palette_outlier_ratio_max"] for value in per_view.values()),
        "source_brown_palette_continuity": all(value["brown_palette_inlier_ratio"] >= VISUAL_THRESHOLDS["brown_palette_inlier_ratio_min"] for value in per_view.values()),
        "cross_view_material_continuity": cross_delta <= VISUAL_THRESHOLDS["cross_view_median_delta_e_max"],
    }
    if write_preview is not None:
        sheet.save(write_preview, format="PNG", optimize=True)
    return {
        "thresholds": VISUAL_THRESHOLDS,
        "projected_subject_leakage_correlation": leakage,
        "per_view": per_view,
        "cross_view_median_delta_e": cross_delta,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "pass": all(checks.values()),
        "renderer": {"method": "depth-selected dense vertex splat with nearest-surface fill and bounded 5px morphology", "sampled_vertices": int(len(vertices)), "background_rgb": BACKGROUND.tolist(), "preview_size": [PANEL * 4, HEADER + PANEL * 2]},
    }


def rejected_preview_hole_ratio(path: Path) -> float:
    sheet = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    ratios = []
    for row in (0, 1):
        for column in range(4):
            y0 = HEADER + row * PANEL + 32
            panel = sheet[y0 : HEADER + (row + 1) * PANEL, column * PANEL : (column + 1) * PANEL]
            mask = np.max(np.abs(panel.astype(np.int16) - BACKGROUND.astype(np.int16)), axis=2) > 3
            closed = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(bool)
            ratios.append(float(np.count_nonzero(closed & ~mask) / max(np.count_nonzero(closed), 1)))
    return max(ratios)


def main() -> None:
    verify_inputs()
    derivation = make_seamless_upholstery_map()
    before = geometry_snapshot(SOURCE_GLB)
    shutil.copy2(SOURCE_GLB, OUTPUT_GLB)
    processor = MaterialProcessor()
    pass1 = processor.apply_pass1(OUTPUT_GLB, DERIVED_TEXTURE, "placeholder", 0.15)
    if not pass1.has_base_color:
        raise AssertionError("Approved MaterialProcessor Pass 1 failed")
    pass2 = asyncio.run(processor.apply_pass2(OUTPUT_GLB, DERIVED_TEXTURE, "fabric"))
    if not (pass2.has_base_color and pass2.has_metallic_roughness and pass2.has_normal_map):
        raise AssertionError(f"Approved MaterialProcessor Pass 2 incomplete: {pass2}")
    after = geometry_snapshot(OUTPUT_GLB)
    if before["vertices"].shape != after["vertices"].shape or before["faces"].shape != after["faces"].shape:
        raise AssertionError("Material correction changed geometry cardinality")
    max_position_delta = float(np.max(np.abs(before["vertices"] - after["vertices"])))
    max_extent_delta = float(np.max(np.abs(before["extents"] - after["extents"])))
    if max_position_delta >= 1e-5 or max_extent_delta >= 1e-5:
        raise AssertionError("Material correction changed source geometry")

    visual = assess_artifact_visual(OUTPUT_GLB, write_preview=OUTPUT_PREVIEW)
    rejected_visual = assess_artifact_visual(REJECTED_ARTIFACT)
    rejected_holes = rejected_preview_hole_ratio(REJECTED_PREVIEW)
    if rejected_visual["checks"]["projected_subject_leakage"]:
        raise AssertionError("Strengthened validation did not reject prior projected-subject false surfaces")
    if not visual["pass"]:
        raise AssertionError(f"Corrected visual validation failed closed: {visual['failed_checks']}")

    record = {
        "schema": "unified-world-pipeline.task-11.8.4a.continuity-corrected-build.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "recliner_uuid": RECLINER_UUID,
        "source_lane": "raw_crop",
        "correction_scope": "seamless upholstery-only source map plus coverage-aware neutral evidence; geometry and approved production material code unchanged",
        "input_bindings": {relative(path): {"sha256": expected, "verified": sha256(path) == expected} for path, expected in EXPECTED_HASHES.items()},
        "visual_rejection_binding": {"path": relative(VISUAL_REJECTION), "sha256": sha256(VISUAL_REJECTION)},
        "material_input_derivation": {"source_path": str(SOURCE_CROP), "source_sha256": EXPECTED_HASHES[SOURCE_CROP], "derived_path": relative(DERIVED_TEXTURE), **derivation},
        "material_pipeline": {"implementation_path": relative(PROCESSOR_PATH), "implementation_sha256": sha256(PROCESSOR_PATH), "pass1": "unchanged MaterialProcessor photo-projection path applied to a copied generated mesh using a non-semantic seamless source map", "pass2": "unchanged MaterialProcessor durable fabric PBR path", "pass1_result": asdict(pass1), "pass2_result": asdict(pass2), "production_code_modified": False, "no_model_or_service": True},
        "geometry_preservation": {"vertex_count": int(len(after["vertices"])), "face_count": int(len(after["faces"])), "max_position_delta": max_position_delta, "max_extent_delta": max_extent_delta, "tolerance": 1e-5, "preserved": True},
        "outputs": {"artifact_path": relative(OUTPUT_GLB), "artifact_sha256": sha256(OUTPUT_GLB), "artifact_bytes": OUTPUT_GLB.stat().st_size, "preview_path": relative(OUTPUT_PREVIEW), "preview_sha256": sha256(OUTPUT_PREVIEW), "preview_dimensions": [PANEL * 4, HEADER + PANEL * 2]},
        "image_based_visual_validation": visual,
        "rejected_candidate_regression": {"artifact_sha256": EXPECTED_HASHES[REJECTED_ARTIFACT], "projected_subject_leakage_correlation": rejected_visual["projected_subject_leakage_correlation"], "projected_subject_leakage_rejected": not rejected_visual["checks"]["projected_subject_leakage"], "stored_preview_max_internal_hole_ratio": rejected_holes, "stored_preview_speckle_or_holes_observed": rejected_holes > VISUAL_THRESHOLDS["internal_hole_ratio_max"]},
        "authority": {"metric_plan_remains_sole_authority_for": ["dimensions", "transforms", "placement", "architecture", "openings", "collision", "navigation"], "camera_contract_remains_plan_derived_authority": True, "world_contract_remains_final_binding_authority": True, "asset_is_not_spatial_authority": True},
    }
    BUILD_RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
