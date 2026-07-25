"""Focused tests for door interaction parameter validation in RuntimePlan builder.

Validates Requirements 5.1 and 5.5:
- 5.1: RuntimePlan accepts door interaction iff open_angle_deg in [-180,180] non-zero
        AND speed_deg_s in (0,720] AND physics is explicit (not trigger)
- 5.5: RuntimePlan builder rejects WorldContract with structured error if door subject
        lacks explicit physics intent or uses trigger body mode
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.world_contract import (
    BodyMode,
    InteractionIntent,
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
    """Build a contract where door_south has the specified body mode for physics."""
    contract = build_test_contract(interactions=(
        {
            "id": "door-action",
            "kind": "door",
            "subject_id": "door_south",
            "parameters": {"open_angle_deg": 90.0},
        },
    ))
    # Patch physics intent for door_south to specified body_mode
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
    # Rebuild contract with patched physics
    patched = contract.model_copy(update={
        "physics": PhysicsPolicy(intents=tuple(new_intents)),
    })
    return patched


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
    # Remove physics intent for door_south
    new_intents = tuple(
        intent for intent in contract.physics.intents
        if intent.subject_id != "door_south"
    )
    patched = contract.model_copy(update={
        "physics": PhysicsPolicy(intents=new_intents),
    })
    return patched


# ---------------------------------------------------------------------------
# Requirement 5.1 — Valid door parameters are accepted
# ---------------------------------------------------------------------------

class TestDoorParameterAcceptance:
    """Valid door parameters produce a RuntimePlan with correct bindings."""

    def test_default_parameters_accepted(self):
        """Door with default params (90°, 120°/s, initially_open=False) is accepted."""
        contract = build_test_contract(interactions=(
            {"id": "door-action", "kind": "door", "subject_id": "door_south",
             "parameters": {}},
        ))
        plan = build_runtime_plan(contract)
        door_binding = next(b for b in plan.interactions if b.kind == "door")
        params = dict(door_binding.parameters)
        assert params["open_angle_deg"] == 90.0
        assert params["speed_deg_s"] == 120.0
        assert params["initially_open"] is False

    def test_negative_angle_accepted(self):
        """Negative open_angle_deg (swing other direction) is valid."""
        plan = build_runtime_plan(_contract_with_door_params(open_angle_deg=-90.0))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["open_angle_deg"] == -90.0

    def test_boundary_angle_minus_180_accepted(self):
        """open_angle_deg = -180 is valid (boundary)."""
        plan = build_runtime_plan(_contract_with_door_params(open_angle_deg=-180.0))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["open_angle_deg"] == -180.0

    def test_boundary_angle_plus_180_accepted(self):
        """open_angle_deg = 180 is valid (boundary)."""
        plan = build_runtime_plan(_contract_with_door_params(open_angle_deg=180.0))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["open_angle_deg"] == 180.0

    def test_small_positive_angle_accepted(self):
        """Small non-zero angle like 1.0° is valid."""
        plan = build_runtime_plan(_contract_with_door_params(open_angle_deg=1.0))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["open_angle_deg"] == 1.0

    def test_speed_at_maximum_720_accepted(self):
        """speed_deg_s = 720.0 is valid (boundary)."""
        plan = build_runtime_plan(_contract_with_door_params(speed_deg_s=720.0))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["speed_deg_s"] == 720.0

    def test_speed_small_value_accepted(self):
        """speed_deg_s just above 0 is valid."""
        plan = build_runtime_plan(_contract_with_door_params(speed_deg_s=0.01))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["speed_deg_s"] == 0.01

    def test_initially_open_true_accepted(self):
        """initially_open = True is valid."""
        plan = build_runtime_plan(_contract_with_door_params(initially_open=True))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["initially_open"] is True

    def test_initially_open_false_accepted(self):
        """initially_open = False is valid."""
        plan = build_runtime_plan(_contract_with_door_params(initially_open=False))
        params = dict(next(b for b in plan.interactions if b.kind == "door").parameters)
        assert params["initially_open"] is False


# ---------------------------------------------------------------------------
# Requirement 5.1 — Invalid door parameters are rejected
# ---------------------------------------------------------------------------

class TestDoorParameterRejection:
    """Invalid door parameters raise ValueError with descriptive message."""

    def test_angle_zero_rejected(self):
        """open_angle_deg = 0 is rejected (non-zero required)."""
        with pytest.raises(ValueError, match="open_angle_deg must be non-zero"):
            build_runtime_plan(_contract_with_door_params(open_angle_deg=0.0))

    def test_angle_above_180_rejected(self):
        """open_angle_deg > 180 is rejected."""
        with pytest.raises(ValueError, match="open_angle_deg must be non-zero and within"):
            build_runtime_plan(_contract_with_door_params(open_angle_deg=181.0))

    def test_angle_below_minus_180_rejected(self):
        """open_angle_deg < -180 is rejected."""
        with pytest.raises(ValueError, match="open_angle_deg must be non-zero and within"):
            build_runtime_plan(_contract_with_door_params(open_angle_deg=-181.0))

    def test_speed_zero_rejected(self):
        """speed_deg_s = 0 is rejected (must be > 0)."""
        with pytest.raises(ValueError, match="speed_deg_s must be within"):
            build_runtime_plan(_contract_with_door_params(speed_deg_s=0.0))

    def test_speed_negative_rejected(self):
        """speed_deg_s < 0 is rejected."""
        with pytest.raises(ValueError, match="speed_deg_s must be within"):
            build_runtime_plan(_contract_with_door_params(speed_deg_s=-1.0))

    def test_speed_above_720_rejected(self):
        """speed_deg_s > 720 is rejected."""
        with pytest.raises(ValueError, match="speed_deg_s must be within"):
            build_runtime_plan(_contract_with_door_params(speed_deg_s=720.1))

    def test_initially_open_non_boolean_int_rejected(self):
        """initially_open as int (1) is rejected — must be actual bool."""
        contract = build_test_contract(interactions=(
            {"id": "door-action", "kind": "door", "subject_id": "door_south",
             "parameters": {"initially_open": 1}},
        ))
        with pytest.raises(ValueError, match="initially_open must be boolean"):
            build_runtime_plan(contract)

    def test_initially_open_non_boolean_string_rejected(self):
        """initially_open as string is rejected — must be actual bool."""
        contract = build_test_contract(interactions=(
            {"id": "door-action", "kind": "door", "subject_id": "door_south",
             "parameters": {"initially_open": "true"}},
        ))
        with pytest.raises(ValueError, match="initially_open must be boolean"):
            build_runtime_plan(contract)

    def test_angle_nan_rejected(self):
        """open_angle_deg = NaN is rejected by _finite_number."""
        with pytest.raises(ValueError):
            build_runtime_plan(_contract_with_door_params(open_angle_deg=float("nan")))

    def test_angle_inf_rejected(self):
        """open_angle_deg = inf is rejected by _finite_number."""
        with pytest.raises(ValueError):
            build_runtime_plan(_contract_with_door_params(open_angle_deg=float("inf")))

    def test_speed_inf_rejected(self):
        """speed_deg_s = inf is rejected by _finite_number."""
        with pytest.raises(ValueError):
            build_runtime_plan(_contract_with_door_params(speed_deg_s=float("inf")))


# ---------------------------------------------------------------------------
# Requirement 5.5 — Door without physics intent or with trigger body mode
# ---------------------------------------------------------------------------

class TestDoorPhysicsRequirements:
    """Door interactions require explicit physics and reject trigger body mode."""

    def test_door_without_physics_intent_rejected(self):
        """Door subject with no physics intent at all raises ValueError."""
        contract = _contract_without_door_physics()
        with pytest.raises(ValueError, match="requires explicit physics intent"):
            build_runtime_plan(contract)

    def test_door_with_trigger_body_mode_rejected(self):
        """Door subject with trigger body mode raises ValueError."""
        contract = _contract_with_door_physics("trigger")
        with pytest.raises(ValueError, match="cannot use a trigger body"):
            build_runtime_plan(contract)

    def test_door_with_kinematic_body_mode_accepted(self):
        """Door subject with kinematic body mode is accepted (Req 5.4)."""
        contract = _contract_with_door_physics("kinematic")
        plan = build_runtime_plan(contract)
        assert any(b.kind == "door" for b in plan.interactions)

    def test_door_with_static_body_mode_accepted(self):
        """Door subject with static body mode is accepted by the builder."""
        contract = _contract_with_door_physics("static")
        plan = build_runtime_plan(contract)
        assert any(b.kind == "door" for b in plan.interactions)

    def test_door_with_dynamic_body_mode_accepted(self):
        """Door subject with dynamic body mode is accepted by the builder."""
        contract = _contract_with_door_physics("dynamic")
        plan = build_runtime_plan(contract)
        assert any(b.kind == "door" for b in plan.interactions)
