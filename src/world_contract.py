"""Versioned, engine-neutral world contract and deterministic approved-input conversion."""

from __future__ import annotations

import hashlib
import json
import math
import re
from enum import Enum
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.camera_contract import CameraContract
from src.floor_plan.models import FloorPlan, FloorPlanV11, PlanItem, PlanOpening
from src.models import MaterialProps, PhysicsBody, SceneGraph, SceneObject

SCHEMA_VERSION = "world-contract/v1"
ROOM_SHELL_SCHEMA_VERSION = "room-shell/v1"
OPENING_SCHEMA_VERSION = "world-opening/v1"
INSTANCE_SCHEMA_VERSION = "world-instance/v1"
MATERIAL_SCHEMA_VERSION = "material-intent/v1"
LIGHT_SCHEMA_VERSION = "world-light/v1"
CAMERA_SCHEMA_VERSION = "camera-binding/v1"
PHYSICS_INTENT_SCHEMA_VERSION = "physics-intent/v1"
PHYSICS_POLICY_SCHEMA_VERSION = "physics-policy/v1"
INTERACTION_SCHEMA_VERSION = "interaction-intent/v1"
EXPORT_POLICY_SCHEMA_VERSION = "export-policy/v1"
COORDINATE_SYSTEM = "right-handed-x-right-y-up-z-depth"
LENGTH_UNIT = "meter"
ANGLE_UNIT = "degree"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_TOLERANCE = 1e-9


class WorldContractError(ValueError):
    """Raised when approved authorities cannot form one unambiguous contract."""


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, frozen=True, str_strip_whitespace=True
    )


def _valid_id(value: str) -> str:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError("must be a stable identifier, not a path or free-form value")
    return value


def _unique(values: Sequence[Any], label: str) -> None:
    ids = [value.id for value in values]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label} IDs: {', '.join(duplicates)}")
class Wall(str, Enum):
    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"


class Mount(str, Enum):
    FLOOR = "floor"
    WALL = "wall"
    CEILING = "ceiling"


class BodyMode(str, Enum):
    STATIC = "static"
    DYNAMIC = "dynamic"
    KINEMATIC = "kinematic"
    TRIGGER = "trigger"


class RelationKind(str, Enum):
    CENTERED = "centered"
    AGAINST_WALL = "against_wall"
    ADJACENT_TO = "adjacent_to"
    NORTH_OF = "north_of"
    SOUTH_OF = "south_of"
    EAST_OF = "east_of"
    WEST_OF = "west_of"
    AROUND = "around"
    ABOVE = "above"
    FACING = "facing"
    NEAR_CORNER = "near_corner"


class ExportTarget(str, Enum):
    UPBGE_BLEND = "upbge_blend"
    UPBGE_RUNTIME = "upbge_runtime"
    GLB = "glb"
    GODOT = "godot"
    THREE_JS = "three_js"
    REFERENCE_RENDER = "reference_render"


