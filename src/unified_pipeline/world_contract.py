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
class MaterialIntent:
    """Material binding intent for an object instance."""
    base_color: str = ""          # hex color or texture reference
    metallic: float = 0.0         # 0-1
    roughness: float = 0.5        # 0-1
    normal_map_ref: str = ""      # path or empty
    pass_level: int = 1           # 1 = immediate, 2 = PBR refined

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_color": self.base_color,
            "metallic": self.metallic,
            "roughness": self.roughness,
            "normal_map_ref": self.normal_map_ref,
            "pass_level": self.pass_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialIntent:
        return cls(
            base_color=str(data.get("base_color", "")),
            metallic=float(data.get("metallic", 0.0)),
            roughness=float(data.get("roughness", 0.5)),
            normal_map_ref=str(data.get("normal_map_ref", "")),
            pass_level=int(data.get("pass_level", 1)),
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

@dataclass(frozen=True)
class LightSource:
    """A light source in the world."""
    light_id: str = ""
    light_type: str = "point"     # "point" | "directional" | "spot" | "area"
    position: Vec3 = field(default_factory=Vec3)
    color: str = "#ffffff"        # hex color
    intensity: float = 1.0
    temperature: float = 5500.0   # Kelvin
    cast_shadows: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "light_id": self.light_id,
            "light_type": self.light_type,
            "position": self.position.to_dict(),
            "color": self.color,
            "intensity": self.intensity,
            "temperature": self.temperature,
            "cast_shadows": self.cast_shadows,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightSource:
        return cls(
            light_id=str(data.get("light_id", "")),
            light_type=str(data.get("light_type", "point")),
            position=Vec3.from_dict(data.get("position", {})),
            color=str(data.get("color", "#ffffff")),
            intensity=float(data.get("intensity", 1.0)),
            temperature=float(data.get("temperature", 5500.0)),
            cast_shadows=bool(data.get("cast_shadows", True)),
        )


@dataclass(frozen=True)
class LightingConfig:
    """Complete lighting configuration for the world."""
    ambient_color: str = "#1a1a2e"
    ambient_intensity: float = 0.3
    lights: tuple[LightSource, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambient_color": self.ambient_color,
            "ambient_intensity": self.ambient_intensity,
            "lights": [light.to_dict() for light in self.lights],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LightingConfig:
        return cls(
            ambient_color=str(data.get("ambient_color", "#1a1a2e")),
            ambient_intensity=float(data.get("ambient_intensity", 0.3)),
            lights=tuple(
                LightSource.from_dict(ld) for ld in data.get("lights", [])
            ),
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

    # Instances
    instances: tuple[ObjectInstance, ...] = ()

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
            "instances": [inst.to_dict() for inst in self.instances],
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
            instances=tuple(
                ObjectInstance.from_dict(d) for d in data.get("instances", [])
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
