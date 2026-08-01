"""Object interaction system — builds WorldContract InteractionBindings.

Produces door-hinge, grab/release, and push/topple bindings from the
DoorPhysicsResult (Task 5.4) and UnifiedPhysicsResult (physics_bridge) models.
Every binding targets a stable UUID from the WorldContract; GLB mesh names and
fuzzy matching are never used. No independent geometry inference, rescaling,
or transform normalization is performed.

Requirements: 22.2, 22.3, 22.4, 31.1–31.5, 34.1
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.unified_pipeline.door_physics import DoorPhysicsConfig, DoorPhysicsResult
from src.unified_pipeline.physics_bridge import UnifiedPhysicsResult
from src.unified_pipeline.world_contract import (
    DoorInteractionMetadata,
    DynamicInteractionMetadata,
    InteractionBinding,
    InteractionCollider,
    Quaternion,
    Vec3,
)


class InteractionSystemError(ValueError):
    """Raised when interaction bindings cannot be built from the given inputs."""


_INTERACTION_NAMESPACE = uuid.UUID("d8a63e07-58f7-5c5a-b8fc-06bfe58f9a3a")

# Default grab/push configuration for dynamic objects
_DEFAULT_GRAB_DISTANCE_M = 3.0
_DEFAULT_HOLD_DISTANCE_M = 1.5
_DEFAULT_HOLD_STIFFNESS = 12.0
_DEFAULT_PUSH_IMPULSE_NS = 10.0
_DEFAULT_LINEAR_DAMPING = 1.0
_DEFAULT_ANGULAR_DAMPING = 1.5
_DEFAULT_DOOR_ANGULAR_SPEED_DEG_S = 120.0
_DEFAULT_DOOR_INTERACTION_DISTANCE_M = 3.0


def _stable_interaction_id(object_id: str, kind: str) -> str:
    """Deterministic interaction UUID from object UUID + kind."""
    return str(uuid.uuid5(_INTERACTION_NAMESPACE, f"{kind}:{object_id}"))


def _validate_uuid(value: str, label: str) -> None:
    """Reject non-UUID identifiers to enforce the stable UUID contract."""
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise InteractionSystemError(
            f"{label} must be a canonical stable UUID, got: {value!r}"
        ) from exc
    if str(parsed) != value.lower().strip():
        raise InteractionSystemError(
            f"{label} must be a canonical stable UUID, got: {value!r}"
        )


def _positive_finite(value: float, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise InteractionSystemError(f"{label} must be a finite positive number")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise InteractionSystemError(f"{label} must be a finite positive number")
    return result


@dataclass(frozen=True)
class DynamicInteractionConfig:
    """Optional per-object tuning for grab/push behavior."""

    grab_distance_m: float = _DEFAULT_GRAB_DISTANCE_M
    hold_distance_m: float = _DEFAULT_HOLD_DISTANCE_M
    hold_stiffness: float = _DEFAULT_HOLD_STIFFNESS
    push_impulse_ns: float = _DEFAULT_PUSH_IMPULSE_NS
    linear_damping: float = _DEFAULT_LINEAR_DAMPING
    angular_damping: float = _DEFAULT_ANGULAR_DAMPING


@dataclass(frozen=True)
class DoorInteractionConfig:
    """Optional per-door tuning beyond what DoorPhysicsResult provides."""

    angular_speed_deg_s: float = _DEFAULT_DOOR_ANGULAR_SPEED_DEG_S
    interaction_distance_m: float = _DEFAULT_DOOR_INTERACTION_DISTANCE_M
    initial_angle_deg: float = 0.0


@dataclass(frozen=True)
class InteractionSystemResult:
    """Immutable set of interaction bindings for one WorldContract."""

    plan_revision: int
    bindings: tuple[InteractionBinding, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_revision": self.plan_revision,
            "bindings": [b.to_dict() for b in self.bindings],
        }


class InteractionSystem:
    """Build InteractionBindings from physics classification and door configs.

    All interaction targets are identified by their stable UUID from the
    WorldContract, never by GLB mesh name or fuzzy matching. No independent
    geometry inference, rescaling, or transform normalization is performed.
    """

    def __init__(
        self,
        *,
        default_dynamic_config: DynamicInteractionConfig | None = None,
        default_door_config: DoorInteractionConfig | None = None,
    ) -> None:
        self._dynamic_config = default_dynamic_config or DynamicInteractionConfig()
        self._door_config = default_door_config or DoorInteractionConfig()

    def build(
        self,
        *,
        physics_results: Sequence[UnifiedPhysicsResult],
        door_physics: DoorPhysicsResult | None = None,
        instance_scales: Mapping[str, tuple[float, float, float]],
        instance_positions: Mapping[str, tuple[float, float, float]] | None = None,
        per_object_dynamic_config: Mapping[str, DynamicInteractionConfig] | None = None,
        per_door_config: Mapping[str, DoorInteractionConfig] | None = None,
    ) -> InteractionSystemResult:
        """Build all interaction bindings for one WorldContract.

        Args:
            physics_results: Physics classification for every object.
            door_physics: Door hinge physics from DoorPhysicsConfigurator.
            instance_scales: Map of object_id → (width, height, depth) from Plan.
            instance_positions: Map of object_id → (x, y, z) world position.
            per_object_dynamic_config: Optional per-object grab/push tuning.
            per_door_config: Optional per-door interaction tuning.

        Returns:
            InteractionSystemResult with all bindings.
        """
        bindings: list[InteractionBinding] = []
        seen_ids: set[str] = set()
        dynamic_configs = per_object_dynamic_config or {}
        door_configs = per_door_config or {}
        positions = instance_positions or {}
        plan_revision: int | None = None

        # Build dynamic interaction bindings (grab/push/topple)
        for result in physics_results:
            _validate_uuid(result.object_id, "physics result object_id")

            if plan_revision is None:
                plan_revision = result.plan_revision
            elif plan_revision != result.plan_revision:
                raise InteractionSystemError(
                    "All physics results must share the same Plan revision"
                )

            if result.body_mode != "DYNAMIC":
                continue

            if result.object_id in seen_ids:
                raise InteractionSystemError(
                    f"Duplicate object_id in physics results: {result.object_id}"
                )
            seen_ids.add(result.object_id)

            scale = instance_scales.get(result.object_id)
            if scale is None:
                raise InteractionSystemError(
                    f"Missing Plan-owned scale for dynamic object {result.object_id}"
                )
            binding = self._build_dynamic_binding(result, scale, dynamic_configs)
            bindings.append(binding)

        # Build door hinge interaction bindings
        if door_physics is not None:
            if plan_revision is None:
                plan_revision = door_physics.plan_revision
            elif plan_revision != door_physics.plan_revision:
                raise InteractionSystemError(
                    "Door physics Plan revision must match physics results"
                )

            for door in door_physics.doors:
                _validate_uuid(door.id, "door config id")
                if door.id in seen_ids:
                    raise InteractionSystemError(
                        f"Duplicate object_id in door configs: {door.id}"
                    )
                seen_ids.add(door.id)

                scale = instance_scales.get(door.id)
                if scale is None:
                    raise InteractionSystemError(
                        f"Missing Plan-owned scale for door {door.id}"
                    )
                position = positions.get(door.id)
                binding = self._build_door_binding(
                    door, scale, position, door_configs
                )
                bindings.append(binding)

        if plan_revision is None:
            raise InteractionSystemError(
                "At least one physics result or door config is required"
            )

        return InteractionSystemResult(
            plan_revision=plan_revision,
            bindings=tuple(bindings),
        )

    def _build_dynamic_binding(
        self,
        result: UnifiedPhysicsResult,
        scale: tuple[float, float, float],
        configs: Mapping[str, DynamicInteractionConfig],
    ) -> InteractionBinding:
        """Build a grab/push/topple binding from physics classification."""
        config = configs.get(result.object_id, self._dynamic_config)
        width, height, depth = scale

        _positive_finite(width, f"{result.object_id} scale.x")
        _positive_finite(height, f"{result.object_id} scale.y")
        _positive_finite(depth, f"{result.object_id} scale.z")
        _positive_finite(result.mass_kg, f"{result.object_id} mass")

        # Collider: dimensions match instance scale exactly (required by contract)
        # Center offset: (0, height/2, 0) preserving Plan-owned instance origin
        collider = InteractionCollider(
            center_offset=Vec3(0.0, height / 2.0, 0.0),
            dimensions=Vec3(width, height, depth),
            rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
            shape="box",
        )

        interaction_id = _stable_interaction_id(result.object_id, "dynamic")
        metadata = DynamicInteractionMetadata(
            mass_kg=result.mass_kg,
            friction=result.friction,
            restitution=result.restitution,
            can_grab=True,
            can_push=True,
            can_topple=result.can_topple,
            grab_distance_m=config.grab_distance_m,
            hold_distance_m=config.hold_distance_m,
            hold_stiffness=config.hold_stiffness,
            push_impulse_ns=config.push_impulse_ns,
            linear_damping=config.linear_damping,
            angular_damping=config.angular_damping,
        )

        return InteractionBinding(
            interaction_id=interaction_id,
            object_id=result.object_id,
            kind="dynamic",
            collider=collider,
            dynamic=metadata,
        )

    def _build_door_binding(
        self,
        door: DoorPhysicsConfig,
        scale: tuple[float, float, float],
        position: tuple[float, float, float] | None,
        configs: Mapping[str, DoorInteractionConfig],
    ) -> InteractionBinding:
        """Build a door hinge binding from DoorPhysicsConfig."""
        config = configs.get(door.id, self._door_config)
        width, height, depth = scale

        _positive_finite(width, f"door {door.id} scale.x")
        _positive_finite(height, f"door {door.id} scale.y")
        _positive_finite(depth, f"door {door.id} scale.z")

        hinge = door.hinge

        # Derive world-space pivot from the Plan-owned door position + hinge config
        # The pivot is at the hinge side of the door in world space.
        # If we have position, use hinge pivot parameter to compute world pivot.
        if position is not None:
            # The pivot is offset from the door position based on hinge side
            # Hinge pivot parameter gives wall-local coordinate;
            # for world-space we express as offset from door center.
            pivot_x = position[0] - width / 2.0  # left-side hinge default
            if hinge.pivot.wall_parameter > door.hinge.pivot.wall_parameter:
                pivot_x = position[0] + width / 2.0
            pivot = Vec3(pivot_x, position[1], position[2])
        else:
            # Fallback: pivot at left edge relative to door center (0, 0, 0)
            pivot = Vec3(-width / 2.0, 0.0, 0.0)

        # Collider matches Plan-owned scale exactly
        collider = InteractionCollider(
            center_offset=Vec3(0.0, height / 2.0, 0.0),
            dimensions=Vec3(width, height, depth),
            rotation=Quaternion(0.0, 0.0, 0.0, 1.0),
            shape="box",
        )

        interaction_id = _stable_interaction_id(door.id, "door_hinge")
        axis = Vec3(hinge.axis[0], hinge.axis[1], hinge.axis[2])

        door_metadata = DoorInteractionMetadata(
            pivot=pivot,
            axis=axis,
            lower_limit_deg=hinge.lower_limit_deg,
            upper_limit_deg=hinge.upper_limit_deg,
            initial_angle_deg=config.initial_angle_deg,
            angular_speed_deg_s=config.angular_speed_deg_s,
            interaction_distance_m=config.interaction_distance_m,
            interaction_mass_kg=door.interaction_mass_kg,
        )

        return InteractionBinding(
            interaction_id=interaction_id,
            object_id=door.id,
            kind="door_hinge",
            collider=collider,
            door=door_metadata,
        )


def build_interaction_bindings(
    *,
    physics_results: Sequence[UnifiedPhysicsResult],
    door_physics: DoorPhysicsResult | None = None,
    instance_scales: Mapping[str, tuple[float, float, float]],
    instance_positions: Mapping[str, tuple[float, float, float]] | None = None,
    per_object_dynamic_config: Mapping[str, DynamicInteractionConfig] | None = None,
    per_door_config: Mapping[str, DoorInteractionConfig] | None = None,
    default_dynamic_config: DynamicInteractionConfig | None = None,
    default_door_config: DoorInteractionConfig | None = None,
) -> InteractionSystemResult:
    """Convenience entry point for one-shot interaction binding construction."""
    system = InteractionSystem(
        default_dynamic_config=default_dynamic_config,
        default_door_config=default_door_config,
    )
    return system.build(
        physics_results=physics_results,
        door_physics=door_physics,
        instance_scales=instance_scales,
        instance_positions=instance_positions,
        per_object_dynamic_config=per_object_dynamic_config,
        per_door_config=per_door_config,
    )


__all__ = [
    "DoorInteractionConfig",
    "DynamicInteractionConfig",
    "InteractionSystem",
    "InteractionSystemError",
    "InteractionSystemResult",
    "build_interaction_bindings",
]
