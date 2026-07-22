"""Deterministic WorldContract-to-UPBGE compilation planning.

This host-side module performs no engine work.  It emits an immutable plan consumed by
the reviewed first-party script in ``src/assembler/upbge_compile.py``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from src.upbge_runtime import (
    RUNTIME_CANDIDATE_FILENAME,
    RuntimePlan,
    build_runtime_plan,
)
from src.world_contract import Wall, WorldContract

COMPILER_PLAN_VERSION = "upbge-compiler-plan/v1"
FIRST_PARTY_SCRIPT = Path(__file__).parent / "assembler" / "upbge_compile.py"


@dataclass(frozen=True)
class CompilerOutputFlags:
    render: bool = False
    blend: bool = True
    glb: bool = False
    runtime: bool = False

    def requested_names(self) -> tuple[tuple[str, str], ...]:
        names: list[tuple[str, str]] = []
        if self.render:
            names.append(("render", "reference.png"))
        if self.blend:
            names.append(("blend", "scene.blend"))
        if self.glb:
            names.append(("glb", "scene.glb"))
        if self.runtime:
            # Compilation emits an untrusted candidate. A separate capability/parity/smoke
            # gate publishes it as a playable runtime artifact.
            names.append(("runtime_candidate", RUNTIME_CANDIDATE_FILENAME))
        names.append(("inventory", "scene_inventory.json"))
        return tuple(names)


@dataclass(frozen=True)
class CompilerLimits:
    max_objects: int = 2048
    max_polygons: int = 2_000_000
    max_texture_dimension: int = 8192


class CompilerLimitError(ValueError):
    """A deterministic compiler-plan resource limit was exceeded."""

    def __init__(self, limit_name: str, actual: int, maximum: int) -> None:
        self.limit_name = limit_name
        self.actual = actual
        self.maximum = maximum
        super().__init__(f"{limit_name} exceeded: {actual}>{maximum}")


@dataclass(frozen=True)
class ApprovedAsset:
    """Immutable binding from an engine-neutral registry ID to one reviewed GLB."""

    source_path: Path
    sha256: str
    triangle_count: int

    def validate(self) -> Path:
        path = Path(self.source_path).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != ".glb":
            raise ValueError("approved assets must be regular self-contained GLB files")
        if (
            len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("approved asset sha256 must be lowercase hexadecimal")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if actual_hash != self.sha256:
            raise ValueError(f"approved asset hash mismatch: {path.name}")
        if (
            isinstance(self.triangle_count, bool)
            or not isinstance(self.triangle_count, int)
            or self.triangle_count <= 0
        ):
            raise ValueError("approved asset triangle_count must be a positive integer")
        return path

    @property
    def relative_path(self) -> str:
        return f"assets/{self.sha256}.glb"


@dataclass(frozen=True)
class GeometryPlan:
    stable_id: str
    role: str
    shape: str
    position_upbge: tuple[float, float, float]
    rotation_upbge_deg: tuple[float, float, float]
    dimensions_upbge: tuple[float, float, float]
    material_id: str
    geometry_strategy: str = "primitive"
    scale_upbge: tuple[float, float, float] = (1.0, 1.0, 1.0)
    asset_registry_id: str | None = None
    asset_relative_path: str | None = None
    asset_sha256: str | None = None
    metadata: tuple[tuple[str, str | bool | int | float], ...] = ()
    estimated_polygons: int = 12


@dataclass(frozen=True)
class OpeningGapPlan:
    stable_id: str
    kind: str
    wall: str
    position_upbge: tuple[float, float, float]
    dimensions_upbge: tuple[float, float, float]
    sill_height_m: float


@dataclass(frozen=True)
class MaterialPlan:
    stable_id: str
    base_color_rgba: tuple[float, float, float, float]
    metallic: float
    roughness: float
    emission_rgba: tuple[float, float, float, float] | None
    emission_strength: float


@dataclass(frozen=True)
class LightPlan:
    stable_id: str
    name: str
    light_type: str
    position_upbge: tuple[float, float, float]
    direction_upbge: tuple[float, float, float]
    color_rgb: tuple[float, float, float]
    intensity: float
    range_m: float
    spot_angle_deg: float
    cast_shadows: bool
    fixture_instance_id: str | None


@dataclass(frozen=True)
class CameraPlan:
    stable_id: str
    position_upbge: tuple[float, float, float]
    target_upbge: tuple[float, float, float]
    up_upbge: tuple[float, float, float]
    vertical_fov_deg: float
    aspect_ratio: float
    raster_px: tuple[int, int]
    near_plane_m: float
    far_plane_m: float


@dataclass(frozen=True)
class PhysicsPlan:
    stable_id: str
    subject_id: str
    body_mode: str
    collision_shape: str
    mass_kg: float
    friction: float
    restitution: float
    can_topple: bool


@dataclass(frozen=True)
class RelationPlan:
    kind: str
    target_id: str | None
    wall: str | None
    parameters_m: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class CompilerPlan:
    schema_version: str
    world_contract_hash: str
    compiler_script_sha256: str
    coordinate_mapping: str
    room_geometry: tuple[GeometryPlan, ...]
    opening_gaps: tuple[OpeningGapPlan, ...]
    instances: tuple[GeometryPlan, ...]
    materials: tuple[MaterialPlan, ...]
    lights: tuple[LightPlan, ...]
    camera: CameraPlan
    physics: tuple[PhysicsPlan, ...]
    gravity_upbge: tuple[float, float, float]
    relationships: tuple[tuple[str, tuple[RelationPlan, ...]], ...]
    runtime: RuntimePlan | None
    outputs: tuple[tuple[str, str], ...]
    expected_inventory_ids: tuple[str, ...]
    estimated_object_count: int
    estimated_polygon_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def domain_to_upbge_xyz(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Map domain X-right/Y-up/Z-depth to UPBGE X-right/Y-depth/Z-up."""
    values = (float(x), float(z), float(y))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("coordinates must be finite")
    return values


