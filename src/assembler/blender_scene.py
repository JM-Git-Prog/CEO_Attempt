"""Blender scene assembly script.

Executed by Blender in headless mode:
  blender --background --python src/assembler/blender_scene.py -- <session_dir>

Reads session.json from the session directory and builds a complete .blend scene
with room geometry, furniture, materials, lights, camera, and physics.
Then renders a blockout PNG and exports glTF.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# Blender modules — only available when run inside Blender
import bpy
import bmesh
from mathutils import Vector, Matrix


def clear_scene():
    """Remove all default objects."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    # Remove orphaned data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


def create_material(name: str, color: tuple, roughness: float = 0.5, metallic: float = 0.0):
    """Create a simple PBR material."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def create_room(width: float, depth: float, height: float):
    """Create room shell (floor, walls, ceiling) as separate objects."""
    half_w, half_d = width / 2, depth / 2

    # Floor
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "Floor"
    floor.scale = (width, depth, 1)
    bpy.ops.object.transform_apply(scale=True)
    floor_mat = create_material("Floor_Material", (0.4, 0.35, 0.3), roughness=0.8)
    floor.data.materials.append(floor_mat)

    # Ceiling
    bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, height))
    ceiling = bpy.context.active_object
    ceiling.name = "Ceiling"
    ceiling.scale = (width, depth, 1)
    ceiling.rotation_euler = (math.pi, 0, 0)
    bpy.ops.object.transform_apply(scale=True, rotation=True)
    ceil_mat = create_material("Ceiling_Material", (0.9, 0.9, 0.88), roughness=0.9)
    ceiling.data.materials.append(ceil_mat)

    # Walls (4 planes)
    wall_mat = create_material("Wall_Material", (0.85, 0.82, 0.78), roughness=0.85)
    walls = [
        ("Wall_North", (0, half_d, height/2), (height, width, 1), (0, math.pi/2, 0)),
        ("Wall_South", (0, -half_d, height/2), (height, width, 1), (0, -math.pi/2, 0)),
        ("Wall_East", (half_w, 0, height/2), (height, depth, 1), (math.pi/2, 0, math.pi/2)),
        ("Wall_West", (-half_w, 0, height/2), (height, depth, 1), (-math.pi/2, 0, -math.pi/2)),
    ]
    for name, loc, scale, rot in walls:
        bpy.ops.mesh.primitive_plane_add(size=1, location=loc)
        wall = bpy.context.active_object
        wall.name = name
        wall.scale = scale
        wall.rotation_euler = rot
        bpy.ops.object.transform_apply(scale=True, rotation=True)
        wall.data.materials.append(wall_mat)

    return floor


def create_furniture_item(item: dict, room_height: float):
    """Create a furniture item as a mesh object with physics."""
    item_id = item["id"]
    name = item.get("name", item_id)
    mount = item.get("mount", "floor")
    x = item.get("x", 0)
    z_plan = item.get("z", 0)  # Plan Z maps to Blender Y
    width = item.get("width", 0.5)
    depth = item.get("depth", 0.5)
    height = item.get("height", 0.5)
    elevation = item.get("elevation", 0)
    rotation_deg = item.get("rotation_deg", 0)

    # Convert plan coordinates to Blender coordinates
    # Plan: X/Z with center at 0,0; Blender: X/Y with Z up
    bx = x
    by = z_plan
    bz = elevation + height / 2

    # Determine shape based on item type
    text = f"{item_id} {name}".lower()

    if "stool" in text or "chair" in text:
        # Cylinder for stools/chairs
        bpy.ops.mesh.primitive_cylinder_add(
            radius=min(width, depth) / 2,
            depth=height,
            location=(bx, by, bz)
        )
    elif "pendant" in text or "light" in text or "chandelier" in text or "lantern" in text:
        # Cone/sphere for lights
        bpy.ops.mesh.primitive_uv_sphere_add(
            radius=max(width, depth) / 2,
            location=(bx, by, bz)
        )
    elif "shelf" in text:
        # Thin box for shelves
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bx, by, bz))
        obj = bpy.context.active_object
        obj.scale = (width, depth, max(height, 0.05))
        bpy.ops.object.transform_apply(scale=True)
    else:
        # Default box
        bpy.ops.mesh.primitive_cube_add(size=1, location=(bx, by, bz))
        obj = bpy.context.active_object
        obj.scale = (width, depth, height)
        bpy.ops.object.transform_apply(scale=True)

    obj = bpy.context.active_object
    obj.name = name
    obj["item_id"] = item_id
    obj["category"] = item.get("category", "furniture")
    obj["mount"] = mount

    # Apply rotation
    if rotation_deg:
        obj.rotation_euler = (0, 0, math.radians(rotation_deg))

    # Material based on category
    category = item.get("category", "furniture")
    colors = {
        "furniture": (0.55, 0.4, 0.25),
        "fixture": (0.7, 0.7, 0.72),
        "architectural": (0.5, 0.45, 0.4),
        "decor": (0.6, 0.5, 0.45),
    }
    color = colors.get(category, (0.5, 0.5, 0.5))
    mat = create_material(f"{item_id}_Material", color, roughness=0.6)
    obj.data.materials.append(mat)

    # Physics
    if mount == "floor":
        obj.rigid_body = None  # Will set up in game properties
    
    return obj


def create_opening(opening: dict, room_width: float, room_depth: float, room_height: float):
    """Create a door or window opening."""
    kind = opening.get("kind", "door")
    wall = opening.get("wall", "north")
    offset = opening.get("offset", 0)
    width = opening.get("width", 0.9)
    height = opening.get("height", 2.1)
    sill = opening.get("sill_height", 0)

    half_w, half_d = room_width / 2, room_depth / 2

    # Position on wall
    if wall == "north":
        loc = (offset, half_d - 0.05, sill + height / 2)
        scale = (width, 0.1, height)
    elif wall == "south":
        loc = (offset, -half_d + 0.05, sill + height / 2)
        scale = (width, 0.1, height)
    elif wall == "east":
        loc = (half_w - 0.05, offset, sill + height / 2)
        scale = (0.1, width, height)
    else:
        loc = (-half_w + 0.05, offset, sill + height / 2)
        scale = (0.1, width, height)

    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.name = f"{kind.title()}_{opening.get('id', 'opening')}"
    obj.scale = scale
    bpy.ops.object.transform_apply(scale=True)

    # Material
    if kind == "door":
        mat = create_material(f"{obj.name}_Mat", (0.35, 0.25, 0.15), roughness=0.7)
    else:
        mat = create_material(f"{obj.name}_Mat", (0.7, 0.85, 0.95), roughness=0.1, metallic=0.0)
    obj.data.materials.append(mat)

    return obj


def setup_camera(camera_data: dict, room_height: float):
    """Set up the scene camera matching the plan's camera contract."""
    bpy.ops.object.camera_add(
        location=(camera_data["x"], camera_data["z"], camera_data.get("y", 1.6))
    )
    cam = bpy.context.active_object
    cam.name = "Canon_Camera"

    # Point at target
    target = Vector((
        camera_data.get("target_x", 0),
        camera_data.get("target_z", 0),
        camera_data.get("target_y", 1.2),
    ))
    direction = target - cam.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()

    # FOV
    fov_deg = camera_data.get("fov_deg", 55)
    cam.data.angle = math.radians(fov_deg)
    cam.data.clip_start = 0.05
    cam.data.clip_end = 100.0

    bpy.context.scene.camera = cam
    return cam


