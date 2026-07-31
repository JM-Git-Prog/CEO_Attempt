"""Deterministic, authority-preserving WorldContract to UPBGE compiler.

The host side always emits a reproducible build bundle.  When a compatible
Blender/UPBGE executable is available and every contract-bound dependency can
be resolved, it also executes the bundled builder and validates its report.
A plan or script is never represented as a real ``.blend`` artifact.

Requirements: 21.3, 21.4, 21.6.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..world_contract import WorldContract, serialize, verify_hash

PLAN_SCHEMA_VERSION = "unified-upbge-plan/v1"
COMPILER_VERSION = "unified-upbge-compiler/v1"
SCENE_COLLECTIONS = ("Architecture", "Instances", "Lights", "Runtime")
_VALID_PHYSICS = frozenset({"static", "dynamic", "kinematic", "trigger"})
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class UPBGECompileError(RuntimeError):
    """Raised when contract integrity or compilation output is invalid."""


@dataclass(frozen=True)
class UPBGECompileResult:
    """Honest description of emitted files and runtime capability."""

    status: str
    artifact_kind: str
    artifact_path: Path
    manifest_path: Path
    plan_path: Path
    builder_script_path: Path
    controller_script_path: Path
    blend_path: Path | None
    is_real_blend: bool
    is_upbge_ready: bool
    contract_hash: str
    plan_revision: str
    fallback_reason: str | None = None
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "artifact_path", "manifest_path", "plan_path",
            "builder_script_path", "controller_script_path", "blend_path",
        ):
            value = data[key]
            data[key] = str(value) if value is not None else None
        return data


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _finite(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise UPBGECompileError(f"{label} must be finite")
    return number


def domain_to_upbge_xyz(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Map contract X-right/Y-up/Z-depth to UPBGE X-right/Y-depth/Z-up."""
    return (_finite(x, "x"), _finite(z, "z"), _finite(y, "y"))


def domain_to_upbge_quaternion(
    x: float, y: float, z: float, w: float,
) -> tuple[float, float, float, float]:
    """Apply the same basis change to an orientation pseudovector."""
    values = tuple(_finite(v, "quaternion") for v in (x, y, z, w))
    if sum(v * v for v in values) <= 1e-12:
        raise UPBGECompileError("rotation quaternion must be non-zero")
    return (-values[0], -values[2], -values[1], values[3])


def _safe_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_.")
    return cleaned or "unnamed"


def _validate_contract(contract: WorldContract) -> None:
    if not isinstance(contract, WorldContract):
        raise TypeError("contract must be unified_pipeline.world_contract.WorldContract")
    if not verify_hash(contract):
        raise UPBGECompileError("WorldContract must have a valid canonical hash")
    if not contract.plan_revision.strip():
        raise UPBGECompileError("WorldContract plan_revision is required")
    if not _HEX_64.fullmatch(contract.camera_hash):
        raise UPBGECompileError("WorldContract camera_hash must be lowercase SHA-256")
    if not contract.room_shell_ref.strip():
        raise UPBGECompileError("WorldContract room_shell_ref is required")

    seen: set[str] = set()
    for instance in contract.instances:
        if not instance.object_id or instance.object_id in seen:
            raise UPBGECompileError("instance IDs must be non-empty and unique")
        seen.add(instance.object_id)
        if instance.physics_intent not in _VALID_PHYSICS:
            raise UPBGECompileError(
                f"{instance.object_id}: unsupported physics intent "
                f"{instance.physics_intent!r}"
            )
        position = instance.position
        scale = instance.scale
        domain_to_upbge_xyz(position.x, position.y, position.z)
        mapped_scale = domain_to_upbge_xyz(scale.x, scale.y, scale.z)
        if any(value <= 0.0 for value in mapped_scale):
            raise UPBGECompileError(f"{instance.object_id}: scale must be positive")
        rotation = instance.rotation
        domain_to_upbge_quaternion(rotation.x, rotation.y, rotation.z, rotation.w)
        material = instance.material_intent
        if not (0.0 <= material.metallic <= 1.0 and 0.0 <= material.roughness <= 1.0):
            raise UPBGECompileError(f"{instance.object_id}: invalid material intent")
        asset = instance.asset_binding
        if not _HEX_64.fullmatch(asset.asset_id) or not asset.mesh_path.strip():
            raise UPBGECompileError(f"{instance.object_id}: invalid approved asset binding")
        if asset.triangle_count <= 0:
            raise UPBGECompileError(f"{instance.object_id}: triangle_count must be positive")

    for light in contract.lighting.lights:
        if not light.light_id:
            raise UPBGECompileError("light IDs must be non-empty")
        domain_to_upbge_xyz(light.position.x, light.position.y, light.position.z)
        _finite(light.intensity, f"{light.light_id}.intensity")
        _finite(light.temperature, f"{light.light_id}.temperature")


