"""
WorldContract: Canonical serialization and hash-bound contract.

The WorldContract is the single deterministic, hash-bound document that every
consumer (browser, Godot, UPBGE) reads identically. It binds Plan revision,
CameraContract hash, room shell, all object instances, lighting, and the
relationship graph into one SHA-256 verified contract.

Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 29.2
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any

from .camera_contract import CameraContract


# ---------------------------------------------------------------------------
# Supporting enums and value types
# ---------------------------------------------------------------------------

class PhysicsIntent(Enum):
    """Physics classification intent for an object instance."""
    STATIC = "static"
    DYNAMIC = "dynamic"
    KINEMATIC = "kinematic"
    TRIGGER = "trigger"


class RelationshipType(Enum):
    """Relationship types in the scene graph."""
    PARENT_CHILD = "parent_child"
    CONTAINMENT = "containment"
    ADJACENCY = "adjacency"
    SUPPORT = "support"


class EventStatus(Enum):
    """Event finality status per Req 19.5, 19.6."""
    PROVISIONAL = "provisional"
    FINAL = "final"


# ---------------------------------------------------------------------------
# Frozen value objects (immutable via __setattr__ override)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Vec3:
    """Immutable 3D vector."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Vec3:
        return cls(x=float(data["x"]), y=float(data["y"]), z=float(data["z"]))


