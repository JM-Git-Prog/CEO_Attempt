"""Property-based tests for interaction hit classification (Property 9).

**Validates: Requirements 4.2, 4.3, 4.4, 4.5**

Property 9: Interaction Hit Classification
- For any raycast hit object: door trigger (has `kiro_open_angle_deg`), grab
  (dynamic + rule match), or no action — mutually exclusive and exhaustive.
- Door classification takes priority over grab.
- Mass validation: mass > max_mass → "none"; mass == max_mass → "grab".
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from src.upbge_runtime import classify_interaction_hit


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Stable IDs used in both hit_properties and grab_rules
stable_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=0,
    max_size=20,
)

# Positive floats for mass values
mass_strategy = st.floats(
    min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
)

# A grab rule dict with max_mass_kg
grab_rule_strategy = st.fixed_dictionaries({
    "max_mass_kg": mass_strategy,
}).map(lambda d: {k: str(v) for k, v in d.items()})

# Random grab_rules dict: mapping stable_id -> rule
grab_rules_strategy = st.dictionaries(
    keys=stable_id_strategy,
    values=grab_rule_strategy,
    min_size=0,
    max_size=5,
)

# Random hit_properties with varying combinations of relevant keys
hit_properties_strategy = st.fixed_dictionaries(
    mapping={},
    optional={
        "kiro_open_angle_deg": st.floats(
            min_value=-180.0, max_value=180.0,
            allow_nan=False, allow_infinity=False,
        ),
        "kiro_body_mode": st.sampled_from(["dynamic", "static", "kinematic", "rigid"]),
        "kiro_stable_id": stable_id_strategy,
        "kiro_mass_kg": mass_strategy,
    },
)


# ---------------------------------------------------------------------------
# Property 9a: Classification is always one of {"door", "grab", "none"}
# (Exhaustiveness)
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    hit_properties=hit_properties_strategy,
    grab_rules=grab_rules_strategy,
)
def test_property_9_classification_exhaustive(
    hit_properties: dict,
    grab_rules: dict,
):
    """Property 9: Result is always one of the three valid classifications.

    **Validates: Requirements 4.2, 4.3, 4.4, 4.5**

    For any combination of hit_properties and grab_rules, classify_interaction_hit
    SHALL return exactly one of {"door", "grab", "none"}.
    """
    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result in {"door", "grab", "none"}, (
        f"Classification must be 'door', 'grab', or 'none', got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 9b: Door priority — kiro_open_angle_deg present → always "door"
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    hit_properties=hit_properties_strategy.filter(
        lambda p: "kiro_open_angle_deg" in p
    ),
    grab_rules=grab_rules_strategy,
)
def test_property_9_door_priority(
    hit_properties: dict,
    grab_rules: dict,
):
    """Property 9: Door takes priority over grab.

    **Validates: Requirements 4.2, 4.3**

    If hit_properties contains kiro_open_angle_deg, the result SHALL always be
    "door" regardless of other properties (including dynamic body mode).
    """
    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result == "door", (
        f"Expected 'door' when kiro_open_angle_deg is present, got '{result}'. "
        f"hit_properties={hit_properties}"
    )


# ---------------------------------------------------------------------------
# Property 9c: Grab classification — dynamic + matching rule + mass OK → "grab"
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    stable_id=stable_id_strategy.filter(lambda s: len(s) > 0),
    obj_mass=st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
    max_mass_offset=st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_9_grab_when_dynamic_rule_match_mass_ok(
    stable_id: str,
    obj_mass: float,
    max_mass_offset: float,
):
    """Property 9: Grab classification when dynamic + rule match + mass <= max_mass.

    **Validates: Requirements 4.4, 4.5**

    If hit is dynamic, has a matching grab rule, and mass <= max_mass_kg,
    the result SHALL be "grab" (no kiro_open_angle_deg present).
    """
    max_mass = obj_mass + max_mass_offset  # Ensures max_mass >= obj_mass

    hit_properties = {
        "kiro_body_mode": "dynamic",
        "kiro_stable_id": stable_id,
        "kiro_mass_kg": obj_mass,
    }
    grab_rules = {
        stable_id: {"max_mass_kg": str(max_mass)},
    }

    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result == "grab", (
        f"Expected 'grab' for dynamic body with matching rule and "
        f"mass({obj_mass}) <= max_mass({max_mass}), got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 9d: Mass exceeds max → "none" (not "grab")
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    stable_id=stable_id_strategy.filter(lambda s: len(s) > 0),
    max_mass=st.floats(
        min_value=0.0, max_value=499.0, allow_nan=False, allow_infinity=False
    ),
    excess=st.floats(
        min_value=0.01, max_value=500.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_9_no_grab_when_mass_exceeds_max(
    stable_id: str,
    max_mass: float,
    excess: float,
):
    """Property 9: Mass validation rejects grab when mass > max_mass_kg.

    **Validates: Requirements 4.4, 4.5**

    If hit is dynamic with a matching rule but obj_mass > max_mass_kg,
    the result SHALL be "none".
    """
    obj_mass = max_mass + excess  # Ensures obj_mass > max_mass

    hit_properties = {
        "kiro_body_mode": "dynamic",
        "kiro_stable_id": stable_id,
        "kiro_mass_kg": obj_mass,
    }
    grab_rules = {
        stable_id: {"max_mass_kg": str(max_mass)},
    }

    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result == "none", (
        f"Expected 'none' when mass({obj_mass}) > max_mass({max_mass}), "
        f"got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 9e: Mass boundary — mass == max_mass → "grab" (boundary is <=)
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    stable_id=stable_id_strategy.filter(lambda s: len(s) > 0),
    mass=st.floats(
        min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_property_9_grab_at_exact_mass_boundary(
    stable_id: str,
    mass: float,
):
    """Property 9: Mass boundary — exactly equal mass is grabbable.

    **Validates: Requirements 4.4, 4.5**

    If obj_mass == max_mass_kg exactly, the result SHALL be "grab"
    (the boundary condition is <=, not <).
    """
    hit_properties = {
        "kiro_body_mode": "dynamic",
        "kiro_stable_id": stable_id,
        "kiro_mass_kg": mass,
    }
    grab_rules = {
        stable_id: {"max_mass_kg": str(mass)},
    }

    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result == "grab", (
        f"Expected 'grab' when mass({mass}) == max_mass({mass}), got '{result}'. "
        f"Boundary condition should be <= (inclusive)."
    )


# ---------------------------------------------------------------------------
# Property 9f: No kiro_open_angle_deg + not dynamic → "none"
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    body_mode=st.sampled_from(["static", "kinematic", "rigid", "no_collision"]),
    stable_id=stable_id_strategy,
    grab_rules=grab_rules_strategy,
)
def test_property_9_none_when_not_door_not_dynamic(
    body_mode: str,
    stable_id: str,
    grab_rules: dict,
):
    """Property 9: Non-door, non-dynamic objects → "none".

    **Validates: Requirements 4.2, 4.3, 4.4, 4.5**

    If hit has no kiro_open_angle_deg and body_mode is not "dynamic",
    the result SHALL always be "none" regardless of grab rules.
    """
    hit_properties = {
        "kiro_body_mode": body_mode,
        "kiro_stable_id": stable_id,
    }

    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result == "none", (
        f"Expected 'none' for non-dynamic body_mode='{body_mode}', "
        f"got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 9g: Dynamic but no matching rule → "none"
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    stable_id=stable_id_strategy,
    obj_mass=mass_strategy,
)
def test_property_9_none_when_dynamic_but_no_rule(
    stable_id: str,
    obj_mass: float,
):
    """Property 9: Dynamic body without a matching grab rule → "none".

    **Validates: Requirements 4.4, 4.5**

    If hit is dynamic but no grab rule exists for its stable_id,
    the result SHALL be "none".
    """
    hit_properties = {
        "kiro_body_mode": "dynamic",
        "kiro_stable_id": stable_id,
        "kiro_mass_kg": obj_mass,
    }
    # Empty grab_rules — no rule matches
    grab_rules: dict = {}

    result = classify_interaction_hit(hit_properties, grab_rules)
    assert result == "none", (
        f"Expected 'none' when no grab rule exists for stable_id='{stable_id}', "
        f"got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 9h: Mutual exclusivity — result cannot be two things at once
# ---------------------------------------------------------------------------


@settings(max_examples=500, deadline=None)
@given(
    hit_properties=hit_properties_strategy,
    grab_rules=grab_rules_strategy,
)
def test_property_9_mutual_exclusivity(
    hit_properties: dict,
    grab_rules: dict,
):
    """Property 9: Classifications are mutually exclusive.

    **Validates: Requirements 4.2, 4.3, 4.4, 4.5**

    The function returns exactly one string — not a set, list, or multiple
    values. The three outcomes are logically exclusive given the priority rules:
    - door: kiro_open_angle_deg present (checked first)
    - grab: dynamic + rule match + mass ok (only if not door)
    - none: everything else
    """
    result = classify_interaction_hit(hit_properties, grab_rules)

    # Verify exactly one classification
    is_door = result == "door"
    is_grab = result == "grab"
    is_none = result == "none"

    assert sum([is_door, is_grab, is_none]) == 1, (
        f"Exactly one classification must be true, got door={is_door}, "
        f"grab={is_grab}, none={is_none}, result='{result}'"
    )

    # Verify consistency with input
    if "kiro_open_angle_deg" in hit_properties:
        assert result == "door", (
            f"Door should take priority when kiro_open_angle_deg present"
        )
    elif result == "grab":
        # If grab, then must be dynamic with matching rule
        assert hit_properties.get("kiro_body_mode") == "dynamic", (
            f"Grab requires dynamic body mode"
        )