def _instance_plan(instance: Any) -> dict[str, Any]:
    position = instance.position
    rotation = instance.rotation
    scale = instance.scale
    asset = instance.asset_binding
    material = instance.material_intent
    return {
        "object_id": instance.object_id,
        "object_name": f"Object_{_safe_id(instance.object_id)}",
        "display_name": instance.name,
        "semantic_label": instance.semantic_label,
        "collection": "Architecture" if instance.is_architectural else "Instances",
        "transform_domain": {
            "position": [position.x, position.y, position.z],
            "rotation_xyzw": [rotation.x, rotation.y, rotation.z, rotation.w],
            "scale": [scale.x, scale.y, scale.z],
        },
        "transform_upbge": {
            "position": list(domain_to_upbge_xyz(position.x, position.y, position.z)),
            "rotation_xyzw": list(domain_to_upbge_quaternion(
                rotation.x, rotation.y, rotation.z, rotation.w,
            )),
            "scale": list(domain_to_upbge_xyz(scale.x, scale.y, scale.z)),
        },
        "asset": {
            "sha256": asset.asset_id,
            "contract_path": asset.mesh_path,
            "bundle_path": f"assets/{asset.asset_id}.glb",
            "triangle_count": asset.triangle_count,
            "vertex_count": asset.vertex_count,
            "generator": asset.generator,
        },
        "physics": {
            "intent": instance.physics_intent,
            "is_architectural": instance.is_architectural,
            "engine_mode": {
                "static": "STATIC", "dynamic": "RIGID_BODY",
                "kinematic": "DYNAMIC", "trigger": "SENSOR",
            }[instance.physics_intent],
        },
        "material": {
            "base_color": material.base_color,
            "metallic": material.metallic,
            "roughness": material.roughness,
            "normal_map_ref": material.normal_map_ref,
            "pass_level": material.pass_level,
        },
    }


def _spawn_plan(contract: WorldContract) -> dict[str, Any]:
    markers = [
        item for item in contract.instances
        if item.semantic_label.strip().lower().replace("-", "_").replace(" ", "_")
        in {"player_spawn", "safe_spawn", "spawn_point"}
    ]
    if markers:
        marker = sorted(markers, key=lambda item: item.object_id)[0]
        return {
            "strategy": "contract_spawn_marker",
            "source_object_id": marker.object_id,
            "position_upbge": list(domain_to_upbge_xyz(
                marker.position.x, marker.position.y, marker.position.z,
            )),
            "rotation_upbge_xyzw": list(domain_to_upbge_quaternion(
                marker.rotation.x, marker.rotation.y,
                marker.rotation.z, marker.rotation.w,
            )),
        }
    return {
        "strategy": "room_shell_collision_probe",
        "source_object_id": None,
        "position_upbge": None,
        "rotation_upbge_xyzw": None,
        "description": (
            "Builder derives a collision-free floor point from the exact "
            "contract-bound room shell; it does not infer room dimensions."
        ),
    }


