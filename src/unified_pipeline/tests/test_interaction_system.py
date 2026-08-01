"""Focused tests for the object interaction system (Task 8.2).

**Validates: Requirements 22.2, 22.3, 22.4, 31.1–31.5, 34.1**

Tests cover:
- Door swing (hinge physics from WorldContract door config)
- Object grab/release (raycasting by stable UUID + constraint)
- Push/topple (impulse application on dynamic objects)
- All targets identified by stable UUID, never by GLB mesh name
- No independent geometry inference, rescaling, or transform normalization
"""
from __future__ import annotations

import math
import uuid
from pathlib import Path

import pytest

from src.unified_pipeline.door_physics import (
    DoorPhysicsConfig,
    DoorPhysicsResult,
    HingeJointConfig,
    HingePivot,
)
from src.unified_pipeline.interaction_system import (
    DoorInteractionConfig,
    DynamicInteractionConfig,
    InteractionSystem,
    InteractionSystemError,
    InteractionSystemResult,
    build_interaction_bindings,
)
from src.unified_pipeline.physics_bridge import UnifiedPhysicsResult
from src.unified_pipeline.world_contract import (
    DoorInteractionMetadata,
    DynamicInteractionMetadata,
    InteractionBinding,
    InteractionCollider,
    Quaternion,
    Vec3,
    validate_interaction_bindings,
)


# --- Fixtures ---


def _dynamic_physics(
    object_id: str = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69",
    *,
    mass_kg: float = 8.5,
    can_topple: bool = True,
    body_mode: str = "DYNAMIC",
    plan_revision: int = 3,
) -> UnifiedPhysicsResult:
    return UnifiedPhysicsResult(
        plan_revision=plan_revision,
        object_id=object_id,
        category="props",
        dimensions_m=(0.55, 0.9, 0.625),
        position_m=(1.2, 0.45, -0.3),
        rotation_deg=(0.0, 45.0, 0.0),
        material="wood",
        body_mode=body_mode,
        mass_kg=mass_kg,
        estimated_mass_kg=mass_kg,
        volume_m3=0.309,
        material_density=600.0,
        friction=0.5,
        restitution=0.2,
        can_topple=can_topple,
        override_reason=None,
    )


def _static_physics(
    object_id: str = "a1b2c3d4-1111-5222-8333-444455556666",
) -> UnifiedPhysicsResult:
    return UnifiedPhysicsResult(
        plan_revision=3,
        object_id=object_id,
        category="architecture",
        dimensions_m=(4.0, 3.0, 0.1),
        position_m=(0.0, 1.5, 2.0),
        rotation_deg=None,
        material="concrete",
        body_mode="STATIC",
        mass_kg=0.0,
        estimated_mass_kg=0.0,
        volume_m3=1.2,
        material_density=2300.0,
        friction=0.6,
        restitution=0.1,
        can_topple=False,
        override_reason="architectural",
    )


def _door_physics_result(
    door_id: str = "3d793b48-2950-5509-938b-37e7a902e55e",
) -> DoorPhysicsResult:
    hinge = HingeJointConfig(
        id=str(uuid.uuid5(uuid.UUID("a261756f-ae8f-57f6-a2ad-fbc43345948f"), f"door-hinge:{door_id}")),
        joint_type="hinge",
        anchor_body_id="wall:north",
        child_body_id=door_id,
        axis=(0.0, 1.0, 0.0),
        pivot=HingePivot(
            parent_wall_id="north",
            wall_parameter=0.15,
            elevation_m=0.0,
        ),
        lower_limit_deg=0.0,
        upper_limit_deg=95.0,
        interaction_mass_kg=18.5,
    )
    door = DoorPhysicsConfig(
        id=door_id,
        opening_id="entry",
        parent_wall_id="north",
        plan_revision=3,
        plan_hash="abc123def456",
        body_mode="STATIC",
        classification_mass_kg=0.0,
        interaction_mass_kg=18.5,
        mass_source="plan_explicit",
        friction=0.6,
        restitution=0.1,
        can_topple=False,
        is_architectural=True,
        hinge=hinge,
    )
    return DoorPhysicsResult(
        plan_revision=3,
        plan_hash="abc123def456",
        doors=(door,),
    )


