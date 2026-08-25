"""Bounded final Task 11.8.4a build using only source-derived pixels.

Transparent pixels in the immutable raw-crop RGBA are filled with the median
visible fabric color from that same crop. The resulting source-derived texture
is passed through the unchanged existing local MaterialProcessor paths.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

BUNDLE_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[5]
ATTEMPT1_DIR = BUNDLE_DIR.parent / "task-11.8.4a-remediated-raw-crop-recliner-0f7d85b5-f7b0-4e18-8e92-6fb2ab65e3c1"
BASE_BUILDER = ATTEMPT1_DIR / "build_remediated_recliner.py"
SOURCE_CROP = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders\danny-v4.1-item-recliner_00002_.png")
DERIVED_TEXTURE = BUNDLE_DIR / "recliner-raw-crop_source-derived-fabric-base.png"
OUTPUT_GLB = BUNDLE_DIR / "recliner-raw-crop_durable-fabric-pbr.glb"
OUTPUT_PREVIEW = BUNDLE_DIR / "recliner-raw-crop_durable-fabric-pbr-neutral-eight-panel.png"
BUILD_RECORD = BUNDLE_DIR / "build-record.json"
EXPECTED_SOURCE_CROP_SHA = "b962f2c58770b7edde18d8aeb4b8f4fa26fc936584c45ea84424639d4d97386a"
CANVAS = 1024
PADDING = 64


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_derived_texture() -> dict[str, object]:
    if DERIVED_TEXTURE.exists():
        raise AssertionError("Refusing to overwrite source-derived material input")
    if sha256(SOURCE_CROP) != EXPECTED_SOURCE_CROP_SHA:
        raise AssertionError("Immutable raw-crop source hash mismatch")
    rgba = Image.open(SOURCE_CROP).convert("RGBA")
    alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    visible = alpha >= 128
    if not np.any(visible):
        raise AssertionError("Raw crop contains no visible object pixels")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
    median = np.median(rgb[visible], axis=0).astype(np.uint8)
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        raise AssertionError("Raw crop alpha bbox is empty")
    crop = rgba.crop(bbox)
    scale = min((CANVAS - 2 * PADDING) / crop.width, (CANVAS - 2 * PADDING) / crop.height)
    resized = crop.resize(
        (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
        Image.Resampling.LANCZOS,
    )
    background = tuple(int(value) for value in median) + (255,)
    canvas = Image.new("RGBA", (CANVAS, CANVAS), background)
    offset = ((CANVAS - resized.width) // 2, (CANVAS - resized.height) // 2)
    canvas.alpha_composite(resized, offset)
    canvas.convert("RGB").save(DERIVED_TEXTURE, format="PNG", optimize=True)
    return {
        "method": "RGBA alpha crop fitted with 64px padding; transparent pixels filled with median RGB of alpha>=128 source pixels",
        "median_visible_fabric_rgb": [int(value) for value in median],
        "source_alpha_bbox": list(bbox),
        "output_size": [CANVAS, CANVAS],
        "output_sha256": sha256(DERIVED_TEXTURE),
    }


def load_base_builder():
    spec = importlib.util.spec_from_file_location("task_11_8_4a_attempt1_builder", BASE_BUILDER)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load bounded base builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    derivation = source_derived_texture()
    module = load_base_builder()
    original_render = module.render_points

    def higher_contrast_render(vertices, degrees, colors):
        image = original_render(vertices, degrees, colors)
        if colors is None:
            pixels = np.asarray(image).copy()
            mask = np.any(pixels != 232, axis=2)
            gray = pixels[:, :, 0].astype(np.int16)
            value = np.clip((gray - 190) * 2 + 55, 45, 185).astype(np.uint8)
            pixels[mask] = np.column_stack((value[mask], value[mask], value[mask]))
            return Image.fromarray(pixels, mode="RGB")
        return image

    module.BUNDLE_DIR = BUNDLE_DIR
    module.SOURCE_TEXTURE = DERIVED_TEXTURE
    module.OUTPUT_GLB = OUTPUT_GLB
    module.OUTPUT_PREVIEW = OUTPUT_PREVIEW
    module.BUILD_RECORD = BUILD_RECORD
    module.EXPECTED_HASHES[DERIVED_TEXTURE] = derivation["output_sha256"]
    module.render_points = higher_contrast_render
    module.main()

    record = json.loads(BUILD_RECORD.read_text(encoding="utf-8"))
    record["material_input_derivation"] = {
        "source_path": str(SOURCE_CROP),
        "source_sha256": EXPECTED_SOURCE_CROP_SHA,
        "derived_path": str(DERIVED_TEXTURE.relative_to(ROOT)).replace("\\", "/"),
        **derivation,
        "source_only_no_model_or_inference": True,
    }
    record["attempt"] = 2
    record["supersedes_failed_attempt_artifact_sha256"] = "3faded4346b3a7499dcd57a058f3b5a2088629c1f89b17bf567c495c38273afb"
    BUILD_RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