def build_upbge_plan(contract: WorldContract) -> dict[str, Any]:
    """Build a deterministic scene plan using only canonical contract values."""
    _validate_contract(contract)
    instances = [_instance_plan(item) for item in contract.instances]
    lights = []
    for light in contract.lighting.lights:
        lights.append({
            "light_id": light.light_id,
            "object_name": f"Light_{_safe_id(light.light_id)}",
            "light_type": light.light_type,
            "position_upbge": list(domain_to_upbge_xyz(
                light.position.x, light.position.y, light.position.z,
            )),
            "color": light.color,
            "intensity": light.intensity,
            "temperature": light.temperature,
            "cast_shadows": light.cast_shadows,
        })
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "compiler_version": COMPILER_VERSION,
        "world_contract_hash": contract.contract_hash,
        "plan_revision": contract.plan_revision,
        "camera_hash": contract.camera_hash,
        "coordinate_mapping": "contract(x,y,z)->upbge(x,z,y)",
        "scene": {
            "name": "UnifiedWorld",
            "root_object": "WorldRoot",
            "collections": list(SCENE_COLLECTIONS),
            "room_shell": {
                "object_name": "RoomShell",
                "contract_reference": contract.room_shell_ref,
                "bundle_path": "room/room_shell.glb",
                "authority": "WorldContract.room_shell_ref",
                "collision": "STATIC",
            },
        },
        "instances": instances,
        "relationships": [item.to_dict() for item in contract.relationships],
        "lighting": {
            "ambient_color": contract.lighting.ambient_color,
            "ambient_intensity": contract.lighting.ambient_intensity,
            "lights": lights,
        },
        "player": {
            "object_name": "Player",
            "camera_name": "PlayerCamera",
            "collection": "Runtime",
            "spawn": _spawn_plan(contract),
            "character_physics": {
                "mode": "CHARACTER", "shape": "CAPSULE",
                "radius_m": 0.35, "height_m": 1.8, "step_height_m": 0.3,
            },
            "controls": {
                "forward": "W", "left": "A", "back": "S", "right": "D",
                "look": "MOUSE", "jump": "SPACE",
            },
            "logic_bricks": [{
                "sensor": {"name": "PlayerAlways", "type": "ALWAYS", "pulse": True},
                "controller": {
                    "name": "PlayerController", "type": "PYTHON",
                    "module": "upbge_player_controller.main",
                },
            }],
        },
    }


PLAYER_CONTROLLER_SOURCE = textwrap.dedent(r'''\
"""UPBGE first-person controller embedded by the unified compiler."""
from mathutils import Vector
from bge import events, logic, render

MOVE_SPEED = 0.08
LOOK_SPEED = 0.0025
JUMP_SPEED = 5.0

def _pressed(keyboard, key):
    return keyboard.events[key] in (logic.KX_INPUT_ACTIVE, logic.KX_INPUT_JUST_ACTIVATED)

def main():
    controller = logic.getCurrentController()
    owner = controller.owner
    keyboard = logic.keyboard
    movement = Vector((0.0, 0.0, 0.0))
    if _pressed(keyboard, events.WKEY): movement.y += MOVE_SPEED
    if _pressed(keyboard, events.SKEY): movement.y -= MOVE_SPEED
    if _pressed(keyboard, events.AKEY): movement.x -= MOVE_SPEED
    if _pressed(keyboard, events.DKEY): movement.x += MOVE_SPEED
    owner.applyMovement(movement, True)
    if _pressed(keyboard, events.SPACEKEY):
        try: owner.jump()
        except (AttributeError, RuntimeError): pass

    width, height = render.getWindowWidth(), render.getWindowHeight()
    center = (width // 2, height // 2)
    mouse = logic.mouse.position
    yaw = (mouse[0] - 0.5) * -LOOK_SPEED * width
    pitch = (mouse[1] - 0.5) * -LOOK_SPEED * height
    owner.applyRotation((0.0, 0.0, yaw), False)
    camera = owner.children.get("PlayerCamera")
    if camera is not None:
        camera.applyRotation((pitch, 0.0, 0.0), True)
    render.setMousePosition(*center)
''')


