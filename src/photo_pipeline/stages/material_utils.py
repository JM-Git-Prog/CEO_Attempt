"""Material and PBR utility helpers for the Photo-to-Real-3D-World V14 pipeline.

Provides texture size selection based on screen-space footprint and
PBR value clamping to valid ranges.

Requirements: 11.4, 5.3
"""
from __future__ import annotations


def select_texture_size(area_pct: float) -> tuple[int, int]:
    """Select texture resolution from object's screen-space area fraction.

    Parameters
    ----------
    area_pct
        Fraction of the image area that the object occupies, in [0, 1].

    Returns
    -------
    (width, height) in pixels — always a power of two.
    """
    if area_pct < 0.02:
        return (256, 256)
    if area_pct <= 0.10:
        return (512, 512)
    return (1024, 1024)


def clamp_pbr_values(
    metallic: float, roughness: float
) -> tuple[float, float]:
    """Clamp PBR scalars into the physically valid [0.0, 1.0] range."""
    m = max(0.0, min(1.0, float(metallic)))
    r = max(0.0, min(1.0, float(roughness)))
    return (m, r)