@dataclass(frozen=True)
class Quaternion:
    """Immutable rotation quaternion (x, y, z, w)."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Quaternion:
        return cls(
            x=float(data["x"]),
            y=float(data["y"]),
            z=float(data["z"]),
            w=float(data["w"]),
        )


@dataclass(frozen=True)
class StaticCollisionBody:
    """One explicit, authoritative static box collider in contract space."""

    body_id: str
    source_id: str
    center: Vec3
    dimensions: Vec3
    rotation: Quaternion = field(default_factory=Quaternion)
    shape: str = "box"
    body_mode: str = "STATIC"
    source_kind: str = "instance"

    def to_dict(self) -> dict[str, Any]:
        return {
            "body_id": self.body_id,
            "source_id": self.source_id,
            "center": self.center.to_dict(),
            "dimensions": self.dimensions.to_dict(),
            "rotation": self.rotation.to_dict(),
            "shape": self.shape,
            "body_mode": self.body_mode,
            "source_kind": self.source_kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StaticCollisionBody:
        return cls(
            body_id=str(data.get("body_id", "")),
            source_id=str(data.get("source_id", "")),
            center=Vec3.from_dict(data.get("center", {})),
            dimensions=Vec3.from_dict(data.get("dimensions", {})),
            rotation=Quaternion.from_dict(
                data.get("rotation", {"x": 0, "y": 0, "z": 0, "w": 1})
            ),
            shape=str(data.get("shape", "box")),
            body_mode=str(data.get("body_mode", "STATIC")),
            source_kind=str(data.get("source_kind", "instance")),
        )


@dataclass(frozen=True)
class FirstPersonNavigation:
    """Hash-bound runtime values for browser walkability; consumers do not infer them."""

    bounds_minimum: Vec3
    bounds_maximum: Vec3
    static_bodies: tuple[StaticCollisionBody, ...]
    spawn_candidates: tuple[Vec3, ...]
    player_radius: float
    player_height: float
    eye_height: float
    movement_speed: float
    gravity: float
    coordinate_system: str = "right-handed-x-right-y-up-z-depth"
    boundary_tolerance_m: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bounds_minimum": self.bounds_minimum.to_dict(),
            "bounds_maximum": self.bounds_maximum.to_dict(),
            "static_bodies": [body.to_dict() for body in self.static_bodies],
            "spawn_candidates": [point.to_dict() for point in self.spawn_candidates],
            "player_radius": self.player_radius,
            "player_height": self.player_height,
            "eye_height": self.eye_height,
            "movement_speed": self.movement_speed,
            "gravity": self.gravity,
            "coordinate_system": self.coordinate_system,
            "boundary_tolerance_m": self.boundary_tolerance_m,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FirstPersonNavigation:
        return cls(
            bounds_minimum=Vec3.from_dict(data.get("bounds_minimum", {})),
            bounds_maximum=Vec3.from_dict(data.get("bounds_maximum", {})),
            static_bodies=tuple(
                StaticCollisionBody.from_dict(item)
                for item in data.get("static_bodies", [])
            ),
            spawn_candidates=tuple(
                Vec3.from_dict(item) for item in data.get("spawn_candidates", [])
            ),
            player_radius=float(data.get("player_radius", 0.0)),
            player_height=float(data.get("player_height", 0.0)),
            eye_height=float(data.get("eye_height", 0.0)),
            movement_speed=float(data.get("movement_speed", 0.0)),
            gravity=float(data.get("gravity", 0.0)),
            coordinate_system=str(data.get("coordinate_system", "")),
            boundary_tolerance_m=float(data.get("boundary_tolerance_m", 0.0)),
        )


@dataclass(frozen=True)
class InteractionCollider:
    """Explicit local box collider authored outside the browser runtime."""

    center_offset: Vec3
    dimensions: Vec3
    rotation: Quaternion = field(default_factory=Quaternion)
    shape: str = "box"

    def to_dict(self) -> dict[str, Any]:
        return {
            "center_offset": self.center_offset.to_dict(),
            "dimensions": self.dimensions.to_dict(),
            "rotation": self.rotation.to_dict(),
            "shape": self.shape,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InteractionCollider:
        return cls(
            center_offset=Vec3.from_dict(data["center_offset"]),
            dimensions=Vec3.from_dict(data["dimensions"]),
            rotation=Quaternion.from_dict(data["rotation"]),
            shape=str(data["shape"]),
        )


@dataclass(frozen=True)
class DynamicInteractionMetadata:
    """Explicit grab, push, topple, and deterministic body parameters."""

    mass_kg: float
    friction: float
    restitution: float
    can_grab: bool
    can_push: bool
    can_topple: bool
    grab_distance_m: float
    hold_distance_m: float
    hold_stiffness: float
    push_impulse_ns: float
    linear_damping: float
    angular_damping: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "mass_kg": self.mass_kg,
            "friction": self.friction,
            "restitution": self.restitution,
            "can_grab": self.can_grab,
            "can_push": self.can_push,
            "can_topple": self.can_topple,
            "grab_distance_m": self.grab_distance_m,
            "hold_distance_m": self.hold_distance_m,
            "hold_stiffness": self.hold_stiffness,
            "push_impulse_ns": self.push_impulse_ns,
            "linear_damping": self.linear_damping,
            "angular_damping": self.angular_damping,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DynamicInteractionMetadata:
        return cls(
            mass_kg=float(data["mass_kg"]),
            friction=float(data["friction"]),
            restitution=float(data["restitution"]),
            can_grab=data["can_grab"],
            can_push=data["can_push"],
            can_topple=data["can_topple"],
            grab_distance_m=float(data["grab_distance_m"]),
            hold_distance_m=float(data["hold_distance_m"]),
            hold_stiffness=float(data["hold_stiffness"]),
            push_impulse_ns=float(data["push_impulse_ns"]),
            linear_damping=float(data["linear_damping"]),
            angular_damping=float(data["angular_damping"]),
        )


@dataclass(frozen=True)
class DoorInteractionMetadata:
    """Explicit world-space hinge metadata derived before compilation."""

    pivot: Vec3
    axis: Vec3
    lower_limit_deg: float
    upper_limit_deg: float
    initial_angle_deg: float
    angular_speed_deg_s: float
    interaction_distance_m: float
    interaction_mass_kg: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "pivot": self.pivot.to_dict(),
            "axis": self.axis.to_dict(),
            "lower_limit_deg": self.lower_limit_deg,
            "upper_limit_deg": self.upper_limit_deg,
            "initial_angle_deg": self.initial_angle_deg,
            "angular_speed_deg_s": self.angular_speed_deg_s,
            "interaction_distance_m": self.interaction_distance_m,
            "interaction_mass_kg": self.interaction_mass_kg,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DoorInteractionMetadata:
        return cls(
            pivot=Vec3.from_dict(data["pivot"]),
            axis=Vec3.from_dict(data["axis"]),
            lower_limit_deg=float(data["lower_limit_deg"]),
            upper_limit_deg=float(data["upper_limit_deg"]),
            initial_angle_deg=float(data["initial_angle_deg"]),
            angular_speed_deg_s=float(data["angular_speed_deg_s"]),
            interaction_distance_m=float(data["interaction_distance_m"]),
            interaction_mass_kg=float(data["interaction_mass_kg"]),
        )


@dataclass(frozen=True)
class InteractionBinding:
    """One hash-bound behavior binding keyed by stable WorldContract UUID."""

    interaction_id: str
    object_id: str
    kind: str
    collider: InteractionCollider
    dynamic: DynamicInteractionMetadata | None = None
    door: DoorInteractionMetadata | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "object_id": self.object_id,
            "kind": self.kind,
            "collider": self.collider.to_dict(),
            "dynamic": self.dynamic.to_dict() if self.dynamic is not None else None,
            "door": self.door.to_dict() if self.door is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InteractionBinding:
        return cls(
            interaction_id=str(data["interaction_id"]),
            object_id=str(data["object_id"]),
            kind=str(data["kind"]),
            collider=InteractionCollider.from_dict(data["collider"]),
            dynamic=(
                DynamicInteractionMetadata.from_dict(data["dynamic"])
                if data.get("dynamic") is not None else None
            ),
            door=(
                DoorInteractionMetadata.from_dict(data["door"])
                if data.get("door") is not None else None
            ),
        )


class InteractionContractError(ValueError):
    """Raised when explicit interaction metadata cannot be represented exactly."""


def validate_interaction_bindings(
    instances: tuple[ObjectInstance, ...],
    interactions: tuple[InteractionBinding, ...],
    *,
    require_dynamic_bindings: bool,
) -> None:
    """Validate UUID-keyed behavior against Plan-owned instance transforms.

    This shared contract check intentionally consumes only explicit metadata. It
    never reads mesh geometry and never derives colliders or transforms.
    """
    instance_by_id = {item.object_id: item for item in instances}
    interaction_ids: set[str] = set()
    object_ids: set[str] = set()

    def stable_uuid(value: str, label: str) -> None:
        try:
            parsed = uuid.UUID(value)
        except (TypeError, ValueError, AttributeError) as exc:
            raise InteractionContractError(
                f"{label} must be a canonical stable UUID"
            ) from exc
        if str(parsed) != value.lower():
            raise InteractionContractError(f"{label} must be a canonical stable UUID")

    def finite_numbers(values: tuple[float, ...], label: str) -> None:
        if any(isinstance(value, bool) or not math.isfinite(value) for value in values):
            raise InteractionContractError(f"{label} must use finite numeric values")

    for binding in interactions:
        stable_uuid(binding.interaction_id, "interaction_id")
        stable_uuid(binding.object_id, "interaction object_id")
        if binding.interaction_id in interaction_ids:
            raise InteractionContractError("interaction IDs must be unique")
        if binding.object_id in object_ids:
            raise InteractionContractError(
                "each object UUID may have only one interaction binding"
            )
        interaction_ids.add(binding.interaction_id)
        object_ids.add(binding.object_id)

        instance = instance_by_id.get(binding.object_id)
        if instance is None:
            raise InteractionContractError(
                f"interaction {binding.interaction_id!r} references an unknown object UUID"
            )
        collider = binding.collider
        collider_values = (
            collider.center_offset.x, collider.center_offset.y, collider.center_offset.z,
            collider.dimensions.x, collider.dimensions.y, collider.dimensions.z,
            collider.rotation.x, collider.rotation.y, collider.rotation.z,
            collider.rotation.w,
        )
        finite_numbers(collider_values, "interaction collider metadata")
        if collider.shape != "box" or min(
            collider.dimensions.x, collider.dimensions.y, collider.dimensions.z
        ) <= 0.0:
            raise InteractionContractError(
                "interaction requires an explicit positive box collider"
            )
        if any(abs(actual - expected) > 1e-9 for actual, expected in zip(
            (collider.dimensions.x, collider.dimensions.y, collider.dimensions.z),
            (instance.scale.x, instance.scale.y, instance.scale.z),
        )):
            raise InteractionContractError(
                "interaction collider dimensions must exactly match Plan-owned instance dimensions"
            )
        if any(abs(actual - expected) > 1e-9 for actual, expected in zip(
            (collider.center_offset.x, collider.center_offset.y, collider.center_offset.z),
            (0.0, instance.scale.y / 2.0, 0.0),
        )):
            raise InteractionContractError(
                "interaction collider center must exactly preserve the Plan-owned instance origin"
            )
        rotation_norm = sum(value * value for value in (
            collider.rotation.x, collider.rotation.y,
            collider.rotation.z, collider.rotation.w,
        ))
        if abs(rotation_norm - 1.0) > 1e-6:
            raise InteractionContractError("interaction collider rotation must be unit length")

        if binding.kind == "dynamic":
            metadata = binding.dynamic
            if metadata is None or binding.door is not None:
                raise InteractionContractError(
                    "dynamic interaction metadata is missing or ambiguous"
                )
            if instance.physics_intent != "dynamic" or instance.is_architectural:
                raise InteractionContractError(
                    "dynamic interaction requires an explicitly dynamic non-architectural instance"
                )
            numbers = (
                metadata.mass_kg, metadata.friction, metadata.restitution,
                metadata.grab_distance_m, metadata.hold_distance_m,
                metadata.hold_stiffness, metadata.push_impulse_ns,
                metadata.linear_damping, metadata.angular_damping,
            )
            finite_numbers(numbers, "dynamic interaction metadata")
            if (
                any(not isinstance(value, bool) for value in (
                    metadata.can_grab, metadata.can_push, metadata.can_topple
                ))
                or not (metadata.can_grab and metadata.can_push and metadata.can_topple)
                or metadata.mass_kg <= 0.0
                or not 0.0 <= metadata.friction <= 1.0
                or not 0.0 <= metadata.restitution <= 1.0
                or metadata.grab_distance_m <= 0.0
                or metadata.hold_distance_m <= 0.0
                or metadata.hold_distance_m > metadata.grab_distance_m
                or metadata.hold_stiffness <= 0.0
                or metadata.push_impulse_ns <= 0.0
                or metadata.linear_damping < 0.0
                or metadata.angular_damping < 0.0
            ):
                raise InteractionContractError(
                    "dynamic interaction metadata is outside safe bounds"
                )
        elif binding.kind == "door_hinge":
            metadata = binding.door
            if metadata is None or binding.dynamic is not None:
                raise InteractionContractError(
                    "door hinge metadata is missing or ambiguous"
                )
            if not instance.is_architectural or instance.physics_intent not in {
                "static", "kinematic"
            }:
                raise InteractionContractError(
                    "door hinge interaction requires an architectural static/kinematic instance"
                )
            numbers = (
                metadata.pivot.x, metadata.pivot.y, metadata.pivot.z,
                metadata.axis.x, metadata.axis.y, metadata.axis.z,
                metadata.lower_limit_deg, metadata.upper_limit_deg,
                metadata.initial_angle_deg, metadata.angular_speed_deg_s,
                metadata.interaction_distance_m, metadata.interaction_mass_kg,
            )
            finite_numbers(numbers, "door hinge metadata")
            axis_norm = math.sqrt(
                metadata.axis.x ** 2 + metadata.axis.y ** 2 + metadata.axis.z ** 2
            )
            if (
                abs(axis_norm - 1.0) > 1e-6
                or abs(metadata.axis.x) > 1e-9
                or abs(metadata.axis.z) > 1e-9
                or metadata.lower_limit_deg >= metadata.upper_limit_deg
                or metadata.lower_limit_deg < -180.0
                or metadata.upper_limit_deg > 180.0
                or not metadata.lower_limit_deg <= metadata.initial_angle_deg <= metadata.upper_limit_deg
                or metadata.angular_speed_deg_s <= 0.0
                or metadata.interaction_distance_m <= 0.0
                or metadata.interaction_mass_kg <= 0.0
            ):
                raise InteractionContractError(
                    "door hinge metadata is outside safe explicit bounds"
                )
        else:
            raise InteractionContractError(
                f"unsupported interaction kind {binding.kind!r}"
            )

    if require_dynamic_bindings:
        required = {
            item.object_id for item in instances
            if item.physics_intent == "dynamic" and not item.is_architectural
        }
        bound = {
            item.object_id for item in interactions if item.kind == "dynamic"
        }
        if required != bound:
            raise InteractionContractError(
                "every dynamic instance requires exactly one explicit interaction binding"
            )


@dataclass(frozen=True)
class MaterialIntent:
    """Material and explicit geometry-shading intent for an object instance."""
    base_color: str = ""          # hex color or texture reference
    metallic: float = 0.0         # 0-1
    roughness: float = 0.5        # 0-1
    normal_map_ref: str = ""      # path or empty
    pass_level: int = 1           # 1 = immediate, 2 = PBR refined
    shading_model: str = "asset"  # asset | smooth | flat; consumers never generate normals
    shading_provenance: str = ""  # SHA-256 of mesh-shading-audit/v1 for explicit models
    render_profile: str = "legacy-authoritative/v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_color": self.base_color,
            "metallic": self.metallic,
            "roughness": self.roughness,
            "normal_map_ref": self.normal_map_ref,
            "pass_level": self.pass_level,
            "shading_model": self.shading_model,
            "shading_provenance": self.shading_provenance,
            "render_profile": self.render_profile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialIntent:
        return cls(
            base_color=str(data.get("base_color", "")),
            metallic=float(data.get("metallic", 0.0)),
            roughness=float(data.get("roughness", 0.5)),
            normal_map_ref=str(data.get("normal_map_ref", "")),
            pass_level=int(data.get("pass_level", 1)),
            shading_model=str(data.get("shading_model", "asset")),
            shading_provenance=str(data.get("shading_provenance", "")),
            render_profile=str(data.get("render_profile", "legacy-authoritative/v1")),
        )


@dataclass(frozen=True)
class AssetBinding:
    """Concrete asset reference bound to an object instance."""
    asset_id: str = ""            # SHA-256 of the approved mesh file
    mesh_path: str = ""           # relative path to .glb
    triangle_count: int = 0
    vertex_count: int = 0
    generator: str = ""           # "hunyuan3d" | "trellis2" | "placeholder"

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "mesh_path": self.mesh_path,
            "triangle_count": self.triangle_count,
            "vertex_count": self.vertex_count,
            "generator": self.generator,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AssetBinding:
        return cls(
            asset_id=str(data.get("asset_id", "")),
            mesh_path=str(data.get("mesh_path", "")),
            triangle_count=int(data.get("triangle_count", 0)),
            vertex_count=int(data.get("vertex_count", 0)),
            generator=str(data.get("generator", "")),
        )


# ---------------------------------------------------------------------------
# Object instance in the world
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ObjectInstance:
    """
    One object instance in the WorldContract.

    Contains solved transforms, asset binding, physics intent, and material
    intent. Each instance corresponds to one UUID from the Brief manifest.
    """
    object_id: str = ""                           # stable UUID from Brief
    name: str = ""
    position: Vec3 = field(default_factory=Vec3)
    rotation: Quaternion = field(default_factory=Quaternion)
    scale: Vec3 = field(default_factory=lambda: Vec3(1.0, 1.0, 1.0))
    asset_binding: AssetBinding = field(default_factory=AssetBinding)
    physics_intent: str = "static"                # PhysicsIntent value
    material_intent: MaterialIntent = field(default_factory=MaterialIntent)
    semantic_label: str = ""
    is_architectural: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "position": self.position.to_dict(),
            "rotation": self.rotation.to_dict(),
            "scale": self.scale.to_dict(),
            "asset_binding": self.asset_binding.to_dict(),
            "physics_intent": self.physics_intent,
            "material_intent": self.material_intent.to_dict(),
            "semantic_label": self.semantic_label,
            "is_architectural": self.is_architectural,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ObjectInstance:
        return cls(
            object_id=str(data.get("object_id", "")),
            name=str(data.get("name", "")),
            position=Vec3.from_dict(data.get("position", {})),
            rotation=Quaternion.from_dict(data.get("rotation", {"x": 0, "y": 0, "z": 0, "w": 1})),
            scale=Vec3.from_dict(data.get("scale", {"x": 1, "y": 1, "z": 1})),
            asset_binding=AssetBinding.from_dict(data.get("asset_binding", {})),
            physics_intent=str(data.get("physics_intent", "static")),
            material_intent=MaterialIntent.from_dict(data.get("material_intent", {})),
            semantic_label=str(data.get("semantic_label", "")),
            is_architectural=bool(data.get("is_architectural", False)),
        )


# ---------------------------------------------------------------------------
# Relationship graph
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Relationship:
    """A directed relationship between two objects in the scene."""
    source_id: str = ""           # UUID of source object
    target_id: str = ""           # UUID of target object
    relationship_type: str = "adjacency"  # RelationshipType value
    metadata: str = ""            # optional JSON-encoded extra data

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship_type": self.relationship_type,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Relationship:
        return cls(
            source_id=str(data.get("source_id", "")),
            target_id=str(data.get("target_id", "")),
            relationship_type=str(data.get("relationship_type", "adjacency")),
            metadata=str(data.get("metadata", "")),
        )


# ---------------------------------------------------------------------------
# Lighting configuration
# ---------------------------------------------------------------------------


class LightingContractError(ValueError):
    """Raised when canonical lighting data is missing or cannot be represented exactly."""


_LIGHT_SOURCE_FIELDS = frozenset({
    "light_id", "light_type", "position", "color", "intensity",
    "temperature", "cast_shadows",
})
_LIGHTING_CONFIG_FIELDS = frozenset({"ambient_color", "ambient_intensity", "lights"})


def _require_lighting_fields(
    data: dict[str, Any], required: frozenset[str], label: str
) -> None:
    missing = sorted(required - set(data))
    if missing:
        raise LightingContractError(
            f"{label} is incomplete; missing authoritative fields: {', '.join(missing)}"
        )


def _lighting_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LightingContractError(f"{label} must be an explicit finite number")
    result = float(value)
    if not math.isfinite(result):
        raise LightingContractError(f"{label} must be an explicit finite number")
    return result


@dataclass(frozen=True)
class LightSource:
    """A fully declared, Scene-Canon-derived light source in contract space."""
    light_id: str = ""
    light_type: str = "point"     # only types with complete authoritative data may compile
    position: Vec3 = field(default_factory=Vec3)
    color: str = "#ffffff"        # final render color; already carries explicit white balance
    intensity: float = 1.0
    temperature: float = 5500.0
    cast_shadows: bool = True
    intensity_unit: str = "relative"  # relative (legacy) | candela
    white_balance_color: str = "#ffffff"
    legacy_color: str = "#ffffff"
    legacy_intensity: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "light_id": self.light_id,
            "light_type": self.light_type,
            "position": self.position.to_dict(),
            "color": self.color,
            "intensity": self.intensity,
            "temperature": self.temperature,
            "cast_shadows": self.cast_shadows,
            "intensity_unit": self.intensity_unit,
            "white_balance_color": self.white_balance_color,
            "legacy_color": self.legacy_color,
            "legacy_intensity": self.legacy_intensity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightSource:
        _require_lighting_fields(data, _LIGHT_SOURCE_FIELDS, "light source")
        position = data["position"]
        if not isinstance(position, dict):
            raise LightingContractError("light position must be an explicit x/y/z object")
        _require_lighting_fields(position, frozenset({"x", "y", "z"}), "light position")
        return cls(
            light_id=data["light_id"],
            light_type=data["light_type"],
            position=Vec3(position["x"], position["y"], position["z"]),
            color=data["color"],
            intensity=data["intensity"],
            temperature=data["temperature"],
            cast_shadows=data["cast_shadows"],
            intensity_unit=str(data.get("intensity_unit", "relative")),
            white_balance_color=str(data.get("white_balance_color", data["color"])),
            legacy_color=str(data.get("legacy_color", data["color"])),
            legacy_intensity=float(data.get("legacy_intensity", data["intensity"])),
        )


@dataclass(frozen=True)
class LightingConfig:
    """Complete ambient, exposure, compatibility, and physical-light authority."""
    ambient_color: str = "#1a1a2e"
    ambient_intensity: float = 0.3
    lights: tuple[LightSource, ...] = ()
    ambient_intensity_unit: str = "relative"
    exposure: float = 1.0
    derivation_profile: str = "legacy-normalized/v1"
    source_luminance: float = -1.0
    source_chromaticity: str = "#ffffff"
    white_balance_color: str = "#ffffff"
    derivation_sha256: str = ""
    legacy_ambient_color: str = "#1a1a2e"
    legacy_ambient_intensity: float = 0.3

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambient_color": self.ambient_color,
            "ambient_intensity": self.ambient_intensity,
            "lights": [light.to_dict() for light in self.lights],
            "ambient_intensity_unit": self.ambient_intensity_unit,
            "exposure": self.exposure,
            "derivation_profile": self.derivation_profile,
            "source_luminance": self.source_luminance,
            "source_chromaticity": self.source_chromaticity,
            "white_balance_color": self.white_balance_color,
            "derivation_sha256": self.derivation_sha256,
            "legacy_ambient_color": self.legacy_ambient_color,
            "legacy_ambient_intensity": self.legacy_ambient_intensity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightingConfig:
        _require_lighting_fields(data, _LIGHTING_CONFIG_FIELDS, "lighting configuration")
        if not isinstance(data["lights"], list):
            raise LightingContractError("lighting configuration lights must be an explicit list")
        return cls(
            ambient_color=data["ambient_color"],
            ambient_intensity=data["ambient_intensity"],
            lights=tuple(LightSource.from_dict(item) for item in data["lights"]),
            ambient_intensity_unit=str(data.get("ambient_intensity_unit", "relative")),
            exposure=float(data.get("exposure", 1.0)),
            derivation_profile=str(data.get("derivation_profile", "legacy-normalized/v1")),
            source_luminance=float(data.get("source_luminance", -1.0)),
            source_chromaticity=str(data.get("source_chromaticity", "#ffffff")),
            white_balance_color=str(data.get("white_balance_color", data["ambient_color"])),
            derivation_sha256=str(data.get("derivation_sha256", "")),
            legacy_ambient_color=str(data.get("legacy_ambient_color", data["ambient_color"])),
            legacy_ambient_intensity=float(data.get("legacy_ambient_intensity", data["ambient_intensity"])),
        )


def validate_lighting_config(
    lighting: LightingConfig,
    *,
    supported_light_types: frozenset[str] | None = None,
) -> None:
    """Validate complete lighting without deriving, clamping, or normalizing values."""
    if not isinstance(lighting, LightingConfig):
        raise LightingContractError("WorldContract lighting must be a LightingConfig")

    def require_hex(value: Any, label: str) -> None:
        if (
            not isinstance(value, str) or len(value) != 7 or not value.startswith("#")
            or any(character not in "0123456789abcdefABCDEF" for character in value[1:])
        ):
            raise LightingContractError(f"{label} must be exact #RRGGBB")

    require_hex(lighting.ambient_color, "ambient light color")
    require_hex(lighting.source_chromaticity, "Canon source chromaticity")
    require_hex(lighting.white_balance_color, "white-balance color")
    require_hex(lighting.legacy_ambient_color, "legacy ambient color")
    ambient = _lighting_number(lighting.ambient_intensity, "ambient light intensity")
    legacy_ambient = _lighting_number(lighting.legacy_ambient_intensity, "legacy ambient intensity")
    exposure = _lighting_number(lighting.exposure, "renderer exposure")
    source_luminance = _lighting_number(lighting.source_luminance, "Canon source luminance")
    if ambient < 0.0 or legacy_ambient < 0.0:
        raise LightingContractError("ambient light intensity cannot be negative")
    if lighting.ambient_intensity_unit not in {"relative", "scene-linear-multiplier"}:
        raise LightingContractError("ambient intensity unit is unsupported")
    if not 0.1 <= exposure <= 4.0:
        raise LightingContractError("renderer exposure must be within 0.1..4.0")
    if source_luminance != -1.0 and not 0.0 <= source_luminance <= 1.0:
        raise LightingContractError("Canon source luminance must be -1 legacy or within 0..1")
    if lighting.derivation_sha256 and (
        len(lighting.derivation_sha256) != 64
        or any(character not in "0123456789abcdef" for character in lighting.derivation_sha256)
    ):
        raise LightingContractError("lighting derivation provenance must be SHA-256")

    physical = lighting.derivation_profile == "canon-mean-relative-luminance-to-three-physical/v1"
    if physical:
        if lighting.ambient_intensity_unit != "scene-linear-multiplier":
            raise LightingContractError("physical lighting requires explicit scene-linear ambient units")
        if not 0.55 <= ambient <= 1.25 or not 0.85 <= exposure <= 1.35:
            raise LightingContractError("physical ambient/exposure values exceed profile bounds")
        if source_luminance < 0.0 or not lighting.derivation_sha256:
            raise LightingContractError("physical lighting requires source luminance and derivation provenance")

    light_ids: set[str] = set()
    for light in lighting.lights:
        if not isinstance(light, LightSource):
            raise LightingContractError("lighting entries must be LightSource values")
        if not isinstance(light.light_id, str) or not light.light_id.strip() or light.light_id in light_ids:
            raise LightingContractError("contract light IDs must be unique and nonempty")
        light_ids.add(light.light_id)
        if not isinstance(light.light_type, str) or (
            supported_light_types is not None and light.light_type not in supported_light_types
        ):
            raise LightingContractError(
                f"light {light.light_id!r} type {light.light_type!r} lacks enough "
                "contract data for exact rendering"
            )
        for axis, value in zip("xyz", (light.position.x, light.position.y, light.position.z)):
            _lighting_number(value, f"light {light.light_id} position.{axis}")
        require_hex(light.color, f"light {light.light_id!r} color")
        require_hex(light.white_balance_color, f"light {light.light_id!r} white-balance color")
        require_hex(light.legacy_color, f"light {light.light_id!r} legacy color")
        intensity = _lighting_number(light.intensity, f"light {light.light_id} intensity")
        legacy_intensity = _lighting_number(light.legacy_intensity, f"light {light.light_id} legacy intensity")
        temperature = _lighting_number(light.temperature, f"light {light.light_id} temperature")
        if intensity < 0.0 or legacy_intensity < 0.0:
            raise LightingContractError(f"light {light.light_id!r} intensity cannot be negative")
        if light.intensity_unit not in {"relative", "candela"}:
            raise LightingContractError(f"light {light.light_id!r} intensity unit is unsupported")
        if not 1000.0 <= temperature <= 12000.0:
            raise LightingContractError(f"light {light.light_id!r} temperature must be within 1000K..12000K")
        if physical and (light.intensity_unit != "candela" or not 8.0 <= intensity <= 56.0):
            raise LightingContractError("physical point-light candela exceeds profile bounds")
        if not isinstance(light.cast_shadows, bool):
            raise LightingContractError(
                f"light {light.light_id!r} cast_shadows must be explicit boolean"
            )


# ---------------------------------------------------------------------------
# WorldContract — the binding contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorldContract:
    """
    The single hash-bound, engine-neutral contract binding Plan, assets,
    physics, lighting, and camera into one deterministic document.

    Every consumer (browser, Godot, UPBGE) reads this identically.
    No artifact claims final status without a valid WorldContract hash.

    Requirements:
        19.1 - Binds Plan revision, CameraContract hash, room shell, instances,
               lighting, relationship graph
        19.2 - Deterministic serialization + SHA-256 hash
        19.3 - Hash binds plan revision, camera, room authority, instances,
               transforms, relationships, materials, physics, approved assets
        19.4 - No artifact claims final without valid hash
        19.5 - Every final event contains solved transforms + exact hash
        19.6 - Provisional events explicitly marked provisional
    """
    # Binding references
    plan_revision: str = ""           # revision identifier (e.g. "rev-3")
    camera_hash: str = ""             # SHA-256 of the CameraContract
    camera: CameraContract | None = None  # exact immutable projection; no consumer inference
    room_shell_ref: str = ""          # path/hash reference to room shell mesh
    navigation: FirstPersonNavigation | None = None  # exact Plan-derived runtime authority

    # Instances
    instances: tuple[ObjectInstance, ...] = ()

    # Explicit runtime interactions; consumers never infer these from assets.
    interactions: tuple[InteractionBinding, ...] = ()

    # Relationships
    relationships: tuple[Relationship, ...] = ()

    # Lighting
    lighting: LightingConfig = field(default_factory=LightingConfig)

    # Contract metadata
    contract_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = ""              # ISO 8601 timestamp (frozen at creation)

    # Computed hash (empty until compute_hash is called)
    contract_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        return {
            "plan_revision": self.plan_revision,
            "camera_hash": self.camera_hash,
            "camera": self.camera.to_dict() if self.camera is not None else None,
            "room_shell_ref": self.room_shell_ref,
            "navigation": self.navigation.to_dict() if self.navigation is not None else None,
            "instances": [inst.to_dict() for inst in self.instances],
            "interactions": [item.to_dict() for item in self.interactions],
            "relationships": [rel.to_dict() for rel in self.relationships],
            "lighting": self.lighting.to_dict(),
            "contract_id": self.contract_id,
            "created_at": self.created_at,
            "contract_hash": self.contract_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorldContract:
        """Reconstruct from a plain dict."""
        return cls(
            plan_revision=str(data.get("plan_revision", "")),
            camera_hash=str(data.get("camera_hash", "")),
            camera=(
                CameraContract.from_dict(data["camera"])
                if data.get("camera") is not None else None
            ),
            room_shell_ref=str(data.get("room_shell_ref", "")),
            navigation=(
                FirstPersonNavigation.from_dict(data["navigation"])
                if data.get("navigation") is not None else None
            ),
            instances=tuple(
                ObjectInstance.from_dict(d) for d in data.get("instances", [])
            ),
            interactions=tuple(
                InteractionBinding.from_dict(d) for d in data.get("interactions", [])
            ),
            relationships=tuple(
                Relationship.from_dict(d) for d in data.get("relationships", [])
            ),
            lighting=LightingConfig.from_dict(data.get("lighting", {})),
            contract_id=str(data.get("contract_id", str(uuid.uuid4()))),
            created_at=str(data.get("created_at", "")),
            contract_hash=str(data.get("contract_hash", "")),
        )


# ---------------------------------------------------------------------------
# Canonical serialization and hashing functions
# ---------------------------------------------------------------------------

def serialize(contract: WorldContract) -> str:
    """
    Produce the canonical JSON serialization of a WorldContract.

    Uses sorted keys and compact separators to ensure determinism.
    The contract_hash field is EXCLUDED from the serializable payload
    used for hashing (it would be circular), but included in the full
    serialization for transport/storage.

    Returns:
        Deterministic JSON string.
    """
    data = contract.to_dict()
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _hashable_payload(contract: WorldContract) -> str:
    """
    Produce the canonical JSON payload used for hash computation.

    Excludes the contract_hash field itself (circular dependency) but
    includes ALL other fields that the hash must bind:
    - plan_revision
    - camera_hash
    - room_shell_ref (room authority)
    - instances (positions, rotations, scales, asset bindings, physics, materials)
    - relationships
    - lighting

    Per Req 19.3: hash binds plan revision, camera, room authority, instances,
    transforms, relationships, materials, physics, and approved asset bindings.
    """
    data = contract.to_dict()
    # Remove contract_hash from the payload used to compute the hash
    data.pop("contract_hash", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_hash(contract: WorldContract) -> str:
    """
    Compute the SHA-256 hash of the WorldContract's canonical payload.

    The hash covers: plan_revision, camera_hash, room_shell_ref,
    all instances (with transforms, asset bindings, physics, materials),
    relationships, and lighting config.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    payload = _hashable_payload(contract)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_hash(contract: WorldContract) -> bool:
    """
    Verify that the stored contract_hash matches the computed hash.

    Returns:
        True if the stored hash equals the freshly computed hash.
        False if there's a mismatch or the hash is empty.
    """
    if not contract.contract_hash:
        return False
    return contract.contract_hash == compute_hash(contract)


