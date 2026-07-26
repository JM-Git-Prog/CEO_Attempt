"""Property-based tests for RuntimePlan template hash integrity (Property 14).

**Validates: Requirements 11.3**

Property 14: RuntimePlan Template Hash Integrity
- For any valid RuntimePlan, each template source SHA-256 matches the
  corresponding entry in template_hashes.
- Every template_id in template_hashes has a corresponding entry in template_sources.
- The hash is computed as hashlib.sha256(source.encode("utf-8")).hexdigest().
"""

from __future__ import annotations

import hashlib

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import (
    RUNTIME_TEMPLATES,
    RuntimePlan,
    build_runtime_plan,
)
from tests.upbge_test_support import build_test_contract


# ---------------------------------------------------------------------------
# Property 14: RuntimePlan Template Hash Integrity (via build_runtime_plan)
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    angle=st.floats(min_value=10.0, max_value=170.0, allow_nan=False, allow_infinity=False),
    speed=st.floats(min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False),
    mass=st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False),
)
def test_property_14_template_hash_integrity_via_build(
    angle: float, speed: float, mass: float,
):
    """Property 14: Each template source SHA-256 matches template_hashes entry.

    **Validates: Requirements 11.3**

    For any RuntimePlan built from a valid WorldContract with varying interaction
    parameters, the SHA-256 hash of each template source in template_sources must
    exactly match the corresponding hash recorded in template_hashes.
    """
    contract = build_test_contract(interactions=(
        {"id": "door-action", "kind": "door", "subject_id": "door_south",
         "parameters": {"open_angle_deg": angle, "speed_deg_s": speed}},
        {"id": "grab-action", "kind": "grab", "subject_id": "door_south",
         "parameters": {"max_mass_kg": mass}},
    ))
    plan = build_runtime_plan(contract)

    # Build lookup from template_sources: template_id -> source
    sources_by_id = {
        template_id: source
        for template_id, _entrypoint, source in plan.template_sources
    }

    # Verify every hash entry has a matching source and the hash is correct
    for template_id, declared_hash in plan.template_hashes:
        assert template_id in sources_by_id, (
            f"template_hashes references '{template_id}' but no matching "
            f"entry exists in template_sources"
        )
        computed_hash = hashlib.sha256(
            sources_by_id[template_id].encode("utf-8")
        ).hexdigest()
        assert computed_hash == declared_hash, (
            f"Hash mismatch for template '{template_id}': "
            f"computed={computed_hash!r}, declared={declared_hash!r}"
        )


@settings(max_examples=50, deadline=None)
@given(
    source_text=st.text(
        min_size=1, max_size=500,
        alphabet=st.characters(whitelist_categories=("L", "Nd", "P", "Zs", "Cc")),
    ),
)
def test_property_14_sha256_computation_is_deterministic(source_text: str):
    """Property 14 (supplementary): SHA-256 of source is deterministic.

    **Validates: Requirements 11.3**

    For any source string, computing SHA-256 via hashlib.sha256(source.encode("utf-8"))
    always produces the same hex digest, ensuring the hash integrity check is stable.
    """
    hash_a = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    hash_b = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    assert hash_a == hash_b
    assert len(hash_a) == 64
    assert all(c in "0123456789abcdef" for c in hash_a)


def test_property_14_all_runtime_templates_covered():
    """Property 14 (coverage): build_runtime_plan covers all RUNTIME_TEMPLATES.

    **Validates: Requirements 11.3**

    The RuntimePlan produced by build_runtime_plan must include hash entries for
    every template in the RUNTIME_TEMPLATES constant, and each hash must match
    the template's sha256 property.
    """
    contract = build_test_contract()
    plan = build_runtime_plan(contract)

    expected_ids = {t.template_id for t in RUNTIME_TEMPLATES}
    actual_hash_ids = {template_id for template_id, _hash in plan.template_hashes}
    actual_source_ids = {template_id for template_id, _ep, _src in plan.template_sources}

    # All templates must appear in both hashes and sources
    assert actual_hash_ids == expected_ids, (
        f"template_hashes missing templates: {expected_ids - actual_hash_ids}"
    )
    assert actual_source_ids == expected_ids, (
        f"template_sources missing templates: {expected_ids - actual_source_ids}"
    )

    # Each hash must match the RuntimeTemplateSpec.sha256 property
    hash_lookup = dict(plan.template_hashes)
    for template in RUNTIME_TEMPLATES:
        assert hash_lookup[template.template_id] == template.sha256, (
            f"Hash mismatch for {template.template_id}: "
            f"plan has {hash_lookup[template.template_id]!r}, "
            f"template.sha256 is {template.sha256!r}"
        )
