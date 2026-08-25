"""Build the Task 11.8.4a source-matched raw-crop recliner candidate once.

This bounded evidence builder copies the immutable Task 11.8.3 raw-crop GLB,
then runs the existing local MaterialProcessor photo-projection and Pass-2 PBR
paths. It never mutates the source candidate, starts a service/session, or
changes spatial/camera/world authority.
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

import numpy as np
import trimesh
from PIL import Image, ImageDraw

BUNDLE_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))

from src.photo_pipeline.stages.material_processor import MaterialProcessor

EVIDENCE_DIR = BUNDLE_DIR.parent
SOURCE_BUNDLE = EVIDENCE_DIR / "task-11.8.3-recliner-bakeoff-8a0a95a4-f73b-42cb-abf4-fb5ede87bd2a"
SOURCE_GLB = SOURCE_BUNDLE / "objects" / "recliner-raw-crop_hunyuan3d.glb"
SOURCE_TEXTURE = SOURCE_BUNDLE / "lane-raw-crop-neutral.png"
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
PRIOR_GATE = EVIDENCE_DIR / "task-11.8.4-standalone-asset-gate-d3f9253c-130b-4a6c-b597-1fc2fa27dd75.json"
OUTPUT_GLB = BUNDLE_DIR / "recliner-raw-crop_durable-fabric-pbr.glb"
OUTPUT_PREVIEW = BUNDLE_DIR / "recliner-raw-crop_durable-fabric-pbr-neutral-eight-panel.png"
BUILD_RECORD = BUNDLE_DIR / "build-record.json"
PROCESSOR_PATH = ROOT / "src" / "photo_pipeline" / "stages" / "material_processor.py"

RECLINER_UUID = "3b2cae03-3556-5c1e-a19b-ea3c1e15694c"
EXPECTED_HASHES = {
    SOURCE_GLB: "970d3b92c8d25f27b088de9696c5762255b72a7e7b7af1180ef8f946fa70ad06",
    SOURCE_TEXTURE: "8f52b50c172cefbeaa6ec19f59495ca27eb88c8a4bf0986c513e6bd62c2444b3",
    SOURCE_CROP: "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a",
    PRIOR_GATE: "823aef9fa29103efabe32aafcd195aa4c76c135eb571e170120dc107aed58d21",
}

PANEL = 420
HEADER = 72
ANGLES = (("front", 0), ("right", 90), ("rear", 180), ("left", 270))
MAX_SAMPLED_VERTICES = 80_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_inputs() -> None:
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise AssertionError(f"Required immutable input missing: {path}")
        observed = sha256(path)
        if observed != expected:
            raise AssertionError(
                f"Immutable input hash mismatch for {path}: {observed} != {expected}"
            )
    if OUTPUT_GLB.exists() or OUTPUT_PREVIEW.exists() or BUILD_RECORD.exists():
        raise AssertionError("Refusing to overwrite immutable Task 11.8.4a outputs")


def one_geometry(scene: trimesh.Scene, *, label: str) -> Any:
    geometries = list(scene.geometry.values())
    if len(geometries) != 1:
        raise AssertionError(f"{label} expected one geometry, got {len(geometries)}")
    return geometries[0]


def geometry_snapshot(path: Path) -> dict[str, Any]:
    scene = trimesh.load(str(path), force="scene", process=False)
    geometry = one_geometry(scene, label=str(path))
    return {
        "vertices": np.asarray(geometry.vertices, dtype=np.float64),
        "faces": np.asarray(geometry.faces, dtype=np.int64),
        "extents": np.asarray(geometry.extents, dtype=np.float64),
    }


def render_points(
    vertices: np.ndarray,
    degrees: float,
    colors: np.ndarray | None,
) -> Image.Image:
    angle = math.radians(degrees)
    rotation = np.array(
        [
            [math.cos(angle), 0.0, math.sin(angle)],
            [0.0, 1.0, 0.0],
            [-math.sin(angle), 0.0, math.cos(angle)],
        ]
    )
    points = vertices @ rotation.T
    xy = points[:, :2]
    depth = points[:, 2]
    span = np.maximum(np.ptp(xy, axis=0), 1e-9)
    scale = 0.82 * PANEL / max(span)
    pixels = np.rint(
        (xy - (xy.min(axis=0) + xy.max(axis=0)) / 2) * scale + PANEL / 2
    ).astype(int)
    pixels[:, 1] = PANEL - 1 - pixels[:, 1]
    valid = np.all((pixels >= 2) & (pixels < PANEL - 2), axis=1)
    pixels = pixels[valid]
    depth = depth[valid]
    colors = None if colors is None else colors[valid]
    order = np.argsort(depth)
    pixels = pixels[order]
    depth = depth[order]
    colors = None if colors is None else colors[order]
    dmin, dmax = float(depth.min()), float(depth.max())
    lighting = 0.72 + 0.28 * (depth - dmin) / max(dmax - dmin, 1e-9)
    if colors is None:
        values = (85 + 155 * lighting).astype(np.uint8)
        rendered = np.column_stack((values, values, values))
    else:
        rendered = np.clip(colors.astype(np.float32) * lighting[:, None], 0, 255).astype(np.uint8)
    image = np.full((PANEL, PANEL, 3), 232, dtype=np.uint8)
    for (x, y), color in zip(pixels, rendered, strict=True):
        image[y - 1 : y + 2, x - 1 : x + 2] = color
    return Image.fromarray(image, mode="RGB")


def texture_vertex_colors(geometry: Any) -> np.ndarray:
    if not hasattr(geometry.visual, "uv") or geometry.visual.uv is None:
        raise AssertionError("Remediated GLB has no UV coordinates")
    material = getattr(geometry.visual, "material", None)
    texture = getattr(material, "baseColorTexture", None)
    if not isinstance(texture, Image.Image):
        raise AssertionError("Remediated GLB baseColorTexture is not embedded/in-memory")
    image = np.asarray(texture.convert("RGB"), dtype=np.uint8)
    uv = np.asarray(geometry.visual.uv, dtype=np.float64)
    if uv.shape != (len(geometry.vertices), 2):
        raise AssertionError(f"UV shape mismatch: {uv.shape}")
    u = np.clip(uv[:, 0], 0.0, 1.0)
    v = np.clip(uv[:, 1], 0.0, 1.0)
    x = np.rint(u * (image.shape[1] - 1)).astype(np.int64)
    y = np.rint((1.0 - v) * (image.shape[0] - 1)).astype(np.int64)
    return image[y, x]


def render_preview(path: Path) -> dict[str, Any]:
    scene = trimesh.load(str(path), force="scene", process=False)
    geometry = one_geometry(scene, label=str(path))
    vertices = np.asarray(geometry.vertices, dtype=np.float64)
    colors = texture_vertex_colors(geometry)
    vertices = vertices - (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    if len(vertices) > MAX_SAMPLED_VERTICES:
        indices = np.linspace(0, len(vertices) - 1, MAX_SAMPLED_VERTICES, dtype=int)
        vertices = vertices[indices]
        colors = colors[indices]

    sheet = Image.new("RGB", (PANEL * 4, HEADER + PANEL * 2), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (16, 12),
        f"Task 11.8.4a neutral review | UUID {RECLINER_UUID}",
        fill=(255, 255, 255),
    )
    draw.text(
        (16, 36),
        "top: geometry/topology silhouette | bottom: embedded durable base-color continuity",
        fill=(210, 210, 210),
    )
    for index, (label, degrees) in enumerate(ANGLES):
        geometry_panel = render_points(vertices, degrees, None)
        material_panel = render_points(vertices, degrees, colors)
        x = index * PANEL
        sheet.paste(geometry_panel, (x, HEADER))
        sheet.paste(material_panel, (x, HEADER + PANEL))
        ImageDraw.Draw(sheet).text((x + 12, HEADER + 12), f"{label} geometry", fill=(20, 20, 20))
        ImageDraw.Draw(sheet).text(
            (x + 12, HEADER + PANEL + 12),
            f"{label} material",
            fill=(20, 20, 20),
        )
    sheet.save(OUTPUT_PREVIEW, format="PNG", optimize=True)
    return {
        "panel_layout": "four columns front/right/rear/left; geometry row then material row",
        "sampled_vertices": len(vertices),
        "background_rgb": [232, 232, 232],
        "output_size": list(sheet.size),
    }


def main() -> None:
    verify_inputs()
    before = geometry_snapshot(SOURCE_GLB)
    shutil.copy2(SOURCE_GLB, OUTPUT_GLB)

    processor = MaterialProcessor()
    pass1 = processor.apply_pass1(
        glb_path=OUTPUT_GLB,
        object_png=SOURCE_TEXTURE,
        generation_method="placeholder",
        image_area_pct=0.15,
    )
    if not pass1.has_base_color:
        raise AssertionError("Existing MaterialProcessor Pass 1 did not embed base color")
    pass2 = asyncio.run(
        processor.apply_pass2(
            glb_path=OUTPUT_GLB,
            object_png=SOURCE_TEXTURE,
            material_type="fabric",
        )
    )
    if not pass2.has_base_color or not pass2.has_metallic_roughness or not pass2.has_normal_map:
        raise AssertionError(f"Existing MaterialProcessor Pass 2 incomplete: {pass2}")

    after = geometry_snapshot(OUTPUT_GLB)
    if before["vertices"].shape != after["vertices"].shape:
        raise AssertionError("Material export changed vertex count")
    if before["faces"].shape != after["faces"].shape:
        raise AssertionError("Material export changed face count")
    max_position_delta = float(np.max(np.abs(before["vertices"] - after["vertices"])))
    max_extent_delta = float(np.max(np.abs(before["extents"] - after["extents"])))
    if max_position_delta >= 1e-5 or max_extent_delta >= 1e-5:
        raise AssertionError(
            f"Material export changed geometry: position={max_position_delta}, extents={max_extent_delta}"
        )

    preview = render_preview(OUTPUT_GLB)
    source_hash_after = sha256(SOURCE_GLB)
    prior_gate_hash_after = sha256(PRIOR_GATE)
    if source_hash_after != EXPECTED_HASHES[SOURCE_GLB]:
        raise AssertionError("Source raw-crop GLB changed during remediation")
    if prior_gate_hash_after != EXPECTED_HASHES[PRIOR_GATE]:
        raise AssertionError("Immutable Task 11.8.4 evidence changed during remediation")

    record = {
        "schema": "unified-world-pipeline.task-11.8.4a.rematerial-build.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "task": "11.8.4a",
        "recliner_uuid": RECLINER_UUID,
        "source_lane": "raw_crop",
        "material_pipeline": {
            "implementation_path": str(PROCESSOR_PATH.relative_to(ROOT)).replace("\\", "/"),
            "implementation_sha256": sha256(PROCESSOR_PATH),
            "pass1": "existing MaterialProcessor photo-projection path applied to a copied non-placeholder generated mesh",
            "pass2": "existing MaterialProcessor durable fabric PBR path",
            "pass1_result": asdict(pass1),
            "pass2_result": asdict(pass2),
            "no_new_model_or_service": True,
        },
        "input_bindings": {
            "raw_crop_glb": {"path": str(SOURCE_GLB.relative_to(ROOT)).replace("\\", "/"), "sha256": EXPECTED_HASHES[SOURCE_GLB]},
            "prepared_source_matched_texture": {"path": str(SOURCE_TEXTURE.relative_to(ROOT)).replace("\\", "/"), "sha256": EXPECTED_HASHES[SOURCE_TEXTURE]},
            "raw_source_crop": {"path": str(SOURCE_CROP), "sha256": EXPECTED_HASHES[SOURCE_CROP]},
            "immutable_task_11_8_4_evidence": {"path": str(PRIOR_GATE.relative_to(ROOT)).replace("\\", "/"), "sha256": EXPECTED_HASHES[PRIOR_GATE]},
        },
        "outputs": {
            "artifact_path": str(OUTPUT_GLB.relative_to(ROOT)).replace("\\", "/"),
            "artifact_sha256": sha256(OUTPUT_GLB),
            "artifact_bytes": OUTPUT_GLB.stat().st_size,
            "preview_path": str(OUTPUT_PREVIEW.relative_to(ROOT)).replace("\\", "/"),
            "preview_sha256": sha256(OUTPUT_PREVIEW),
            "preview": preview,
        },
        "geometry_preservation": {
            "geometry_count": 1,
            "vertex_count": int(len(after["vertices"])),
            "face_count": int(len(after["faces"])),
            "max_position_delta": max_position_delta,
            "max_extent_delta": max_extent_delta,
            "tolerance": 1e-5,
            "preserved": True,
        },
        "authority": {
            "asset_is_non_authoritative_until_approved_and_worldcontract_bound": True,
            "metric_plan_remains_sole_authority_for": [
                "dimensions", "transforms", "placement", "architecture", "openings", "collision", "navigation"
            ],
            "camera_contract_remains_plan_derived_authority": True,
            "world_contract_remains_final_binding_authority": True,
        },
    }
    BUILD_RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
