"""Property-based tests for gravity force computation (Property 4).

**Validates: Requirements 2.4**

Property 4: Gravity Force Computation
- For any gravity ∈ [0.0, 50.0] and mass ≥ 1.0, the applied force vector
  SHALL be exactly (0.0, 0.0, -g * max(m, 1.0)).
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import compute_gravity_force


# ---------------------------------------------------------------------------
# Property 4: Gravity Force Computation
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    gravity=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    mass=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_property_4_gravity_force_computation(gravity: float, mass: float):
    """Property 4: Force vector is exactly (0, 0, -gravity * max(mass, 1.0)).

    **Validates: Requirements 2.4**

    For any gravity in [0.0, 50.0] and mass in [0.01, 1000.0], the computed
    gravity force must have x=0, y=0, and z = -gravity * max(mass, 1.0).
    """
    result = compute_gravity_force(gravity, mass)

    effective_mass = max(mass, 1.0)
    expected_z = -gravity * effective_mass

    # X component always zero
    assert result[0] == 0.0, f"x component must be 0.0, got {result[0]}"

    # Y component always zero
    assert result[1] == 0.0, f"y component must be 0.0, got {result[1]}"

    # Z component is exact (deterministic floating-point arithmetic)
    assert result[2] == expected_z, (
        f"z component must be {expected_z}, got {result[2]} "
        f"(gravity={gravity}, mass={mass}, effective_mass={effective_mass})"
    )


@settings(max_examples=500, deadline=None)
@given(
    gravity=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    mass=st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False),
)
def test_property_4_mass_floor_behavior(gravity: float, mass: float):
    """Property 4 (mass floor): When mass < 1.0, effective mass is floored to 1.0.

    **Validates: Requirements 2.4**

    For any mass below 1.0, the function must use 1.0 as the effective mass,
    producing the same result as compute_gravity_force(gravity, 1.0).
    """
    result = compute_gravity_force(gravity, mass)
    result_at_one = compute_gravity_force(gravity, 1.0)

    # When mass < 1.0, result must equal result with mass=1.0
    assert result == result_at_one, (
        f"Mass floor violated: mass={mass} gave {result}, "
        f"but mass=1.0 gave {result_at_one}"
    )

    # Explicitly verify the z component uses effective_mass=1.0
    assert result[2] == -gravity * 1.0, (
        f"z component must be {-gravity * 1.0} when mass < 1.0, got {result[2]}"
    )


@settings(max_examples=500, deadline=None)
@given(
    mass=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_property_4_zero_gravity_produces_zero_force(mass: float):
    """Property 4 (zero gravity): When gravity == 0.0, force is (0, 0, 0).

    **Validates: Requirements 2.4**

    Regardless of mass, zero gravity must produce a zero force vector.
    """
    result = compute_gravity_force(0.0, mass)

    assert result == (0.0, 0.0, 0.0), (
        f"Zero gravity must produce (0,0,0), got {result} with mass={mass}"
    )


@settings(max_examples=500, deadline=None)
@given(
    gravity=st.floats(min_value=0.0, max_value=50.0, allow_nan=False, allow_infinity=False),
    mass=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
)
def test_property_4_force_always_non_positive_z(gravity: float, mass: float):
    """Property 4 (direction): Force z-component is always <= 0 (downward).

    **Validates: Requirements 2.4**

    Since gravity is non-negative and mass is positive, the resulting force
    in z must always be non-positive (pointing downward in world space).
    """
    result = compute_gravity_force(gravity, mass)

    assert result[2] <= 0.0, (
        f"Force z must be non-positive (downward), got {result[2]} "
        f"(gravity={gravity}, mass={mass})"
    )
