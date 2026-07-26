"""Property-based tests for CompilerPlan deterministic hash (Property 13).

**Validates: Requirements 11.2**

Property 13: CompilerPlan Deterministic Hash
- For any valid CompilerPlan inputs (WorldContract + output flags + compiler limits +
  wall thickness), building the CompilerPlan twice produces identical SHA-256 hashes
  via `content_hash()`.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.upbge_compiler import (
    CompilerLimits,
    CompilerOutputFlags,
    build_compiler_plan,
)
from tests.upbge_test_support import build_test_contract


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_output_flags = st.builds(
    CompilerOutputFlags,
    render=st.booleans(),
    blend=st.booleans(),
    glb=st.booleans(),
    runtime=st.booleans(),
)

_wall_thickness = st.floats(
    min_value=0.01, max_value=1.0, allow_nan=False, allow_infinity=False,
)


# ---------------------------------------------------------------------------
# Property 13: deterministic hash
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(flags=_output_flags, wall_thickness_m=_wall_thickness)
def test_property_compiler_plan_deterministic_hash(
    flags: CompilerOutputFlags,
    wall_thickness_m: float,
) -> None:
    """Building CompilerPlan twice with identical inputs produces identical SHA-256 hash.

    **Validates: Requirements 11.2**
    """
    contract = build_test_contract()

    first = build_compiler_plan(contract, outputs=flags, wall_thickness_m=wall_thickness_m)
    second = build_compiler_plan(contract, outputs=flags, wall_thickness_m=wall_thickness_m)

    assert first.canonical_bytes() == second.canonical_bytes(), (
        "canonical_bytes() differ for identical inputs"
    )
    assert first.content_hash() == second.content_hash(), (
        "content_hash() differ for identical inputs"
    )


# ---------------------------------------------------------------------------
# Sanity check: different inputs → different hashes
# ---------------------------------------------------------------------------


@settings(max_examples=50)
@given(
    flags_a=_output_flags,
    flags_b=_output_flags,
    wall_a=_wall_thickness,
    wall_b=_wall_thickness,
)
def test_property_different_inputs_produce_different_hashes(
    flags_a: CompilerOutputFlags,
    flags_b: CompilerOutputFlags,
    wall_a: float,
    wall_b: float,
) -> None:
    """Different CompilerPlan inputs should generally produce different hashes.

    We only assert when we know the inputs are actually different — this is a
    sanity check rather than a strict invariant, since hash collisions are
    theoretically possible but astronomically unlikely for SHA-256.
    """
    # Skip when both input sets are identical
    if (flags_a.render == flags_b.render and flags_a.blend == flags_b.blend
            and flags_a.glb == flags_b.glb and flags_a.runtime == flags_b.runtime
            and wall_a == wall_b):
        return

    contract = build_test_contract()

    plan_a = build_compiler_plan(contract, outputs=flags_a, wall_thickness_m=wall_a)
    plan_b = build_compiler_plan(contract, outputs=flags_b, wall_thickness_m=wall_b)

    # Different inputs should yield different canonical bytes (and thus different hashes)
    assert plan_a.content_hash() != plan_b.content_hash(), (
        f"Hash collision: different inputs produced the same hash. "
        f"flags_a={flags_a}, wall_a={wall_a}, flags_b={flags_b}, wall_b={wall_b}"
    )
