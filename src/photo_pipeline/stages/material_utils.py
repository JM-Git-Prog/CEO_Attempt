"""Material utility functions for the V14 pipeline.

Pure functions for texture size selection and PBR value clamping.
No external dependencies — used by the MaterialProcessor and property tests.

Requirements: 11.4, 5.3
"""


def select_texture_size(area_pct: float) -> tuple[int, int]:
    """Select texture dimensions by object screen-space footprint.

    area_pct is the fraction of image area (0.0 to 1.0 scale, NOT percentage).
    Thresholds:
        - < 0.02  → 256×256  (small objects, less than 2% of image)
        - 0.02 to 0.10 → 512×512  (medium objects, 2%-10% of image)
        - > 0.10  → 1024×1024 (large objects, more than 10% of image)

    All dimensions are powers of two for WebGL compatibility.
    """
    if area_pct < 0.02:
        return (256, 256)
    elif area_pct <= 0.10:
        return (512, 512)
    else:
        return (1024, 1024)


def clamp_pbr_values(metallic: float, roughness: float) -> tuple[float, float]:
    """Clamp PBR metallic and roughness values to valid [0.0, 1.0] range.

    Ensures material parameters stay within physically-based rendering bounds
    regardless of upstream estimation noise.
    """
    metallic_clamped = max(0.0, min(1.0, metallic))
    roughness_clamped = max(0.0, min(1.0, roughness))
    return (metallic_clamped, roughness_clamped)
