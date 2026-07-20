"""
Godot Scene Assembler - Generates a complete, runnable Godot 4 project.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path

from src.models import DoorSpec, LightType, PhysicsBody, SceneGraph, SceneLight, SceneObject


def assemble_godot_project(scene: SceneGraph, output_dir: Path, mesh_paths: dict[str, Path]) -> Path:
    """Main entry point: assemble a complete Godot project."""
    builder = GodotProjectBuilder(scene, output_dir, mesh_paths)
    return builder.build()


def _safe_name(name: str) -> str:
    return name.replace(" ", "_").replace("-", "_").replace(".", "_")


def _hex_to_floats(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        return tuple(round(int(hex_color[i:i+2], 16) / 255.0, 3) for i in (0, 2, 4))
    return (0.5, 0.5, 0.5)


class GodotProjectBuilder:
    def __init__(self, scene: SceneGraph, output_dir: Path, mesh_paths: dict[str, Path]):
        self.scene = scene
        self.project_dir = output_dir / "godot_project"
        self.mesh_paths = mesh_paths

    def build(self) -> Path:
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self._copy_assets()
        self._write_project_godot()
        self._write_player_script()
        self._write_player_scene()
        self._write_main_scene()
        return self.project_dir

    def _copy_assets(self):
        assets_dir = self.project_dir / "assets" / "meshes"
        assets_dir.mkdir(parents=True, exist_ok=True)
        for obj_id, mesh_path in self.mesh_paths.items():
            if mesh_path.exists():
                shutil.copy2(mesh_path, assets_dir / mesh_path.name)

    def _write_project_godot(self):
        content = f'''config_version=5

[application]

config/name="The Living Room"
config/description="Generated world - {self.scene.name}"
run/main_scene="res://main.tscn"
config/features=PackedStringArray("4.3", "Forward Plus")

[display]

window/size/viewport_width=1280
window/size/viewport_height=720

[input]

move_forward={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":87,"physical_keycode":0,"key_label":0,"unicode":119,"location":0,"echo":false,"script":null)]
}}
move_backward={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":83,"physical_keycode":0,"key_label":0,"unicode":115,"location":0,"echo":false,"script":null)]
}}
move_left={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":65,"physical_keycode":0,"key_label":0,"unicode":97,"location":0,"echo":false,"script":null)]
}}
move_right={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":68,"physical_keycode":0,"key_label":0,"unicode":100,"location":0,"echo":false,"script":null)]
}}
interact={{
"deadzone": 0.5,
"events": [Object(InputEventKey,"resource_local_to_scene":false,"resource_name":"","device":-1,"window_id":0,"alt_pressed":false,"shift_pressed":false,"ctrl_pressed":false,"meta_pressed":false,"pressed":false,"keycode":69,"physical_keycode":0,"key_label":0,"unicode":101,"location":0,"echo":false,"script":null)]
}}

[physics]

3d/default_gravity=9.8

[rendering]

renderer/rendering_method="forward_plus"
environment/defaults/default_clear_color=Color(0.1, 0.1, 0.15, 1)
'''
        (self.project_dir / "project.godot").write_text(content)

    def _write_player_scene(self):
        content = '''[gd_scene load_steps=2 format=3 uid="uid://player_scene"]

[ext_resource type="Script" path="res://player.gd" id="1"]

[sub_resource type="CapsuleShape3D" id="1"]
radius = 0.3
height = 1.8

[node name="Player" type="CharacterBody3D"]
script = ExtResource("1")

[node name="CollisionShape" type="CollisionShape3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.9, 0)
shape = SubResource("1")

[node name="Head" type="Node3D" parent="."]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1.6, 0)

[node name="Camera3D" type="Camera3D" parent="Head"]
current = true
fov = 75.0

[node name="InteractRay" type="RayCast3D" parent="Head"]
target_position = Vector3(0, 0, -3)
enabled = true

[node name="GrabPoint" type="Marker3D" parent="Head"]
transform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, -1.5)
'''
        (self.project_dir / "player.tscn").write_text(content)

    def _write_player_script(self):
        script = '''extends CharacterBody3D

const SPEED = 4.0
const MOUSE_SENSITIVITY = 0.003
const PUSH_FORCE = 5.0

var gravity = ProjectSettings.get_setting("physics/3d/default_gravity")
var grabbed_object: RigidBody3D = null
var head: Node3D
var interact_ray: RayCast3D
var grab_point: Marker3D

func _ready():
\thead = $Head
\tinteract_ray = $Head/InteractRay
\tgrab_point = $Head/GrabPoint
\tInput.set_mouse_mode(Input.MOUSE_MODE_CAPTURED)

func _unhandled_input(event):
\tif event is InputEventMouseMotion:
\t\trotate_y(-event.relative.x * MOUSE_SENSITIVITY)
\t\thead.rotate_x(-event.relative.y * MOUSE_SENSITIVITY)
\t\thead.rotation.x = clamp(head.rotation.x, -PI/2, PI/2)
\tif event.is_action_pressed("interact"):
\t\t_toggle_grab()
\tif event is InputEventKey and event.pressed and event.keycode == KEY_ESCAPE:
\t\tInput.set_mouse_mode(Input.MOUSE_MODE_VISIBLE)

func _toggle_grab():
\tif grabbed_object:
\t\tgrabbed_object = null
\telse:
\t\tif interact_ray.is_colliding():
\t\t\tvar collider = interact_ray.get_collider()
\t\t\tif collider is RigidBody3D:
\t\t\t\tgrabbed_object = collider

func _physics_process(delta):
\tif not is_on_floor():
\t\tvelocity.y -= gravity * delta
\tvar input_dir = Input.get_vector("move_left", "move_right", "move_forward", "move_backward")
\tvar direction = (transform.basis * Vector3(input_dir.x, 0, input_dir.y)).normalized()
\tif direction:
\t\tvelocity.x = direction.x * SPEED
\t\tvelocity.z = direction.z * SPEED
\telse:
\t\tvelocity.x = move_toward(velocity.x, 0, SPEED * delta * 10)
\t\tvelocity.z = move_toward(velocity.z, 0, SPEED * delta * 10)
\tmove_and_slide()
\tfor i in get_slide_collision_count():
\t\tvar collision = get_slide_collision(i)
\t\tvar collider = collision.get_collider()
\t\tif collider is RigidBody3D:
\t\t\tcollider.apply_central_impulse(-collision.get_normal() * PUSH_FORCE * delta)
\tif grabbed_object:
\t\tvar move_dir = grab_point.global_position - grabbed_object.global_position
\t\tgrabbed_object.linear_velocity = move_dir * 10.0
'''
        (self.project_dir / "player.gd").write_text(script)

    def _write_main_scene(self):
        """Write the main.tscn with room shell, objects, lights, player."""
        lines = []
        ext_res = []
        sub_res = []
        ext_id = 0
        sub_id = 0

        # External resources: meshes
        mesh_ext_map = {}
        for obj_id, mesh_path in self.mesh_paths.items():
            ext_id += 1
            ext_res.append(f'[ext_resource type="ArrayMesh" path="res://assets/meshes/{mesh_path.name}" id="{ext_id}"]')
            mesh_ext_map[obj_id] = ext_id

        # Player scene
        ext_id += 1
        player_ext_id = ext_id
        ext_res.append(f'[ext_resource type="PackedScene" path="res://player.tscn" id="{ext_id}"]')

        # Sub resources: collision shapes, materials, meshes for room shell
        h = self.scene.room.height
        w = self.scene.room.width
        d = self.scene.room.depth

        # Floor shape + mesh + material
        sub_id += 1; floor_shape = sub_id
        sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; floor_mesh = sub_id
        sub_res.append(f'[sub_resource type="BoxMesh" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; floor_mat = sub_id
        fr, fg, fb = _hex_to_floats(self.scene.room.floor_material.base_color)
        sub_res.append(f'[sub_resource type="StandardMaterial3D" id="{sub_id}"]\nalbedo_color = Color({fr}, {fg}, {fb}, 1)\nroughness = {self.scene.room.floor_material.roughness}')

        # Ceiling
        sub_id += 1; ceil_shape = sub_id
        sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; ceil_mesh = sub_id
        sub_res.append(f'[sub_resource type="BoxMesh" id="{sub_id}"]\nsize = Vector3({w}, 0.1, {d})')
        sub_id += 1; ceil_mat = sub_id
        cr, cg, cb = _hex_to_floats(self.scene.room.ceiling_material.base_color)
        sub_res.append(f'[sub_resource type="StandardMaterial3D" id="{sub_id}"]\nalbedo_color = Color({cr}, {cg}, {cb}, 1)\nroughness = {self.scene.room.ceiling_material.roughness}')

        # Wall material
        sub_id += 1; wall_mat = sub_id
        wr, wg, wb = _hex_to_floats(self.scene.room.wall_material.base_color)
        sub_res.append(f'[sub_resource type="StandardMaterial3D" id="{sub_id}"]\nalbedo_color = Color({wr}, {wg}, {wb}, 1)\nroughness = {self.scene.room.wall_material.roughness}')

        # Wall meshes and shapes
        wall_data = {}
        for wname, size in [("north", f"{w}, {h}, 0.2"), ("south", f"{w}, {h}, 0.2"),
                            ("east", f"0.2, {h}, {d}"), ("west", f"0.2, {h}, {d}")]:
            sub_id += 1
            wall_data[wname] = {"shape": sub_id}
            sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({size})')
            sub_id += 1
            wall_data[wname]["mesh"] = sub_id
            sub_res.append(f'[sub_resource type="BoxMesh" id="{sub_id}"]\nsize = Vector3({size})')

        # Object collision shapes
        obj_shapes = {}
        for obj in self.scene.objects:
            sub_id += 1
            obj_shapes[obj.id] = sub_id
            if obj.primitive_shape == "cylinder":
                r = min(obj.dimensions.x, obj.dimensions.z) / 2
                sub_res.append(f'[sub_resource type="CylinderShape3D" id="{sub_id}"]\nradius = {r}\nheight = {obj.dimensions.y}')
            else:
                sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({obj.dimensions.x}, {obj.dimensions.y}, {obj.dimensions.z})')

        # Door shapes
        door_shapes = {}
        for door in self.scene.doors:
            sub_id += 1
            door_shapes[door.id] = sub_id
            sub_res.append(f'[sub_resource type="BoxShape3D" id="{sub_id}"]\nsize = Vector3({door.width}, {door.height}, 0.04)')

        # Environment
        sub_id += 1; env_id = sub_id
        ar, ag, ab = _hex_to_floats(self.scene.ambient_color)
        sub_res.append(f'[sub_resource type="Environment" id="{sub_id}"]\nbackground_mode = 1\nbackground_color = Color({ar}, {ag}, {ab}, 1)\nambient_light_source = 2\nambient_light_color = Color({ar}, {ag}, {ab}, 1)\nambient_light_energy = {self.scene.ambient_energy}\ntonemap_mode = 2\nssao_enabled = true\nglow_enabled = true')

        # --- Nodes ---
        nodes = []
        nodes.append('[node name="World" type="Node3D"]')

        # Environment
        nodes.append(f'\n[node name="Environment" type="WorldEnvironment" parent="."]\nenvironment = SubResource("{env_id}")')

        # Floor
        nodes.append(f'\n[node name="Floor" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, -0.05, 0)')
        nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="Floor"]\nmesh = SubResource("{floor_mesh}")\nsurface_material_override/0 = SubResource("{floor_mat}")')
        nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="Floor"]\nshape = SubResource("{floor_shape}")')

        # Ceiling
        nodes.append(f'\n[node name="Ceiling" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, {h + 0.05}, 0)')
        nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="Ceiling"]\nmesh = SubResource("{ceil_mesh}")\nsurface_material_override/0 = SubResource("{ceil_mat}")')
        nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="Ceiling"]\nshape = SubResource("{ceil_shape}")')

        # Walls
        half_w, half_d = w / 2, d / 2
        wall_pos = {"north": f"0, {h/2}, {half_d+0.1}", "south": f"0, {h/2}, {-(half_d+0.1)}",
                    "east": f"{half_w+0.1}, {h/2}, 0", "west": f"{-(half_w+0.1)}, {h/2}, 0"}
        for wname, pos in wall_pos.items():
            nodes.append(f'\n[node name="Wall_{wname}" type="StaticBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {pos})')
            nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="Wall_{wname}"]\nmesh = SubResource("{wall_data[wname]["mesh"]}")\nsurface_material_override/0 = SubResource("{wall_mat}")')
            nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="Wall_{wname}"]\nshape = SubResource("{wall_data[wname]["shape"]}")')

        # Objects
        for obj in self.scene.objects:
            body = "StaticBody3D" if obj.physics.body_type == PhysicsBody.STATIC else "RigidBody3D"
            px, pz = obj.position.x, obj.position.z
            py = obj.position.y + obj.dimensions.y / 2
            name = _safe_name(obj.name)
            ry = math.radians(obj.rotation.y)

            if abs(obj.rotation.y) > 0.1:
                c, s = math.cos(ry), math.sin(ry)
                t = f"Transform3D({c:.4f}, 0, {s:.4f}, 0, 1, 0, {-s:.4f}, 0, {c:.4f}, {px}, {py}, {pz})"
            else:
                t = f"Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {px}, {py}, {pz})"

            node_str = f'\n[node name="{name}" type="{body}" parent="."]\ntransform = {t}'
            if body == "RigidBody3D":
                node_str += f"\nmass = {obj.physics.mass_kg}"
            nodes.append(node_str)

            if obj.id in mesh_ext_map:
                nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="{name}"]\nmesh = ExtResource("{mesh_ext_map[obj.id]}")')
            if obj.id in obj_shapes:
                nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="{name}"]\nshape = SubResource("{obj_shapes[obj.id]}")')

        # Doors
        for door in self.scene.doors:
            name = _safe_name("Door_" + door.id)
            py = door.height / 2
            nodes.append(f'\n[node name="{name}" type="RigidBody3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {door.position.x}, {py}, {door.position.z})\nmass = {door.physics.mass_kg}')
            if door.id in mesh_ext_map:
                nodes.append(f'\n[node name="Mesh" type="MeshInstance3D" parent="{name}"]\nmesh = ExtResource("{mesh_ext_map[door.id]}")')
            if door.id in door_shapes:
                nodes.append(f'\n[node name="Col" type="CollisionShape3D" parent="{name}"]\nshape = SubResource("{door_shapes[door.id]}")')

        # Lights
        for light in self.scene.lights:
            r, g, b = _hex_to_floats(light.color)
            px, py, pz = light.position.x, light.position.y, light.position.z
            name = _safe_name(light.name)

            if light.light_type == LightType.POINT:
                nodes.append(f'\n[node name="{name}" type="OmniLight3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {px}, {py}, {pz})\nlight_color = Color({r}, {g}, {b}, 1)\nlight_energy = {light.intensity}\nomni_range = {light.range_meters}\nshadow_enabled = {"true" if light.cast_shadows else "false"}')
            elif light.light_type == LightType.DIRECTIONAL:
                nodes.append(f'\n[node name="{name}" type="DirectionalLight3D" parent="."]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {px}, {py}, {pz})\nlight_color = Color({r}, {g}, {b}, 1)\nlight_energy = {light.intensity}\nshadow_enabled = {"true" if light.cast_shadows else "false"}')

        # Player
        nodes.append(f'\n[node name="Player" parent="." instance=ExtResource("{player_ext_id}")]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0.9, {half_d - 0.5})')

        # Write file
        total = len(ext_res) + len(sub_res) + 2
        out = f'[gd_scene load_steps={total} format=3 uid="uid://main_scene"]\n\n'
        out += "\n".join(ext_res) + "\n\n"
        out += "\n\n".join(sub_res) + "\n\n"
        out += "\n".join(nodes) + "\n"
        (self.project_dir / "main.tscn").write_text(out)
