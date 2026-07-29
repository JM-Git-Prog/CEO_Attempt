"""Property-based tests for Physics Classification Correctness.

# Feature: photo-to-real-3d-world-v14

## Property 11: Physics Classification Correctness

**Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**

For any object with dimensions (w, h, d) in meters, a material from the
density table, and an is_architectural flag:
- IF is_architectural is True → body_mode=STATIC, mass_kg=0, friction=0.6,
  restitution=0.1, can_topple=False
- ELSE IF volume × density ≤ 25kg → body_mode=DYNAMIC, mass_kg=volume×density,
  friction=0.5, restitution=0.2, can_topple=True
- ELSE → body_mode=STATIC, mass_kg=0, friction=0.6, restitution=0.1,
  can_topple=False

Uses Hypothesis with custom strategies generating:
- Positive float dimensions (width, height, depth) in meters
- Materials from the DENSITY_TABLE plus unknown materials (default density 950.0)
- Boolean is_architectural flag
- Tests all three classification branches exhaustively
"""

from __future__ import annotations

import math

from hypothesis import given, settings, HealthCheck, assume
from hypothesis import strategies as st

from src.photo_pipeline.stages.physics_classifier import PhysicsClassifier


# ---------------------------------------------------------------------------
# Constants (mirrored from implementation for oracle comparison)
# ---------------------------------------------------------------------------

DENSITY_TABLE: dict[str, float] = {
    "wood": 600,
    "metal": 7800,
    "glass": 2500,
    "fabric": 200,
    "ceramic": 2300,
    "plastic": 950,
}
DEFAULT_DENSITY: float = 950.0
MASS_THRESHOLD_KG: float = 25.0

# Known + unknown materials for comprehensive generation
KNOWN_MATERIALS = list(DENSITY_TABLE.keys())
UNKNOWN_MATERIALS = ["rubber", "concrete", "stone", "leather", "foam", "carbon_fiber"]
ALL_MATERIALS = KNOWN_MATERIALS + UNKNOWN_MATERIALS


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Positive floats for dimensions in meters (realistic object sizes)
_dimension = st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False)

# Dimensions tuple: 3 positive floats (w, h, d)
_dimensions = st.tuples(_dimension, _dimension, _dimension)

# Materials: known + unknown to test both density lookup and default
_known_material = st.sampled_from(KNOWN_MATERIALS)
_unknown_material = st.sampled_from(UNKNOWN_MATERIALS)
_any_material = st.sampled_from(ALL_MATERIALS)

# Architectural flag
_is_architectural = st.booleans()


# ---------------------------------------------------------------------------
# Property 11: Physics Classification Correctness
# ---------------------------------------------------------------------------


class TestPhysicsClassificationCorrectnessProperty:
    """Property 11: Physics Classification Correctness.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    """

    @given(
        dimensions=_dimensions,
        material=_any_material,
        is_architectural=_is_architectural,
    )
    @settings(
        max_examples=500,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_physics_classification_all_branches(
        self,
        dimensions: tuple[float, float, float],
        material: str,
        is_architectural: bool,
    ) -> None:
        """All three classification branches produce correct outputs."""
        classifier = PhysicsClassifier()
        result = classifier.classify(dimensions, material, is_architectural)

        # Compute expected values
        w, h, d = dimensions
        volume = w * h * d
        density = DENSITY_TABLE.get(material, DEFAULT_DENSITY)
        mass = volume * density

        # Verify volume and density are recorded correctly
        assert math.isclose(result.volume_m3, volume, rel_tol=1e-9), (
            f"Volume mismatch: expected {volume}, got {result.volume_m3}"
        )
        assert math.isclose(result.material_density, density, rel_tol=1e-9), (
            f"Density mismatch: expected {density}, got {result.material_density}"
        )

        if is_architectural:
            # Branch 1: Architectural override → STATIC
            assert result.body_mode == "STATIC"
            assert result.mass_kg == 0.0
            assert math.isclose(result.friction, 0.6, rel_tol=1e-9)
            assert math.isclose(result.restitution, 0.1, rel_tol=1e-9)
            assert result.can_topple is False
            assert result.override_reason == "architectural_function"
        elif mass <= MASS_THRESHOLD_KG:
            # Branch 2: Light object → DYNAMIC
            assert result.body_mode == "DYNAMIC"
            assert math.isclose(result.mass_kg, mass, rel_tol=1e-9), (
                f"Mass mismatch: expected {mass}, got {result.mass_kg}"
            )
            assert math.isclose(result.friction, 0.5, rel_tol=1e-9)
            assert math.isclose(result.restitution, 0.2, rel_tol=1e-9)
            assert result.can_topple is True
            assert result.override_reason is None
        else:
            # Branch 3: Heavy object → STATIC
            assert result.body_mode == "STATIC"
            assert result.mass_kg == 0.0
            assert math.isclose(result.friction, 0.6, rel_tol=1e-9)
            assert math.isclose(result.restitution, 0.1, rel_tol=1e-9)
            assert result.can_topple is False
            assert result.override_reason is None

    @given(
        dimensions=_dimensions,
        material=_known_material,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_architectural_always_static(
        self,
        dimensions: tuple[float, float, float],
        material: str,
    ) -> None:
        """Architectural objects are always STATIC regardless of mass.

        **Validates: Requirement 6.5**
        """
        classifier = PhysicsClassifier()
        result = classifier.classify(dimensions, material, is_architectural=True)

        assert result.body_mode == "STATIC"
        assert result.mass_kg == 0.0
        assert result.can_topple is False
        assert result.override_reason == "architectural_function"

    @given(
        dimensions=_dimensions,
        material=_any_material,
    )
    @settings(
        max_examples=200,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_dynamic_iff_mass_at_or_below_threshold(
        self,
        dimensions: tuple[float, float, float],
        material: str,
    ) -> None:
        """Non-architectural objects are DYNAMIC iff mass ≤ 25kg.

        **Validates: Requirements 6.1, 6.3, 6.4**
        """
        classifier = PhysicsClassifier()
        result = classifier.classify(dimensions, material, is_architectural=False)

        w, h, d = dimensions
        volume = w * h * d
        density = DENSITY_TABLE.get(material, DEFAULT_DENSITY)
        mass = volume * density

        if mass <= MASS_THRESHOLD_KG:
            assert result.body_mode == "DYNAMIC", (
                f"Expected DYNAMIC for mass={mass:.4f}kg (≤ {MASS_THRESHOLD_KG}kg)"
            )
            assert math.isclose(result.mass_kg, mass, rel_tol=1e-9)
            assert result.can_topple is True
        else:
            assert result.body_mode == "STATIC", (
                f"Expected STATIC for mass={mass:.4f}kg (> {MASS_THRESHOLD_KG}kg)"
            )
            assert result.mass_kg == 0.0
            assert result.can_topple is False

    @given(
        dimensions=_dimensions,
        material=_unknown_material,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    def test_unknown_material_uses_default_density(
        self,
        dimensions: tuple[float, float, float],
        material: str,
    ) -> None:
        """Unknown materials default to density 950.0 kg/m³.

        **Validates: Requirement 6.2**
        """
        classifier = PhysicsClassifier()
        result = classifier.classify(dimensions, material, is_architectural=False)

        assert math.isclose(result.material_density, DEFAULT_DENSITY, rel_tol=1e-9), (
            f"Unknown material '{material}' should use default density "
            f"{DEFAULT_DENSITY}, got {result.material_density}"
        )
