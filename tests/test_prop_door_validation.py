"""Property-based tests for door interaction parameter validation (Property 7).

**Validates: Requirements 5.1, 5.5**

Property 7: Door Interaction Parameter Validation
- For any door interaction intent, RuntimePlan accepts iff open_angle_deg in [-180,180]
  non-zero AND speed_deg_s in (0,720] AND physics is not trigger body mode.
- Door subject must have explicit physics intent.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings, assume, strategies as st

from src.world_contract import (
    BodyMode,
    PhysicsIntent,
    PhysicsPolicy,
    WorldContract,
)
from src.upbge_runtime import build_runtime_plan
from tests.upbge_test_support import build_test_contract


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contract_with_door_params(
    *,
    open_angle_deg: float = 90.0,
    speed_deg_s: float = 120.0,
    initially_open: bool = False,
) -> WorldContract:
    """Build a test contract with a single door interaction using specified params."""
    return build_test_contract(interactions=(
        {
            "id": "door-action",
            "kind": "door",
            "subject_id": "door_south",
            "parameters": {
                "open_angle_deg": open_angle_deg,
                "speed_deg_s": speed_deg_s,
                "initially_open": initially_open,
            },
        },
    ))


def _contract_with_door_physics(body_mode: str) -> WorldContract:
    """Build a contract where door_south has the specified body mode."""
    contract = build_test_contract(interactions=(
        {
            "id": "door-action",
            "kind": "door",
            "subject_id": "door_south",
            "parameters": {"open_angle_deg": 90.0},
        },
    ))
    new_intents = []
    for intent in contract.physics.intents:
        if intent.subject_id == "door_south":
            new_intents.append(PhysicsIntent(
                id=intent.id,
                subject_id=intent.subject_id,
                body_mode=BodyMode(body_mode),
                collision_shape=intent.collision_shape,
                mass_kg=intent.mass_kg if body_mode == "dynamic" else 0.0,
                friction=intent.friction,
                restitution=intent.restitution,
                can_topple=False,
            ))
        else:
            new_intents.append(intent)
    return contract.model_copy(update={
        "physics": PhysicsPolicy(intents=tuple(new_intents)),
    })


def _contract_without_door_physics() -> WorldContract:
    """Build a contract where door_south has NO physics intent at all."""
    contract = build_test_contract(interactions=(
        {
            "id": "door-action",
            "kind": "door",
            "subject_id": "door_south",
            "parameters": {"open_angle_deg": 90.0},
        },
    ))
    new_intents = tuple(
        intent for intent in contract.physics.intents
        if intent.subject_id != "door_south"
    )
    return contract.model_copy(update={
        "physics": PhysicsPolicy(intents=new_intents),
    })


# ---------------------------------------------------------------------------
# Property 7.1: Valid door parameters with acceptable physics are ACCEPTED
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(
    angle=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0.0),
    speed=st.floats(min_value=0.01, max_value=720.0, allow_nan=False, allow_infinity=False),
    initially_open=st.booleans(),
    body_mode=st.sampled_from(["static", "kinematic", "dynamic"]),
)
def test_property_7_valid_door_params_accepted(
    angle: float, speed: float, initially_open: bool, body_mode: str,
):
    """Property 7: Valid door parameters with non-trigger physics produce a RuntimePlan.

    **Validates: Requirements 5.1, 5.5**

    For any open_angle_deg in [-180,180] (non-zero), speed_deg_s in (0,720],
    initially_open as bool, and physics body mode in {static, kinematic, dynamic},
    build_runtime_plan must succeed and produce a door binding with matching params.
    """
    # Build contract with specified params
    contract = _contract_with_door_params(
        open_angle_deg=angle,
        speed_deg_s=speed,
        initially_open=initially_open,
    )
    # Patch physics to the chosen body_mode
    new_intents = []
    for intent in contract.physics.intents:
        if intent.subject_id == "door_south":
            new_intents.append(PhysicsIntent(
                id=intent.id,
                subject_id=intent.subject_id,
                body_mode=BodyMode(body_mode),
                collision_shape=intent.collision_shape,
                mass_kg=intent.mass_kg if body_mode == "dynamic" else 0.0,
                friction=intent.friction,
                restitution=intent.restitution,
                can_topple=False,
            ))
        else:
            new_intents.append(intent)
    contract = contract.model_copy(update={
        "physics": PhysicsPolicy(intents=tuple(new_intents)),
    })

    plan = build_runtime_plan(contract)
    door_binding = next(b for b in plan.interactions if b.kind == "door")
    params = dict(door_binding.parameters)
    assert params["open_angle_deg"] == angle
    assert params["speed_deg_s"] == speed
    assert params["initially_open"] is initially_open


# ---------------------------------------------------------------------------
# Property 7.2: Invalid door parameters are REJECTED with ValueError
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(
    angle=st.one_of(
        # Zero angle (invalid)
        st.just(0.0),
        # Below -180 (invalid)
        st.floats(min_value=-1e6, max_value=-180.01, allow_nan=False, allow_infinity=False),
        # Above 180 (invalid)
        st.floats(min_value=180.01, max_value=1e6, allow_nan=False, allow_infinity=False),
    ),
    speed=st.floats(min_value=0.01, max_value=720.0, allow_nan=False, allow_infinity=False),
    initially_open=st.booleans(),
)
def test_property_7_invalid_angle_rejected(
    angle: float, speed: float, initially_open: bool,
):
    """Property 7: Invalid open_angle_deg raises ValueError.

    **Validates: Requirements 5.1, 5.5**

    For open_angle_deg = 0 or outside [-180, 180], build_runtime_plan must reject
    with ValueError regardless of other valid parameters.
    """
    with pytest.raises(ValueError):
        build_runtime_plan(_contract_with_door_params(
            open_angle_deg=angle,
            speed_deg_s=speed,
            initially_open=initially_open,
        ))


@settings(max_examples=50, deadline=None)
@given(
    angle=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0.0),
    speed=st.one_of(
        # Zero speed (invalid)
        st.just(0.0),
        # Negative speed (invalid)
        st.floats(min_value=-1e6, max_value=-0.01, allow_nan=False, allow_infinity=False),
        # Above 720 (invalid)
        st.floats(min_value=720.01, max_value=1e6, allow_nan=False, allow_infinity=False),
    ),
    initially_open=st.booleans(),
)
def test_property_7_invalid_speed_rejected(
    angle: float, speed: float, initially_open: bool,
):
    """Property 7: Invalid speed_deg_s raises ValueError.

    **Validates: Requirements 5.1, 5.5**

    For speed_deg_s <= 0 or > 720, build_runtime_plan must reject with ValueError
    regardless of other valid parameters.
    """
    with pytest.raises(ValueError):
        build_runtime_plan(_contract_with_door_params(
            open_angle_deg=angle,
            speed_deg_s=speed,
            initially_open=initially_open,
        ))


# ---------------------------------------------------------------------------
# Property 7.3: Trigger body mode is REJECTED
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(
    angle=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0.0),
    speed=st.floats(min_value=0.01, max_value=720.0, allow_nan=False, allow_infinity=False),
    initially_open=st.booleans(),
)
def test_property_7_trigger_physics_rejected(
    angle: float, speed: float, initially_open: bool,
):
    """Property 7: Door with trigger body mode raises ValueError.

    **Validates: Requirements 5.1, 5.5**

    For any valid door parameters, if the door subject uses trigger body mode,
    build_runtime_plan must reject with ValueError.
    """
    contract = _contract_with_door_params(
        open_angle_deg=angle,
        speed_deg_s=speed,
        initially_open=initially_open,
    )
    # Patch physics to trigger
    new_intents = []
    for intent in contract.physics.intents:
        if intent.subject_id == "door_south":
            new_intents.append(PhysicsIntent(
                id=intent.id,
                subject_id=intent.subject_id,
                body_mode=BodyMode("trigger"),
                collision_shape=intent.collision_shape,
                mass_kg=0.0,
                friction=intent.friction,
                restitution=intent.restitution,
                can_topple=False,
            ))
        else:
            new_intents.append(intent)
    contract = contract.model_copy(update={
        "physics": PhysicsPolicy(intents=tuple(new_intents)),
    })

    with pytest.raises(ValueError, match="cannot use a trigger body"):
        build_runtime_plan(contract)


# ---------------------------------------------------------------------------
# Property 7.4: Missing physics intent is REJECTED
# ---------------------------------------------------------------------------

@settings(max_examples=50, deadline=None)
@given(
    angle=st.floats(min_value=-180.0, max_value=180.0, allow_nan=False, allow_infinity=False).filter(lambda x: x != 0.0),
    speed=st.floats(min_value=0.01, max_value=720.0, allow_nan=False, allow_infinity=False),
    initially_open=st.booleans(),
)
def test_property_7_missing_physics_rejected(
    angle: float, speed: float, initially_open: bool,
):
    """Property 7: Door without physics intent raises ValueError.

    **Validates: Requirements 5.1, 5.5**

    For any valid door parameters, if the door subject has no physics intent at all,
    build_runtime_plan must reject with ValueError.
    """
    contract = _contract_with_door_params(
        open_angle_deg=angle,
        speed_deg_s=speed,
        initially_open=initially_open,
    )
    # Remove physics intent for door_south
    new_intents = tuple(
        intent for intent in contract.physics.intents
        if intent.subject_id != "door_south"
    )
    contract = contract.model_copy(update={
        "physics": PhysicsPolicy(intents=new_intents),
    })

    with pytest.raises(ValueError, match="requires explicit physics intent"):
        build_runtime_plan(contract)