class Vector3(ContractModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Dimensions(ContractModel):
    width_m: float = Field(gt=0.0)
    height_m: float = Field(gt=0.0)
    depth_m: float = Field(gt=0.0)


class Transform(ContractModel):
    position_m: Vector3 = Field(default_factory=Vector3)
    rotation_deg: Vector3 = Field(default_factory=Vector3)
    scale: Vector3 = Field(default_factory=lambda: Vector3(x=1.0, y=1.0, z=1.0))

    @model_validator(mode="after")
    def positive_scale(self) -> "Transform":
        if min(self.scale.x, self.scale.y, self.scale.z) <= 0:
            raise ValueError("transform scale components must be positive")
        return self


class SourceBinding(ContractModel):
    session_id: str
    interface_version: int = Field(ge=1)
    profile_id: str
    plan_revision: int = Field(ge=0)
    plan_hash: str
    scene_graph_hash: str
    camera_contract_id: str
    camera_contract_hash: str
    appearance_intent_hash: str
    canon_hash: str | None = None

    _session_id = field_validator("session_id")(_valid_id)
    _profile_id = field_validator("profile_id")(_valid_id)
    _camera_id = field_validator("camera_contract_id")(_valid_id)

    @field_validator(
        "plan_hash", "scene_graph_hash", "camera_contract_hash",
        "appearance_intent_hash", "canon_hash",
    )
    @classmethod
    def valid_hash(cls, value: str | None) -> str | None:
        if value is not None and not _HASH_PATTERN.fullmatch(value):
            raise ValueError("must be a lowercase SHA-256 hash")
        return value


class MaterialIntent(ContractModel):
    schema_version: Literal["material-intent/v1"] = MATERIAL_SCHEMA_VERSION
    id: str
    base_color: str = "#808080"
    metallic: float = Field(default=0.0, ge=0.0, le=1.0)
    roughness: float = Field(default=0.8, ge=0.0, le=1.0)
    emission_color: str | None = None
    emission_strength: float = Field(default=0.0, ge=0.0)

    _id = field_validator("id")(_valid_id)


class RoomShell(ContractModel):
    schema_version: Literal["room-shell/v1"] = ROOM_SHELL_SCHEMA_VERSION
    id: str = "room"
    dimensions: Dimensions
    floor_material_id: str
    wall_material_id: str
    ceiling_material_id: str

    _ids = field_validator(
        "id", "floor_material_id", "wall_material_id", "ceiling_material_id"
    )(_valid_id)


class WorldOpening(ContractModel):
    schema_version: Literal["world-opening/v1"] = OPENING_SCHEMA_VERSION
    id: str
    room_id: str = "room"
    kind: Literal["door", "window"]
    wall: Wall
    offset_m: float = 0.0
    width_m: float = Field(gt=0.0)
    height_m: float = Field(gt=0.0)
    sill_height_m: float = Field(default=0.0, ge=0.0)
    physics_intent_id: str | None = None

    _ids = field_validator("id", "room_id", "physics_intent_id")(
        lambda value: _valid_id(value) if value is not None else value
    )
class RelationIntent(ContractModel):
    kind: RelationKind
    target_id: str | None = None
    wall: Wall | None = None
    parameters_m: dict[str, float] = Field(default_factory=dict)
    weight: float = Field(default=1.0, gt=0.0)
    relaxable: bool = False

    _target_id = field_validator("target_id")(
        lambda value: _valid_id(value) if value is not None else value
    )

    @model_validator(mode="after")
    def required_reference(self) -> "RelationIntent":
        wall_relations = {RelationKind.AGAINST_WALL, RelationKind.NEAR_CORNER}
        target_optional = wall_relations | {RelationKind.CENTERED}
        if self.kind in wall_relations and self.wall is None:
            raise ValueError(f"{self.kind.value} requires a wall")
        if self.kind not in target_optional and self.target_id is None:
            raise ValueError(f"{self.kind.value} requires a target_id")
        return self


class WorldInstance(ContractModel):
    schema_version: Literal["world-instance/v1"] = INSTANCE_SCHEMA_VERSION
    id: str
    name: str
    category: Literal["furniture", "fixture", "architectural", "decor"]
    mount: Mount
    transform: Transform
    dimensions: Dimensions
    fixed: bool = False
    clearance_m: float = Field(default=0.0, ge=0.0)
    material_id: str
    physics_intent_id: str
    geometry_strategy: Literal["primitive", "generated", "asset"] = "primitive"
    primitive_shape: Literal["box", "cylinder", "sphere", "plane", "capsule"] | None = None
    asset_registry_id: str | None = None
    description: str = ""
    relations: tuple[RelationIntent, ...] = ()

    _ids = field_validator("id", "material_id", "physics_intent_id")(_valid_id)
    _asset_id = field_validator("asset_registry_id")(
        lambda value: _valid_id(value) if value is not None else value
    )

    @model_validator(mode="after")
    def explicit_geometry_binding(self) -> "WorldInstance":
        if self.geometry_strategy == "asset":
            if self.asset_registry_id is None:
                raise ValueError("asset geometry strategy requires asset_registry_id")
            if self.primitive_shape is not None:
                raise ValueError("asset geometry strategy cannot declare primitive_shape")
        else:
            if self.primitive_shape is None:
                raise ValueError(
                    f"{self.geometry_strategy} geometry strategy requires primitive_shape"
                )
            if self.asset_registry_id is not None:
                raise ValueError(
                    f"{self.geometry_strategy} geometry strategy cannot declare asset_registry_id"
                )
        return self

    @field_validator("relations")
    @classmethod
    def order_relations(cls, values: tuple[RelationIntent, ...]) -> tuple[RelationIntent, ...]:
        return tuple(sorted(values, key=lambda item: (
            item.kind.value, item.target_id or "", item.wall.value if item.wall else ""
        )))


class PhysicsIntent(ContractModel):
    schema_version: Literal["physics-intent/v1"] = PHYSICS_INTENT_SCHEMA_VERSION
    id: str
    subject_id: str
    body_mode: BodyMode
    collision_shape: Literal["box", "cylinder", "sphere", "capsule", "mesh"] = "box"
    mass_kg: float = Field(default=0.0, ge=0.0)
    friction: float = Field(default=0.5, ge=0.0)
    restitution: float = Field(default=0.1, ge=0.0, le=1.0)
    can_topple: bool = False

    _ids = field_validator("id", "subject_id")(_valid_id)

    @model_validator(mode="after")
    def dynamic_mass(self) -> "PhysicsIntent":
        if self.body_mode == BodyMode.DYNAMIC and self.mass_kg <= 0:
            raise ValueError("dynamic physics intent requires positive mass_kg")
        return self


class PhysicsPolicy(ContractModel):
    schema_version: Literal["physics-policy/v1"] = PHYSICS_POLICY_SCHEMA_VERSION
    gravity_m_s2: Vector3 = Field(default_factory=lambda: Vector3(x=0.0, y=-9.81, z=0.0))
    intents: tuple[PhysicsIntent, ...] = ()

    @field_validator("intents")
    @classmethod
    def order_intents(cls, values: tuple[PhysicsIntent, ...]) -> tuple[PhysicsIntent, ...]:
        _unique(values, "physics intent")
        subjects = [value.subject_id for value in values]
        duplicate_subjects = sorted({value for value in subjects if subjects.count(value) > 1})
        if duplicate_subjects:
            raise ValueError(
                f"conflicting physics authorities for: {', '.join(duplicate_subjects)}"
            )
        return tuple(sorted(values, key=lambda item: item.id))


class WorldLight(ContractModel):
    schema_version: Literal["world-light/v1"] = LIGHT_SCHEMA_VERSION
    id: str
    name: str
    light_type: Literal["point", "spot", "directional", "area"]
    position_m: Vector3
    direction: Vector3 = Field(default_factory=lambda: Vector3(x=0.0, y=-1.0, z=0.0))
    color: str
    color_temperature_k: int = Field(default=4000, gt=0)
    intensity: float = Field(default=1.0, ge=0.0)
    range_m: float = Field(default=5.0, gt=0.0)
    spot_angle_deg: float = Field(default=45.0, gt=0.0, lt=180.0)
    cast_shadows: bool = True
    fixture_instance_id: str | None = None

    _ids = field_validator("id", "fixture_instance_id")(
        lambda value: _valid_id(value) if value is not None else value
    )


class CameraBinding(ContractModel):
    schema_version: Literal["camera-binding/v1"] = CAMERA_SCHEMA_VERSION
    id: str
    source_schema_version: str
    projection: Literal["perspective"] = "perspective"
    position_m: Vector3
    target_m: Vector3
    up: Vector3
    vertical_fov_deg: float = Field(gt=0.0, lt=180.0)
    aspect_ratio: float = Field(gt=0.0)
    image_width_px: int = Field(gt=0)
    image_height_px: int = Field(gt=0)
    near_plane_m: float = Field(gt=0.0)
    far_plane_m: float = Field(gt=0.0)

    _id = field_validator("id")(_valid_id)

    @model_validator(mode="after")
    def valid_frustum(self) -> "CameraBinding":
        if self.near_plane_m >= self.far_plane_m:
            raise ValueError("camera near plane must be less than far plane")
        if self.position_m == self.target_m:
            raise ValueError("camera position and target must differ")
        if self.up == Vector3():
            raise ValueError("camera up vector must be non-zero")
        return self
class AppearanceIntent(ContractModel):
    schema_version: Literal["appearance-intent/v1"] = "appearance-intent/v1"
    id: str
    era: str = ""
    mood: str = ""
    palette: str = ""
    architecture_notes: str = ""
    lighting_notes: str = ""
    key_objects: tuple[str, ...] = ()
    image_prompt: str = ""

    _id = field_validator("id")(_valid_id)

    @field_validator("key_objects")
    @classmethod
    def order_key_objects(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(values))


class InteractionIntent(ContractModel):
    schema_version: Literal["interaction-intent/v1"] = INTERACTION_SCHEMA_VERSION
    id: str
    kind: Literal["door", "grab"]
    subject_id: str
    target_id: str | None = None
    parameters: dict[str, str | bool | int | float] = Field(default_factory=dict)

    _ids = field_validator("id", "subject_id", "target_id")(
        lambda value: _valid_id(value) if value is not None else value
    )


class ExportPolicy(ContractModel):
    schema_version: Literal["export-policy/v1"] = EXPORT_POLICY_SCHEMA_VERSION
    targets: tuple[ExportTarget, ...] = ()
    unsupported_behavior: Literal["reject", "report"] = "report"
    include_metadata_sidecar: bool = True

    @field_validator("targets")
    @classmethod
    def order_targets(cls, values: tuple[ExportTarget, ...]) -> tuple[ExportTarget, ...]:
        if len(set(values)) != len(values):
            raise ValueError("duplicate export targets")
        return tuple(sorted(values, key=lambda target: target.value))


class WorldContract(ContractModel):
    schema_version: Literal["world-contract/v1"] = SCHEMA_VERSION
    coordinate_system: Literal["right-handed-x-right-y-up-z-depth"] = COORDINATE_SYSTEM
    length_unit: Literal["meter"] = LENGTH_UNIT
    angle_unit: Literal["degree"] = ANGLE_UNIT
    source: SourceBinding
    room: RoomShell
    openings: tuple[WorldOpening, ...] = ()
    instances: tuple[WorldInstance, ...] = ()
    materials: tuple[MaterialIntent, ...] = ()
    lights: tuple[WorldLight, ...] = ()
    camera: CameraBinding
    appearance: AppearanceIntent
    physics: PhysicsPolicy = Field(default_factory=PhysicsPolicy)
    interactions: tuple[InteractionIntent, ...] = ()
    exports: ExportPolicy = Field(default_factory=ExportPolicy)

    @field_validator("openings", "instances", "materials", "lights", "interactions")
    @classmethod
    def order_identity_collections(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        _unique(values, "world")
        return tuple(sorted(values, key=lambda item: item.id))

    @model_validator(mode="after")
    def validate_graph(self) -> "WorldContract":
        material_ids = {item.id for item in self.materials}
        required_materials = {
            self.room.floor_material_id,
            self.room.wall_material_id,
            self.room.ceiling_material_id,
        }
        missing = sorted(required_materials - material_ids)
        if missing:
            raise ValueError(f"dangling room material references: {', '.join(missing)}")

        instance_ids = {item.id for item in self.instances}
        opening_ids = {item.id for item in self.openings}
        physics_ids = {item.id for item in self.physics.intents}
        reference_ids = instance_ids | opening_ids | {self.room.id}
        for opening in self.openings:
            if opening.room_id != self.room.id:
                raise ValueError(f"opening {opening.id} has dangling room reference")
            wall_length = (
                self.room.dimensions.width_m
                if opening.wall in {Wall.NORTH, Wall.SOUTH}
                else self.room.dimensions.depth_m
            )
            if abs(opening.offset_m) + opening.width_m / 2 > wall_length / 2 + _TOLERANCE:
                raise ValueError(f"opening {opening.id} exceeds its wall dimensions")
            if opening.sill_height_m + opening.height_m > (
                self.room.dimensions.height_m + _TOLERANCE
            ):
                raise ValueError(f"opening {opening.id} exceeds room height")
            if opening.physics_intent_id and opening.physics_intent_id not in physics_ids:
                raise ValueError(f"opening {opening.id} has dangling physics reference")

        for instance in self.instances:
            if instance.material_id not in material_ids:
                raise ValueError(f"instance {instance.id} has dangling material reference")
            if instance.physics_intent_id not in physics_ids:
                raise ValueError(f"instance {instance.id} has dangling physics reference")
            for relation in instance.relations:
                if relation.target_id and relation.target_id not in reference_ids:
                    raise ValueError(
                        f"instance {instance.id} relation has dangling target {relation.target_id}"
                    )
                if relation.target_id == instance.id:
                    raise ValueError(f"instance {instance.id} cannot relate to itself")

        for intent in self.physics.intents:
            if intent.subject_id not in instance_ids | opening_ids:
                raise ValueError(f"physics {intent.id} has dangling subject {intent.subject_id}")
        for light in self.lights:
            if light.fixture_instance_id and light.fixture_instance_id not in instance_ids:
                raise ValueError(f"light {light.id} has dangling fixture reference")
        for interaction in self.interactions:
            if interaction.subject_id not in instance_ids | opening_ids:
                raise ValueError(f"interaction {interaction.id} has dangling subject")
            if interaction.target_id and interaction.target_id not in reference_ids:
                raise ValueError(f"interaction {interaction.id} has dangling target")
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_world_contract(self)

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
def _json_value(value: Any, *, sort_identity_lists: bool = False) -> Any:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_value(item, sort_identity_lists=sort_identity_lists)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        result = [_json_value(item, sort_identity_lists=sort_identity_lists) for item in value]
        if sort_identity_lists and all(
            isinstance(item, dict) and isinstance(item.get("id"), str) for item in result
        ):
            result.sort(key=lambda item: item["id"])
        return result
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WorldContractError("canonical JSON rejects non-finite numbers")
        return 0.0 if value == 0.0 else value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise WorldContractError(f"unsupported canonical value type: {type(value).__name__}")


def _canonical_json_bytes(value: Any, *, sort_identity_lists: bool = False) -> bytes:
    normalized = _json_value(value, sort_identity_lists=sort_identity_lists)
    try:
        text = json.dumps(
            normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WorldContractError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def canonical_world_contract(
    value: WorldContract | Mapping[str, Any] | str | bytes,
) -> bytes:
    """Validate and serialize a contract to canonical UTF-8 JSON bytes."""
    if isinstance(value, (str, bytes)):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WorldContractError(f"invalid world contract JSON: {exc}") from exc
    contract = value if isinstance(value, WorldContract) else WorldContract.model_validate(value)
    return _canonical_json_bytes(contract)


def world_contract_hash(value: WorldContract | Mapping[str, Any] | str | bytes) -> str:
    return hashlib.sha256(canonical_world_contract(value)).hexdigest()


def world_contract_from_json(value: str | bytes) -> WorldContract:
    try:
        return WorldContract.model_validate_json(value)
    except ValueError as exc:
        raise WorldContractError(f"invalid world contract: {exc}") from exc


def _source_hash(value: Any) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(value, sort_identity_lists=True)
    ).hexdigest()


def _same(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=_TOLERANCE)


def _assert_same(label: str, left: float, right: float) -> None:
    if not _same(left, right):
        raise WorldContractError(
            f"conflicting authorities for {label}: Plan={left!r}, Scene_Graph={right!r}"
        )


def _check_input_ids(plan: FloorPlan, scene: SceneGraph) -> None:
    plan_ids = [item.id for item in plan.items] + [item.id for item in plan.openings]
    duplicates = sorted({value for value in plan_ids if plan_ids.count(value) > 1})
    if duplicates:
        raise WorldContractError(f"duplicate Plan IDs: {', '.join(duplicates)}")
    for label, values in (
        ("Scene_Graph object", scene.objects),
        ("Scene_Graph light", scene.lights),
        ("Scene_Graph opening", [*scene.doors, *scene.windows]),
    ):
        ids = [value.id for value in values]
        duplicates = sorted({value for value in ids if ids.count(value) > 1})
        if duplicates:
            raise WorldContractError(f"duplicate {label} IDs: {', '.join(duplicates)}")


def _validate_authorities(plan: FloorPlan, scene: SceneGraph) -> None:
    _check_input_ids(plan, scene)
    _assert_same("room.width", plan.room.width, scene.room.width)
    _assert_same("room.depth", plan.room.depth, scene.room.depth)
    _assert_same("room.height", plan.room.height, scene.room.height)
    plan_items = {item.id: item for item in plan.items}
    extras = sorted({item.id for item in scene.objects} - set(plan_items))
    if extras:
        raise WorldContractError(
            f"Scene_Graph contains objects outside authoritative Plan: {', '.join(extras)}"
        )
    for authored in scene.objects:
        planned = plan_items[authored.id]
        for label, left, right in (
            ("x", planned.x, authored.position.x),
            ("elevation", planned.elevation, authored.position.y),
            ("z", planned.z, authored.position.z),
            ("width", planned.width, authored.dimensions.x),
            ("height", planned.height, authored.dimensions.y),
            ("depth", planned.depth, authored.dimensions.z),
            ("rotation", planned.rotation_deg, authored.rotation.y),
        ):
            _assert_same(f"instance {planned.id} {label}", left, right)
        for axis, value in (
            ("x", authored.scale.x), ("y", authored.scale.y), ("z", authored.scale.z)
        ):
            _assert_same(f"instance {planned.id} scale.{axis}", 1.0, value)

    plan_openings = {item.id: item for item in plan.openings}
    graph_openings = [*scene.doors, *scene.windows]
    extras = sorted({item.id for item in graph_openings} - set(plan_openings))
    if extras:
        raise WorldContractError(
            f"Scene_Graph contains openings outside authoritative Plan: {', '.join(extras)}"
        )
    half_width, half_depth = plan.room.width / 2, plan.room.depth / 2
    for authored in graph_openings:
        planned = plan_openings[authored.id]
        authored_kind = "door" if hasattr(authored, "swing_direction") else "window"
        if authored_kind != planned.kind or authored.wall != planned.wall:
            raise WorldContractError(f"conflicting authorities for opening {planned.id}")
        expected_x = planned.offset if planned.wall in {"north", "south"} else (
            half_width if planned.wall == "east" else -half_width
        )
        expected_z = planned.offset if planned.wall in {"east", "west"} else (
            half_depth if planned.wall == "north" else -half_depth
        )
        _assert_same(f"opening {planned.id} x", expected_x, authored.position.x)
        _assert_same(f"opening {planned.id} z", expected_z, authored.position.z)
        _assert_same(f"opening {planned.id} width", planned.width, authored.width)
        _assert_same(f"opening {planned.id} height", planned.height, authored.height)
        if planned.kind == "window":
            _assert_same(
                f"opening {planned.id} sill_height", planned.sill_height,
                authored.sill_height,
            )
def _material(material_id: str, source: MaterialProps) -> MaterialIntent:
    return MaterialIntent(
        id=material_id,
        base_color=source.base_color,
        metallic=source.metallic,
        roughness=source.roughness,
        emission_color=source.emission_color,
        emission_strength=source.emission_strength,
    )


def _physics(
    physics_id: str,
    subject_id: str,
    source: Any,
    *,
    force_static: bool = False,
    shape: str = "box",
) -> PhysicsIntent:
    mode = {
        PhysicsBody.STATIC: BodyMode.STATIC,
        PhysicsBody.RIGID: BodyMode.DYNAMIC,
        PhysicsBody.KINEMATIC: BodyMode.KINEMATIC,
    }[source.body_type]
    if force_static:
        mode = BodyMode.STATIC
    allowed_shapes = {"box", "cylinder", "sphere", "capsule"}
    collision_shape = shape if shape in allowed_shapes else "box"
    return PhysicsIntent(
        id=physics_id,
        subject_id=subject_id,
        body_mode=mode,
        collision_shape=collision_shape,
        mass_kg=source.mass_kg,
        friction=source.friction,
        restitution=source.restitution,
        can_topple=source.can_topple and not force_static,
    )


def _appearance(value: BaseModel | Mapping[str, Any] | None) -> tuple[AppearanceIntent, str]:
    payload: dict[str, Any]
    if value is None:
        payload = {}
    elif isinstance(value, BaseModel):
        payload = value.model_dump(mode="json")
    else:
        payload = dict(value)
    forbidden = {
        "room", "items", "objects", "openings", "camera", "position", "rotation",
        "transform", "transforms", "dimensions", "physics",
    }
    conflicts = sorted(forbidden & set(payload))
    if conflicts:
        raise WorldContractError(
            "appearance intent cannot claim geometry/camera authority: " + ", ".join(conflicts)
        )
    payload_hash = _source_hash(payload)
    return AppearanceIntent(
        id=f"appearance-{payload_hash[:16]}",
        era=str(payload.get("era", "")),
        mood=str(payload.get("mood", "")),
        palette=str(payload.get("palette", "")),
        architecture_notes=str(payload.get("architecture_notes", "")),
        lighting_notes=str(payload.get("lighting_notes", "")),
        key_objects=tuple(str(item) for item in payload.get("key_objects", ())),
        image_prompt=str(payload.get("image_prompt", "")),
    ), payload_hash


def _camera(source: CameraContract) -> CameraBinding:
    if source.coordinate_system != COORDINATE_SYSTEM:
        raise WorldContractError(
            f"unsupported Camera_Contract coordinate system: {source.coordinate_system}"
        )
    return CameraBinding(
        id=source.contract_id,
        source_schema_version=source.schema_version,
        projection=source.projection,
        position_m=Vector3(**source.position.model_dump()),
        target_m=Vector3(**source.target.model_dump()),
        up=Vector3(**source.up.model_dump()),
        vertical_fov_deg=source.vertical_fov_deg,
        aspect_ratio=source.aspect_ratio,
        image_width_px=source.image_width,
        image_height_px=source.image_height,
        near_plane_m=source.near_plane,
        far_plane_m=source.far_plane,
    )


def build_world_contract(
    plan: FloorPlan,
    scene_graph: SceneGraph,
    camera_contract: CameraContract,
    *,
    session_id: str,
    interface_version: int,
    profile_id: str,
    plan_revision: int,
    appearance_intent: BaseModel | Mapping[str, Any] | None = None,
    canon_hash: str | None = None,
    export_policy: ExportPolicy | Mapping[str, Any] | None = None,
    interactions: Sequence[InteractionIntent | Mapping[str, Any]] = (),
    relations: Mapping[str, Sequence[RelationIntent | Mapping[str, Any]]] | None = None,
) -> WorldContract:
    """Build one deterministic contract from approved, non-overlapping authorities."""
    _validate_authorities(plan, scene_graph)
    appearance, appearance_hash = _appearance(appearance_intent)
    authored_objects = {item.id: item for item in scene_graph.objects}
    authored_doors = {item.id: item for item in scene_graph.doors}
    plan_relation_map: dict[str, list[RelationIntent]] = {}
    if isinstance(plan, FloorPlanV11):
        for relation in plan.relationships:
            plan_relation_map.setdefault(relation.subject_id, []).append(
                RelationIntent(
                    kind=relation.kind,
                    target_id=relation.target_id,
                    wall=relation.wall,
                    parameters_m=relation.parameters_m,
                    weight=relation.weight,
                    relaxable=relation.relaxable,
                )
            )
    if relations is not None and plan_relation_map:
        raise WorldContractError(
            "relations cannot have both Plan authority and an external side channel"
        )
    relation_map = relations if relations is not None else plan_relation_map
    unknown_relation_subjects = sorted(set(relation_map) - {item.id for item in plan.items})
    if unknown_relation_subjects:
        raise WorldContractError(
            "relations have dangling subjects: " + ", ".join(unknown_relation_subjects)
        )

    room_materials = (
        _material("material:room:floor", scene_graph.room.floor_material),
        _material("material:room:wall", scene_graph.room.wall_material),
        _material("material:room:ceiling", scene_graph.room.ceiling_material),
    )
    materials: list[MaterialIntent] = list(room_materials)
    instances: list[WorldInstance] = []
    physics: list[PhysicsIntent] = []
    palette = {
        "furniture": "#9b7048", "fixture": "#6b8582",
        "architectural": "#81769a", "decor": "#6f7e94",
    }
    for item in plan.items:
        authored = authored_objects.get(item.id)
        material_id = f"material:instance:{item.id}"
        physics_id = f"physics:instance:{item.id}"
        source_material = authored.material if authored else MaterialProps(
            base_color=palette[item.category]
        )
        materials.append(_material(material_id, source_material))
        if authored:
            shape = authored.primitive_shape or "box"
            if authored.mesh_type not in {"primitive", "generated"}:
                raise WorldContractError(
                    f"unsupported geometry strategy for {item.id}: {authored.mesh_type}"
                )
            geometry_strategy = authored.mesh_type
            source_physics = authored.physics
        else:
            shape = "box"
            geometry_strategy = "generated"
            source_physics = _default_physics(item)
        physics.append(
            _physics(
                physics_id, item.id, source_physics,
                force_static=item.fixed, shape=shape,
            )
        )
        authored_relations = tuple(
            value if isinstance(value, RelationIntent) else RelationIntent.model_validate(value)
            for value in relation_map.get(item.id, ())
        )
        instances.append(WorldInstance(
            id=item.id,
            name=item.name,
            category=item.category,
            mount=item.mount,
            transform=Transform(
                position_m=Vector3(x=item.x, y=item.elevation, z=item.z),
                rotation_deg=Vector3(x=0.0, y=item.rotation_deg, z=0.0),
            ),
            dimensions=Dimensions(
                width_m=item.width, height_m=item.height, depth_m=item.depth
            ),
            fixed=item.fixed,
            clearance_m=item.clearance_m,
            material_id=material_id,
            physics_intent_id=physics_id,
            geometry_strategy=geometry_strategy,
            primitive_shape=shape if shape in {"box", "cylinder", "sphere", "plane", "capsule"} else None,
            description=item.description or (authored.description if authored else ""),
            relations=authored_relations,
        ))
    openings: list[WorldOpening] = []
    for opening in plan.openings:
        physics_id = None
        authored_door = authored_doors.get(opening.id)
        if authored_door is not None:
            physics_id = f"physics:opening:{opening.id}"
            physics.append(
                _physics(
                    physics_id, opening.id, authored_door.physics,
                    shape="box",
                )
            )
        openings.append(WorldOpening(
            id=opening.id,
            kind=opening.kind,
            wall=opening.wall,
            offset_m=opening.offset,
            width_m=opening.width,
            height_m=opening.height,
            sill_height_m=opening.sill_height,
            physics_intent_id=physics_id,
        ))

    instance_ids = {item.id for item in instances}
    lights = tuple(WorldLight(
        id=light.id,
        name=light.name,
        light_type=light.light_type.value,
        position_m=Vector3(**light.position.model_dump()),
        direction=Vector3(**light.direction.model_dump()),
        color=light.color,
        color_temperature_k=light.color_temperature_k,
        intensity=light.intensity,
        range_m=light.range_meters,
        spot_angle_deg=light.spot_angle_deg,
        cast_shadows=light.cast_shadows,
        fixture_instance_id=light.id if light.id in instance_ids else None,
    ) for light in scene_graph.lights)
    interaction_models = tuple(
        value if isinstance(value, InteractionIntent)
        else InteractionIntent.model_validate(value)
        for value in interactions
    )
    policy = (
        export_policy if isinstance(export_policy, ExportPolicy)
        else ExportPolicy.model_validate(export_policy or {})
    )
    source = SourceBinding(
        session_id=session_id,
        interface_version=interface_version,
        profile_id=profile_id,
        plan_revision=plan_revision,
        plan_hash=_source_hash(plan),
        scene_graph_hash=_source_hash(scene_graph),
        camera_contract_id=camera_contract.contract_id,
        camera_contract_hash=_source_hash(camera_contract),
        appearance_intent_hash=appearance_hash,
        canon_hash=canon_hash,
    )
    return WorldContract(
        source=source,
        room=RoomShell(
            dimensions=Dimensions(
                width_m=plan.room.width,
                height_m=plan.room.height,
                depth_m=plan.room.depth,
            ),
            floor_material_id="material:room:floor",
            wall_material_id="material:room:wall",
            ceiling_material_id="material:room:ceiling",
        ),
        openings=tuple(openings),
        instances=tuple(instances),
        materials=tuple(materials),
        lights=lights,
        camera=_camera(camera_contract),
        appearance=appearance,
        physics=PhysicsPolicy(intents=tuple(physics)),
        interactions=interaction_models,
        exports=policy,
    )


def _default_physics(item: PlanItem) -> Any:
    """Create explicit deterministic intent when Scene_Graph omitted a Plan instance."""
    from src.models import PhysicsProps

    return PhysicsProps(
        body_type=PhysicsBody.STATIC if item.fixed else PhysicsBody.RIGID,
        mass_kg=40.0 if item.fixed else 8.0,
        can_topple=not item.fixed,
    )
