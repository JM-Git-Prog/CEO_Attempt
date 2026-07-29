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
"""

from __future__ import annotations

import math

from hypothesis import given, settings
from hypothesis import strategies as st

from src.photo_pipeline.stages.physics_classifier import PhysicsClassifier


# ---------------------------------------------------------------------------
# Density table (oracle for property verification)
# ---------------------------------------------------------------------------

DENSITY_TABLE: dict[str, float] = {
    "wood": 600.0,
    "metal": 7800.0,
    "glass": 2500.0,
    "fabric": 200.0,
    "ceramic": 2300.0,
    "plastic": 950.0,
}
MASS_THRESHOLD_KG: float = 25.0


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

dimensions_m = st.tuples(
    st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
)

material_st = st.sampled_from(list(DENSITY_TABLE.keys()))

is_architectural_st = st.booleans()


# ---------------------------------------------------------------------------
# Property 11: Physics Classification Correctness
# ---------------------------------------------------------------------------


class TestPhysicsClassificationCorrectness:
    """Property 11: Physics Classification Correctness.

    **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
    """

    @given(
        dims=dimensions_m,
        material=material_st,
        is_architectural=is_architectural_st,
    )
    @settings(max_examples=50, deadline=None)
    def test_physics_classification_correctness(
        self,
        dims: tuple[float, float, float],
        material: str,
        is_architectural: bool,
    ) -> None:
        """For any valid object inputs, the classifier produces correct outputs
        matching all three classification branches.

        **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5**
        """
        classifier = PhysicsClassifier()
        result = classifier.classify(dims, material, is_architectural)

        w, h, d = dims
        volume = w * h * d
        density = DENSITY_TABLE[material]
        mass = volume * density

        # Common invariants: volume and density always recorded
        assert math.isclose(result.volume_m3, volume, rel_tol=1e-9)
        assert math.isclose(result.material_density, density, rel_tol=1e-9)

        if is_architectural:
            # Branch 1: Architectural → always STATIC
            assert result.body_mode == "STATIC"
            assert result.mass_kg == 0.0
            assert math.isclose(result.friction, 0.6, rel_tol=1e-9)
            assert math.isclose(result.restitution, 0.1, rel_tol=1e-9)
            assert result.can_topple is False
        elif mass <= MASS_THRESHOLD_KG:
            # Branch 2: Light non-architectural → DYNAMIC
            assert result.body_mode == "DYNAMIC"
            assert math.isclose(result.mass_kg, mass, rel_tol=1e-9)
            assert math.isclose(result.friction, 0.5, rel_tol=1e-9)
            assert math.isclose(result.restitution, 0.2, rel_tol=1e-9)
            assert result.can_topple is True
        else:
            # Branch 3: Heavy non-architectural → STATIC
            assert result.body_mode == "STATIC"
            assert result.mass_kg == 0.0
            assert math.isclose(result.friction, 0.6, rel_tol=1e-9)
            assert math.isclose(result.restitution, 0.1, rel_tol=1e-9)
            assert result.can_topple is False