# ---------------------------------------------------------------------------
# Builder functions (since frozen dataclasses can't be mutated)
# ---------------------------------------------------------------------------

def bind_plan_revision(contract: WorldContract, plan_revision: str) -> WorldContract:
    """
    Create a new WorldContract with the given plan_revision bound.

    Args:
        contract: The existing contract.
        plan_revision: The plan revision identifier to bind.

    Returns:
        A new WorldContract with plan_revision set.
    """
    data = contract.to_dict()
    data["plan_revision"] = plan_revision
    return WorldContract.from_dict(data)


def bind_camera_hash(contract: WorldContract, camera_hash: str) -> WorldContract:
    """
    Create a new WorldContract with the given camera_hash bound.

    Args:
        contract: The existing contract.
        camera_hash: The SHA-256 hash of the CameraContract.

    Returns:
        A new WorldContract with camera_hash set.
    """
    data = contract.to_dict()
    data["camera_hash"] = camera_hash
    return WorldContract.from_dict(data)


def finalize(contract: WorldContract) -> WorldContract:
    """
    Compute the hash and return a finalized WorldContract.

    This is the last step before a contract is published. After this,
    any consumer can call verify_hash() to confirm integrity.

    Returns:
        A new WorldContract with contract_hash set.
    """
    computed = compute_hash(contract)
    data = contract.to_dict()
    data["contract_hash"] = computed
    return WorldContract.from_dict(data)