UPBGE_BUILDER_SOURCE = textwrap.dedent(r'''\
"""Run inside Blender/UPBGE; consumes only the signed unified scene plan."""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy


def arguments():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    return parser.parse_args(raw)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in list(bpy.data.collections):
        bpy.data.collections.remove(collection)


def collection(name):
    value = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(value)
    return value


def move_to(obj, target):
    for owner in list(obj.users_collection): owner.objects.unlink(obj)
    target.objects.link(obj)


def color(value):
    text = value.lstrip("#")
    if len(text) not in (6, 8): raise ValueError("invalid contract color")
    channels = [int(text[i:i + 2], 16) / 255.0 for i in range(0, len(text), 2)]
    return tuple(channels[:3] + [channels[3] if len(channels) == 4 else 1.0])


def material(spec, name):
    value = bpy.data.materials.new(name)
    value.diffuse_color = color(spec["base_color"])
    value.use_nodes = True
    node = value.node_tree.nodes.get("Principled BSDF")
    if node:
        node.inputs["Base Color"].default_value = value.diffuse_color
        node.inputs["Metallic"].default_value = spec["metallic"]
        node.inputs["Roughness"].default_value = spec["roughness"]
    value["world_contract_material"] = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return value


def import_glb(path, target):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    imported = [obj for obj in bpy.context.scene.objects if obj not in before]
    if not imported: raise RuntimeError("GLB import created no objects: " + str(path))
    for obj in imported: move_to(obj, target)
    return imported


def configure_physics(objects, spec):
    configured = True
    for obj in objects:
        obj["world_contract_physics_intent"] = spec["intent"]
        game = getattr(obj, "game", None)
        if game is None:
            configured = False
            continue
        try:
            game.physics_type = spec["engine_mode"]
            game.use_collision_bounds = True
            game.collision_bounds_type = "CONVEX_HULL"
            game.use_actor = True
            game.use_ghost = spec["intent"] == "trigger"
            if spec["intent"] == "kinematic":
                obj["world_contract_kinematic"] = True
        except (AttributeError, RuntimeError, TypeError):
            configured = False
    return configured


def build_instance(spec, collections):
    imported = import_glb(Path(BUNDLE) / spec["asset"]["bundle_path"], collections[spec["collection"]])
    if len(imported) == 1:
        root = imported[0]
    else:
        root = bpy.data.objects.new(spec["object_name"], None)
        collections[spec["collection"]].objects.link(root)
        for child in imported:
            if child.parent is None: child.parent = root
    root.name = spec["object_name"]
    transform = spec["transform_upbge"]
    root.location = transform["position"]
    root.rotation_mode = "QUATERNION"
    root.rotation_quaternion = (transform["rotation_xyzw"][3], *transform["rotation_xyzw"][:3])
    root.scale = transform["scale"]
    root["world_contract_object_id"] = spec["object_id"]
    root["world_contract_transform"] = json.dumps(spec["transform_domain"], sort_keys=True, separators=(",", ":"))
    root["world_contract_asset_sha256"] = spec["asset"]["sha256"]
    mat = material(spec["material"], "Material_" + spec["object_id"])
    for obj in imported:
        if obj.type == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(mat)
    physics_ok = configure_physics(imported, spec["physics"])
    return root, imported, physics_ok


def world_bounds(objects):
    points = [obj.matrix_world @ mathutils.Vector(corner) for obj in objects for corner in obj.bound_box]
    if not points: raise RuntimeError("room shell has no bounded geometry")
    return tuple(min(p[i] for p in points) for i in range(3)), tuple(max(p[i] for p in points) for i in range(3))


def overlaps_xy(point, objects, radius):
    for obj in objects:
        if obj.type != "MESH": continue
        points = [obj.matrix_world @ mathutils.Vector(corner) for corner in obj.bound_box]
        low = [min(p[i] for p in points) for i in range(3)]
        high = [max(p[i] for p in points) for i in range(3)]
        if low[0] - radius <= point[0] <= high[0] + radius and low[1] - radius <= point[1] <= high[1] + radius:
            return True
    return False


def resolve_spawn(spawn, room_objects, obstacle_objects, physics):
    if spawn["strategy"] == "contract_spawn_marker":
        return spawn["position_upbge"]
    low, high = world_bounds(room_objects)
    fractions = ((.5, .5), (.25, .25), (.75, .25), (.25, .75), (.75, .75), (.5, .25), (.5, .75))
    radius = physics["radius_m"]
    z = low[2] + physics["height_m"] / 2.0 + 0.05
    for fx, fy in fractions:
        candidate = (low[0] + (high[0] - low[0]) * fx, low[1] + (high[1] - low[1]) * fy, z)
        if not overlaps_xy(candidate, obstacle_objects, radius): return candidate
    raise RuntimeError("no collision-free player spawn found in contract room shell")


def add_logic(player, source):
    text = bpy.data.texts.get("upbge_player_controller.py") or bpy.data.texts.new("upbge_player_controller.py")
    text.clear(); text.write(source)
    game = getattr(player, "game", None)
    if game is None: return False
    try:
        bpy.context.view_layer.objects.active = player
        player.select_set(True)
        bpy.ops.logic.sensor_add(type="ALWAYS", object=player.name)
        sensor = game.sensors[-1]
        sensor.name = "PlayerAlways"
        sensor.use_pulse_true_level = True
        bpy.ops.logic.controller_add(type="PYTHON", object=player.name)
        controller = game.controllers[-1]
        controller.name = "PlayerController"
        controller.mode = "MODULE"
        controller.module = "upbge_player_controller.main"
        sensor.link(controller)
        return True
    except (AttributeError, RuntimeError, TypeError): return False


def build_player(spec, room_objects, obstacles, target):
    physics = spec["character_physics"]
    spawn = resolve_spawn(spec["spawn"], room_objects, obstacles, physics)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=spawn)
    player = bpy.context.object
    player.dimensions = (physics["radius_m"] * 2.0, physics["radius_m"] * 2.0, physics["height_m"])
    player.name = spec["object_name"]
    move_to(player, target)
    player.hide_render = True
    player["world_contract_spawn"] = json.dumps(spec["spawn"], sort_keys=True, separators=(",", ":"))
    game = getattr(player, "game", None)
    physics_ok = False
    if game is not None:
        try:
            game.physics_type = "CHARACTER"
            game.use_collision_bounds = True
            game.collision_bounds_type = "CAPSULE"
            physics_ok = True
        except (AttributeError, RuntimeError, TypeError): pass
    camera_data = bpy.data.cameras.new(spec["camera_name"])
    camera = bpy.data.objects.new(spec["camera_name"], camera_data)
    target.objects.link(camera)
    camera.parent = player
    camera.location = (0.0, 0.0, physics["height_m"] * 0.35)
    bpy.context.scene.camera = camera
    logic_ok = add_logic(player, (Path(BUNDLE) / "upbge_player_controller.py").read_text(encoding="utf-8"))
    return player, physics_ok, logic_ok, spawn


def build_light(spec, target):
    kind = {"directional": "SUN", "point": "POINT", "spot": "SPOT", "area": "AREA"}.get(spec["light_type"], "POINT")
    data = bpy.data.lights.new(spec["object_name"], kind)
    data.color = color(spec["color"])[:3]
    data.energy = spec["intensity"]
    data.use_shadow = spec["cast_shadows"]
    obj = bpy.data.objects.new(spec["object_name"], data)
    target.objects.link(obj)
    obj.location = spec["position_upbge"]
    obj["world_contract_light_id"] = spec["light_id"]


def main():
    global BUNDLE, mathutils
    args = arguments(); BUNDLE = args.bundle
    import mathutils
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    clear_scene()
    collections = {name: collection(name) for name in plan["scene"]["collections"]}
    root = bpy.data.objects.new(plan["scene"]["root_object"], None)
    bpy.context.scene.collection.objects.link(root)
    root["world_contract_hash"] = plan["world_contract_hash"]
    root["plan_revision"] = plan["plan_revision"]
    room_objects = import_glb(Path(BUNDLE) / plan["scene"]["room_shell"]["bundle_path"], collections["Architecture"])
    for obj in room_objects:
        obj["world_contract_room_shell_ref"] = plan["scene"]["room_shell"]["contract_reference"]
    physics_results = []
    obstacle_objects = []
    for spec in plan["instances"]:
        _root, imported, ok = build_instance(spec, collections)
        obstacle_objects.extend(imported)
        physics_results.append(ok)
    for spec in plan["lighting"]["lights"]: build_light(spec, collections["Lights"])
    world = bpy.context.scene.world or bpy.data.worlds.new("UnifiedWorld")
    bpy.context.scene.world = world
    world.color = color(plan["lighting"]["ambient_color"])[:3]
    player, character_ok, logic_ok, spawn = build_player(plan["player"], room_objects, obstacle_objects, collections["Runtime"])
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output))
    report = {
        "blend_saved": output.is_file(), "character_physics_configured": character_ok,
        "logic_bricks_attached": logic_ok, "player_spawn_upbge": list(spawn),
        "scene_collections": list(plan["scene"]["collections"]),
        "world_contract_hash": plan["world_contract_hash"],
        "instance_physics_configured": all(physics_results),
    }
    Path(args.report).write_text(json.dumps(report, sort_keys=True, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__": main()
''')


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _resolve_file(value: str, root: Path) -> Path | None:
    if value.startswith("file://"):
        candidate = Path(value[7:])
    elif ":sha256:" in value or value.startswith("sha256:"):
        return None
    else:
        candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None
    return resolved if resolved.is_file() else None