def setup_lighting(items: list, room_height: float):
    """Add scene lighting — ambient + point lights for each ceiling fixture."""
    # Ambient light (sun)
    bpy.ops.object.light_add(type='SUN', location=(0, 0, room_height + 2))
    sun = bpy.context.active_object
    sun.name = "Ambient_Sun"
    sun.data.energy = 0.3

    # Point lights for each ceiling fixture in the plan
    for item in items:
        if item.get("mount") == "ceiling":
            bpy.ops.object.light_add(
                type='POINT',
                location=(item["x"], item["z"], item.get("elevation", room_height - 0.3) + 0.1)
            )
            light = bpy.context.active_object
            light.name = f"Light_{item['id']}"
            light.data.energy = 50
            light.data.color = (1.0, 0.9, 0.7)  # Warm
            light.data.shadow_soft_size = 0.3


def render_blockout(output_path: str, width: int = 1024, height: int = 768):
    """Render the scene as a neutral blockout (gray materials, simple lighting)."""
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.filepath = output_path
    scene.render.image_settings.file_format = 'PNG'

    # Override all materials to gray for blockout
    override_mat = create_material("Blockout_Override", (0.6, 0.6, 0.6), roughness=0.8)
    # Actually, keep distinct materials but desaturate them for structure visibility

    bpy.ops.render.render(write_still=True)


def export_gltf(output_path: str):
    """Export the scene as glTF 2.0 for Godot/Three.js."""
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB',
        export_materials='EXPORT',
        export_cameras=True,
        export_lights=True,
    )


def main():
    """Main entry point — reads session JSON and builds the scene."""
    # Parse args after "--"
    argv = sys.argv
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
    else:
        args = []

    if not args:
        print("Usage: blender --background --python blender_scene.py -- <session_dir>")
        sys.exit(1)

    session_dir = Path(args[0])
    session_file = session_dir / "session.json"

    if not session_file.exists():
        print(f"Error: {session_file} not found")
        sys.exit(1)

    session = json.loads(session_file.read_text(encoding="utf-8"))
    plan = session.get("floor_plan")
    if not plan:
        print("Error: No floor_plan in session")
        sys.exit(1)

    room = plan["room"]
    items = plan.get("items", [])
    openings = plan.get("openings", [])
    camera = plan.get("camera", {"x": 2, "y": 1.6, "z": -1.5})

    print(f"Building scene: {room['width']}x{room['depth']}x{room['height']}m, "
          f"{len(items)} items, {len(openings)} openings")

    # Build
    clear_scene()
    create_room(room["width"], room["depth"], room["height"])

    for item in items:
        create_furniture_item(item, room["height"])

    for opening in openings:
        create_opening(opening, room["width"], room["depth"], room["height"])

    setup_camera(camera, room["height"])
    setup_lighting(items, room["height"])

    # Render blockout
    blockout_path = str(session_dir / "blockout_blender.png")
    render_blockout(blockout_path)
    print(f"Blockout rendered: {blockout_path}")

    # Save .blend
    blend_path = str(session_dir / "scene.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    print(f"Scene saved: {blend_path}")

    # Export glTF
    gltf_path = str(session_dir / "scene.glb")
    export_gltf(gltf_path)
    print(f"glTF exported: {gltf_path}")

    print("Done.")


if __name__ == "__main__":
    main()
