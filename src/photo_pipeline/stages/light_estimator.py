"""Light Estimator — CPU-based heuristic light estimation from source image.

This module estimates scene lighting from a single RGB photograph using
image analysis heuristics:

1. **Direction estimation**: Divide the image into quadrants, find the brightest
   quadrant, and infer the primary light direction in WorldContract Y-up coords.

2. **Color temperature estimation**: Sample the brightest non-saturated pixels
   (top 5% luminance, not clipped at 255), compute an average R/B ratio, and
   map it to Kelvin (high R/B = warm ~3000K, low R/B = cool ~8000K).

3. **Intensity estimation**: Derive intensity from mean image luminance, mapped
   and clamped to the WorldContract [0, 100] range.

4. **Ambient estimation**: Ambient intensity is a fraction of the main intensity;
   ambient color is the average image color in hex.

5. **Confidence**: High when clear directional lighting is detected (quadrant
   brightness ratio > 1.5); low when lighting is uniform.

Fallback to a neutral overhead light triggers when:
- Estimated intensity is zero
- Direction is a zero vector
- Any estimation error occurs

Pure computation functions are separated from the async interface for
independent testability.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
from PIL import Image

from src.photo_pipeline.models import LightEstimateResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_COLOR_TEMP_K = 1800
_MAX_COLOR_TEMP_K = 12000
_DEFAULT_COLOR_TEMP_K = 5500

_MIN_INTENSITY = 0.0
_MAX_INTENSITY = 100.0

_MIN_AMBIENT = 0.0
_MAX_AMBIENT = 1.0

# Top percentage of luminance pixels to sample for color temperature
_BRIGHT_PIXEL_PERCENTILE = 95

# Quadrant brightness ratio threshold for high-confidence directional light
_DIRECTIONAL_RATIO_THRESHOLD = 1.5


# ---------------------------------------------------------------------------
# Pure helper functions (testable without I/O)
# ---------------------------------------------------------------------------


def default_light() -> LightEstimateResult:
    """Return the default overhead neutral light fallback.

    Direction [0, -1, 0] means light coming from directly above (Y-up coords).
    Color temperature 5500K is neutral daylight. Intensity 1.0 on the [0, 100]
    scale is a minimal baseline.

    Returns
    -------
    LightEstimateResult
        Default light with overhead direction, neutral color, low intensity.
    """
    return LightEstimateResult(
        sun_direction=(0.0, -1.0, 0.0),
        color_temperature_k=_DEFAULT_COLOR_TEMP_K,
        intensity=1.0,
        ambient_intensity=0.3,
        ambient_color="#808080",
        confidence=0.0,
    )


def _compute_quadrant_brightness(image: np.ndarray) -> tuple[float, float, float, float]:
    """Compute average brightness per image quadrant.

    Divides the image into four quadrants (top-left, top-right, bottom-left,
    bottom-right) and computes the mean luminance of each.

    Parameters
    ----------
    image : np.ndarray
        RGB image array of shape (H, W, 3), dtype uint8.

    Returns
    -------
    tuple[float, float, float, float]
        Average brightness for (top-left, top-right, bottom-left, bottom-right).
    """
    # Convert to grayscale luminance using standard weights
    luminance = (
        0.2126 * image[:, :, 0].astype(np.float64)
        + 0.7152 * image[:, :, 1].astype(np.float64)
        + 0.0722 * image[:, :, 2].astype(np.float64)
    )

    h, w = luminance.shape
    mid_h = h // 2
    mid_w = w // 2

    # Guard against zero-size quadrants (images smaller than 2x2)
    if mid_h == 0 or mid_w == 0:
        mean_val = float(luminance.mean()) if luminance.size > 0 else 0.0
        return (mean_val, mean_val, mean_val, mean_val)

    tl = float(luminance[:mid_h, :mid_w].mean())
    tr = float(luminance[:mid_h, mid_w:].mean())
    bl = float(luminance[mid_h:, :mid_w].mean())
    br = float(luminance[mid_h:, mid_w:].mean())

    return (tl, tr, bl, br)


def _quadrant_to_direction(quadrant_brightness: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """Map quadrant brightness to a 3D light direction vector.

    The brightest quadrant suggests the light source position. We map this
    to a normalized 3D direction vector in WorldContract coordinates (Y-up):
    - X axis: left/right (positive = right)
    - Y axis: up/down (positive = up, light comes from above → negative Y)
    - Z axis: front/back (positive = toward camera)

    The direction vector points FROM the light source TOWARD the scene
    (i.e., the direction light travels).

    Parameters
    ----------
    quadrant_brightness : tuple[float, float, float, float]
        Brightness of (top-left, top-right, bottom-left, bottom-right).

    Returns
    -------
    tuple[float, float, float]
        Normalized 3D direction vector.
    """
    tl, tr, bl, br = quadrant_brightness

    # Compute horizontal and vertical bias
    # Positive x_bias means light is from the left (brighter on left → light from left)
    left_avg = (tl + bl) / 2.0
    right_avg = (tr + br) / 2.0
    top_avg = (tl + tr) / 2.0
    bottom_avg = (bl + br) / 2.0

    # Direction components: light travels FROM bright side TOWARD dark side
    # If left is brighter, light comes from left → direction has positive X
    # But in WorldContract, we express direction as the light travel direction
    x = -(left_avg - right_avg)  # from bright to dark
    # If top is brighter, light comes from above → negative Y (downward)
    y = -(top_avg - bottom_avg)
    # Default Z component: slight forward bias
    z = -0.3 * max(tl, tr, bl, br)

    # Normalize
    magnitude = math.sqrt(x * x + y * y + z * z)
    if magnitude < 1e-8:
        # Uniform lighting — return straight down
        return (0.0, -1.0, 0.0)

    return (x / magnitude, y / magnitude, z / magnitude)


def _estimate_color_temp_from_image(image: np.ndarray) -> int:
    """Estimate color temperature from the brightest non-saturated pixels.

    Samples the top 5% luminance pixels (excluding fully saturated at 255)
    and computes the average R/B ratio. Maps this ratio to Kelvin:
    - High R/B (warm): ~3000K
    - Low R/B (cool): ~8000K

    Parameters
    ----------
    image : np.ndarray
        RGB image array of shape (H, W, 3), dtype uint8.

    Returns
    -------
    int
        Estimated color temperature in Kelvin, clamped to [1800, 12000].
    """
    # Compute luminance
    luminance = (
        0.2126 * image[:, :, 0].astype(np.float64)
        + 0.7152 * image[:, :, 1].astype(np.float64)
        + 0.0722 * image[:, :, 2].astype(np.float64)
    )

    # Find the luminance threshold for top 5%
    threshold = np.percentile(luminance, _BRIGHT_PIXEL_PERCENTILE)

    # Create mask: bright but not saturated (any channel at 255)
    bright_mask = luminance >= threshold
    saturated_mask = np.any(image == 255, axis=2)
    valid_mask = bright_mask & ~saturated_mask

    # If no valid bright non-saturated pixels, just use bright pixels
    if not np.any(valid_mask):
        valid_mask = bright_mask

    # If still no pixels (e.g., all pixels are saturated), return neutral
    if not np.any(valid_mask):
        return _DEFAULT_COLOR_TEMP_K

    # Extract R and B values for valid pixels
    r_values = image[:, :, 0][valid_mask].astype(np.float64)
    b_values = image[:, :, 2][valid_mask].astype(np.float64)

    # Compute average R/B ratio (avoid division by zero)
    mean_b = b_values.mean()
    if mean_b < 1.0:
        mean_b = 1.0
    rb_ratio = r_values.mean() / mean_b

    # Map R/B ratio to Kelvin
    # Empirical mapping: R/B ~ 1.5 → ~3000K (warm), R/B ~ 0.7 → ~8000K (cool)
    # Linear interpolation between anchor points
    # rb_ratio=1.5 → 3000K, rb_ratio=1.0 → 5500K, rb_ratio=0.7 → 8000K
    if rb_ratio >= 1.5:
        kelvin = 2500
    elif rb_ratio <= 0.7:
        kelvin = 9000
    else:
        # Linear mapping: rb_ratio in [0.7, 1.5] → kelvin in [9000, 2500]
        t = (rb_ratio - 0.7) / (1.5 - 0.7)  # 0.0 at cool end, 1.0 at warm end
        kelvin = int(9000 - t * (9000 - 2500))

    # Clamp to valid range
    return max(_MIN_COLOR_TEMP_K, min(_MAX_COLOR_TEMP_K, kelvin))


def _estimate_intensity_from_image(image: np.ndarray) -> float:
    """Estimate light intensity from mean image luminance.

    Computes mean luminance (0-255 → 0-1), multiplies by 5.0, clamps to
    [0.5, 8.0], then normalizes to [0, 100] scale.

    Parameters
    ----------
    image : np.ndarray
        RGB image array of shape (H, W, 3), dtype uint8.

    Returns
    -------
    float
        Estimated intensity in [0, 100] range.
    """
    # Mean luminance normalized to [0, 1]
    luminance = (
        0.2126 * image[:, :, 0].astype(np.float64)
        + 0.7152 * image[:, :, 1].astype(np.float64)
        + 0.0722 * image[:, :, 2].astype(np.float64)
    )
    mean_lum = luminance.mean() / 255.0

    # Map: mean_lum * 5.0, clamped to [0.5, 8.0]
    raw_intensity = mean_lum * 5.0
    raw_intensity = max(0.5, min(8.0, raw_intensity))

    # Normalize [0.5, 8.0] to [0, 100]
    # 0.5 → ~6.25, 8.0 → 100.0
    normalized = (raw_intensity / 8.0) * 100.0

    return max(_MIN_INTENSITY, min(_MAX_INTENSITY, normalized))


def _compute_ambient(intensity: float, image: np.ndarray) -> tuple[float, str]:
    """Compute ambient intensity and ambient color.

    Ambient intensity is 30% of the main intensity (clamped to [0, 1]).
    Ambient color is the average image color as hex.

    Parameters
    ----------
    intensity : float
        Main light intensity (0-100 scale).
    image : np.ndarray
        RGB image array of shape (H, W, 3), dtype uint8.

    Returns
    -------
    tuple[float, str]
        (ambient_intensity clamped to [0, 1], ambient_color as hex string).
    """
    # Ambient intensity: 0.3 * (intensity / 100.0) to get it on [0, 1] scale
    # Since intensity is on [0, 100], normalize to [0, 1] first
    ambient_intensity = 0.3 * (intensity / 100.0)
    ambient_intensity = max(_MIN_AMBIENT, min(_MAX_AMBIENT, ambient_intensity))

    # Average image color
    avg_r = int(image[:, :, 0].mean())
    avg_g = int(image[:, :, 1].mean())
    avg_b = int(image[:, :, 2].mean())
    ambient_color = f"#{avg_r:02x}{avg_g:02x}{avg_b:02x}"

    return ambient_intensity, ambient_color


def _compute_confidence(quadrant_brightness: tuple[float, float, float, float]) -> float:
    """Compute confidence score for the light estimation.

    High confidence when clear directional lighting is detected (quadrant
    brightness ratio > 1.5). Low confidence when lighting is uniform.

    Parameters
    ----------
    quadrant_brightness : tuple[float, float, float, float]
        Brightness of (top-left, top-right, bottom-left, bottom-right).

    Returns
    -------
    float
        Confidence score in [0.0, 1.0].
    """
    values = list(quadrant_brightness)
    max_brightness = max(values)
    min_brightness = min(values)

    if min_brightness < 1e-8:
        # Very dark minimum — likely strong directional light
        if max_brightness > 1e-8:
            return 1.0
        else:
            return 0.0

    ratio = max_brightness / min_brightness

    if ratio >= _DIRECTIONAL_RATIO_THRESHOLD:
        # Clear directional lighting
        # Scale: ratio 1.5 → confidence 0.7, ratio 3.0+ → confidence 1.0
        confidence = 0.7 + 0.3 * min(1.0, (ratio - 1.5) / 1.5)
        return min(1.0, confidence)
    else:
        # Uniform lighting — low confidence
        # Scale: ratio 1.0 → confidence 0.1, ratio 1.5 → confidence 0.7
        confidence = 0.1 + 0.6 * (ratio - 1.0) / 0.5
        return max(0.0, min(0.7, confidence))


def estimate_light_from_array(image: np.ndarray) -> LightEstimateResult:
    """Estimate lighting from an RGB image array.

    This is the core estimation function operating on a numpy array.
    It combines direction, color temperature, intensity, and ambient
    estimation, applying the default fallback if results are degenerate.

    Parameters
    ----------
    image : np.ndarray
        RGB image array of shape (H, W, 3), dtype uint8.

    Returns
    -------
    LightEstimateResult
        Complete light estimation result.
    """
    if image.size == 0 or image.ndim != 3 or image.shape[2] < 3:
        return default_light()

    try:
        # 1. Direction estimation via quadrant analysis
        quadrant_brightness = _compute_quadrant_brightness(image)
        direction = _quadrant_to_direction(quadrant_brightness)

        # 2. Color temperature estimation
        color_temp = _estimate_color_temp_from_image(image)

        # 3. Intensity estimation
        intensity = _estimate_intensity_from_image(image)

        # 4. Ambient estimation
        ambient_intensity, ambient_color = _compute_ambient(intensity, image)

        # 5. Confidence score
        confidence = _compute_confidence(quadrant_brightness)

        # Validate: check for degenerate results requiring fallback
        dir_magnitude = math.sqrt(
            direction[0] ** 2 + direction[1] ** 2 + direction[2] ** 2
        )

        if intensity <= 0.0 or dir_magnitude < 1e-6:
            logger.warning(
                "Light estimation produced degenerate results "
                "(intensity=%.3f, dir_magnitude=%.6f) — using fallback",
                intensity,
                dir_magnitude,
            )
            return default_light()

        # Ensure direction is normalized (should already be, but guarantee it)
        if abs(dir_magnitude - 1.0) > 0.01:
            direction = (
                direction[0] / dir_magnitude,
                direction[1] / dir_magnitude,
                direction[2] / dir_magnitude,
            )

        return LightEstimateResult(
            sun_direction=direction,
            color_temperature_k=color_temp,
            intensity=intensity,
            ambient_intensity=ambient_intensity,
            ambient_color=ambient_color,
            confidence=confidence,
        )

    except Exception as exc:
        logger.warning(
            "Light estimation failed (%s) — using default fallback", exc
        )
        return default_light()


# ---------------------------------------------------------------------------
# LightEstimator class — async interface matching the pipeline pattern
# ---------------------------------------------------------------------------


class LightEstimator:
    """Estimates scene lighting from the source image.

    Uses CPU-based heuristics (quadrant brightness analysis, R/B ratio color
    temperature, luminance-based intensity) to produce a LightEstimateResult
    compatible with WorldContract light entries.

    Falls back to a default overhead neutral light if estimation produces
    degenerate results (zero intensity, zero direction) or on any error.
    """

    async def estimate(self, source_image: Path) -> LightEstimateResult:
        """Run the light estimation pipeline on a source image.

        1. Load the source image as an RGB numpy array
        2. Analyze quadrant brightness for direction estimation
        3. Estimate color temperature from bright non-saturated pixels
        4. Estimate intensity from mean luminance
        5. Compute ambient parameters
        6. Compute confidence score
        7. Return LightEstimateResult (or default fallback on failure)

        Parameters
        ----------
        source_image : Path
            Path to the source RGB image (JPEG or PNG).

        Returns
        -------
        LightEstimateResult
            Structured result with direction, color temp, intensity, ambient,
            and confidence.
        """
        try:
            img = Image.open(source_image).convert("RGB")
            image_array = np.array(img, dtype=np.uint8)
            img.close()
        except Exception as exc:
            logger.warning(
                "Failed to load image for light estimation (%s) — using fallback",
                exc,
            )
            return default_light()

        return estimate_light_from_array(image_array)