def add_instance(contract: WorldContract, instance: ObjectInstance) -> WorldContract:
    """
    Create a new WorldContract with an additional object instance.

    Args:
        contract: The existing contract.
        instance: The ObjectInstance to add.

    Returns:
        A new WorldContract with the instance appended.
    """
    data = contract.to_dict()
    data["instances"] = list(data["instances"]) + [instance.to_dict()]
    return WorldContract.from_dict(data)


def add_relationship(contract: WorldContract, relationship: Relationship) -> WorldContract:
    """
    Create a new WorldContract with an additional relationship.

    Args:
        contract: The existing contract.
        relationship: The Relationship to add.

    Returns:
        A new WorldContract with the relationship appended.
    """
    data = contract.to_dict()
    data["relationships"] = list(data["relationships"]) + [relationship.to_dict()]
    return WorldContract.from_dict(data)


def set_lighting(contract: WorldContract, lighting: LightingConfig) -> WorldContract:
    """
    Create a new WorldContract with the given lighting config.

    Args:
        contract: The existing contract.
        lighting: The LightingConfig to set.

    Returns:
        A new WorldContract with lighting set.
    """
    data = contract.to_dict()
    data["lighting"] = lighting.to_dict()
    return WorldContract.from_dict(data)


# ---------------------------------------------------------------------------
# Event helpers (Req 19.5, 19.6)
# ---------------------------------------------------------------------------

