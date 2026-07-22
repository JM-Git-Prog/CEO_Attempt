"""Typed structural parity, GLB reload, and runtime smoke gates."""

from __future__ import annotations

import json
import math
import re
import struct
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.world_contract import WorldContract


class GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class InventoryVector(GateModel):
    x: float
    y: float
    z: float


class InventoryDimensions(GateModel):
    width_m: float = Field(gt=0)
    height_m: float = Field(gt=0)
    depth_m: float = Field(gt=0)


class InventoryTransform(GateModel):
    position_m: InventoryVector
    rotation_deg: InventoryVector
    scale: InventoryVector = Field(default_factory=lambda: InventoryVector(x=1, y=1, z=1))


class InventoryRoom(GateModel):
    id: str
    dimensions: InventoryDimensions


class InventoryOpening(GateModel):
    id: str
    room_id: str
    kind: Literal["door", "window"]
    wall: str
    offset_m: float
    width_m: float
    height_m: float
    sill_height_m: float = 0.0


class InventoryRelation(GateModel):
    kind: str
    target_id: str | None = None
    wall: str | None = None
    parameters_m: tuple[tuple[str, float], ...] = ()


class InventoryObject(GateModel):
    id: str
    transform: InventoryTransform
    dimensions: InventoryDimensions
    mount: str
    category: str
    material_id: str
    relations: tuple[InventoryRelation, ...] = ()


class InventoryLight(GateModel):
    id: str
    light_type: str
    position_m: InventoryVector
    direction: InventoryVector
    color: str
    intensity: float
    range_m: float
    spot_angle_deg: float
    cast_shadows: bool
    fixture_instance_id: str | None = None


class InventoryCamera(GateModel):
    id: str
    projection: str
    position_m: InventoryVector
    target_m: InventoryVector
    up: InventoryVector
    vertical_fov_deg: float
    aspect_ratio: float
    image_width_px: int
    image_height_px: int
    near_plane_m: float
    far_plane_m: float


class InventoryPhysics(GateModel):
    id: str
    subject_id: str
    body_mode: str
    collision_shape: str
    mass_kg: float
    friction: float
    restitution: float
    can_topple: bool


class InventoryInteraction(GateModel):
    id: str
    kind: str
    subject_id: str
    target_id: str | None = None
    parameters: tuple[tuple[str, str | bool | int | float], ...] = ()