def upbge_to_domain_xyz(x: float, y: float, z: float) -> tuple[float, float, float]:
    values = (float(x), float(z), float(y))
    if not all(math.isfinite(value) for value in values):
        raise ValueError("coordinates must be finite")
    return values


def _vector(value: Any) -> tuple[float, float, float]:
    return domain_to_upbge_xyz(value.x, value.y, value.z)


def _dimensions(value: Any) -> tuple[float, float, float]:
    return domain_to_upbge_xyz(value.width_m, value.height_m, value.depth_m)


def _hex_color(value: str) -> tuple[float, float, float, float]:
    text = value.removeprefix("#")
    if len(text) not in {6, 8}:
        raise ValueError(f"unsupported color literal: {value}")
    try:
        channels = tuple(int(text[index:index + 2], 16) / 255.0 for index in range(0, len(text), 2))
    except ValueError as exc:
        raise ValueError(f"unsupported color literal: {value}") from exc
    return (*channels[:3], channels[3] if len(channels) == 4 else 1.0)


def compiler_script_hash(path: Path = FIRST_PARTY_SCRIPT) -> str:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("first-party compiler script is not a regular file")
    return hashlib.sha256(resolved.read_bytes()).hexdigest()


def _opening_horizontal_interval(opening: Any) -> tuple[float, float]:
    return opening.offset_m - opening.width_m / 2.0, opening.offset_m + opening.width_m / 2.0


