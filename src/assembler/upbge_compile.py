"""First-party UPBGE scene compiler.

Executed by UPBGE, not imported by the product process.  It consumes canonical
WorldContract bytes plus a deterministic host-generated compiler plan.
"""

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path


def _arguments():
    parser = argparse.ArgumentParser(description="Compile a canonical WorldContract in UPBGE")
    parser.add_argument("--input", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--render", required=True, choices=("0", "1"))
    parser.add_argument("--blend", required=True, choices=("0", "1"))
    parser.add_argument("--glb", required=True, choices=("0", "1"))
    parser.add_argument("--runtime", required=True, choices=("0", "1"))
    parser.add_argument("--max-objects", required=True, type=int)
    parser.add_argument("--max-polygons", required=True, type=int)
    parser.add_argument("--max-texture-dimension", required=True, type=int)
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    return parser.parse_args(arguments)


def _inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _validate_inputs(args):
    input_path = Path(args.input).resolve(strict=True)
    plan_path = Path(args.plan).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve(strict=True)
    if not output_dir.is_dir():
        raise ValueError("output directory must already exist")
    contract_bytes = input_path.read_bytes()
    contract = json.loads(contract_bytes.decode("utf-8"))
    canonical = json.dumps(
        contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if canonical != contract_bytes:
        raise ValueError("input is not canonical WorldContract JSON")
    plan = _load_json(plan_path)
    if plan.get("schema_version") != "upbge-compiler-plan/v1":
        raise ValueError("unsupported compiler plan")
    script_hash = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()
    if script_hash != plan.get("compiler_script_sha256"):
        raise ValueError("compiler script hash does not match first-party plan")
    if hashlib.sha256(contract_bytes).hexdigest() != plan.get("world_contract_hash"):
        raise ValueError("compiler plan does not match WorldContract")
    if plan.get("estimated_object_count", 0) > args.max_objects:
        raise ValueError("object limit exceeded")
    if plan.get("estimated_polygon_count", 0) > args.max_polygons:
        raise ValueError("polygon limit exceeded")
    if min(args.max_objects, args.max_polygons, args.max_texture_dimension) <= 0:
        raise ValueError("limits must be positive")

    outputs = dict(plan.get("outputs", ()))
    if len(outputs) != len(plan.get("outputs", ())):
        raise ValueError("compiler plan contains duplicate output roles")
    enabled = {
        ("runtime_candidate" if role == "runtime" else role)
        for role in ("render", "blend", "glb", "runtime")
        if getattr(args, role) == "1"
    }
    planned = {
        "runtime" if role == "runtime_candidate" else role
        for role in set(outputs) - {"inventory"}
    }
    if planned != enabled or outputs.get("inventory") != "scene_inventory.json":
        raise ValueError("command output flags do not match signed compiler plan")
    for role, filename in outputs.items():
        if not filename or Path(filename).name != filename:
            raise ValueError("compiler output filename is not a safe basename: " + role)

    input_root = plan_path.parent.resolve()
    for instance in plan.get("instances", ()):
        strategy = instance.get("geometry_strategy")
        if strategy not in {"primitive", "generated", "asset"}:
            raise ValueError("unsupported geometry strategy")
        if strategy != "asset":
            if instance.get("asset_relative_path") or instance.get("asset_sha256"):
                raise ValueError("non-asset geometry cannot carry an asset binding")
            continue
        relative = instance.get("asset_relative_path")
        expected_hash = instance.get("asset_sha256")
        if not relative or not expected_hash or Path(relative).is_absolute():
            raise ValueError("asset geometry requires a relative hash-bound asset")
        asset_path = (input_root / relative).resolve(strict=True)
        if not _inside(asset_path, input_root) or asset_path.suffix.lower() != ".glb":
            raise ValueError("asset path escaped the read-only input directory")
        if hashlib.sha256(asset_path.read_bytes()).hexdigest() != expected_hash:
            raise ValueError("asset bytes do not match compiler plan")
    return contract, plan, output_dir


def _clear_scene(bpy):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.meshes, bpy.data.curves, bpy.data.materials,
                       bpy.data.cameras, bpy.data.lights):
        for datablock in list(collection):
            if datablock.users == 0:
                collection.remove(datablock)


def _material(bpy, spec):
    material = bpy.data.materials.new(spec["stable_id"])
    material.diffuse_color = tuple(spec["base_color_rgba"])
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF")
    if node:
        node.inputs["Base Color"].default_value = tuple(spec["base_color_rgba"])
        node.inputs["Metallic"].default_value = spec["metallic"]
        node.inputs["Roughness"].default_value = spec["roughness"]
        if spec.get("emission_rgba"):
            emission = node.inputs.get("Emission Color") or node.inputs.get("Emission")
            if emission:
                emission.default_value = tuple(spec["emission_rgba"])
            strength = node.inputs.get("Emission Strength")
            if strength:
                strength.default_value = spec["emission_strength"]
    material["kiro_stable_id"] = spec["stable_id"]
    return material


def _apply_geometry_spec(bpy, obj, spec, materials):
    obj.name = spec["stable_id"]
    obj.location = tuple(spec["position_upbge"])
    obj.rotation_euler = tuple(math.radians(value) for value in spec["rotation_upbge_deg"])
    obj.dimensions = tuple(spec["dimensions_upbge"])
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.scale = tuple(spec.get("scale_upbge", (1.0, 1.0, 1.0)))
    material = materials.get(spec["material_id"])
    if material:
        obj.data.materials.clear()
        obj.data.materials.append(material)
    obj["kiro_stable_id"] = spec["stable_id"]
    obj["kiro_role"] = spec["role"]
    obj["kiro_material_id"] = spec["material_id"]
    obj["kiro_geometry_strategy"] = spec.get("geometry_strategy", "primitive")
    obj["kiro_transform_scale"] = list(spec.get("scale_upbge", (1.0, 1.0, 1.0)))
    if spec.get("asset_registry_id"):
        obj["kiro_asset_registry_id"] = spec["asset_registry_id"]
        obj["kiro_asset_sha256"] = spec["asset_sha256"]
    for key, value in spec.get("metadata", []):
        obj["kiro_" + key] = value
    if spec["role"] in {"floor", "ceiling", "wall_segment"}:
        game = getattr(obj, "game", None)
        if game is None:
            raise RuntimeError("verified UPBGE build exposes no game physics API")
        game.physics_type = "STATIC"
        game.use_collision_bounds = True
        game.collision_bounds_type = "BOX"
        obj["kiro_body_mode"] = "static"
        obj["kiro_collision_shape"] = "box"
    return obj


def _add_primitive(bpy, spec, materials):
    shape = spec["shape"]
    if shape == "box":
        bpy.ops.mesh.primitive_cube_add(size=1.0)
    elif shape == "cylinder":
        bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.5, depth=1.0)
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.5)
    elif shape == "plane":
        bpy.ops.mesh.primitive_plane_add(size=1.0)
    elif shape == "capsule":
        # Geometry remains deterministic; collision intent independently selects CAPSULE.
        bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.5)
    else:
        raise ValueError("unsupported geometry shape: " + str(shape))
    return _apply_geometry_spec(bpy, bpy.context.object, spec, materials)


