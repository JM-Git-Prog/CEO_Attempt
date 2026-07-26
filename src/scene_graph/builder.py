"""
Scene Graph Builder - Takes a SceneConcept and produces a complete SceneGraph.
"""

from __future__ import annotations

import sys

from src.floor_plan.models import FloorPlan
from src.models import (
    DoorSpec, MaterialProps, PhysicsBody, PhysicsProps,
    RoomShell, SceneGraph, SceneLight, SceneObject, Vec3, WindowSpec, SceneConcept,
)
from src.orchestrator.llm import generate_json
from src.orchestrator.prompts import SCENE_GRAPH_SYSTEM


async def build_scene_graph(
    concept: SceneConcept,
    floor_plan: FloorPlan | None = None,
    *,
    timeout_seconds: float | None = None,
    enforce_plan_lights: bool = False,
) -> SceneGraph:
    """Generate appearance/physics while preserving approved plan geometry."""
    plan_context = floor_plan.model_dump_json() if floor_plan else "No approved plan supplied"
    user_prompt = f"""Build a scene graph for this space:

Era: {concept.era}
Mood: {concept.mood}
Palette: {concept.palette}
Architecture: {concept.architecture_notes}
Objects: {', '.join(concept.key_objects)}
Lighting: {concept.lighting_notes}

APPROVED FLOOR PLAN (authoritative): {plan_context}
Use every floor-plan item ID exactly. Room dimensions, item X/Z positions, footprints,
heights, rotations, doors, and windows must not change. Add materials, physics, and lighting."""

    data = await generate_json(
        system=SCENE_GRAPH_SYSTEM,
        user=user_prompt,
        timeout_seconds=timeout_seconds,
    )
    scene = _parse_scene_graph(data)
    if floor_plan:
        _apply_plan_constraints(scene, floor_plan, enforce_plan_lights=enforce_plan_lights)
    _validate_scene(scene)
    return scene


def _parse_scene_graph(data: dict) -> SceneGraph:
    """Parse raw JSON dict into a validated SceneGraph model."""
    room_data = data.get("room", {})
    _default_material = {"base_color": "#808080", "metallic": 0.0, "roughness": 0.8}
    room = RoomShell(
        width=room_data.get("width", 5.0),
        depth=room_data.get("depth", 4.0),
        height=room_data.get("height", 3.0),
        floor_material=MaterialProps(**room_data.get("floor_material", _default_material)),
        wall_material=MaterialProps(**room_data.get("wall_material", _default_material)),
        ceiling_material=MaterialProps(**room_data.get("ceiling_material", _default_material)),
    )

    objects = []
    for obj_data in data.get("objects", []):
        obj = SceneObject(
            id=obj_data["id"],
            name=obj_data["name"],
            object_type=obj_data["object_type"],
            position=Vec3(**obj_data["position"]),
            rotation=Vec3(**obj_data.get("rotation", {"x": 0, "y": 0, "z": 0})),
            scale=Vec3(**obj_data.get("scale", {"x": 1, "y": 1, "z": 1})),
            dimensions=Vec3(**obj_data["dimensions"]),
            physics=PhysicsProps(
                body_type=PhysicsBody(obj_data["physics"]["body_type"]),
                mass_kg=obj_data["physics"]["mass_kg"],
                friction=obj_data["physics"].get("friction", 0.5),
                restitution=obj_data["physics"].get("restitution", 0.1),
                can_topple=obj_data["physics"].get("can_topple", False),
            ),
            material=MaterialProps(**obj_data["material"]),
            mesh_type=obj_data.get("mesh_type", "primitive"),
            primitive_shape=obj_data.get("primitive_shape", "box"),
            description=obj_data.get("description", ""),
        )
        objects.append(obj)

    lights = []
    for ld in data.get("lights", []):
        lights.append(SceneLight(
            id=ld["id"], name=ld["name"], light_type=ld["light_type"],
            position=Vec3(**ld["position"]),
            direction=Vec3(**ld.get("direction", {"x": 0, "y": -1, "z": 0})),
            color=ld["color"],
            color_temperature_k=ld.get("color_temperature_k", 4000),
            intensity=ld.get("intensity", 1.0),
            range_meters=ld.get("range_meters", 5.0),
            spot_angle_deg=ld.get("spot_angle_deg", 45.0),
            cast_shadows=ld.get("cast_shadows", True),
        ))

    doors = []
    for dd in data.get("doors", []):
        doors.append(DoorSpec(
            id=dd["id"], position=Vec3(**dd["position"]), wall=dd["wall"],
            width=dd.get("width", 0.9), height=dd.get("height", 2.1),
            swing_direction=dd.get("swing_direction", "inward"),
        ))

    windows = []
    for wd in data.get("windows", []):
        windows.append(WindowSpec(
            id=wd["id"], position=Vec3(**wd["position"]), wall=wd["wall"],
            width=wd.get("width", 1.2), height=wd.get("height", 1.0),
            sill_height=wd.get("sill_height", 0.9),
        ))

    return SceneGraph(
        name=data.get("name", "unnamed_scene"),
        description=data.get("description", ""),
        room=room, objects=objects, lights=lights, doors=doors, windows=windows,
        ambient_color=data.get("ambient_color", "#1a1a2e"),
        ambient_energy=data.get("ambient_energy", 0.3),
    )