def _wall_segment_geometry(
    contract: WorldContract, *, wall_thickness_m: float
) -> tuple[GeometryPlan, ...]:
    room = contract.room.dimensions
    segments: list[GeometryPlan] = []
    for wall in Wall:
        length = room.width_m if wall in {Wall.NORTH, Wall.SOUTH} else room.depth_m
        openings = [item for item in contract.openings if item.wall == wall]
        boundaries = {-length / 2.0, length / 2.0}
        for opening in openings:
            boundaries.update(_opening_horizontal_interval(opening))
        horizontal = sorted(boundaries)
        wall_rectangles: list[tuple[float, float, float, float]] = []
        for left, right in zip(horizontal, horizontal[1:]):
            if right - left <= 1e-9:
                continue
            midpoint = (left + right) / 2.0
            active = [
                item for item in openings
                if _opening_horizontal_interval(item)[0] < midpoint < _opening_horizontal_interval(item)[1]
            ]
            vertical = {0.0, room.height_m}
            for opening in active:
                vertical.update((opening.sill_height_m, opening.sill_height_m + opening.height_m))
            heights = sorted(vertical)
            for bottom, top in zip(heights, heights[1:]):
                if top - bottom <= 1e-9:
                    continue
                center_y = (bottom + top) / 2.0
                is_gap = any(
                    item.sill_height_m < center_y < item.sill_height_m + item.height_m
                    for item in active
                )
                if not is_gap:
                    wall_rectangles.append((left, right, bottom, top))

        for index, (left, right, bottom, top) in enumerate(wall_rectangles):
            along = (left + right) / 2.0
            vertical = (bottom + top) / 2.0
            if wall == Wall.NORTH:
                position = (along, vertical, room.depth_m / 2.0)
                dimensions = (right - left, top - bottom, wall_thickness_m)
            elif wall == Wall.SOUTH:
                position = (along, vertical, -room.depth_m / 2.0)
                dimensions = (right - left, top - bottom, wall_thickness_m)
            elif wall == Wall.EAST:
                position = (room.width_m / 2.0, vertical, along)
                dimensions = (wall_thickness_m, top - bottom, right - left)
            else:
                position = (-room.width_m / 2.0, vertical, along)
                dimensions = (wall_thickness_m, top - bottom, right - left)
            segments.append(GeometryPlan(
                stable_id=f"wall:{wall.value}:segment:{index:04d}",
                role="wall_segment",
                shape="box",
                position_upbge=domain_to_upbge_xyz(*position),
                rotation_upbge_deg=(0.0, 0.0, 0.0),
                dimensions_upbge=domain_to_upbge_xyz(*dimensions),
                material_id=contract.room.wall_material_id,
                metadata=(("wall", wall.value),),
            ))
    return tuple(segments)


def _room_geometry(contract: WorldContract, wall_thickness_m: float) -> tuple[GeometryPlan, ...]:
    room = contract.room.dimensions
    floor = GeometryPlan(
        stable_id="room:floor", role="floor", shape="box",
        position_upbge=domain_to_upbge_xyz(0.0, -wall_thickness_m / 2.0, 0.0),
        rotation_upbge_deg=(0.0, 0.0, 0.0),
        dimensions_upbge=domain_to_upbge_xyz(room.width_m, wall_thickness_m, room.depth_m),
        material_id=contract.room.floor_material_id,
    )
    ceiling = GeometryPlan(
        stable_id="room:ceiling", role="ceiling", shape="box",
        position_upbge=domain_to_upbge_xyz(0.0, room.height_m + wall_thickness_m / 2.0, 0.0),
        rotation_upbge_deg=(0.0, 0.0, 0.0),
        dimensions_upbge=domain_to_upbge_xyz(room.width_m, wall_thickness_m, room.depth_m),
        material_id=contract.room.ceiling_material_id,
    )
    return (floor, ceiling, *_wall_segment_geometry(contract, wall_thickness_m=wall_thickness_m))


def _opening_plans(contract: WorldContract, wall_thickness_m: float) -> tuple[OpeningGapPlan, ...]:
    room = contract.room.dimensions
    plans = []
    for opening in contract.openings:
        along = opening.offset_m
        vertical = opening.sill_height_m + opening.height_m / 2.0
        if opening.wall == Wall.NORTH:
            position = (along, vertical, room.depth_m / 2.0)
            dimensions = (opening.width_m, opening.height_m, wall_thickness_m)
        elif opening.wall == Wall.SOUTH:
            position = (along, vertical, -room.depth_m / 2.0)
            dimensions = (opening.width_m, opening.height_m, wall_thickness_m)
        elif opening.wall == Wall.EAST:
            position = (room.width_m / 2.0, vertical, along)
            dimensions = (wall_thickness_m, opening.height_m, opening.width_m)
        else:
            position = (-room.width_m / 2.0, vertical, along)
            dimensions = (wall_thickness_m, opening.height_m, opening.width_m)
        plans.append(OpeningGapPlan(
            stable_id=opening.id, kind=opening.kind, wall=opening.wall.value,
            position_upbge=domain_to_upbge_xyz(*position),
            dimensions_upbge=domain_to_upbge_xyz(*dimensions),
            sill_height_m=opening.sill_height_m,
        ))
    return tuple(plans)


