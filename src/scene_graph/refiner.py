"""Canon-versus-render visual refinement using plan-safe appearance patches."""

from __future__ import annotations

import json
from pathlib import Path

from src.floor_plan.models import FloorPlan
from src.models import MaterialProps, SceneConcept, SceneGraph
from src.orchestrator.llm import generate_vision_json

REFINER_SYSTEM = """You are the visual quality director for an editable 3D interior.
Image 1 is the approved photoreal canon. Image 2 is the current 3D render. Compare them
and return a SMALL appearance-only JSON patch. Geometry is immutable: never propose room,
position, rotation, scale, dimension, opening, object count, or camera changes.
Return exactly: {"summary":string,"similarity_score":number 0..100,"changes":[string],
"object_materials":[{"id":string,"base_color":"#RRGGBB","metallic":0..1,
"roughness":0..1,"emission_color":"#RRGGBB or null","emission_strength":0..10}],
"room_materials":{"floor":material or null,"wall":material or null,"ceiling":material or null},
"lights":[{"id":string,"color":"#RRGGBB","intensity":number 0..20}],
"ambient_color":"#RRGGBB","ambient_energy":number 0..2}. Use only supplied IDs."""


async def refine_scene_graph(
    scene: SceneGraph,
    concept: SceneConcept,
    canon_path: Path,
    render_path: Path,
    feedback: str,
    floor_plan: FloorPlan | None = None,
) -> tuple[SceneGraph, dict]:
    manifest = {
        "style": {"era": concept.era, "mood": concept.mood, "palette": concept.palette},
        "room_materials": {
            "floor": scene.room.floor_material.model_dump(mode="json"),
            "wall": scene.room.wall_material.model_dump(mode="json"),
            "ceiling": scene.room.ceiling_material.model_dump(mode="json"),
        },
        "objects": [{"id": item.id, "name": item.name, "material": item.material.model_dump(mode="json")} for item in scene.objects],
        "lights": [{"id": item.id, "color": item.color, "intensity": item.intensity} for item in scene.lights],
        "ambient": {"color": scene.ambient_color, "energy": scene.ambient_energy},
        "plan": {"name": floor_plan.name, "room": floor_plan.room.model_dump()} if floor_plan else None,
    }
    prompt = f"User feedback: {feedback}\nCurrent visual manifest: {json.dumps(manifest, separators=(',', ':'))}\nReturn only the compact appearance patch."
    patch = await generate_vision_json(REFINER_SYSTEM, prompt, [str(canon_path), str(render_path)])
    revised = scene.model_copy(deep=True)
    _apply_patch(revised, patch)
    report = {
        "summary": str(patch.get("summary", "World appearance revised from visual feedback")),
        "similarity_score": _clamp(_number(patch.get("similarity_score"), 0), 0, 100),
        "changes": [str(item) for item in patch.get("changes", [])][:20],
    }
    return revised, report


def _apply_patch(scene: SceneGraph, patch: dict) -> None:
    objects = {item.id: item for item in scene.objects}
    for authored in patch.get("object_materials", [])[:64]:
        target = objects.get(str(authored.get("id", "")))
        if target:
            target.material = _material_patch(target.material, authored)
    room_targets = {
        "floor": scene.room.floor_material,
        "wall": scene.room.wall_material,
        "ceiling": scene.room.ceiling_material,
    }
    for key, authored in (patch.get("room_materials") or {}).items():
        if key in room_targets and isinstance(authored, dict):
            updated = _material_patch(room_targets[key], authored)
            if key == "floor":
                scene.room.floor_material = updated
            elif key == "wall":
                scene.room.wall_material = updated
            else:
                scene.room.ceiling_material = updated
    lights = {item.id: item for item in scene.lights}
    for authored in patch.get("lights", [])[:16]:
        target = lights.get(str(authored.get("id", "")))
        if target:
            target.color = _hex(authored.get("color"), target.color)
            target.intensity = _clamp(_number(authored.get("intensity"), target.intensity), 0, 20)
    scene.ambient_color = _hex(patch.get("ambient_color"), scene.ambient_color)
    scene.ambient_energy = _clamp(_number(patch.get("ambient_energy"), scene.ambient_energy), 0, 2)


def _material_patch(original: MaterialProps, authored: dict) -> MaterialProps:
    return MaterialProps(
        base_color=_hex(authored.get("base_color"), original.base_color),
        metallic=_clamp(_number(authored.get("metallic"), original.metallic), 0, 1),
        roughness=_clamp(_number(authored.get("roughness"), original.roughness), 0, 1),
        emission_color=_hex(authored.get("emission_color"), original.emission_color) if authored.get("emission_color") else original.emission_color,
        emission_strength=_clamp(_number(authored.get("emission_strength"), original.emission_strength), 0, 10),
    )


def _hex(value, fallback: str | None) -> str | None:
    text = str(value or "")
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text
        except ValueError:
            pass
    return fallback


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