def make_final_event(
    contract: WorldContract,
    object_id: str,
    event_type: str = "object_placed",
) -> dict[str, Any]:
    """
    Create a final event payload for an object, containing solved transforms
    and the exact contract hash.

    Per Req 19.5: Every final object event contains solved transforms + exact hash.

    Args:
        contract: The finalized WorldContract.
        object_id: UUID of the object this event concerns.
        event_type: Type of event.

    Returns:
        Event dict with status=final, transforms, and contract hash.

    Raises:
        ValueError: If the contract has no hash (not finalized).
    """
    if not contract.contract_hash:
        raise ValueError(
            "Cannot create final event from un-finalized contract. "
            "Call finalize() first."
        )

    # Find the instance
    instance = None
    for inst in contract.instances:
        if inst.object_id == object_id:
            instance = inst
            break

    if instance is None:
        raise ValueError(f"Object {object_id} not found in contract instances.")

    return {
        "status": EventStatus.FINAL.value,
        "event_type": event_type,
        "object_id": object_id,
        "position": instance.position.to_dict(),
        "rotation": instance.rotation.to_dict(),
        "scale": instance.scale.to_dict(),
        "contract_hash": contract.contract_hash,
    }


def make_provisional_event(
    object_id: str,
    event_type: str = "object_placed",
    position: Vec3 | None = None,
    rotation: Quaternion | None = None,
    scale: Vec3 | None = None,
) -> dict[str, Any]:
    """
    Create a provisional event payload (before contract finalization).

    Per Req 19.6: Provisional events are explicitly marked provisional.

    Args:
        object_id: UUID of the object.
        event_type: Type of event.
        position: Optional provisional position.
        rotation: Optional provisional rotation.
        scale: Optional provisional scale.

    Returns:
        Event dict with status=provisional.
    """
    event: dict[str, Any] = {
        "status": EventStatus.PROVISIONAL.value,
        "event_type": event_type,
        "object_id": object_id,
        "contract_hash": None,
    }
    if position is not None:
        event["position"] = position.to_dict()
    if rotation is not None:
        event["rotation"] = rotation.to_dict()
    if scale is not None:
        event["scale"] = scale.to_dict()
    return event
