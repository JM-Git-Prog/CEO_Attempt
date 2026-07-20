"""
Scene Graph Builder - Takes a SceneConcept and produces a complete SceneGraph.
"""

from __future__ import annotations

import sys

from src.models import (
    DoorSpec, MaterialProps, PhysicsBody, PhysicsProps,
    RoomShell, SceneGraph, SceneLight, SceneObject, Vec3, WindowSpec, SceneConcept,
)
from src.orchestrator.llm import generate_json
from src.orchestrator.prompts import SCENE_GRAPH_SYSTEM


async def build_scene_graph(concept: SceneConcept) -> SceneGraph:
    """Generate a complete scene graph from the scene concept."""
    user_prompt = f"""Build a scene graph for this space:

Era: {concept.era}
Mood: {concept.mood}
Palette: {concept.palette}
Architecture: {concept.architecture_notes}
Objects: {', '.join(concept.key_objects)}
Lighting: {concept.lighting_notes}

Place every object. Assign realistic physics properties. Configure lighting to match the mood."""

    data = await generate_json(system=SCENE_GRAPH_SYSTEM, user=user_prompt)
    scene = _parse_scene_graph(data)
    _validate_scene(scene)
    return scene


def _parse_scene_graph(data: dict) -> SceneGraph:
    """Parse raw JSON dict into a validated SceneGraph model."""
    room = RoomShell(
        width=data["room"]["width"],
        depth=data["room"]["depth"],
        height=data["room"]["height"],
        floor_material=MaterialProps(**data["room"]["floor_material"]),
        wall_material=MaterialProps(**data["room"]["wall_material"]),
        ceiling_material=MaterialProps(**data["room"]["ceiling_material"]),
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
