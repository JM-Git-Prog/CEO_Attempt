"""Deterministic Scene Canon to physical browser-lighting authority.

The Canon image owns mood, not arbitrary renderer units.  This module converts
its normalized mean luminance and chromaticity once, upstream of WorldContract
assembly.  Consumers receive explicit values and units and must not infer,
clamp, white-balance, or reinterpret them.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Iterable

from src.unified_pipeline.world_contract import LightingConfig, LightSource, Vec3

PROFILE = "canon-mean-relative-luminance-to-three-physical/v1"
TEMPERATURE_KELVIN = 5500.0
AMBIENT_MIN = 0.55
AMBIENT_MAX = 1.25
POINT_CANDELA_MIN = 8.0
POINT_CANDELA_MAX = 56.0
EXPOSURE_MIN = 0.85
EXPOSURE_MAX = 1.35


@dataclass(frozen=True, slots=True)
class CanonLightingEvidence:
    """Hashable source measurement used to derive contract lighting."""

    mean_rgb: tuple[float, float, float]
    normalized_luminance: float
    source_sha256: str
    derivation_sha256: str


def _bounded(value: float, minimum: float, maximum: float) -> float:
    if not math.isfinite(value):
        raise ValueError("Canon lighting input must be finite")
    return max(minimum, min(maximum, value))


def _hex(rgb: Iterable[float]) -> str:
    values = tuple(rgb)
    if len(values) != 3 or any(not math.isfinite(float(value)) for value in values):
        raise ValueError("Canon chromaticity requires three finite channels")
    return "#" + "".join(f"{round(_bounded(float(value), 0.0, 255.0)):02X}" for value in values)


def _kelvin_rgb(kelvin: float) -> tuple[float, float, float]:
    """Return an explicit sRGB white-balance color using a documented approximation."""
    if not 1000.0 <= kelvin <= 12000.0:
        raise ValueError("color temperature must be within 1000K..12000K")
    temperature = kelvin / 100.0
    if temperature <= 66.0:
        red = 255.0
        green = 99.4708025861 * math.log(temperature) - 161.1195681661
        blue = 0.0 if temperature <= 19.0 else 138.5177312231 * math.log(temperature - 10.0) - 305.0447927307
    else:
        red = 329.698727446 * ((temperature - 60.0) ** -0.1332047592)
        green = 288.1221695283 * ((temperature - 60.0) ** -0.0755148492)
        blue = 255.0
    return tuple(_bounded(value, 0.0, 255.0) for value in (red, green, blue))


def derive_canon_lighting(
    mean_rgb: tuple[float, float, float],
    *,
    room_height_m: float,
    source_sha256: str,
) -> tuple[LightingConfig, CanonLightingEvidence]:
    """Convert one Canon measurement into explicit renderer-ready authority.

    Mapping (all coefficients are versioned by ``PROFILE``):
      L = Rec.709(mean_sRGB) / 255
      ambient scene-linear multiplier = clamp(0.55 + 1.20 L, 0.55, 1.25)
      point intensity cd = clamp(8 + 48 L, 8, 56)
      exposure = clamp(0.85 + 0.70 L, 0.85, 1.35)

    Canon chromaticity is normalized by its maximum channel before combining
    with the explicit 5500K white-balance color.  This preserves warm ratios
    without using the dark mean RGB as an energy attenuator.
    """
    if len(mean_rgb) != 3 or any(not math.isfinite(float(value)) or not 0.0 <= float(value) <= 255.0 for value in mean_rgb):
        raise ValueError("Canon mean RGB must contain three finite values in 0..255")
    if not math.isfinite(room_height_m) or room_height_m <= 0.0:
        raise ValueError("room height must be positive and finite")
    if len(source_sha256) != 64 or any(character not in "0123456789abcdef" for character in source_sha256):
        raise ValueError("Canon source SHA-256 must be lowercase hexadecimal")

    luminance = (0.2126 * mean_rgb[0] + 0.7152 * mean_rgb[1] + 0.0722 * mean_rgb[2]) / 255.0
    luminance = _bounded(luminance, 0.0, 1.0)
    legacy_color = _hex(mean_rgb)
    legacy_ambient = _bounded(luminance * 0.55, 0.08, 0.8)
    legacy_point = _bounded(luminance * 2.0, 0.25, 2.0)
    ambient = _bounded(0.55 + 1.20 * luminance, AMBIENT_MIN, AMBIENT_MAX)
    point_cd = _bounded(8.0 + 48.0 * luminance, POINT_CANDELA_MIN, POINT_CANDELA_MAX)
    exposure = _bounded(0.85 + 0.70 * luminance, EXPOSURE_MIN, EXPOSURE_MAX)

    maximum = max(mean_rgb)
    chroma = (1.0, 1.0, 1.0) if maximum <= 0.0 else tuple(value / maximum for value in mean_rgb)
    white_balance = _kelvin_rgb(TEMPERATURE_KELVIN)
    render_rgb = tuple(chroma[index] * white_balance[index] for index in range(3))
    white_balance_color = _hex(white_balance)
    render_color = _hex(render_rgb)
    derivation = {
        "profile": PROFILE,
        "source_sha256": source_sha256,
        "mean_rgb": list(mean_rgb),
        "normalized_luminance": luminance,
        "temperature_kelvin": TEMPERATURE_KELVIN,
        "white_balance_color": white_balance_color,
        "render_color": render_color,
        "ambient_scene_linear": ambient,
        "point_candela": point_cd,
        "exposure": exposure,
        "legacy": {
            "color": legacy_color,
            "ambient_intensity": legacy_ambient,
            "point_intensity": legacy_point,
        },
    }
    derivation_sha256 = hashlib.sha256(
        json.dumps(derivation, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    lighting = LightingConfig(
        ambient_color=white_balance_color,
        ambient_intensity=ambient,
        ambient_intensity_unit="scene-linear-multiplier",
        exposure=exposure,
        derivation_profile=PROFILE,
        source_luminance=luminance,
        source_chromaticity=legacy_color,
        white_balance_color=white_balance_color,
        derivation_sha256=derivation_sha256,
        legacy_ambient_color=legacy_color,
        legacy_ambient_intensity=legacy_ambient,
        lights=(LightSource(
            light_id="canon-luminance-centroid",
            light_type="point",
            position=Vec3(0.0, room_height_m * 0.88, 0.0),
            color=render_color,
            intensity=point_cd,
            intensity_unit="candela",
            temperature=TEMPERATURE_KELVIN,
            white_balance_color=white_balance_color,
            legacy_color=legacy_color,
            legacy_intensity=legacy_point,
            cast_shadows=True,
        ),),
    )
    return lighting, CanonLightingEvidence(
        mean_rgb=mean_rgb,
        normalized_luminance=luminance,
        source_sha256=source_sha256,
        derivation_sha256=derivation_sha256,
    )
