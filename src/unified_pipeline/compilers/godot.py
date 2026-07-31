"""Strict WorldContract-to-Godot 4 project compiler.

The compiler is a representation adapter, not a scene solver. It validates the
canonical hash, copies approved assets byte-for-byte, and writes only values
already present in one WorldContract. Spawn and hinge data are accepted from
JSON relationship metadata; absent values are never guessed.

Requirements: 21.2, 21.4, 21.6.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.unified_pipeline.world_contract import (
    ObjectInstance,
    Relationship,
    WorldContract,
    serialize,
    verify_hash,
)


class GodotCompilerError(ValueError):
    """Raised when a contract cannot be represented without consumer drift."""


@dataclass(frozen=True)
class GodotCompileResult:
    """Immutable inventory of a generated, contract-bound Godot project."""

    project_dir: Path
    project_file: Path
    main_scene: Path
    player_scene: Path
    player_script: Path
    contract_file: Path
    manifest_file: Path
    contract_hash: str
    plan_revision: str
    artifact_paths: tuple[Path, ...]


@dataclass(frozen=True)
class _Spawn:
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    source: str


@dataclass(frozen=True)
class _Hinge:
    child_id: str
    anchor_id: str
    pivot: tuple[float, float, float]
    axis: tuple[float, float, float]
    lower_limit_deg: float
    upper_limit_deg: float
    mass_kg: float | None
    source_relationship: tuple[str, str, str]


_NODE_RE = re.compile(r"[^A-Za-z0-9_]")
_SUPPORTED_PHYSICS = {
    "static": "StaticBody3D",
    "dynamic": "RigidBody3D",
    "kinematic": "AnimatableBody3D",
    "trigger": "Area3D",
}
_LIGHT_NODES = {
    "point": "OmniLight3D",
    "directional": "DirectionalLight3D",
    "spot": "SpotLight3D",
}


def _node_name(value: str, *, prefix: str = "Node") -> str:
    cleaned = _NODE_RE.sub("_", value.strip())
    if not cleaned:
        cleaned = prefix
    if cleaned[0].isdigit():
        cleaned = f"{prefix}_{cleaned}"
    return cleaned


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise GodotCompilerError(f"{label} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise GodotCompilerError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise GodotCompilerError(f"{label} must be finite")
    return result


def _positive(value: Any, label: str) -> float:
    result = _number(value, label)
    if result <= 0.0:
        raise GodotCompilerError(f"{label} must be positive")
    return result


def _fmt(value: float) -> str:
    """Round-trip-safe decimal formatting; never clamps or rounds authority."""
    result = _number(value, "Godot numeric value")
    if result == 0.0:
        return "0.0"
    return format(result, ".17g")


def _vec3(values: Iterable[float]) -> str:
    x, y, z = tuple(values)
    return f"Vector3({_fmt(x)}, {_fmt(y)}, {_fmt(z)})"


def _quat(values: Iterable[float]) -> str:
    x, y, z, w = tuple(values)
    return f"Quaternion({_fmt(x)}, {_fmt(y)}, {_fmt(z)}, {_fmt(w)})"


def _quoted(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _color(value: str, label: str) -> tuple[float, float, float, float]:
    raw = value.strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", raw):
        raise GodotCompilerError(f"{label} must be an explicit #RRGGBB or #RRGGBBAA color")
    channels = [int(raw[index:index + 2], 16) / 255.0 for index in range(1, len(raw), 2)]
    if len(channels) == 3:
        channels.append(1.0)
    return tuple(channels)  # type: ignore[return-value]


def _color_expr(value: str, label: str) -> str:
    return "Color(" + ", ".join(_fmt(item) for item in _color(value, label)) + ")"


def _mapping_vec3(value: Any, label: str) -> tuple[float, float, float]:
    if isinstance(value, Mapping):
        source = (value.get("x"), value.get("y"), value.get("z"))
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        source = tuple(value)
    else:
        raise GodotCompilerError(f"{label} must contain explicit x, y, z values")
    return tuple(_number(item, label) for item in source)  # type: ignore[return-value]


def _mapping_quat(value: Any, label: str) -> tuple[float, float, float, float]:
    if isinstance(value, Mapping):
        source = (value.get("x"), value.get("y"), value.get("z"), value.get("w"))
    elif isinstance(value, (list, tuple)) and len(value) == 4:
        source = tuple(value)
    else:
        raise GodotCompilerError(f"{label} must contain explicit x, y, z, w values")
    result = tuple(_number(item, label) for item in source)
    if sum(item * item for item in result) <= 0.0:
        raise GodotCompilerError(f"{label} cannot be a zero quaternion")
    return result  # type: ignore[return-value]


def _metadata_payload(relationship: Relationship) -> dict[str, Any]:
    if not relationship.metadata.strip():
        return {}
    try:
        payload = json.loads(relationship.metadata)
    except json.JSONDecodeError as exc:
        raise GodotCompilerError(
            f"relationship {relationship.source_id!r}->{relationship.target_id!r} "
            "contains invalid JSON metadata"
        ) from exc
    if not isinstance(payload, dict):
        raise GodotCompilerError("relationship metadata must decode to an object")
    return payload


def _nested(payload: Mapping[str, Any], key: str) -> Any:
    if key in payload:
        return payload[key]
    godot = payload.get("godot")
    return godot.get(key) if isinstance(godot, Mapping) else None


def _extract_spawn(contract: WorldContract) -> _Spawn:
    candidates: list[_Spawn] = []
    for relationship in contract.relationships:
        payload = _metadata_payload(relationship)
        raw = _nested(payload, "player_spawn")
        if raw is None and payload.get("kind") == "player_spawn":
            raw = payload
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise GodotCompilerError("player_spawn metadata must be an object")
        candidates.append(_Spawn(
            position=_mapping_vec3(raw.get("position"), "player spawn position"),
            rotation=_mapping_quat(
                raw.get("rotation", raw.get("quaternion")), "player spawn rotation"
            ),
            source=f"relationship:{relationship.source_id}->{relationship.target_id}",
        ))

    for instance in contract.instances:
        if instance.semantic_label.strip().lower() == "player_spawn":
            candidates.append(_Spawn(
                position=(instance.position.x, instance.position.y, instance.position.z),
                rotation=(
                    instance.rotation.x, instance.rotation.y,
                    instance.rotation.z, instance.rotation.w,
                ),
                source=f"instance:{instance.object_id}",
            ))

    if not candidates:
        raise GodotCompilerError(
            "WorldContract requires an explicit player_spawn relationship metadata object "
            "or a player_spawn instance; the compiler will not infer a safe spawn"
        )
    first = candidates[0]
    if any(item.position != first.position or item.rotation != first.rotation for item in candidates[1:]):
        raise GodotCompilerError("WorldContract contains conflicting player spawn authorities")
    return first


def _extract_hinges(contract: WorldContract) -> tuple[_Hinge, ...]:
    hinges: list[_Hinge] = []
    seen: set[str] = set()
    instance_ids = {item.object_id for item in contract.instances}
    for relationship in contract.relationships:
        payload = _metadata_payload(relationship)
        raw = _nested(payload, "door_hinge")
        if raw is None:
            raw = _nested(payload, "hinge")
        if raw is None:
            continue
        if not isinstance(raw, Mapping):
            raise GodotCompilerError("door hinge metadata must be an object")
        child_id = str(raw.get("child_body_id", relationship.source_id)).strip()
        anchor_id = str(raw.get("anchor_body_id", relationship.target_id)).strip()
        if child_id not in instance_ids:
            raise GodotCompilerError(f"hinge child {child_id!r} is not a contract instance")
        if anchor_id != "room" and anchor_id not in instance_ids:
            raise GodotCompilerError(f"hinge anchor {anchor_id!r} is not a contract instance or room")
        if child_id in seen:
            raise GodotCompilerError(f"instance {child_id!r} has multiple hinge authorities")

        pivot_raw = raw.get("pivot_position", raw.get("position"))
        pivot = raw.get("pivot")
        if pivot_raw is None and isinstance(pivot, Mapping):
            pivot_raw = pivot.get("position")
            if pivot_raw is None and all(key in pivot for key in ("x", "y", "z")):
                pivot_raw = pivot
        if pivot_raw is None:
            raise GodotCompilerError(
                f"hinge for {child_id!r} requires an explicit world-space pivot position; "
                "wall parameters are not re-solved by compilers"
            )
        axis = _mapping_vec3(raw.get("axis"), f"hinge {child_id} axis")
        if sum(value * value for value in axis) <= 0.0:
            raise GodotCompilerError(f"hinge {child_id!r} axis cannot be zero")
        lower = _number(raw.get("lower_limit_deg"), f"hinge {child_id} lower limit")
        upper = _number(raw.get("upper_limit_deg"), f"hinge {child_id} upper limit")
        if lower > upper:
            raise GodotCompilerError(f"hinge {child_id!r} limits are reversed")
        mass_raw = raw.get("interaction_mass_kg", raw.get("mass_kg"))
        mass = None if mass_raw is None else _positive(mass_raw, f"hinge {child_id} mass")
        hinges.append(_Hinge(
            child_id=child_id,
            anchor_id=anchor_id,
            pivot=_mapping_vec3(pivot_raw, f"hinge {child_id} pivot"),
            axis=axis,
            lower_limit_deg=lower,
            upper_limit_deg=upper,
            mass_kg=mass,
            source_relationship=(
                relationship.source_id, relationship.target_id,
                relationship.relationship_type,
            ),
        ))
        seen.add(child_id)
    return tuple(hinges)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_instance(instance: ObjectInstance) -> None:
    if not instance.object_id.strip():
        raise GodotCompilerError("contract instances require stable object IDs")
    if instance.physics_intent not in _SUPPORTED_PHYSICS:
        raise GodotCompilerError(
            f"instance {instance.object_id!r} has unsupported physics intent "
            f"{instance.physics_intent!r}"
        )
    for label, values in (
        ("position", (instance.position.x, instance.position.y, instance.position.z)),
        ("rotation", (
            instance.rotation.x, instance.rotation.y,
            instance.rotation.z, instance.rotation.w,
        )),
        ("scale", (instance.scale.x, instance.scale.y, instance.scale.z)),
    ):
        tuple(_number(value, f"{instance.object_id} {label}") for value in values)
    if min(instance.scale.x, instance.scale.y, instance.scale.z) <= 0.0:
        raise GodotCompilerError(f"instance {instance.object_id!r} scale must stay positive")
    rotation = (
        instance.rotation.x, instance.rotation.y,
        instance.rotation.z, instance.rotation.w,
    )
    if sum(value * value for value in rotation) <= 0.0:
        raise GodotCompilerError(f"instance {instance.object_id!r} rotation cannot be zero")
    if not instance.asset_binding.mesh_path.strip() or not instance.asset_binding.asset_id.strip():
        raise GodotCompilerError(f"instance {instance.object_id!r} lacks an approved asset binding")


class GodotCompiler:
    """Emit a runnable Godot 4 project from exactly one canonical contract."""

    schema_version = "godot-world-compiler/v1"

    def compile(
        self, contract: WorldContract, output_dir: str | Path
    ) -> GodotCompileResult:
        if not isinstance(contract, WorldContract):
            raise TypeError("GodotCompiler requires unified_pipeline.world_contract.WorldContract")
        if not verify_hash(contract):
            raise GodotCompilerError("WorldContract hash is empty or invalid")
        if not contract.plan_revision.strip() or not contract.camera_hash.strip():
            raise GodotCompilerError("WorldContract must bind plan revision and camera hash")

        ids = [item.object_id for item in contract.instances]
        if len(ids) != len(set(ids)):
            raise GodotCompilerError("WorldContract instance IDs must be unique")
        for instance in contract.instances:
            _validate_instance(instance)
        for light in contract.lighting.lights:
            if light.light_type not in _LIGHT_NODES:
                raise GodotCompilerError(
                    f"light {light.light_id!r} type {light.light_type!r} has no exact "
                    "Godot 4 runtime representation"
                )

        spawn = _extract_spawn(contract)
        hinges = _extract_hinges(contract)
        project_dir = Path(output_dir)
        project_dir.mkdir(parents=True, exist_ok=True)
        assets = self._copy_assets(contract, project_dir)

        project_file = project_dir / "project.godot"
        player_script = project_dir / "player.gd"
        body_script = project_dir / "contract_body.gd"
        player_scene = project_dir / "player.tscn"
        main_scene = project_dir / "main.tscn"
        contract_file = project_dir / "world_contract.json"
        manifest_file = project_dir / "compiler_manifest.json"

        project_file.write_text(self._project_text(contract), encoding="utf-8")
        player_script.write_text(_PLAYER_SCRIPT, encoding="utf-8")
        body_script.write_text(_BODY_SCRIPT, encoding="utf-8")
        player_scene.write_text(_PLAYER_SCENE, encoding="utf-8")
        main_scene.write_text(
            self._scene_text(contract, assets, spawn, hinges), encoding="utf-8"
        )
        contract_file.write_text(serialize(contract), encoding="utf-8")

        artifacts = (
            project_file, main_scene, player_scene, player_script, body_script,
            contract_file, *sorted(set(assets.values()), key=lambda path: path.as_posix()),
        )
        manifest = {
            "schema_version": self.schema_version,
            "target": {"engine": "Godot", "major_version": 4},
            "contract_hash": contract.contract_hash,
            "plan_revision": contract.plan_revision,
            "camera_hash": contract.camera_hash,
            "room_shell_ref": contract.room_shell_ref,
            "spawn": {
                "position": list(spawn.position),
                "rotation": list(spawn.rotation),
                "source": spawn.source,
            },
            "instances": [item.to_dict() for item in contract.instances],
            "relationships": [item.to_dict() for item in contract.relationships],
            "lighting": contract.lighting.to_dict(),
            "door_hinges": [self._hinge_manifest(item) for item in hinges],
            "authority": {
                "source": "one_canonical_world_contract",
                "asset_copy": "byte_for_byte_sha256_verified",
                "transform_policy": "exact_no_clamp_rescale_offset_or_normalization",
                "missing_authority_policy": "fail_closed",
            },
            "artifacts": [
                {
                    "path": path.relative_to(project_dir).as_posix(),
                    "sha256": _sha256(path),
                }
                for path in artifacts
            ],
        }
        manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return GodotCompileResult(
            project_dir=project_dir,
            project_file=project_file,
            main_scene=main_scene,
            player_scene=player_scene,
            player_script=player_script,
            contract_file=contract_file,
            manifest_file=manifest_file,
            contract_hash=contract.contract_hash,
            plan_revision=contract.plan_revision,
            artifact_paths=(*artifacts, manifest_file),
        )

    @staticmethod
    def _copy_assets(
        contract: WorldContract, project_dir: Path
    ) -> dict[str, Path]:
        asset_dir = project_dir / "assets" / "meshes"
        asset_dir.mkdir(parents=True, exist_ok=True)
        copied_by_hash: dict[str, Path] = {}
        result: dict[str, Path] = {}
        for instance in contract.instances:
            source = Path(instance.asset_binding.mesh_path)
            if not source.is_file():
                raise GodotCompilerError(
                    f"approved mesh for {instance.object_id!r} does not exist: {source}"
                )
            actual_hash = _sha256(source)
            if actual_hash != instance.asset_binding.asset_id:
                raise GodotCompilerError(
                    f"approved mesh hash mismatch for {instance.object_id!r}"
                )
            suffix = source.suffix.lower()
            if suffix not in {".glb", ".gltf"}:
                raise GodotCompilerError(
                    f"approved mesh for {instance.object_id!r} must be GLB or glTF"
                )
            destination = copied_by_hash.get(actual_hash)
            if destination is None:
                destination = asset_dir / f"{actual_hash}{suffix}"
                if destination.exists() and _sha256(destination) != actual_hash:
                    raise GodotCompilerError(f"output asset collision at {destination}")
                if not destination.exists():
                    shutil.copyfile(source, destination)
                if _sha256(destination) != actual_hash:
                    raise GodotCompilerError("byte-for-byte asset copy verification failed")
                copied_by_hash[actual_hash] = destination
            result[instance.object_id] = destination
        return result

    @staticmethod
    def _project_text(contract: WorldContract) -> str:
        title = _quoted(f"World {contract.contract_id}")
        return f'''config_version=5

[application]
config/name={title}
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.3", "Forward Plus")

[input]
move_forward={{"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":87)]}}
move_backward={{"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":83)]}}
move_left={{"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":65)]}}
move_right={{"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":68)]}}
interact={{"deadzone":0.5,"events":[Object(InputEventKey,"physical_keycode":69)]}}

[physics]
3d/default_gravity=9.8

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
'''

    @staticmethod
    def _hinge_manifest(hinge: _Hinge) -> dict[str, Any]:
        return {
            "child_id": hinge.child_id,
            "anchor_id": hinge.anchor_id,
            "pivot": list(hinge.pivot),
            "axis": list(hinge.axis),
            "lower_limit_deg": hinge.lower_limit_deg,
            "upper_limit_deg": hinge.upper_limit_deg,
            "mass_kg": hinge.mass_kg,
            "source_relationship": list(hinge.source_relationship),
        }

    def _scene_text(
        self,
        contract: WorldContract,
        assets: Mapping[str, Path],
        spawn: _Spawn,
        hinges: tuple[_Hinge, ...],
    ) -> str:
        ext_resources = [
            '[ext_resource type="PackedScene" path="res://player.tscn" id="player"]',
            '[ext_resource type="Script" path="res://contract_body.gd" id="body_script"]',
        ]
        asset_ids: dict[str, str] = {}
        for index, instance in enumerate(contract.instances, start=1):
            resource_id = f"asset_{index}"
            relative = assets[instance.object_id].relative_to(assets[instance.object_id].parents[2])
            ext_resources.append(
                f'[ext_resource type="PackedScene" path="res://{relative.as_posix()}" '
                f'id="{resource_id}"]'
            )
            asset_ids[instance.object_id] = resource_id

        environment = contract.lighting
        sub_resources = [
            '[sub_resource type="Environment" id="environment"]\n'
            'background_mode = 1\n'
            f'background_color = {_color_expr(environment.ambient_color, "ambient color")}\n'
            'ambient_light_source = 3\n'
            f'ambient_light_color = {_color_expr(environment.ambient_color, "ambient color")}\n'
            f'ambient_light_energy = {_fmt(environment.ambient_intensity)}'
        ]
        load_steps = len(ext_resources) + len(sub_resources) + 1
        lines = [f'[gd_scene load_steps={load_steps} format=3]', ""]
        lines.extend(ext_resources)
        lines.append("")
        lines.extend(sub_resources)
        lines.extend([
            "",
            '[node name="World" type="Node3D"]',
            f'metadata/_kiro_world_contract_hash = {_quoted(contract.contract_hash)}',
            f'metadata/_kiro_plan_revision = {_quoted(contract.plan_revision)}',
            f'metadata/_kiro_camera_hash = {_quoted(contract.camera_hash)}',
            f'metadata/_kiro_room_shell_ref = {_quoted(contract.room_shell_ref)}',
            'metadata/_kiro_length_unit = "meter"',
            'metadata/_kiro_coordinate_system = "right-handed-x-right-y-up-z-depth"',
            "",
            '[node name="Environment" type="WorldEnvironment" parent="."]',
            'environment = SubResource("environment")',
        ])

        hinges_by_child = {item.child_id: item for item in hinges}
        body_names: dict[str, str] = {}
        for instance in contract.instances:
            name = _node_name(instance.object_id, prefix="Object")
            if name in body_names.values():
                name = f"{name}_{hashlib.sha256(instance.object_id.encode()).hexdigest()[:8]}"
            body_names[instance.object_id] = name
            hinge = hinges_by_child.get(instance.object_id)
            body_type = "RigidBody3D" if hinge is not None else _SUPPORTED_PHYSICS[instance.physics_intent]
            position = (instance.position.x, instance.position.y, instance.position.z)
            rotation = (
                instance.rotation.x, instance.rotation.y,
                instance.rotation.z, instance.rotation.w,
            )
            scale = (instance.scale.x, instance.scale.y, instance.scale.z)
            lines.extend([
                "",
                f'[node name={_quoted(name)} type="{body_type}" parent="."]',
                f'position = {_vec3(position)}',
                f'quaternion = {_quat(rotation)}',
                f'scale = {_vec3(scale)}',
                'script = ExtResource("body_script")',
                f'metadata/_kiro_stable_id = {_quoted(instance.object_id)}',
                f'metadata/_kiro_physics_intent = {_quoted(instance.physics_intent)}',
                f'metadata/_kiro_asset_sha256 = {_quoted(instance.asset_binding.asset_id)}',
                f'metadata/_kiro_material_intent = {_quoted(json.dumps(instance.material_intent.to_dict(), sort_keys=True, separators=(",", ":")))}',
                f'metadata/_kiro_semantic_label = {_quoted(instance.semantic_label)}',
            ])
            if hinge is not None:
                lines.append('metadata/_kiro_door_hinge = true')
                if hinge.mass_kg is not None:
                    lines.append(f'mass = {_fmt(hinge.mass_kg)}')
            lines.extend([
                "",
                f'[node name="Visual" parent={_quoted(name)} instance=ExtResource({_quoted(asset_ids[instance.object_id])})]',
            ])

        for index, hinge in enumerate(hinges, start=1):
            child_name = body_names[hinge.child_id]
            hinge_name = _node_name(f"DoorHinge_{hinge.child_id}_{index}", prefix="DoorHinge")
            lines.extend([
                "",
                f'[node name={_quoted(hinge_name)} type="HingeJoint3D" parent="."]',
                f'position = {_vec3(hinge.pivot)}',
                f'node_b = NodePath({_quoted("../" + child_name)})',
                'angular_limit/enable = true',
                f'angular_limit/lower = {_fmt(math.radians(hinge.lower_limit_deg))}',
                f'angular_limit/upper = {_fmt(math.radians(hinge.upper_limit_deg))}',
                f'metadata/_kiro_axis = {_vec3(hinge.axis)}',
                f'metadata/_kiro_lower_limit_deg = {_fmt(hinge.lower_limit_deg)}',
                f'metadata/_kiro_upper_limit_deg = {_fmt(hinge.upper_limit_deg)}',
            ])
            if hinge.anchor_id != "room":
                lines.append(
                    f'node_a = NodePath({_quoted("../" + body_names[hinge.anchor_id])})'
                )

        for index, light in enumerate(contract.lighting.lights, start=1):
            if not light.light_id.strip():
                raise GodotCompilerError("contract lights require stable IDs")
            light_type = _LIGHT_NODES[light.light_type]
            light_name = _node_name(light.light_id, prefix=f"Light{index}")
            lines.extend([
                "",
                f'[node name={_quoted(light_name)} type="{light_type}" parent="."]',
                f'position = {_vec3((light.position.x, light.position.y, light.position.z))}',
                f'light_color = {_color_expr(light.color, f"light {light.light_id} color")}',
                f'light_energy = {_fmt(light.intensity)}',
                f'shadow_enabled = {"true" if light.cast_shadows else "false"}',
                f'metadata/_kiro_stable_id = {_quoted(light.light_id)}',
                f'metadata/_kiro_temperature_kelvin = {_fmt(light.temperature)}',
            ])

        lines.extend([
            "",
            '[node name="Player" parent="." instance=ExtResource("player")]',
            f'position = {_vec3(spawn.position)}',
            f'quaternion = {_quat(spawn.rotation)}',
            f'metadata/_kiro_spawn_source = {_quoted(spawn.source)}',
            "",
        ])
        return "\n".join(lines)


def compile_godot_project(
    contract: WorldContract, output_dir: str | Path
) -> GodotCompileResult:
    """Functional entry point for orchestration and compiler selection."""
    return GodotCompiler().compile(contract, output_dir)


_PLAYER_SCENE = '''[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://player.gd" id="player_script"]

[sub_resource type="CapsuleShape3D" id="player_shape"]
radius = 0.3
height = 1.8

[node name="Player" type="CharacterBody3D"]
script = ExtResource("player_script")

[node name="CollisionShape3D" type="CollisionShape3D" parent="."]
position = Vector3(0, 0.9, 0)
shape = SubResource("player_shape")

[node name="Head" type="Node3D" parent="."]
position = Vector3(0, 1.6, 0)

[node name="Camera3D" type="Camera3D" parent="Head"]
current = true

[node name="InteractRay" type="RayCast3D" parent="Head"]
target_position = Vector3(0, 0, -3)
enabled = true
collide_with_areas = false

[node name="GrabPoint" type="Marker3D" parent="Head"]
position = Vector3(0, 0, -1.5)
'''


_PLAYER_SCRIPT = '''extends CharacterBody3D

const MOVE_SPEED := 4.0
const MOUSE_SENSITIVITY := 0.003
const PUSH_IMPULSE := 0.08
const HOLD_STIFFNESS := 12.0

var _gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")
var _grabbed: RigidBody3D = null
@onready var _head: Node3D = $Head
@onready var _ray: RayCast3D = $Head/InteractRay
@onready var _grab_point: Marker3D = $Head/GrabPoint

func _ready() -> void:
    Input.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)

func _unhandled_input(event: InputEvent) -> void:
    if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
        rotate_y(-event.relative.x * MOUSE_SENSITIVITY)
        _head.rotate_x(-event.relative.y * MOUSE_SENSITIVITY)
        _head.rotation.x = clamp(_head.rotation.x, -PI / 2.0, PI / 2.0)
    if event.is_action_pressed("interact"):
        _toggle_grab()
    if event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
        Input.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)

func _toggle_grab() -> void:
    if is_instance_valid(_grabbed):
        _grabbed = null
        return
    _ray.force_raycast_update()
    if _ray.is_colliding():
        var collider := _ray.get_collider()
        if collider is RigidBody3D:
            _grabbed = collider
            _grabbed.sleeping = false

func _physics_process(delta: float) -> void:
    if not is_on_floor():
        velocity.y -= _gravity * delta
    var input_vector := Input.get_vector(
        "move_left", "move_right", "move_forward", "move_backward"
    )
    var direction := (transform.basis * Vector3(input_vector.x, 0.0, input_vector.y)).normalized()
    velocity.x = direction.x * MOVE_SPEED if direction else move_toward(
        velocity.x, 0.0, MOVE_SPEED * delta * 10.0
    )
    velocity.z = direction.z * MOVE_SPEED if direction else move_toward(
        velocity.z, 0.0, MOVE_SPEED * delta * 10.0
    )
    move_and_slide()
    for index in get_slide_collision_count():
        var collision := get_slide_collision(index)
        var collider := collision.get_collider()
        if collider is RigidBody3D:
            collider.apply_central_impulse(-collision.get_normal() * PUSH_IMPULSE)
    if is_instance_valid(_grabbed):
        var displacement := _grab_point.global_position - _grabbed.global_position
        _grabbed.linear_velocity = displacement * HOLD_STIFFNESS
'''


_BODY_SCRIPT = '''extends CollisionObject3D

func _ready() -> void:
    call_deferred("_build_contract_collision")

func _build_contract_collision() -> void:
    var meshes: Array[MeshInstance3D] = []
    _collect_meshes(self, meshes)
    for mesh_instance in meshes:
        if mesh_instance.mesh == null:
            continue
        var collision := CollisionShape3D.new()
        collision.name = "ContractCollision"
        collision.transform = global_transform.affine_inverse() * mesh_instance.global_transform
        if self is RigidBody3D or self is Area3D:
            collision.shape = mesh_instance.mesh.create_convex_shape(true, false)
        else:
            collision.shape = mesh_instance.mesh.create_trimesh_shape()
        if collision.shape != null:
            add_child(collision)

func _collect_meshes(node: Node, output: Array[MeshInstance3D]) -> void:
    for child in node.get_children():
        if child is MeshInstance3D:
            output.append(child)
        _collect_meshes(child, output)
'''