def _instance_plans(
    contract: WorldContract,
    asset_registry: Mapping[str, ApprovedAsset],
) -> tuple[GeometryPlan, ...]:
    polygon_estimates = {
        "box": 12, "plane": 2, "cylinder": 128, "sphere": 512, "capsule": 256,
    }
    plans = []
    for item in contract.instances:
        shape = item.primitive_shape or "asset"
        asset = None
        asset_path = None
        estimated_polygons = polygon_estimates.get(shape, 0)
        if item.geometry_strategy == "asset":
            registry_id = item.asset_registry_id
            asset = asset_registry.get(registry_id or "")
            if asset is None:
                raise ValueError(
                    f"asset instance {item.id} has no approved registry binding for {registry_id}"
                )
            asset.validate()
            asset_path = asset.relative_path
            estimated_polygons = asset.triangle_count
        elif shape not in polygon_estimates:
            raise ValueError(f"unsupported explicit geometry shape for {item.id}: {shape}")
        transform = item.transform
        metadata: tuple[tuple[str, str | bool | int | float], ...] = (
            ("category", item.category),
            ("fixed", item.fixed),
            ("geometry_strategy", item.geometry_strategy),
            ("mount", item.mount.value),
        )
        if item.asset_registry_id:
            metadata += (("asset_registry_id", item.asset_registry_id),)
        plans.append(GeometryPlan(
            stable_id=item.id, role="instance", shape=shape,
            position_upbge=_vector(transform.position_m),
            rotation_upbge_deg=_vector(transform.rotation_deg),
            dimensions_upbge=_dimensions(item.dimensions),
            material_id=item.material_id,
            geometry_strategy=item.geometry_strategy,
            scale_upbge=_vector(transform.scale),
            asset_registry_id=item.asset_registry_id,
            asset_relative_path=asset_path,
            asset_sha256=asset.sha256 if asset else None,
            metadata=metadata,
            estimated_polygons=estimated_polygons,
        ))
    return tuple(plans)


def _material_plans(contract: WorldContract) -> tuple[MaterialPlan, ...]:
    return tuple(MaterialPlan(
        stable_id=item.id,
        base_color_rgba=_hex_color(item.base_color),
        metallic=item.metallic,
        roughness=item.roughness,
        emission_rgba=_hex_color(item.emission_color) if item.emission_color else None,
        emission_strength=item.emission_strength,
    ) for item in contract.materials)


def _light_plans(contract: WorldContract) -> tuple[LightPlan, ...]:
    return tuple(LightPlan(
        stable_id=item.id,
        name=item.name,
        light_type={"directional": "SUN"}.get(item.light_type, item.light_type.upper()),
        position_upbge=_vector(item.position_m),
        direction_upbge=_vector(item.direction),
        color_rgb=_hex_color(item.color)[:3],
        intensity=item.intensity,
        range_m=item.range_m,
        spot_angle_deg=item.spot_angle_deg,
        cast_shadows=item.cast_shadows,
        fixture_instance_id=item.fixture_instance_id,
    ) for item in contract.lights)


def _camera_plan(contract: WorldContract) -> CameraPlan:
    camera = contract.camera
    return CameraPlan(
        stable_id=camera.id,
        position_upbge=_vector(camera.position_m),
        target_upbge=_vector(camera.target_m),
        up_upbge=_vector(camera.up),
        vertical_fov_deg=camera.vertical_fov_deg,
        aspect_ratio=camera.aspect_ratio,
        raster_px=(camera.image_width_px, camera.image_height_px),
        near_plane_m=camera.near_plane_m,
        far_plane_m=camera.far_plane_m,
    )


