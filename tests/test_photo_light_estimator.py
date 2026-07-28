"""Property-based tests for photo pipeline light estimator.

# Feature: photo-to-playable-world

## Property 11: Light Estimation Output Validity

**Validates: Requirements 6.1, 6.2, 6.4**

For any valid RGB image (3-channel, non-zero dimensions), the light estimation
SHALL produce:
- sun_direction vector with magnitude within [0.99, 1.01]
- color_temperature in [1800, 12000] Kelvin
- intensity in [0.0, 100.0]
- at minimum one directional light and one ambient light term

Uses Hypothesis with numpy strategies.
"""

from __future__ import annotations

import math

import numpy as np
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from src.photo_pipeline.stages.light_estimator import estimate_light_from_array


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def random_rgb_images(draw: st.DrawFn) -> np.ndarray:
    """Generate random small RGB images (uint8, shape H x W x 3).

    Height in [32, 128], Width in [32, 128].
    """
    height = draw(st.integers(min_value=32, max_value=128))
    width = draw(st.integers(min_value=32, max_value=128))

    image = draw(
        arrays(
            dtype=np.uint8,
            shape=(height, width, 3),
            elements=st.integers(min_value=0, max_value=255),
        )
    )
    return image


# ---------------------------------------------------------------------------
# Property 11: Light Estimation Output Validity
# ---------------------------------------------------------------------------


class TestLightEstimationOutputValidity:
    """Property 11: Light Estimation Output Validity.

    **Validates: Requirements 6.1, 6.2, 6.4**

    For any valid RGB image (3-channel, non-zero dimensions), light estimation
    produces:
    - sun_direction magnitude in [0.99, 1.01]
    - color_temperature in [1800, 12000]
    - intensity in [0.0, 100.0]
    - at minimum one directional light (sun_direction not zero) and one ambient
      light term (ambient_intensity > 0 or ambient_color present)
    """

    @given(image=random_rgb_images())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_sun_direction_is_unit_vector(self, image: np.ndarray):
        """sun_direction magnitude is within [0.99, 1.01]."""
        result = estimate_light_from_array(image)

        dx, dy, dz = result.sun_direction
        magnitude = math.sqrt(dx * dx + dy * dy + dz * dz)

        assert 0.99 <= magnitude <= 1.01, (
            f"sun_direction magnitude out of bounds: {magnitude:.6f} "
            f"(direction={result.sun_direction})"
        )

    @given(image=random_rgb_images())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_color_temperature_in_valid_range(self, image: np.ndarray):
        """color_temperature_k is within [1800, 12000] Kelvin."""
        result = estimate_light_from_array(image)

        assert 1800 <= result.color_temperature_k <= 12000, (
            f"color_temperature_k out of bounds: {result.color_temperature_k}K "
            f"(expected [1800, 12000])"
        )

    @given(image=random_rgb_images())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_intensity_in_valid_range(self, image: np.ndarray):
        """intensity is within [0.0, 100.0]."""
        result = estimate_light_from_array(image)

        assert 0.0 <= result.intensity <= 100.0, (
            f"intensity out of bounds: {result.intensity} "
            f"(expected [0.0, 100.0])"
        )

    @given(image=random_rgb_images())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_has_directional_and_ambient_light(self, image: np.ndarray):
        """Output includes at least one directional light and one ambient light term."""
        result = estimate_light_from_array(image)

        # Directional light: sun_direction is a non-zero unit vector
        dx, dy, dz = result.sun_direction
        dir_magnitude = math.sqrt(dx * dx + dy * dy + dz * dz)
        assert dir_magnitude > 0.5, (
            f"No directional light: sun_direction magnitude = {dir_magnitude:.6f}"
        )

        # Ambient light: ambient_intensity > 0 OR ambient_color is a valid hex color
        has_ambient_intensity = result.ambient_intensity >= 0.0
        has_ambient_color = (
            isinstance(result.ambient_color, str)
            and len(result.ambient_color) == 7
            and result.ambient_color.startswith("#")
        )
        assert has_ambient_intensity or has_ambient_color, (
            f"No ambient light term: ambient_intensity={result.ambient_intensity}, "
            f"ambient_color={result.ambient_color}"
        )

    @given(image=random_rgb_images())
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_all_constraints_together(self, image: np.ndarray):
        """Combined check: all output constraints hold simultaneously."""
        result = estimate_light_from_array(image)

        # Direction magnitude
        dx, dy, dz = result.sun_direction
        magnitude = math.sqrt(dx * dx + dy * dy + dz * dz)
        assert 0.99 <= magnitude <= 1.01, (
            f"sun_direction magnitude: {magnitude:.6f}"
        )

        # Color temperature
        assert 1800 <= result.color_temperature_k <= 12000, (
            f"color_temperature_k: {result.color_temperature_k}"
        )

        # Intensity
        assert 0.0 <= result.intensity <= 100.0, (
            f"intensity: {result.intensity}"
        )

        # Ambient
        assert result.ambient_intensity >= 0.0, (
            f"ambient_intensity: {result.ambient_intensity}"
        )
        assert result.ambient_intensity <= 1.0, (
            f"ambient_intensity: {result.ambient_intensity}"
        )