# --- Test: Dynamic object grab/release ---


class TestDynamicInteraction:
    """Req 22.3: Dynamic objects grabbable, pushable, toppable by UUID."""

    def test_builds_dynamic_binding_from_physics_result(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )

        assert len(result.bindings) == 1
        binding = result.bindings[0]
        assert binding.object_id == object_id
        assert binding.kind == "dynamic"
        assert binding.dynamic is not None
        assert binding.door is None

    def test_dynamic_binding_has_stable_uuid_interaction_id(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )

        binding = result.bindings[0]
        # interaction_id is a valid UUID
        parsed = uuid.UUID(binding.interaction_id)
        assert str(parsed) == binding.interaction_id
        # Deterministic: same input → same ID
        result2 = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )
        assert result2.bindings[0].interaction_id == binding.interaction_id

    def test_collider_dimensions_match_plan_owned_scale(self) -> None:
        """Req 31: No geometry inference — collider matches Plan scale."""
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )

        collider = result.bindings[0].collider
        assert collider.dimensions.x == 0.55
        assert collider.dimensions.y == 0.9
        assert collider.dimensions.z == 0.625
        # Center offset preserves Plan-owned origin
        assert collider.center_offset.x == 0.0
        assert collider.center_offset.y == pytest.approx(0.45)
        assert collider.center_offset.z == 0.0

    def test_grab_metadata_uses_physics_mass_and_friction(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id, mass_kg=6.0)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )

        metadata = result.bindings[0].dynamic
        assert metadata.mass_kg == 6.0
        assert metadata.friction == 0.5
        assert metadata.restitution == 0.2
        assert metadata.can_grab is True
        assert metadata.can_push is True

    def test_topple_flag_from_physics_classification(self) -> None:
        """Req 22.4: Topple based on physics, not geometry inspection."""
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        topple_physics = _dynamic_physics(object_id, can_topple=True)
        no_topple_physics = _dynamic_physics(object_id, can_topple=False)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result_topple = build_interaction_bindings(
            physics_results=[topple_physics],
            instance_scales=scales,
        )
        result_no = build_interaction_bindings(
            physics_results=[no_topple_physics],
            instance_scales=scales,
        )

        assert result_topple.bindings[0].dynamic.can_topple is True
        assert result_no.bindings[0].dynamic.can_topple is False

    def test_custom_dynamic_config_overrides_defaults(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id)
        scales = {object_id: (0.55, 0.9, 0.625)}
        custom = DynamicInteractionConfig(
            grab_distance_m=5.0,
            hold_distance_m=2.5,
            hold_stiffness=20.0,
            push_impulse_ns=15.0,
            linear_damping=2.0,
            angular_damping=3.0,
        )

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
            per_object_dynamic_config={object_id: custom},
        )

        metadata = result.bindings[0].dynamic
        assert metadata.grab_distance_m == 5.0
        assert metadata.hold_distance_m == 2.5
        assert metadata.hold_stiffness == 20.0
        assert metadata.push_impulse_ns == 15.0
        assert metadata.linear_damping == 2.0
        assert metadata.angular_damping == 3.0

    def test_static_objects_skipped(self) -> None:
        """Only DYNAMIC physics results produce interaction bindings."""
        static = _static_physics()
        scales = {static.object_id: (4.0, 3.0, 0.1)}

        result = build_interaction_bindings(
            physics_results=[static],
            instance_scales=scales,
        )

        assert len(result.bindings) == 0


# --- Test: Door swing hinge physics ---