def _relationship_plans(contract: WorldContract) -> tuple[tuple[str, tuple[RelationPlan, ...]], ...]:
    result = []
    for instance in contract.instances:
        relations = tuple(RelationPlan(
            kind=relation.kind.value,
            target_id=relation.target_id,
            wall=relation.wall.value if relation.wall else None,
            parameters_m=tuple(sorted(relation.parameters_m.items())),
        ) for relation in instance.relations)
        result.append((instance.id, relations))
    return tuple(result)


def build_compiler_plan(
    contract: WorldContract,
    *,
    outputs: CompilerOutputFlags = CompilerOutputFlags(),
    limits: CompilerLimits = CompilerLimits(),
    wall_thickness_m: float = 0.1,
    asset_registry: Mapping[str, ApprovedAsset] | None = None,
) -> CompilerPlan:
    """Build an immutable deterministic plan without mutating the WorldContract."""
    if not math.isfinite(wall_thickness_m) or wall_thickness_m <= 0.0:
        raise ValueError("wall_thickness_m must be positive and finite")
    if min(limits.max_objects, limits.max_polygons, limits.max_texture_dimension) <= 0:
        raise ValueError("compiler limits must be positive")
    room_geometry = _room_geometry(contract, wall_thickness_m)
    instances = _instance_plans(contract, asset_registry or {})
    opening_gaps = _opening_plans(contract, wall_thickness_m)
    lights = _light_plans(contract)
    runtime = build_runtime_plan(contract) if outputs.runtime else None
    runtime_door_ids = {
        item.subject_id for item in (runtime.interactions if runtime else ())
        if item.kind == "door" and item.subject_id not in {instance.stable_id for instance in instances}
    }
    runtime_object_count = (1 + len(runtime_door_ids)) if runtime else 0
    # Lights, aperture markers, and camera are separate scene objects. Aperture markers are
    # non-rendering empties carrying stable IDs, never opaque panels or collision bodies.
    object_count = (
        len(room_geometry) + len(opening_gaps) + len(instances) + len(lights) + 1
        + runtime_object_count
    )
    polygon_count = (
        sum(item.estimated_polygons for item in (*room_geometry, *instances))
        + runtime_object_count * 12
    )
    if object_count > limits.max_objects:
        raise CompilerLimitError("max_objects", object_count, limits.max_objects)
    if polygon_count > limits.max_polygons:
        raise CompilerLimitError("max_polygons", polygon_count, limits.max_polygons)
    physics = tuple(PhysicsPlan(
        stable_id=item.id,
        subject_id=item.subject_id,
        body_mode=item.body_mode.value,
        collision_shape=item.collision_shape,
        mass_kg=item.mass_kg,
        friction=item.friction,
        restitution=item.restitution,
        can_topple=item.can_topple,
    ) for item in contract.physics.intents)
    expected_ids = tuple(sorted(
        [item.stable_id for item in room_geometry]
        + [item.stable_id for item in opening_gaps]
        + [item.stable_id for item in instances]
        + [item.stable_id for item in lights]
        + [contract.camera.id]
    ))
    return CompilerPlan(
        schema_version=COMPILER_PLAN_VERSION,
        world_contract_hash=contract.content_hash(),
        compiler_script_sha256=compiler_script_hash(),
        coordinate_mapping="domain(x,y,z)->upbge(x,z,y)",
        room_geometry=room_geometry,
        opening_gaps=opening_gaps,
        instances=instances,
        materials=_material_plans(contract),
        lights=lights,
        camera=_camera_plan(contract),
        physics=physics,
        gravity_upbge=_vector(contract.physics.gravity_m_s2),
        relationships=_relationship_plans(contract),
        runtime=runtime,
        outputs=outputs.requested_names(),
        expected_inventory_ids=expected_ids,
        estimated_object_count=object_count,
        estimated_polygon_count=polygon_count,
    )