class MachineInventory(GateModel):
    schema_version: Literal["machine-scene-inventory/v1"] = "machine-scene-inventory/v1"
    target: str
    coordinate_system: str
    length_unit: str
    room: InventoryRoom
    openings: tuple[InventoryOpening, ...] = ()
    objects: tuple[InventoryObject, ...] = ()
    lights: tuple[InventoryLight, ...] = ()
    cameras: tuple[InventoryCamera, ...] = ()
    physics: tuple[InventoryPhysics, ...] = ()
    interactions: tuple[InventoryInteraction, ...] = ()

    @field_validator("openings", "objects", "lights", "cameras", "physics", "interactions")
    @classmethod
    def unique_ids(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        ids = [item.id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("inventory collections require unique IDs")
        return tuple(sorted(values, key=lambda item: item.id))


class NumericTolerances(GateModel):
    position_m: float = Field(default=1e-4, ge=0)
    dimensions_m: float = Field(default=1e-4, ge=0)
    rotation_deg: float = Field(default=1e-3, ge=0)
    scale: float = Field(default=1e-5, ge=0)
    camera: float = Field(default=1e-4, ge=0)
    physics: float = Field(default=1e-4, ge=0)
    light: float = Field(default=1e-4, ge=0)
    material: float = Field(default=1e-4, ge=0)


class ParityIssue(GateModel):
    code: str
    path: str
    expected: Any = None
    actual: Any = None
    tolerance: float | None = None


class StructuralParityReport(GateModel):
    schema_version: Literal["structural-parity-report/v1"] = "structural-parity-report/v1"
    target: str
    world_contract_hash: str
    passed: bool
    artifact_accepted: bool
    tolerances: NumericTolerances
    issues: tuple[ParityIssue, ...] = ()
    compared_counts: tuple[tuple[str, int], ...] = ()


def inventory_from_world_contract(contract: WorldContract, *, target: str = "contract") -> MachineInventory:
    def vector(value: Any) -> InventoryVector:
        return InventoryVector(x=value.x, y=value.y, z=value.z)

    def dimensions(value: Any) -> InventoryDimensions:
        return InventoryDimensions(
            width_m=value.width_m, height_m=value.height_m, depth_m=value.depth_m,
        )

    return MachineInventory(
        target=target, coordinate_system=contract.coordinate_system, length_unit=contract.length_unit,
        room=InventoryRoom(id=contract.room.id, dimensions=dimensions(contract.room.dimensions)),
        openings=tuple(InventoryOpening(
            id=item.id, room_id=item.room_id, kind=item.kind, wall=item.wall.value,
            offset_m=item.offset_m, width_m=item.width_m, height_m=item.height_m,
            sill_height_m=item.sill_height_m,
        ) for item in contract.openings),
        objects=tuple(InventoryObject(
            id=item.id,
            transform=InventoryTransform(
                position_m=vector(item.transform.position_m),
                rotation_deg=vector(item.transform.rotation_deg), scale=vector(item.transform.scale),
            ),
            dimensions=dimensions(item.dimensions), mount=item.mount.value, category=item.category,
            material_id=item.material_id,
            relations=tuple(InventoryRelation(
                kind=relation.kind.value, target_id=relation.target_id,
                wall=relation.wall.value if relation.wall else None,
                parameters_m=tuple(sorted(relation.parameters_m.items())),
            ) for relation in item.relations),
        ) for item in contract.instances),
        lights=tuple(InventoryLight(
            id=item.id, light_type=item.light_type, position_m=vector(item.position_m),
            direction=vector(item.direction), color=item.color, intensity=item.intensity,
            range_m=item.range_m, spot_angle_deg=item.spot_angle_deg,
            cast_shadows=item.cast_shadows, fixture_instance_id=item.fixture_instance_id,
        ) for item in contract.lights),
        cameras=(InventoryCamera(
            id=contract.camera.id, projection=contract.camera.projection,
            position_m=vector(contract.camera.position_m), target_m=vector(contract.camera.target_m),
            up=vector(contract.camera.up), vertical_fov_deg=contract.camera.vertical_fov_deg,
            aspect_ratio=contract.camera.aspect_ratio,
            image_width_px=contract.camera.image_width_px,
            image_height_px=contract.camera.image_height_px,
            near_plane_m=contract.camera.near_plane_m, far_plane_m=contract.camera.far_plane_m,
        ),),
        physics=tuple(InventoryPhysics(
            id=item.id, subject_id=item.subject_id, body_mode=item.body_mode.value,
            collision_shape=item.collision_shape, mass_kg=item.mass_kg, friction=item.friction,
            restitution=item.restitution, can_topple=item.can_topple,
        ) for item in contract.physics.intents),
        interactions=tuple(InventoryInteraction(
            id=item.id, kind=item.kind, subject_id=item.subject_id, target_id=item.target_id,
            parameters=tuple(sorted(item.parameters.items())),
        ) for item in contract.interactions),
    )


def compare_inventory(
    contract: WorldContract,
    inventory: MachineInventory,
    tolerances: NumericTolerances | None = None,
) -> StructuralParityReport:
    """Compare exact identities/counts and all authoritative structural fields."""
    expected = inventory_from_world_contract(contract, target=inventory.target)
    tolerance = tolerances or NumericTolerances()
    issues: list[ParityIssue] = []

    def exact(path: str, left: Any, right: Any) -> None:
        if left != right:
            issues.append(ParityIssue(code="exact_mismatch", path=path, expected=left, actual=right))

    def numeric(path: str, left: float, right: float, limit: float) -> None:
        if not math.isclose(left, right, rel_tol=0.0, abs_tol=limit):
            issues.append(ParityIssue(
                code="numeric_tolerance_exceeded", path=path, expected=left,
                actual=right, tolerance=limit,
            ))

    exact("coordinate_system", expected.coordinate_system, inventory.coordinate_system)
    exact("length_unit", expected.length_unit, inventory.length_unit)
    exact("room.id", expected.room.id, inventory.room.id)
    for field in ("width_m", "height_m", "depth_m"):
        numeric(
            f"room.dimensions.{field}", getattr(expected.room.dimensions, field),
            getattr(inventory.room.dimensions, field), tolerance.dimensions_m,
        )

    collections = (
        ("openings", expected.openings, inventory.openings),
        ("objects", expected.objects, inventory.objects),
        ("lights", expected.lights, inventory.lights),
        ("cameras", expected.cameras, inventory.cameras),
        ("physics", expected.physics, inventory.physics),
        ("interactions", expected.interactions, inventory.interactions),
    )
    counts: list[tuple[str, int]] = []
    for label, wanted, found in collections:
        counts.append((label, len(found)))
        exact(f"{label}.count", len(wanted), len(found))
        exact(f"{label}.ids", tuple(item.id for item in wanted), tuple(item.id for item in found))

    def pairs(wanted: tuple[Any, ...], found: tuple[Any, ...]):
        found_by_id = {item.id: item for item in found}
        return ((item, found_by_id[item.id]) for item in wanted if item.id in found_by_id)

    for wanted, found in pairs(expected.openings, inventory.openings):
        for field in ("room_id", "kind", "wall"):
            exact(f"openings.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field))
        for field in ("offset_m", "width_m", "height_m", "sill_height_m"):
            numeric(
                f"openings.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field),
                tolerance.dimensions_m,
            )

    for wanted, found in pairs(expected.objects, inventory.objects):
        for field in ("mount", "category", "material_id", "relations"):
            exact(f"objects.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field))
        for group, limit in (
            ("position_m", tolerance.position_m), ("rotation_deg", tolerance.rotation_deg),
            ("scale", tolerance.scale),
        ):
            for axis in ("x", "y", "z"):
                numeric(
                    f"objects.{wanted.id}.transform.{group}.{axis}",
                    getattr(getattr(wanted.transform, group), axis),
                    getattr(getattr(found.transform, group), axis), limit,
                )
        for field in ("width_m", "height_m", "depth_m"):
            numeric(
                f"objects.{wanted.id}.dimensions.{field}", getattr(wanted.dimensions, field),
                getattr(found.dimensions, field), tolerance.dimensions_m,
            )

    for wanted, found in pairs(expected.lights, inventory.lights):
        for field in ("light_type", "color", "cast_shadows", "fixture_instance_id"):
            exact(f"lights.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field))
        for vector_name in ("position_m", "direction"):
            for axis in ("x", "y", "z"):
                numeric(
                    f"lights.{wanted.id}.{vector_name}.{axis}",
                    getattr(getattr(wanted, vector_name), axis),
                    getattr(getattr(found, vector_name), axis), tolerance.light,
                )
        for field in ("intensity", "range_m", "spot_angle_deg"):
            numeric(
                f"lights.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field),
                tolerance.light,
            )

    for wanted, found in pairs(expected.cameras, inventory.cameras):
        for field in ("projection", "image_width_px", "image_height_px"):
            exact(f"cameras.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field))
        for vector_name in ("position_m", "target_m", "up"):
            for axis in ("x", "y", "z"):
                numeric(
                    f"cameras.{wanted.id}.{vector_name}.{axis}",
                    getattr(getattr(wanted, vector_name), axis),
                    getattr(getattr(found, vector_name), axis), tolerance.camera,
                )
        for field in ("vertical_fov_deg", "aspect_ratio", "near_plane_m", "far_plane_m"):
            numeric(
                f"cameras.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field),
                tolerance.camera,
            )

    for wanted, found in pairs(expected.physics, inventory.physics):
        for field in ("subject_id", "body_mode", "collision_shape", "can_topple"):
            exact(f"physics.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field))
        for field in ("mass_kg", "friction", "restitution"):
            numeric(
                f"physics.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field),
                tolerance.physics,
            )

    for wanted, found in pairs(expected.interactions, inventory.interactions):
        for field in ("kind", "subject_id", "target_id", "parameters"):
            exact(f"interactions.{wanted.id}.{field}", getattr(wanted, field), getattr(found, field))

    passed = not issues
    return StructuralParityReport(
        target=inventory.target, world_contract_hash=contract.content_hash(), passed=passed,
        artifact_accepted=passed, tolerances=tolerance, issues=tuple(issues),
        compared_counts=tuple(counts),
    )


class ValidationCheck(GateModel):
    name: str
    passed: bool
    diagnostic: str = ""


class GLBReloadReport(GateModel):
    schema_version: Literal["glb-reload-report/v1"] = "glb-reload-report/v1"
    path: str
    available: bool
    passed: bool
    artifact_accepted: bool
    checks: tuple[ValidationCheck, ...]
    geometry_count: int = Field(default=0, ge=0)
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    stable_ids: tuple[str, ...] = ()
    camera_count: int = Field(default=0, ge=0)
    camera_ids: tuple[str, ...] = ()
    light_count: int = Field(default=0, ge=0)
    light_ids: tuple[str, ...] = ()


def _glb_document(path: Path) -> Mapping[str, Any]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("not a GLB file")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2 or total_length != len(data):
        raise ValueError("invalid GLB v2 header")
    cursor = 12
    while cursor + 8 <= len(data):
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        chunk = data[cursor:cursor + length]
        cursor += length
        if chunk_type == 0x4E4F534A:
            return json.loads(chunk.rstrip(b" \t\r\n\x00").decode("utf-8"))
    raise ValueError("GLB has no JSON chunk")


def validate_glb_reload(
    path: str | Path,
    *,
    expected_stable_ids: tuple[str, ...] = (),
    expected_camera_ids: tuple[str, ...] = (),
    expected_light_ids: tuple[str, ...] = (),
    require_camera: bool = True,
    require_lights: bool = True,
) -> GLBReloadReport:
    """Reload through trimesh and inspect GLB metadata without trusting exporter claims."""
    glb = Path(path)
    checks: list[ValidationCheck] = []
    if not glb.is_file():
        return GLBReloadReport(
            path=str(glb), available=False, passed=False, artifact_accepted=False,
            checks=(ValidationCheck(name="file", passed=False, diagnostic="GLB is unavailable"),),
        )
    try:
        import numpy as np
        import trimesh

        loaded = trimesh.load(glb, force="scene", process=False)
        scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
        geometries = tuple(scene.geometry.values())
        finite_geometry = bool(geometries) and all(
            len(geometry.vertices) > 0
            and np.isfinite(geometry.vertices).all()
            and np.isfinite(geometry.faces).all()
            for geometry in geometries
        )
        checks.append(ValidationCheck(
            name="finite_geometry", passed=finite_geometry,
            diagnostic="" if finite_geometry else "geometry is empty or non-finite",
        ))
        bounds_array = scene.bounds
        finite_bounds = bool(
            bounds_array is not None
            and getattr(bounds_array, "shape", None) == (2, 3)
            and np.isfinite(bounds_array).all()
            and np.less_equal(bounds_array[0], bounds_array[1]).all()
        )
        checks.append(ValidationCheck(
            name="finite_bounds", passed=bool(finite_bounds),
            diagnostic="" if finite_bounds else "scene bounds are unavailable or non-finite",
        ))
        document = _glb_document(glb)
        nodes = document.get("nodes", [])
        if not isinstance(nodes, list) or any(not isinstance(node, Mapping) for node in nodes):
            raise ValueError("GLB nodes must be an array of objects")

        def node_stable_id(node: Mapping[str, Any]) -> str | None:
            extras = node.get("extras")
            if not isinstance(extras, Mapping):
                return None
            for key in ("kiro_stable_id", "stable_id", "id"):
                identifier = extras.get(key)
                if isinstance(identifier, str) and identifier:
                    return identifier
            return None

        discovered_ids = tuple(
            identifier for node in nodes if (identifier := node_stable_id(node)) is not None
        )
        stable_ids = tuple(sorted(set(discovered_ids)))
        duplicate_ids = tuple(sorted({
            identifier for identifier in discovered_ids if discovered_ids.count(identifier) > 1
        }))
        missing_ids = tuple(sorted(set(expected_stable_ids) - set(stable_ids)))
        invalid_expected_ids = len(expected_stable_ids) != len(set(expected_stable_ids))
        extras_passed = not missing_ids and not duplicate_ids and not invalid_expected_ids
        extras_diagnostics = []
        if missing_ids:
            extras_diagnostics.append("missing stable IDs: " + ", ".join(missing_ids))
        if duplicate_ids:
            extras_diagnostics.append("duplicate stable IDs: " + ", ".join(duplicate_ids))
        if invalid_expected_ids:
            extras_diagnostics.append("expected stable IDs are not unique")
        checks.append(ValidationCheck(
            name="stable_id_extras", passed=extras_passed,
            diagnostic="; ".join(extras_diagnostics),
        ))

        cameras = document.get("cameras", [])
        if not isinstance(cameras, list):
            raise ValueError("GLB cameras must be an array")
        camera_count = len(cameras)
        camera_ids = tuple(sorted(
            identifier for node in nodes
            if isinstance(node.get("camera"), int)
            and (identifier := node_stable_id(node)) is not None
        ))
        camera_count_matches = (
            camera_count == len(expected_camera_ids)
            if expected_camera_ids else (not require_camera or camera_count > 0)
        )
        camera_ids_match = not expected_camera_ids or (
            camera_ids == tuple(sorted(expected_camera_ids))
            and len(camera_ids) == len(set(camera_ids))
        )
        checks.append(ValidationCheck(
            name="cameras", passed=camera_count_matches and camera_ids_match,
            diagnostic="" if camera_count_matches and camera_ids_match else (
                f"camera count/IDs differ: expected={tuple(sorted(expected_camera_ids)) or 'present'} "
                f"actual={camera_ids} count={camera_count}"
            ),
        ))

        root_extensions = document.get("extensions", {})
        if not isinstance(root_extensions, Mapping):
            raise ValueError("GLB extensions must be an object")
        light_extension = root_extensions.get("KHR_lights_punctual", {})
        if not isinstance(light_extension, Mapping):
            raise ValueError("KHR_lights_punctual must be an object")
        lights = light_extension.get("lights", [])
        if not isinstance(lights, list):
            raise ValueError("KHR_lights_punctual lights must be an array")
        light_count = len(lights)
        light_ids = tuple(sorted(
            identifier for node in nodes
            if isinstance(node.get("extensions"), Mapping)
            and isinstance(node["extensions"].get("KHR_lights_punctual"), Mapping)
            and isinstance(node["extensions"]["KHR_lights_punctual"].get("light"), int)
            and (identifier := node_stable_id(node)) is not None
        ))
        light_count_matches = (
            light_count == len(expected_light_ids)
            if expected_light_ids else (not require_lights or light_count > 0)
        )
        light_ids_match = not expected_light_ids or (
            light_ids == tuple(sorted(expected_light_ids))
            and len(light_ids) == len(set(light_ids))
        )
        checks.append(ValidationCheck(
            name="punctual_lights", passed=light_count_matches and light_ids_match,
            diagnostic="" if light_count_matches and light_ids_match else (
                f"light count/IDs differ: expected={tuple(sorted(expected_light_ids)) or 'present'} "
                f"actual={light_ids} count={light_count}"
            ),
        ))
        passed = all(check.passed for check in checks)
        bounds = None
        if finite_bounds:
            bounds = (
                tuple(float(value) for value in bounds_array[0]),
                tuple(float(value) for value in bounds_array[1]),
            )
        return GLBReloadReport(
            path=str(glb), available=True, passed=passed, artifact_accepted=passed,
            checks=tuple(checks), geometry_count=len(geometries), bounds=bounds,
            stable_ids=stable_ids, camera_count=camera_count, camera_ids=camera_ids,
            light_count=light_count, light_ids=light_ids,
        )
    except Exception as exc:
        checks.append(ValidationCheck(name="reload", passed=False, diagnostic=str(exc)))
        return GLBReloadReport(
            path=str(glb), available=True, passed=False, artifact_accepted=False,
            checks=tuple(checks),
        )


class RuntimeCheckState(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class RuntimeSmokeCheck(GateModel):
    name: str
    mandatory: bool
    state: RuntimeCheckState
    diagnostic: str = ""


class RuntimeSmokeReport(GateModel):
    schema_version: Literal["runtime-smoke-report/v1"] = "runtime-smoke-report/v1"
    engine: str
    engine_path: str | None = None
    package_path: str
    available: bool
    status: Literal["passed", "failed", "unavailable", "rejected"]
    passed: bool
    artifact_accepted: bool
    checks: tuple[RuntimeSmokeCheck, ...]
    diagnostics: tuple[str, ...] = ()


RuntimeRunner = Callable[[Path, Path, tuple[str, ...]], Mapping[str, bool | str]]
_RUNTIME_BASE_CHECKS = (
    "load", "player_spawn", "movement", "collision", "opening_traversal",
)


def run_runtime_smoke(
    *,
    engine_path: str | Path | None,
    package_path: str | Path,
    required_interactions: tuple[str, ...] = (),
    runner: RuntimeRunner | None = None,
    engine: str = "UPBGE",
) -> RuntimeSmokeReport:
    """Run an injected bounded harness and require exact machine-evidence check IDs."""
    package = Path(package_path)
    executable = Path(engine_path) if engine_path is not None else None
    check_names = _RUNTIME_BASE_CHECKS + tuple(
        f"interaction:{identifier}" for identifier in required_interactions
    )
    if len(required_interactions) != len(set(required_interactions)):
        diagnostic = "required runtime interaction IDs must be unique"
        return RuntimeSmokeReport(
            engine=engine, engine_path=str(executable) if executable else None,
            package_path=str(package), available=bool(executable and executable.is_file()),
            status="rejected", passed=False, artifact_accepted=False,
            checks=tuple(RuntimeSmokeCheck(
                name=name, mandatory=True, state=RuntimeCheckState.FAILED,
                diagnostic=diagnostic,
            ) for name in check_names), diagnostics=(diagnostic,),
        )
    if executable is None or not executable.is_file():
        diagnostic = "runtime engine is not installed or configured"
        return RuntimeSmokeReport(
            engine=engine, engine_path=str(executable) if executable else None,
            package_path=str(package), available=False, status="unavailable", passed=False,
            artifact_accepted=False,
            checks=tuple(RuntimeSmokeCheck(
                name=name, mandatory=True, state=RuntimeCheckState.UNAVAILABLE,
                diagnostic=diagnostic,
            ) for name in check_names), diagnostics=(diagnostic,),
        )
    if not package.is_file():
        diagnostic = "runtime package is unavailable or is not a regular file"
        return RuntimeSmokeReport(
            engine=engine, engine_path=str(executable), package_path=str(package),
            available=True, status="rejected", passed=False, artifact_accepted=False,
            checks=tuple(RuntimeSmokeCheck(
                name=name, mandatory=True, state=RuntimeCheckState.FAILED,
                diagnostic=diagnostic,
            ) for name in check_names), diagnostics=(diagnostic,),
        )
    if runner is None:
        diagnostic = "runtime smoke runner is not configured"
        return RuntimeSmokeReport(
            engine=engine, engine_path=str(executable), package_path=str(package),
            available=True, status="unavailable", passed=False, artifact_accepted=False,
            checks=tuple(RuntimeSmokeCheck(
                name=name, mandatory=True, state=RuntimeCheckState.UNAVAILABLE,
                diagnostic=diagnostic,
            ) for name in check_names), diagnostics=(diagnostic,),
        )
    try:
        raw = runner(executable, package, required_interactions)
        actual_names = set(raw)
        expected_names = set(check_names)
        identifiers_match = actual_names == expected_names
        diagnostics = () if identifiers_match else (
            "runtime evidence check IDs/count do not exactly match the request",
        )
        checks = []
        for name in check_names:
            value = raw.get(name, False)
            passed = value is True
            checks.append(RuntimeSmokeCheck(
                name=name, mandatory=True,
                state=RuntimeCheckState.PASSED if passed else RuntimeCheckState.FAILED,
                diagnostic="" if passed else (str(value) if value else "mandatory check failed"),
            ))
        passed = identifiers_match and all(
            check.state == RuntimeCheckState.PASSED for check in checks
        )
        return RuntimeSmokeReport(
            engine=engine, engine_path=str(executable), package_path=str(package),
            available=True, status="passed" if passed else "failed", passed=passed,
            artifact_accepted=passed, checks=tuple(checks), diagnostics=diagnostics,
        )
    except Exception as exc:
        diagnostic = f"runtime smoke runner failed: {exc}"
        return RuntimeSmokeReport(
            engine=engine, engine_path=str(executable), package_path=str(package),
            available=True, status="failed", passed=False, artifact_accepted=False,
            checks=tuple(RuntimeSmokeCheck(
                name=name, mandatory=True, state=RuntimeCheckState.FAILED,
                diagnostic=diagnostic,
            ) for name in check_names), diagnostics=(diagnostic,),
        )


def runtime_smoke_gate(report: RuntimeSmokeReport, *, mandatory: bool = True) -> bool:
    """Return artifact acceptance; unavailable mandatory runtimes fail closed."""
    return report.artifact_accepted if mandatory else (report.passed or not report.available)


def write_gate_report(report: GateModel, path: str | Path) -> Path:
    """Persist immutable canonical gate evidence, including rejection diagnostics."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    with destination.open("x", encoding="utf-8") as handle:
        json.dump(
            payload, handle, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        )
    return destination


def validate_upbge_inventory(
    contract: WorldContract,
    path: str | Path,
    tolerances: NumericTolerances | None = None,
) -> StructuralParityReport:
    """Validate every authoritative contract field emitted in UPBGE machine inventory."""
    from src.upbge_compiler import domain_to_upbge_xyz

    tolerance = tolerances or NumericTolerances()
    issues: list[ParityIssue] = []
    inventory_path = Path(path)
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("inventory root must be an object")
    except (OSError, UnicodeError, ValueError) as exc:
        return StructuralParityReport(
            target="upbge", world_contract_hash=contract.content_hash(), passed=False,
            artifact_accepted=False, tolerances=tolerance,
            issues=(ParityIssue(code="inventory_unavailable", path=str(inventory_path), actual=str(exc)),),
        )

    def exact(label: str, expected: Any, actual: Any) -> None:
        if expected != actual:
            issues.append(ParityIssue(
                code="exact_mismatch", path=label, expected=expected, actual=actual,
            ))

    def numeric(label: str, expected: float, actual: Any, limit: float) -> None:
        try:
            found = float(actual)
            matches = math.isfinite(found) and math.isclose(
                float(expected), found, rel_tol=0.0, abs_tol=limit,
            )
        except (TypeError, ValueError):
            matches = False
        if not matches:
            issues.append(ParityIssue(
                code="numeric_tolerance_exceeded", path=label, expected=expected,
                actual=actual, tolerance=limit,
            ))

    def vector(label: str, expected: tuple[float, float, float], actual: Any, limit: float) -> None:
        if not isinstance(actual, (list, tuple)) or len(actual) != 3:
            issues.append(ParityIssue(
                code="numeric_tolerance_exceeded", path=label, expected=expected,
                actual=actual, tolerance=limit,
            ))
            return
        for index, axis in enumerate(("x", "y", "z")):
            numeric(f"{label}.{axis}", expected[index], actual[index], limit)

    def collection(label: str, expected_ids: tuple[str, ...]) -> dict[str, Mapping[str, Any]]:
        raw = payload.get(label, [])
        if not isinstance(raw, list) or any(not isinstance(item, Mapping) for item in raw):
            exact(f"{label}.type", "array<object>", type(raw).__name__)
            raw = []
        ids = [item.get("stable_id") for item in raw]
        exact(f"{label}.count", len(expected_ids), len(raw))
        exact(f"{label}.ids", tuple(sorted(expected_ids)), tuple(sorted(
            str(identity) for identity in ids if identity is not None
        )))
        if len(ids) != len(set(ids)):
            issues.append(ParityIssue(code="duplicate_id", path=f"{label}.ids", actual=ids))
        return {
            str(item["stable_id"]): item for item in raw if item.get("stable_id") is not None
        }

    exact("schema_version", "upbge-scene-inventory/v1", payload.get("schema_version"))
    exact("world_contract_hash", contract.content_hash(), payload.get("world_contract_hash"))
    exact("coordinate_system", "right-handed-x-right-y-depth-z-up", payload.get("coordinate_system"))
    exact("source_coordinate_system", contract.coordinate_system, payload.get("source_coordinate_system"))
    exact("coordinate_mapping", "domain(x,y,z)->upbge(x,z,y)", payload.get("coordinate_mapping"))
    exact("length_unit", contract.length_unit, payload.get("length_unit"))
    exact("angle_unit", contract.angle_unit, payload.get("angle_unit"))

    room = payload.get("room") if isinstance(payload.get("room"), Mapping) else {}
    exact("room.id", contract.room.id, room.get("stable_id"))
    exact("room.floor_material_id", contract.room.floor_material_id, room.get("floor_material_id"))
    exact("room.wall_material_id", contract.room.wall_material_id, room.get("wall_material_id"))
    exact("room.ceiling_material_id", contract.room.ceiling_material_id, room.get("ceiling_material_id"))
    vector(
        "room.dimensions_upbge",
        domain_to_upbge_xyz(
            contract.room.dimensions.width_m, contract.room.dimensions.height_m,
            contract.room.dimensions.depth_m,
        ), room.get("dimensions_upbge"), tolerance.dimensions_m,
    )

    openings = collection("openings", tuple(item.id for item in contract.openings))
    room_dimensions = contract.room.dimensions
    for item in contract.openings:
        actual = openings.get(item.id)
        if actual is None:
            continue
        for field, expected in (
            ("room_id", item.room_id), ("kind", item.kind), ("wall", item.wall.value),
            ("physics_intent_id", item.physics_intent_id),
        ):
            exact(f"openings.{item.id}.{field}", expected, actual.get(field))
        for field in ("offset_m", "width_m", "height_m", "sill_height_m"):
            numeric(
                f"openings.{item.id}.{field}", getattr(item, field), actual.get(field),
                tolerance.dimensions_m,
            )
        along = item.offset_m
        vertical = item.sill_height_m + item.height_m / 2.0
        if item.wall.value == "north":
            position = (along, vertical, room_dimensions.depth_m / 2.0)
            dimensions = (item.width_m, item.height_m, 0.1)
        elif item.wall.value == "south":
            position = (along, vertical, -room_dimensions.depth_m / 2.0)
            dimensions = (item.width_m, item.height_m, 0.1)
        elif item.wall.value == "east":
            position = (room_dimensions.width_m / 2.0, vertical, along)
            dimensions = (0.1, item.height_m, item.width_m)
        else:
            position = (-room_dimensions.width_m / 2.0, vertical, along)
            dimensions = (0.1, item.height_m, item.width_m)
        vector(f"openings.{item.id}.position_upbge", domain_to_upbge_xyz(*position), actual.get("position_upbge"), tolerance.position_m)
        converted_dimensions = actual.get("dimensions_upbge")
        if not isinstance(converted_dimensions, (list, tuple)) or len(converted_dimensions) != 3:
            vector(
                f"openings.{item.id}.dimensions_upbge", domain_to_upbge_xyz(*dimensions),
                converted_dimensions, tolerance.dimensions_m,
            )
        else:
            width_axis, height_axis = (
                ((0, item.width_m), (2, item.height_m))
                if item.wall.value in {"north", "south"}
                else ((1, item.width_m), (2, item.height_m))
            )
            numeric(
                f"openings.{item.id}.dimensions_upbge.width", width_axis[1],
                converted_dimensions[width_axis[0]], tolerance.dimensions_m,
            )
            numeric(
                f"openings.{item.id}.dimensions_upbge.height", height_axis[1],
                converted_dimensions[height_axis[0]], tolerance.dimensions_m,
            )
            thickness_axis = 1 if item.wall.value in {"north", "south"} else 0
            try:
                thickness = float(converted_dimensions[thickness_axis])
            except (TypeError, ValueError):
                thickness = -1.0
            if not math.isfinite(thickness) or thickness <= 0.0:
                issues.append(ParityIssue(
                    code="invalid_compiler_value",
                    path=f"openings.{item.id}.dimensions_upbge.wall_thickness",
                    actual=converted_dimensions[thickness_axis],
                ))

    objects = collection("objects", tuple(item.id for item in contract.instances))
    for item in contract.instances:
        actual = objects.get(item.id)
        if actual is None:
            continue
        for field, expected in (
            ("role", "instance"), ("name", item.name), ("category", item.category),
            ("mount", item.mount.value), ("fixed", item.fixed),
            ("material_id", item.material_id), ("physics_intent_id", item.physics_intent_id),
            ("geometry_strategy", item.geometry_strategy),
            ("primitive_shape", item.primitive_shape),
            ("asset_registry_id", item.asset_registry_id), ("description", item.description),
        ):
            exact(f"objects.{item.id}.{field}", expected, actual.get(field))
        numeric(f"objects.{item.id}.clearance_m", item.clearance_m, actual.get("clearance_m"), tolerance.dimensions_m)
        position = domain_to_upbge_xyz(*item.transform.position_m.model_dump().values())
        rotation = domain_to_upbge_xyz(*item.transform.rotation_deg.model_dump().values())
        scale = domain_to_upbge_xyz(*item.transform.scale.model_dump().values())
        dimensions = domain_to_upbge_xyz(
            item.dimensions.width_m, item.dimensions.height_m, item.dimensions.depth_m,
        )
        vector(f"objects.{item.id}.position_upbge", position, actual.get("position_upbge"), tolerance.position_m)
        vector(f"objects.{item.id}.rotation_upbge_deg", rotation, actual.get("rotation_upbge_deg"), tolerance.rotation_deg)
        vector(f"objects.{item.id}.scale_upbge", scale, actual.get("scale_upbge"), tolerance.scale)
        vector(f"objects.{item.id}.dimensions_upbge", dimensions, actual.get("dimensions_upbge"), tolerance.dimensions_m)
        vector(
            f"objects.{item.id}.compiled_dimensions_upbge",
            tuple(dimension * factor for dimension, factor in zip(dimensions, scale)),
            actual.get("compiled_dimensions_upbge"), tolerance.dimensions_m,
        )
        exact(
            f"objects.{item.id}.relations",
            [relation.model_dump(mode="json") for relation in item.relations],
            actual.get("relations"),
        )

    materials = collection("materials", tuple(item.id for item in contract.materials))
    for item in contract.materials:
        actual = materials.get(item.id)
        if actual is None:
            continue
        exact(f"materials.{item.id}.base_color", item.base_color, actual.get("base_color"))
        exact(f"materials.{item.id}.emission_color", item.emission_color, actual.get("emission_color"))
        for field in ("metallic", "roughness", "emission_strength"):
            numeric(f"materials.{item.id}.{field}", getattr(item, field), actual.get(field), tolerance.material)

    lights = collection("lights", tuple(item.id for item in contract.lights))
    for item in contract.lights:
        actual = lights.get(item.id)
        if actual is None:
            continue
        engine_type = {"directional": "SUN"}.get(item.light_type, item.light_type.upper())
        for field, expected in (
            ("name", item.name), ("light_type", item.light_type),
            ("engine_light_type", engine_type), ("color", item.color),
            ("color_temperature_k", item.color_temperature_k),
            ("cast_shadows", item.cast_shadows),
            ("fixture_instance_id", item.fixture_instance_id),
        ):
            exact(f"lights.{item.id}.{field}", expected, actual.get(field))
        vector(f"lights.{item.id}.position_upbge", domain_to_upbge_xyz(*item.position_m.model_dump().values()), actual.get("position_upbge"), tolerance.light)
        vector(f"lights.{item.id}.direction_upbge", domain_to_upbge_xyz(*item.direction.model_dump().values()), actual.get("direction_upbge"), tolerance.light)
        for field in ("intensity", "range_m", "spot_angle_deg"):
            numeric(f"lights.{item.id}.{field}", getattr(item, field), actual.get(field), tolerance.light)

    camera = payload.get("camera") if isinstance(payload.get("camera"), Mapping) else {}
    exact("cameras.count", 1, 1 if camera else 0)
    for field, expected in (
        ("stable_id", contract.camera.id),
        ("source_schema_version", contract.camera.source_schema_version),
        ("projection", contract.camera.projection),
        ("raster_px", [contract.camera.image_width_px, contract.camera.image_height_px]),
    ):
        exact(f"camera.{field}", expected, camera.get(field))
    for field, source in (
        ("position_upbge", contract.camera.position_m),
        ("target_upbge", contract.camera.target_m), ("up_upbge", contract.camera.up),
    ):
        vector(f"camera.{field}", domain_to_upbge_xyz(*source.model_dump().values()), camera.get(field), tolerance.camera)
    for field in ("vertical_fov_deg", "aspect_ratio", "near_plane_m", "far_plane_m"):
        numeric(f"camera.{field}", getattr(contract.camera, field), camera.get(field), tolerance.camera)

    physics = collection("physics", tuple(item.id for item in contract.physics.intents))
    vector(
        "physics.gravity_upbge",
        domain_to_upbge_xyz(*contract.physics.gravity_m_s2.model_dump().values()),
        payload.get("gravity_upbge"), tolerance.physics,
    )
    for item in contract.physics.intents:
        actual = physics.get(item.id)
        if actual is None:
            continue
        for field, expected in (
            ("subject_id", item.subject_id), ("body_mode", item.body_mode.value),
            ("collision_shape", item.collision_shape), ("can_topple", item.can_topple),
        ):
            exact(f"physics.{item.id}.{field}", expected, actual.get(field))
        for field in ("mass_kg", "friction", "restitution"):
            numeric(f"physics.{item.id}.{field}", getattr(item, field), actual.get(field), tolerance.physics)

    interactions = collection("interactions", tuple(item.id for item in contract.interactions))
    for item in contract.interactions:
        actual = interactions.get(item.id)
        if actual is None:
            continue
        for field, expected in (
            ("kind", item.kind), ("subject_id", item.subject_id),
            ("target_id", item.target_id), ("parameters", item.parameters),
        ):
            exact(f"interactions.{item.id}.{field}", expected, actual.get(field))

    passed = not issues
    return StructuralParityReport(
        target="upbge", world_contract_hash=contract.content_hash(), passed=passed,
        artifact_accepted=passed, tolerances=tolerance, issues=tuple(issues),
        compared_counts=(
            ("rooms", 1 if room else 0), ("openings", len(openings)),
            ("objects", len(objects)), ("materials", len(materials)),
            ("lights", len(lights)), ("cameras", 1 if camera else 0),
            ("physics", len(physics)), ("interactions", len(interactions)),
        ),
    )


def validate_godot_project(
    contract: WorldContract,
    project_path: str | Path,
    metadata_path: str | Path,
    tolerances: NumericTolerances | None = None,
) -> StructuralParityReport:
    """Validate the generated V11 Godot project and its hash-bound portable metadata.

    The metadata is revalidated as a WorldContract, while the scene itself must carry
    every stable identity and the exact source contract hash. This avoids accepting a
    contract-to-itself comparison that is not bound to generated target artifacts.
    """
    tolerance = tolerances or NumericTolerances()
    issues: list[ParityIssue] = []
    project = Path(project_path)
    metadata_file = Path(metadata_path)
    required = tuple(project / name for name in (
        "project.godot", "main.tscn", "player.tscn", "player.gd"
    ))
    for path in required:
        if not path.is_file():
            issues.append(ParityIssue(
                code="artifact_unavailable", path=str(path), expected="regular file",
                actual="missing",
            ))
    try:
        payload = json.loads(metadata_file.read_text(encoding="utf-8"))
        exported = WorldContract.model_validate(payload["world_contract"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return StructuralParityReport(
            target="godot", world_contract_hash=contract.content_hash(), passed=False,
            artifact_accepted=False, tolerances=tolerance,
            issues=tuple([*issues, ParityIssue(
                code="inventory_unavailable", path=str(metadata_file), actual=str(exc),
            )]),
        )
    if payload.get("world_contract_hash") != contract.content_hash():
        issues.append(ParityIssue(
            code="exact_mismatch", path="metadata.world_contract_hash",
            expected=contract.content_hash(), actual=payload.get("world_contract_hash"),
        ))
    report = compare_inventory(
        contract, inventory_from_world_contract(exported, target="godot"), tolerance
    )
    issues.extend(report.issues)
    main_scene = project / "main.tscn"
    if main_scene.is_file():
        text = main_scene.read_text(encoding="utf-8")
        expected_hash_marker = (
            f'metadata/_kiro_world_contract_hash = "{contract.content_hash()}"'
        )
        if expected_hash_marker not in text:
            issues.append(ParityIssue(
                code="exact_mismatch", path="godot.main_scene.world_contract_hash",
                expected=contract.content_hash(), actual="missing",
            ))
        actual_ids = set(re.findall(
            r'metadata/_kiro_stable_id\s*=\s*"([A-Za-z0-9_.:@-]+)"', text
        ))
        expected_ids = {
            *(item.id for item in contract.instances),
            *(item.id for item in contract.openings),
            *(item.id for item in contract.lights),
            contract.camera.id,
        }
        if expected_ids != actual_ids:
            issues.append(ParityIssue(
                code="exact_mismatch", path="godot.main_scene.stable_ids",
                expected=tuple(sorted(expected_ids)), actual=tuple(sorted(actual_ids)),
            ))
        for opening in contract.openings:
            if f'Aperture_{opening.id.replace("-", "_").replace(".", "_")}' not in text:
                issues.append(ParityIssue(
                    code="opening_aperture_missing",
                    path=f"godot.main_scene.openings.{opening.id}",
                    expected="CSG subtraction aperture", actual="missing",
                ))
    passed = not issues
    return StructuralParityReport(
        target="godot", world_contract_hash=contract.content_hash(), passed=passed,
        artifact_accepted=passed, tolerances=tolerance, issues=tuple(issues),
        compared_counts=report.compared_counts,
    )