def _discover_executable(explicit: Path | str | None) -> Path | None:
    candidates: list[str] = []
    if explicit is not None:
        candidates.append(str(explicit))
    elif os.environ.get("UPBGE_EXECUTABLE"):
        candidates.append(os.environ["UPBGE_EXECUTABLE"])
    else:
        candidates.extend(("upbge", "blender"))
    for candidate in candidates:
        found = shutil.which(candidate)
        path = Path(found or candidate).expanduser()
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if resolved.is_file():
            return resolved
    return None


class UPBGECompiler:
    """Emit a deterministic bundle and, when possible, a validated .blend."""

    def __init__(
        self,
        *,
        executable: Path | str | None = None,
        asset_root: Path | str | None = None,
        room_shells: Mapping[str, Path | str] | None = None,
        timeout_seconds: float = 180.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        self.executable = _discover_executable(executable)
        self.asset_root = Path(asset_root or ".").expanduser().resolve()
        self.room_shells = {
            key: Path(value).expanduser() for key, value in (room_shells or {}).items()
        }
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def _stage_dependencies(
        self, contract: WorldContract, output_dir: Path,
    ) -> tuple[str, ...]:
        unresolved: list[str] = []
        room_source = self.room_shells.get(contract.room_shell_ref)
        if room_source is not None:
            try:
                room_source = room_source.resolve(strict=True)
            except (FileNotFoundError, OSError):
                room_source = None
        else:
            room_source = _resolve_file(contract.room_shell_ref, self.asset_root)
        if room_source is None or room_source.suffix.lower() != ".glb":
            unresolved.append(f"room_shell:{contract.room_shell_ref}")
        else:
            destination = output_dir / "room" / "room_shell.glb"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(room_source, destination)

        copied_assets: set[str] = set()
        for instance in contract.instances:
            asset = instance.asset_binding
            if asset.asset_id in copied_assets:
                continue
            source = _resolve_file(asset.mesh_path, self.asset_root)
            if source is None or source.suffix.lower() != ".glb":
                unresolved.append(f"asset:{instance.object_id}:{asset.mesh_path}")
                continue
            content = source.read_bytes()
            if _sha256(content) != asset.asset_id:
                unresolved.append(f"asset_hash:{instance.object_id}:{asset.mesh_path}")
                continue
            _write_bytes(output_dir / "assets" / f"{asset.asset_id}.glb", content)
            copied_assets.add(asset.asset_id)
        return tuple(sorted(unresolved))

    def compile(self, contract: WorldContract, output_dir: Path | str) -> UPBGECompileResult:
        """Compile ``contract`` without mutating or independently re-estimating it."""
        plan = build_upbge_plan(contract)
        target = Path(output_dir).expanduser().resolve()
        target.mkdir(parents=True, exist_ok=True)
        plan_path = target / "upbge_scene_plan.json"
        builder_path = target / "build_upbge.py"
        controller_path = target / "upbge_player_controller.py"
        contract_path = target / "world_contract.json"
        manifest_path = target / "artifact_manifest.json"
        blend_path = target / "scene.blend"
        report_path = target / "upbge_build_report.json"

        plan_bytes = _canonical_bytes(plan)
        contract_bytes = serialize(contract).encode("utf-8")
        _write_bytes(plan_path, plan_bytes)
        _write_bytes(builder_path, UPBGE_BUILDER_SOURCE.encode("utf-8"))
        _write_bytes(controller_path, PLAYER_CONTROLLER_SOURCE.encode("utf-8"))
        _write_bytes(contract_path, contract_bytes)
        manifest = {
            "artifact_kind": "deterministic_upbge_build_bundle",
            "claim": "build_inputs_only_not_a_blend",
            "compiler_version": COMPILER_VERSION,
            "world_contract_hash": contract.contract_hash,
            "plan_revision": contract.plan_revision,
            "files": {
                "world_contract.json": _sha256(contract_bytes),
                "upbge_scene_plan.json": _sha256(plan_bytes),
                "build_upbge.py": _sha256(UPBGE_BUILDER_SOURCE.encode("utf-8")),
                "upbge_player_controller.py": _sha256(PLAYER_CONTROLLER_SOURCE.encode("utf-8")),
            },
        }
        _write_bytes(manifest_path, _canonical_bytes(manifest))
        unresolved = self._stage_dependencies(contract, target)

        diagnostics: list[str] = []
        if unresolved:
            diagnostics.extend(f"unresolved contract dependency: {item}" for item in unresolved)
            return self._fallback_result(
                contract, target, manifest_path, plan_path, builder_path,
                controller_path, "unresolved_contract_dependencies", diagnostics,
            )
        if self.executable is None:
            diagnostics.append(
                "Blender/UPBGE executable unavailable; emitted deterministic plan and scripts only"
            )
            return self._fallback_result(
                contract, target, manifest_path, plan_path, builder_path,
                controller_path, "blender_or_upbge_unavailable", diagnostics,
            )

        blend_path.unlink(missing_ok=True)
        report_path.unlink(missing_ok=True)
        command = [
            str(self.executable), "--background", "--factory-startup",
            "--python", str(builder_path), "--",
            "--plan", str(plan_path), "--bundle", str(target),
            "--output", str(blend_path), "--report", str(report_path),
        ]
        try:
            completed = self.runner(
                command, capture_output=True, text=True,
                timeout=self.timeout_seconds, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            diagnostics.append(f"builder execution failed: {type(exc).__name__}: {exc}")
            return self._fallback_result(
                contract, target, manifest_path, plan_path, builder_path,
                controller_path, "builder_execution_failed", diagnostics,
            )
        if completed.returncode != 0:
            diagnostics.append(f"builder exited with code {completed.returncode}")
            if completed.stderr:
                diagnostics.append(completed.stderr.strip()[-2000:])
            return self._fallback_result(
                contract, target, manifest_path, plan_path, builder_path,
                controller_path, "builder_failed", diagnostics,
            )
        return self._validate_blend(
            contract, target, manifest_path, plan_path, builder_path,
            controller_path, blend_path, report_path, diagnostics,
        )

    @staticmethod
    def _fallback_result(
        contract: WorldContract,
        target: Path,
        manifest_path: Path,
        plan_path: Path,
        builder_path: Path,
        controller_path: Path,
        reason: str,
        diagnostics: Sequence[str],
    ) -> UPBGECompileResult:
        return UPBGECompileResult(
            status="fallback",
            artifact_kind="deterministic_upbge_build_bundle",
            artifact_path=target,
            manifest_path=manifest_path,
            plan_path=plan_path,
            builder_script_path=builder_path,
            controller_script_path=controller_path,
            blend_path=None,
            is_real_blend=False,
            is_upbge_ready=False,
            contract_hash=contract.contract_hash,
            plan_revision=contract.plan_revision,
            fallback_reason=reason,
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _validate_blend(
        contract: WorldContract,
        target: Path,
        manifest_path: Path,
        plan_path: Path,
        builder_path: Path,
        controller_path: Path,
        blend_path: Path,
        report_path: Path,
        diagnostics: list[str],
    ) -> UPBGECompileResult:
        real_blend = (
            blend_path.is_file()
            and blend_path.stat().st_size >= 12
            and blend_path.read_bytes()[:7] == b"BLENDER"
        )
        if not report_path.is_file():
            diagnostics.append("builder produced no validation report")
            report: dict[str, Any] = {}
        else:
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                diagnostics.append(f"invalid builder report: {exc}")
                report = {}
        expected_collections = list(SCENE_COLLECTIONS)
        ready = bool(
            real_blend
            and report.get("blend_saved") is True
            and report.get("character_physics_configured") is True
            and report.get("logic_bricks_attached") is True
            and report.get("instance_physics_configured") is True
            and report.get("scene_collections") == expected_collections
            and report.get("world_contract_hash") == contract.contract_hash
            and isinstance(report.get("player_spawn_upbge"), list)
            and len(report["player_spawn_upbge"]) == 3
        )
        if ready:
            status, kind, reason = "compiled", "upbge_blend", None
        elif real_blend:
            status, kind, reason = "degraded", "blender_blend_degraded", "upbge_validation_failed"
            diagnostics.append("a real .blend exists but UPBGE character/logic validation did not pass")
        else:
            status, kind, reason = "fallback", "deterministic_upbge_build_bundle", "invalid_blend_output"
            diagnostics.append("builder did not produce a recognizable Blender file")
        return UPBGECompileResult(
            status=status,
            artifact_kind=kind,
            artifact_path=blend_path if real_blend else target,
            manifest_path=manifest_path,
            plan_path=plan_path,
            builder_script_path=builder_path,
            controller_script_path=controller_path,
            blend_path=blend_path if real_blend else None,
            is_real_blend=real_blend,
            is_upbge_ready=ready,
            contract_hash=contract.contract_hash,
            plan_revision=contract.plan_revision,
            fallback_reason=reason,
            diagnostics=tuple(diagnostics),
        )


__all__ = [
    "COMPILER_VERSION", "PLAN_SCHEMA_VERSION", "UPBGECompileError",
    "UPBGECompileResult", "UPBGECompiler", "build_upbge_plan",
    "domain_to_upbge_quaternion", "domain_to_upbge_xyz",
]
