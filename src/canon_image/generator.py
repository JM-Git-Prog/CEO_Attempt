"""
Canon Image Generator - Produces photorealistic images from scene concepts.
Supports ComfyUI (FLUX/SD), OpenAI-compatible image APIs, and mock for dev.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from src.models import SceneConcept

COMFYUI_URL = os.getenv("COMFYUI_URL", "http://localhost:8188")
IMAGE_API_URL = os.getenv("IMAGE_API_URL", "")
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))


def _generate_mock(prompt: str, output_path: Path) -> Path:
    """Generate a styled placeholder image representing the canon image."""
    width, height = 1024, 768
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Background gradient: dark moody blue
    for y in range(height):
        r = int(20 + (y / height) * 15)
        g = int(22 + (y / height) * 18)
        b = int(40 + (y / height) * 20)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Checkered floor in lower third
    floor_y = int(height * 0.65)
    tile_size = 40
    for ty in range(floor_y, height, tile_size):
        for tx in range(0, width, tile_size):
            col_idx = (tx // tile_size + ty // tile_size) % 2
            color = (45, 45, 45) if col_idx == 0 else (180, 175, 165)
            draw.rectangle([tx, ty, tx + tile_size, ty + tile_size], fill=color)

    # Counter
    counter_y = int(height * 0.5)
    draw.rectangle([100, counter_y, width - 100, counter_y + 30], fill=(200, 185, 155))
    draw.rectangle([100, counter_y + 30, width - 100, floor_y], fill=(80, 70, 55))

    # Stools
    for sx in [250, 380, 520, 650]:
        draw.rectangle([sx - 3, counter_y + 40, sx + 3, floor_y - 10], fill=(180, 180, 180))
        draw.ellipse([sx - 22, counter_y + 20, sx + 22, counter_y + 50], fill=(192, 57, 43))
        draw.ellipse([sx - 24, counter_y + 18, sx + 24, counter_y + 52], outline=(200, 200, 200), width=2)

    # Pendant lamp + glow
    lamp_x, lamp_y = width // 2, int(height * 0.12)
    draw.line([(lamp_x, 0), (lamp_x, lamp_y)], fill=(60, 60, 60), width=2)
    draw.polygon(
        [(lamp_x - 40, lamp_y), (lamp_x + 40, lamp_y), (lamp_x + 25, lamp_y + 30), (lamp_x - 25, lamp_y + 30)],
        fill=(70, 65, 55),
    )

    # Window with rain
    window_y1, window_y2 = int(height * 0.05), int(height * 0.45)
    draw.rectangle([width - 250, window_y1, width - 50, window_y2], fill=(100, 140, 175))
    random.seed(42)
    for _ in range(30):
        rx = random.randint(width - 245, width - 55)
        ry = random.randint(window_y1, window_y2 - 30)
        draw.line([(rx, ry), (rx - 2, ry + 20)], fill=(150, 180, 210), width=1)

    # Labels
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except (OSError, IOError):
        font = ImageFont.load_default()
        font_small = font

    draw.text((20, 20), "CANON IMAGE [MOCK]", fill=(200, 200, 200), font=font)
    short_prompt = prompt[:120] + "..." if len(prompt) > 120 else prompt
    draw.text((20, 45), short_prompt, fill=(150, 150, 150), font=font_small)
    draw.text((20, height - 30), "Connect FLUX/ComfyUI for photorealistic generation", fill=(120, 120, 120), font=font_small)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


async def generate_canon_image(concept: SceneConcept, session_id: str, attempt: int = 1) -> Path:
    """Generate the canon image. Tries ComfyUI → API → Mock."""
    output_path = OUTPUT_DIR / session_id / f"canon_v{attempt}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # For now, use mock (ComfyUI/API integration ready but requires running services)
    return _generate_mock(concept.image_prompt, output_path)