def _validate_scene(scene: SceneGraph) -> None:
    """Validate spatial coherence."""
    half_w = scene.room.width / 2
    half_d = scene.room.depth / 2
    errors = []

    for obj in scene.objects:
        if abs(obj.position.x) > half_w + 0.5:
            errors.append(f"{obj.id}: x outside room")
        if abs(obj.position.z) > half_d + 0.5:
            errors.append(f"{obj.id}: z outside room")
        if obj.position.y < -0.1:
            errors.append(f"{obj.id}: below floor")

    if errors:
        print(f"[SceneGraph Validation] {len(errors)} warnings:", file=sys.stderr)
        for e in errors[:5]:
            print(f"  - {e}", file=sys.stderr)


def _apply_plan_constraints(
    scene: SceneGraph, plan: FloorPlan, *, enforce_plan_lights: bool = False
) -> None:
    """Make approved plan geometry authoritative over LLM-authored scene details."""
    scene.room.width = plan.room.width
    scene.room.depth = plan.room.depth
    scene.room.height = plan.room.height
    authored = {obj.id: obj for obj in scene.objects}
    constrained: list[SceneObject] = []
    palette = {
        "furniture": "#9b7048",
        "fixture": "#6b8582",
        "architectural": "#81769a",
        "decor": "#6f7e94",
    }
    for item in plan.items:
        obj = authored.get(item.id)
        if obj is None:
            obj = SceneObject(
                id=item.id,
                name=item.name,
                object_type=item.category,
                position=Vec3(),
                dimensions=Vec3(x=item.width, y=item.height, z=item.depth),
                physics=PhysicsProps(
                    body_type=PhysicsBody.STATIC if item.fixed else PhysicsBody.RIGID,
                    mass_kg=40.0 if item.fixed else 8.0,
                    can_topple=not item.fixed,
                ),
                material=MaterialProps(base_color=palette[item.category]),
                mesh_type="generated",
                primitive_shape="box",
                description=item.description,
            )
        obj.name = item.name
        obj.object_type = item.category
        obj.position = Vec3(x=item.x, y=item.elevation, z=item.z)
        obj.rotation = Vec3(x=0.0, y=item.rotation_deg, z=0.0)
        obj.scale = Vec3(x=1.0, y=1.0, z=1.0)
        obj.dimensions = Vec3(x=item.width, y=item.height, z=item.depth)
        obj.description = item.description or obj.description
        if item.fixed:
            obj.physics.body_type = PhysicsBody.STATIC
        constrained.append(obj)
    scene.objects = constrained
    if enforce_plan_lights:
        light_items = [
            item for item in plan.items
            if item.category == "fixture"
            and any(token in f"{item.name} {item.description}".lower() for token in ("light", "lamp", "pendant"))
        ]
        scene.lights = [
            SceneLight(
                id=item.id,
                name=item.name,
                light_type="point",
                position=Vec3(x=item.x, y=item.elevation, z=item.z),
                direction=Vec3(x=0.0, y=-1.0, z=0.0),
                color="#ffb347",
                color_temperature_k=3000,
                intensity=2.5,
                range_meters=5.0,
                spot_angle_deg=45.0,
                cast_shadows=True,
            )
            for item in light_items
        ]
    scene.doors = []
    scene.windows = []
    half_w, half_d = plan.room.width / 2, plan.room.depth / 2
    for opening in plan.openings:
        if opening.wall == "north":
            position = Vec3(x=opening.offset, y=0, z=half_d)
        elif opening.wall == "south":
            position = Vec3(x=opening.offset, y=0, z=-half_d)
        elif opening.wall == "east":
            position = Vec3(x=half_w, y=0, z=opening.offset)
        else:
            position = Vec3(x=-half_w, y=0, z=opening.offset)
        if opening.kind == "door":
            scene.doors.append(DoorSpec(id=opening.id, position=position, wall=opening.wall, width=opening.width, height=opening.height))
        else:
            scene.windows.append(WindowSpec(id=opening.id, position=position, wall=opening.wall, width=opening.width, height=opening.height, sill_height=opening.sill_height))