class TestDoorInteraction:
    """Req 22.2: Doors swing on configured hinges when interacted with."""

    def test_builds_door_hinge_binding(self) -> None:
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        door_physics = _door_physics_result(door_id)
        scales = {door_id: (0.8, 2.0, 0.05)}

        result = build_interaction_bindings(
            physics_results=[],
            door_physics=door_physics,
            instance_scales=scales,
        )

        assert len(result.bindings) == 1
        binding = result.bindings[0]
        assert binding.object_id == door_id
        assert binding.kind == "door_hinge"
        assert binding.door is not None
        assert binding.dynamic is None

    def test_door_binding_has_stable_uuid_interaction_id(self) -> None:
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        door_physics = _door_physics_result(door_id)
        scales = {door_id: (0.8, 2.0, 0.05)}

        result = build_interaction_bindings(
            physics_results=[],
            door_physics=door_physics,
            instance_scales=scales,
        )

        binding = result.bindings[0]
        parsed = uuid.UUID(binding.interaction_id)
        assert str(parsed) == binding.interaction_id

    def test_door_hinge_limits_from_door_physics_config(self) -> None:
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        door_physics = _door_physics_result(door_id)
        scales = {door_id: (0.8, 2.0, 0.05)}

        result = build_interaction_bindings(
            physics_results=[],
            door_physics=door_physics,
            instance_scales=scales,
        )

        door_meta = result.bindings[0].door
        assert door_meta.lower_limit_deg == 0.0
        assert door_meta.upper_limit_deg == 95.0
        assert door_meta.interaction_mass_kg == 18.5
        assert door_meta.axis == Vec3(0.0, 1.0, 0.0)

    def test_door_collider_matches_plan_scale(self) -> None:
        """Req 31: Collider dimensions = Plan-owned door scale, not inferred."""
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        door_physics = _door_physics_result(door_id)
        scales = {door_id: (0.8, 2.0, 0.05)}

        result = build_interaction_bindings(
            physics_results=[],
            door_physics=door_physics,
            instance_scales=scales,
        )

        collider = result.bindings[0].collider
        assert collider.dimensions.x == 0.8
        assert collider.dimensions.y == 2.0
        assert collider.dimensions.z == 0.05
        assert collider.center_offset.y == pytest.approx(1.0)

    def test_custom_door_config_overrides_defaults(self) -> None:
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        door_physics = _door_physics_result(door_id)
        scales = {door_id: (0.8, 2.0, 0.05)}
        custom = DoorInteractionConfig(
            angular_speed_deg_s=200.0,
            interaction_distance_m=4.0,
            initial_angle_deg=10.0,
        )

        result = build_interaction_bindings(
            physics_results=[],
            door_physics=door_physics,
            instance_scales=scales,
            per_door_config={door_id: custom},
        )

        door_meta = result.bindings[0].door
        assert door_meta.angular_speed_deg_s == 200.0
        assert door_meta.interaction_distance_m == 4.0
        assert door_meta.initial_angle_deg == 10.0

    def test_door_pivot_from_position_and_hinge_side(self) -> None:
        """Pivot derived from Plan-owned position, not from GLB geometry."""
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        door_physics = _door_physics_result(door_id)
        scales = {door_id: (0.8, 2.0, 0.05)}
        positions = {door_id: (-1.0, 0.0, 1.4)}

        result = build_interaction_bindings(
            physics_results=[],
            door_physics=door_physics,
            instance_scales=scales,
            instance_positions=positions,
        )

        pivot = result.bindings[0].door.pivot
        # Pivot at left edge: position.x - width/2
        assert pivot.x == pytest.approx(-1.4)
        assert pivot.y == 0.0
        assert pivot.z == 1.4


# --- Test: Push/topple impulse application ---