def _add_asset(bpy, spec, materials, input_root):
    relative = spec.get("asset_relative_path")
    if not relative:
        raise ValueError("asset geometry has no approved relative path")
    asset_path = (input_root / relative).resolve(strict=True)
    if not _inside(asset_path, input_root):
        raise ValueError("asset path traversal rejected")
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(asset_path))
    imported = [obj for obj in bpy.data.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise ValueError("approved asset contains no mesh geometry")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    for imported_obj in imported:
        if imported_obj != obj and imported_obj.name in bpy.data.objects:
            bpy.data.objects.remove(imported_obj, do_unlink=True)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
    obj.location = (0.0, 0.0, 0.0)
    return _apply_geometry_spec(bpy, obj, spec, materials)


def _configure_physics(obj, spec):
    obj["kiro_physics_id"] = spec["stable_id"]
    obj["kiro_body_mode"] = spec["body_mode"]
    obj["kiro_collision_shape"] = spec["collision_shape"]
    obj["kiro_mass_kg"] = spec["mass_kg"]
    obj["kiro_friction"] = spec["friction"]
    obj["kiro_restitution"] = spec["restitution"]
    obj["kiro_can_topple"] = spec["can_topple"]
    game = getattr(obj, "game", None)
    if game is None:
        raise RuntimeError("verified UPBGE build exposes no game physics API")
    physics_types = {"static": "STATIC", "dynamic": "RIGID_BODY",
                     "kinematic": "DYNAMIC", "trigger": "SENSOR"}
    collision_bounds = {"box": "BOX", "cylinder": "CYLINDER", "sphere": "SPHERE",
                        "capsule": "CAPSULE", "mesh": "TRIANGLE_MESH"}
    body_mode = spec["body_mode"]
    collision_shape = spec["collision_shape"]
    if body_mode not in physics_types or collision_shape not in collision_bounds:
        raise ValueError("unsupported explicit physics configuration")
    game.physics_type = physics_types[body_mode]
    game.use_collision_bounds = True
    game.collision_bounds_type = collision_bounds[collision_shape]
    game.use_actor = True
    game.use_ghost = body_mode == "trigger"
    if body_mode == "dynamic":
        game.mass = spec["mass_kg"]
    if body_mode == "kinematic":
        obj["kiro_kinematic"] = True
    material = getattr(obj, "active_material", None)
    material_physics = getattr(material, "physics", None)
    if material_physics is not None:
        material_physics.friction = spec["friction"]
        if hasattr(material_physics, "elasticity"):
            material_physics.elasticity = spec["restitution"]


def _camera(bpy, spec):
    from mathutils import Matrix, Vector
    data = bpy.data.cameras.new(spec["stable_id"] + ":data")
    data.type = "PERSP"
    data.sensor_fit = "VERTICAL"
    data.angle_y = math.radians(spec["vertical_fov_deg"])
    data.clip_start = spec["near_plane_m"]
    data.clip_end = spec["far_plane_m"]
    obj = bpy.data.objects.new(spec["stable_id"], data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(spec["position_upbge"])
    forward = (Vector(spec["target_upbge"]) - obj.location).normalized()
    authored_up = Vector(spec["up_upbge"]).normalized()
    right = forward.cross(authored_up)
    if right.length < 1e-8:
        raise ValueError("camera forward and up vectors are collinear")
    right.normalize()
    corrected_up = right.cross(forward).normalized()
    obj.matrix_world = Matrix((right, corrected_up, -forward)).transposed().to_4x4()
    obj.location = tuple(spec["position_upbge"])
    obj["kiro_stable_id"] = spec["stable_id"]
    obj["kiro_role"] = "camera"
    obj["kiro_vertical_fov_deg"] = spec["vertical_fov_deg"]
    obj["kiro_aspect_ratio"] = spec["aspect_ratio"]
    obj["kiro_near_plane_m"] = spec["near_plane_m"]
    obj["kiro_far_plane_m"] = spec["far_plane_m"]
    obj["kiro_raster_px"] = list(spec["raster_px"])
    scene = bpy.context.scene
    scene.camera = obj
    scene.render.resolution_x, scene.render.resolution_y = spec["raster_px"]
    scene.render.resolution_percentage = 100
    raster_aspect = spec["raster_px"][0] / spec["raster_px"][1]
    scene.render.pixel_aspect_x = spec["aspect_ratio"] / raster_aspect
    scene.render.pixel_aspect_y = 1.0
    return obj


def _light(bpy, spec):
    from mathutils import Vector
    data = bpy.data.lights.new(spec["stable_id"] + ":data", type=spec["light_type"])
    data.color = tuple(spec["color_rgb"])
    data.energy = spec["intensity"]
    if hasattr(data, "cutoff_distance"):
        data.cutoff_distance = spec["range_m"]
    if spec["light_type"] == "SPOT":
        data.spot_size = math.radians(spec["spot_angle_deg"])
    data.use_shadow = spec["cast_shadows"]
    obj = bpy.data.objects.new("light:" + spec["stable_id"], data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = tuple(spec["position_upbge"])
    direction = Vector(spec["direction_upbge"])
    if direction.length:
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    obj["kiro_stable_id"] = spec["stable_id"]
    obj["kiro_role"] = "light_source"
    if spec.get("fixture_instance_id"):
        obj["kiro_fixture_instance_id"] = spec["fixture_instance_id"]
    return obj


def _opening_marker(bpy, spec):
    obj = bpy.data.objects.new("opening:" + spec["stable_id"], None)
    bpy.context.scene.collection.objects.link(obj)
    obj.empty_display_type = "CUBE"
    obj.empty_display_size = 1.0
    obj.location = tuple(spec["position_upbge"])
    obj.scale = tuple(value / 2.0 for value in spec["dimensions_upbge"])
    obj.hide_render = True
    obj["kiro_stable_id"] = spec["stable_id"]
    obj["kiro_role"] = "opening_aperture"
    obj["kiro_opening_kind"] = spec["kind"]
    obj["kiro_wall"] = spec["wall"]
    obj["kiro_sill_height_m"] = spec["sill_height_m"]
    return obj


def _configure_scene(bpy, contract, plan):
    scene = bpy.context.scene
    scene["kiro_world_contract_hash"] = plan["world_contract_hash"]
    scene["kiro_coordinate_system"] = contract["coordinate_system"]
    scene["kiro_length_unit"] = contract["length_unit"]
    scene["kiro_angle_unit"] = contract["angle_unit"]
    scene["kiro_compiler_plan_version"] = plan["schema_version"]
    scene.gravity = tuple(plan["gravity_upbge"])
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    world = scene.world or bpy.data.worlds.new("kiro:neutral-world")
    scene.world = world
    world.use_nodes = True
    background = world.node_tree.nodes.get("Background")
    if background:
        background.inputs["Color"].default_value = (0.055, 0.055, 0.055, 1.0)
        background.inputs["Strength"].default_value = 0.35
    if hasattr(scene, "view_settings"):
        try:
            scene.view_settings.look = "Medium High Contrast"
        except TypeError:
            pass


def _write_inventory(output_dir, contract, plan, objects):
    """Write complete contract authority plus actual/converted UPBGE scene values."""
    path = output_dir / "scene_inventory.json"
    if path.exists():
        raise FileExistsError(path)
    plan_openings = {item["stable_id"]: item for item in plan["opening_gaps"]}
    plan_objects = {item["stable_id"]: item for item in objects}

    compiled_objects = []
    for item in contract["instances"]:
        actual = dict(plan_objects[item["id"]])
        actual.update({
            "name": item["name"], "category": item["category"], "mount": item["mount"],
            "fixed": item["fixed"], "clearance_m": item["clearance_m"],
            "physics_intent_id": item["physics_intent_id"],
            "primitive_shape": item.get("primitive_shape"),
            "asset_registry_id": item.get("asset_registry_id"),
            "description": item.get("description", ""),
            "relations": item.get("relations", []),
        })
        compiled_objects.append(actual)

    openings = []
    for item in contract["openings"]:
        converted = dict(plan_openings[item["id"]])
        converted.update({
            "room_id": item["room_id"], "offset_m": item["offset_m"],
            "width_m": item["width_m"], "height_m": item["height_m"],
            "physics_intent_id": item.get("physics_intent_id"),
        })
        openings.append(converted)

    materials = [{
        "stable_id": item["id"], "base_color": item["base_color"],
        "metallic": item["metallic"], "roughness": item["roughness"],
        "emission_color": item.get("emission_color"),
        "emission_strength": item["emission_strength"],
    } for item in contract["materials"]]
    plan_lights = {item["stable_id"]: item for item in plan["lights"]}
    lights = []
    for item in contract["lights"]:
        converted = dict(plan_lights[item["id"]])
        converted.update({
            "light_type": item["light_type"], "engine_light_type": converted["light_type"],
            "color": item["color"], "color_temperature_k": item["color_temperature_k"],
        })
        lights.append(converted)

    camera = dict(plan["camera"])
    camera.update({
        "source_schema_version": contract["camera"]["source_schema_version"],
        "projection": contract["camera"]["projection"],
    })
    interactions = [{
        "stable_id": item["id"], "kind": item["kind"],
        "subject_id": item["subject_id"], "target_id": item.get("target_id"),
        "parameters": item.get("parameters", {}),
    } for item in contract["interactions"]]
    room = contract["room"]
    inventory = {
        "schema_version": "upbge-scene-inventory/v1",
        "world_contract_hash": plan["world_contract_hash"],
        "coordinate_system": "right-handed-x-right-y-depth-z-up",
        "source_coordinate_system": contract["coordinate_system"],
        "coordinate_mapping": plan["coordinate_mapping"],
        "length_unit": contract["length_unit"], "angle_unit": contract["angle_unit"],
        "room": {
            "stable_id": room["id"],
            "dimensions_upbge": [
                room["dimensions"]["width_m"], room["dimensions"]["depth_m"],
                room["dimensions"]["height_m"],
            ],
            "floor_material_id": room["floor_material_id"],
            "wall_material_id": room["wall_material_id"],
            "ceiling_material_id": room["ceiling_material_id"],
        },
        "objects": sorted(compiled_objects, key=lambda value: value["stable_id"]),
        "openings": sorted(openings, key=lambda value: value["stable_id"]),
        "relationships": plan["relationships"], "camera": camera,
        "lights": sorted(lights, key=lambda value: value["stable_id"]),
        "materials": sorted(materials, key=lambda value: value["stable_id"]),
        "physics": sorted(plan["physics"], key=lambda value: value["stable_id"]),
        "gravity_upbge": plan["gravity_upbge"],
        "interactions": sorted(interactions, key=lambda value: value["stable_id"]),
        "outputs": plan["outputs"],
        "expected_inventory_ids": plan["expected_inventory_ids"],
    }
    with path.open("x", encoding="utf-8") as handle:
        json.dump(inventory, handle, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _add_logic_module(bpy, module_name, source):
    text_name = module_name + ".py"
    existing = bpy.data.texts.get(text_name)
    if existing:
        bpy.data.texts.remove(existing)
    text = bpy.data.texts.new(text_name)
    text.write(source)


def _attach_logic(bpy, obj, module_name):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.logic.sensor_add(type="ALWAYS", object=obj.name)
    sensor = obj.game.sensors[-1]
    sensor.use_pulse_true_level = True
    bpy.ops.logic.controller_add(type="PYTHON", object=obj.name)
    controller = obj.game.controllers[-1]
    controller.mode = "MODULE"
    controller.module = module_name + ".main"
    sensor.link(controller)


def _configure_runtime(bpy, plan, object_by_id, camera_obj):
    runtime = plan.get("runtime")
    if not runtime:
        raise ValueError("runtime output requested without runtime plan")
    source_by_template = {}
    for template_id, _component_class, source in runtime["template_sources"]:
        module_name = "kiro_" + template_id.replace(".", "_")
        _add_logic_module(bpy, module_name, source)
        source_by_template[template_id] = module_name
    bpy.ops.mesh.primitive_cube_add(size=1.0)
    player = bpy.context.object
    player.dimensions = (0.7, 0.7, 1.8)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    player.hide_render = True
    player.name = "runtime:player"
    player.location = tuple(plan["camera"]["position_upbge"])
    player["kiro_stable_id"] = "runtime:player"
    player["kiro_role"] = "runtime_player"
    if not getattr(player, "game", None):
        raise RuntimeError("verified UPBGE build exposes no game API")
    player.game.physics_type = "CHARACTER"
    player.game.use_collision_bounds = True
    player.game.collision_bounds_type = "CAPSULE"
    player.game.mass = 80.0
    player["kiro_gravity"] = abs(runtime["gravity_upbge"][2])
    _attach_logic(bpy, player, source_by_template[runtime["player_template_id"]])
    camera_obj.parent = player
    camera_obj.matrix_parent_inverse = player.matrix_world.inverted()
    openings = {item["stable_id"]: item for item in plan["opening_gaps"]}
    grab_bindings = [item for item in runtime["interactions"] if item["kind"] == "grab"]
    if grab_bindings:
        grab_rules = {
            item["subject_id"]: dict(item["parameters"])
            for item in grab_bindings
        }
        player["kiro_grab_rules_json"] = json.dumps(grab_rules, sort_keys=True, separators=(",", ":"))
        player["kiro_max_distance_m"] = max(
            rule["max_distance_m"] for rule in grab_rules.values()
        )
        _attach_logic(bpy, player, source_by_template[grab_bindings[0]["template_id"]])
    for binding in runtime["interactions"]:
        subject = object_by_id.get(binding["subject_id"])
        if binding["kind"] == "door" and subject is None:
            gap = openings.get(binding["subject_id"])
            if not gap:
                raise ValueError("door interaction has no subject geometry")
            door_spec = {
                "stable_id": binding["subject_id"], "role": "runtime_door", "shape": "box",
                "position_upbge": gap["position_upbge"], "rotation_upbge_deg": (0, 0, 0),
                "dimensions_upbge": gap["dimensions_upbge"], "material_id": "", "metadata": [],
            }
            subject = _add_primitive(bpy, door_spec, {})
            physics_spec = next(
                (item for item in plan["physics"] if item["subject_id"] == binding["subject_id"]),
                None,
            )
            if physics_spec is None:
                raise ValueError("door interaction requires explicit physics intent")
            _configure_physics(subject, physics_spec)
        if binding["kind"] == "door":
            for key, value in binding["parameters"]:
                subject["kiro_" + key] = value
            _attach_logic(bpy, subject, source_by_template[binding["template_id"]])
    return player


def _safe_output(output_dir, filename):
    path = (output_dir / filename).resolve()
    if not _inside(path, output_dir):
        raise ValueError("output path traversal rejected")
    return path


def main():
    args = _arguments()
    contract, plan, output_dir = _validate_inputs(args)
    import bpy
    _clear_scene(bpy)
    _configure_scene(bpy, contract, plan)
    materials = {item["stable_id"]: _material(bpy, item) for item in plan["materials"]}
    object_by_id = {}
    inventory_objects = []
    input_root = Path(args.plan).resolve(strict=True).parent
    for spec in plan["room_geometry"] + plan["instances"]:
        if spec.get("geometry_strategy") == "asset":
            obj = _add_asset(bpy, spec, materials, input_root)
        else:
            obj = _add_primitive(bpy, spec, materials)
        object_by_id[spec["stable_id"]] = obj
        inventory_objects.append({
            "stable_id": spec["stable_id"], "role": spec["role"],
            "geometry_strategy": spec.get("geometry_strategy", "primitive"),
            "position_upbge": list(obj.location),
            "rotation_upbge_deg": [math.degrees(value) for value in obj.rotation_euler],
            "scale_upbge": list(obj.scale),
            "dimensions_upbge": spec["dimensions_upbge"],
            "compiled_dimensions_upbge": list(obj.dimensions),
            "material_id": spec["material_id"],
            "metadata": spec.get("metadata", []),
        })
    for physics in plan["physics"]:
        subject = object_by_id.get(physics["subject_id"])
        if subject is not None:
            _configure_physics(subject, physics)
    camera_obj = _camera(bpy, plan["camera"])
    for opening_spec in plan["opening_gaps"]:
        _opening_marker(bpy, opening_spec)
    for light_spec in plan["lights"]:
        _light(bpy, light_spec)
    _write_inventory(output_dir, contract, plan, inventory_objects)
    scene = bpy.context.scene
    requested = {role: filename for role, filename in plan["outputs"]}
    if args.render == "1":
        scene.render.filepath = str(_safe_output(output_dir, requested["render"]))
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
    if args.glb == "1":
        bpy.ops.export_scene.gltf(
            filepath=str(_safe_output(output_dir, requested["glb"])),
            export_format="GLB", export_extras=True, export_cameras=True, export_lights=True,
        )
    if args.blend == "1":
        bpy.ops.wm.save_as_mainfile(filepath=str(_safe_output(output_dir, requested["blend"])))
    if args.runtime == "1":
        _configure_runtime(bpy, plan, object_by_id, camera_obj)
        bpy.ops.wm.save_as_mainfile(
            filepath=str(_safe_output(output_dir, requested["runtime_candidate"]))
        )


if __name__ == "__main__":
    main()
