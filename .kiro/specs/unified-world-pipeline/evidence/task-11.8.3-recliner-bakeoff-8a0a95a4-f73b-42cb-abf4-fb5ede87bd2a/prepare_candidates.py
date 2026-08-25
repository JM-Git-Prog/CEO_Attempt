"""Deterministically prepare neutral-background 2D bake-off inputs from existing evidence.

No model inference is performed. The Qwen lane remains explicitly historical and
is not promoted to a Golden Room source-matched amodal completion.
"""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\Danny Tornado\renders")
OUT = Path(__file__).resolve().parent
RAW = ROOT / "danny-v4.1-item-recliner_00002_.png"
QWEN_DIFF = ROOT / "danny-v31-qwendiff-recliner_00001_.png"
CANVAS = 1024
BACKGROUND = (127, 127, 127, 255)


def fit_rgba(image: Image.Image, alpha: Image.Image) -> Image.Image:
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("candidate alpha is empty")
    rgba = image.convert("RGBA")
    rgba.putalpha(alpha)
    crop = rgba.crop(bbox)
    scale = min((CANVAS - 128) / crop.width, (CANVAS - 128) / crop.height)
    resized = crop.resize(
        (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", (CANVAS, CANVAS), BACKGROUND)
    offset = ((CANVAS - resized.width) // 2, (CANVAS - resized.height) // 2)
    canvas.alpha_composite(resized, offset)
    return canvas.convert("RGB")


raw = Image.open(RAW).convert("RGBA")
raw_alpha = raw.getchannel("A")
raw_preview = fit_rgba(raw, raw_alpha)
raw_preview.save(OUT / "lane-raw-crop-neutral.png", optimize=True)

# The historical Qwen artifact is a whole-frame difference image. Apply only
# the source recliner mask to make residual contamination inspectable under the
# same framing; this does not convert it into true amodal completion evidence.
qwen = Image.open(QWEN_DIFF).convert("RGBA")
qwen_preview = fit_rgba(qwen, raw_alpha)
qwen_preview.save(OUT / "lane-qwen-historical-difference-neutral.png", optimize=True)

sheet = Image.new("RGB", (CANVAS * 2, CANVAS + 72), (28, 28, 28))
sheet.paste(raw_preview, (0, 72))
sheet.paste(qwen_preview, (CANVAS, 72))
draw = ImageDraw.Draw(sheet)
draw.text((24, 24), "RAW CROP — source-matched RGBA", fill=(255, 255, 255))
draw.text((CANVAS + 24, 24), "QWEN — historical difference, not amodal", fill=(255, 210, 90))
sheet.save(OUT / "recliner-lane-comparison.png", optimize=True)