class TestPushTopple:
    """Req 22.4: Physics responds realistically — push, topple, settle."""

    def test_push_impulse_metadata_available(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id, mass_kg=8.5)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )

        metadata = result.bindings[0].dynamic
        assert metadata.push_impulse_ns > 0.0
        assert metadata.mass_kg == 8.5
        # Impulse delta = push_impulse / mass
        velocity_delta = metadata.push_impulse_ns / metadata.mass_kg
        assert velocity_delta > 0.0

    def test_angular_damping_for_topple_control(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id, can_topple=True)
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=[physics],
            instance_scales=scales,
        )

        metadata = result.bindings[0].dynamic
        assert metadata.angular_damping >= 0.0
        assert metadata.linear_damping >= 0.0


# --- Test: UUID enforcement ---


class TestUUIDEnforcement:
    """Req 34.1: All targets identified by stable UUID, never by name."""

    def test_rejects_non_uuid_object_id(self) -> None:
        physics = _dynamic_physics("not-a-uuid")
        scales = {"not-a-uuid": (0.5, 0.5, 0.5)}

        with pytest.raises(InteractionSystemError, match="stable UUID"):
            build_interaction_bindings(
                physics_results=[physics],
                instance_scales=scales,
            )

    def test_rejects_duplicate_object_ids(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = [_dynamic_physics(object_id), _dynamic_physics(object_id)]
        scales = {object_id: (0.55, 0.9, 0.625)}

        with pytest.raises(InteractionSystemError, match="Duplicate"):
            build_interaction_bindings(
                physics_results=physics,
                instance_scales=scales,
            )

    def test_rejects_missing_scale_for_dynamic(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = _dynamic_physics(object_id)

        with pytest.raises(InteractionSystemError, match="Missing Plan-owned scale"):
            build_interaction_bindings(
                physics_results=[physics],
                instance_scales={},
            )

    def test_rejects_mismatched_plan_revision(self) -> None:
        id1 = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        id2 = "b1c2d3e4-5555-5666-8777-888899990000"
        physics = [
            _dynamic_physics(id1, plan_revision=3),
            _dynamic_physics(id2, plan_revision=4),
        ]
        scales = {id1: (0.55, 0.9, 0.625), id2: (0.5, 0.5, 0.5)}

        with pytest.raises(InteractionSystemError, match="same Plan revision"):
            build_interaction_bindings(
                physics_results=physics,
                instance_scales=scales,
            )


# --- Test: Combined door + dynamic ---


class TestCombinedInteractions:
    """Full scene with both doors and dynamic objects."""

    def test_builds_mixed_door_and_dynamic_bindings(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        door_id = "3d793b48-2950-5509-938b-37e7a902e55e"
        physics = [_dynamic_physics(object_id)]
        door_physics = _door_physics_result(door_id)
        scales = {
            object_id: (0.55, 0.9, 0.625),
            door_id: (0.8, 2.0, 0.05),
        }

        result = build_interaction_bindings(
            physics_results=physics,
            door_physics=door_physics,
            instance_scales=scales,
        )

        assert len(result.bindings) == 2
        kinds = {b.kind for b in result.bindings}
        assert kinds == {"dynamic", "door_hinge"}
        ids = {b.object_id for b in result.bindings}
        assert ids == {object_id, door_id}
        assert result.plan_revision == 3

    def test_result_serializes_roundtrip(self) -> None:
        object_id = "42bcbdb1-83e4-5e41-9d9a-706e2f897f69"
        physics = [_dynamic_physics(object_id)]
        scales = {object_id: (0.55, 0.9, 0.625)}

        result = build_interaction_bindings(
            physics_results=physics,
            instance_scales=scales,
        )

        data = result.to_dict()
        assert data["plan_revision"] == 3
        assert len(data["bindings"]) == 1
        restored = InteractionBinding.from_dict(data["bindings"][0])
        assert restored == result.bindings[0]

    def test_requires_at_least_one_input(self) -> None:
        with pytest.raises(InteractionSystemError, match="At least one"):
            build_interaction_bindings(
                physics_results=[],
                instance_scales={},
            )
