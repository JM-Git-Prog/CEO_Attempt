"""
Mock LLM responses for development and demo mode.
Produces a complete, realistic 1950s diner scene when no live LLM is available.
"""

from __future__ import annotations

import json

MOCK_SCENE_CONCEPT = {
    "era": "1950s",
    "mood": "warm and nostalgic, rainy evening atmosphere",
    "palette": "chrome silver, red vinyl, cream tile, warm amber light, cool blue-gray from outside",
    "architecture_notes": "Cream ceramic tile wainscoting on lower walls, painted plaster upper walls in soft cream. Black and white checkered linoleum floor. Pressed tin ceiling tiles painted cream. Chrome trim throughout.",
    "key_objects": [
        "formica counter with chrome edge trim",
        "chrome diner stool with red vinyl seat",
        "chrome diner stool with red vinyl seat",
        "chrome diner stool with red vinyl seat",
        "chrome diner stool with red vinyl seat",
        "industrial pendant lamp",
        "pie display case with glass doors",
        "chrome napkin dispenser on counter",
        "coffee mug",
    ],
    "lighting_notes": "Primary: warm industrial pendant lamp over counter (~3000K). Secondary: cool blue-gray ambient light from rain-streaked storefront window. Strong warm/cool contrast. Deep shadows in corners.",
    "image_prompt": "Interior photograph of a 1950s American diner counter at evening. Four chrome stools with red vinyl seats line a formica counter with chrome edge trim. A single industrial pendant lamp hangs low over the counter, casting warm amber light. Through the large storefront window, rain streaks the glass and cool blue-gray evening light filters in. Checkered black and white linoleum floor, cream tile wainscoting, pressed tin ceiling. A glass pie case sits at one end. Photorealistic, moody, cinematic lighting, shot on 35mm film.",
}

MOCK_FLOOR_PLAN = {
    "name": "1950s American Diner",
    "room": {"width": 6.0, "depth": 4.0, "height": 2.8},
    "items": [
        {
            "id": "counter_1", "name": "Formica Counter", "category": "furniture",
            "x": 0.0, "z": 1.35, "width": 4.2, "depth": 0.8, "height": 1.2,
            "elevation": 0.0, "rotation_deg": 0.0, "fixed": True,
            "clearance_m": 0.5, "description": "Chrome-trimmed pale mint-green counter",
        },
        *[
            {
                "id": f"stool_{index}", "name": "Red Vinyl Chrome Swivel Stool",
                "category": "furniture", "x": x, "z": 0.3, "width": 0.6,
                "depth": 0.6, "height": 1.0, "elevation": 0.0,
                "rotation_deg": 0.0, "fixed": False, "clearance_m": 0.2,
                "description": "Individual diner stool",
            }
            for index, x in enumerate((-1.275, -0.425, 0.425, 1.275), 1)
        ],
        *[
            {
                "id": f"light_{index}", "name": "Polished Chrome Pendant Light",
                "category": "fixture", "x": x, "z": 1.35, "width": 0.3,
                "depth": 0.3, "height": 0.5, "elevation": 2.3,
                "rotation_deg": 0.0, "fixed": True, "clearance_m": 0.1,
                "description": "Individual pendant above counter",
            }
            for index, x in enumerate((-0.65, 0.0, 0.65), 1)
        ],
    ],
    "openings": [
        {"id": "opening_1", "kind": "door", "wall": "west", "offset": 1.35,
         "width": 0.9, "height": 2.0, "sill_height": 0.0},
        {"id": "opening_2", "kind": "window", "wall": "south", "offset": 0.0,
         "width": 3.6, "height": 2.5, "sill_height": 0.0},
    ],
    "camera": {"x": 2.55, "y": 1.6, "z": -1.55, "target_x": 0.0,
               "target_y": 1.2, "target_z": 1.35, "fov_deg": 55.0},
    "circulation_notes": ["Clear circulation aisle behind the stools."],
    "design_notes": ["Preserve exact counter, stool, pendant, door, and window counts."],
}

MOCK_SCENE_GRAPH = {
    "name": "fifties_diner_counter",
    "description": "A moody 1950s diner counter scene with warm pendant lighting and rainy evening atmosphere",
    "room": {
        "width": 7.0,
        "depth": 5.0,
        "height": 3.2,
        "floor_material": {"base_color": "#2a2a2a", "metallic": 0.1, "roughness": 0.4},
        "wall_material": {"base_color": "#f5f0e8", "metallic": 0.0, "roughness": 0.85},
        "ceiling_material": {"base_color": "#ede8dc", "metallic": 0.2, "roughness": 0.6},
    },
    "objects": [
        {
            "id": "counter_01",
            "name": "Diner Counter",
            "object_type": "furniture",
            "position": {"x": 0.0, "y": 0.0, "z": -0.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 4.5, "y": 1.05, "z": 0.65},
            "physics": {"body_type": "static", "mass_kg": 200.0, "friction": 0.6, "restitution": 0.05, "can_topple": False},
            "material": {"base_color": "#d4c5a9", "metallic": 0.3, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "box",
            "description": "Formica countertop with chrome edge trim",
        },
        {
            "id": "stool_01",
            "name": "Diner Stool 1",
            "object_type": "furniture",
            "position": {"x": -1.2, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": 10.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "stool_02",
            "name": "Diner Stool 2",
            "object_type": "furniture",
            "position": {"x": -0.4, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": -5.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "stool_03",
            "name": "Diner Stool 3",
            "object_type": "furniture",
            "position": {"x": 0.4, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "stool_04",
            "name": "Diner Stool 4",
            "object_type": "furniture",
            "position": {"x": 1.2, "y": 0.0, "z": 0.5},
            "rotation": {"x": 0.0, "y": 15.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.4, "y": 0.75, "z": 0.4},
            "physics": {"body_type": "rigid", "mass_kg": 8.0, "friction": 0.7, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0392b", "metallic": 0.7, "roughness": 0.3},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "Chrome pedestal diner stool with red vinyl cushion seat",
        },
        {
            "id": "pie_case_01",
            "name": "Pie Display Case",
            "object_type": "fixture",
            "position": {"x": 2.8, "y": 0.0, "z": -0.5},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.7, "y": 1.2, "z": 0.5},
            "physics": {"body_type": "static", "mass_kg": 50.0, "friction": 0.5, "restitution": 0.05, "can_topple": False},
            "material": {"base_color": "#e8e8e8", "metallic": 0.4, "roughness": 0.2},
            "mesh_type": "primitive",
            "primitive_shape": "box",
            "description": "Glass and chrome pie display case",
        },
        {
            "id": "mug_01",
            "name": "Coffee Mug",
            "object_type": "decor",
            "position": {"x": -0.8, "y": 1.05, "z": -0.4},
            "rotation": {"x": 0.0, "y": 35.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.09, "y": 0.1, "z": 0.09},
            "physics": {"body_type": "rigid", "mass_kg": 0.35, "friction": 0.6, "restitution": 0.05, "can_topple": True},
            "material": {"base_color": "#f0f0f0", "metallic": 0.1, "roughness": 0.7},
            "mesh_type": "primitive",
            "primitive_shape": "cylinder",
            "description": "White ceramic diner coffee mug",
        },
        {
            "id": "napkin_dispenser_01",
            "name": "Napkin Dispenser",
            "object_type": "decor",
            "position": {"x": 0.6, "y": 1.05, "z": -0.6},
            "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
            "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
            "dimensions": {"x": 0.14, "y": 0.15, "z": 0.08},
            "physics": {"body_type": "rigid", "mass_kg": 1.2, "friction": 0.5, "restitution": 0.1, "can_topple": True},
            "material": {"base_color": "#c0c0c0", "metallic": 0.9, "roughness": 0.15},
            "mesh_type": "primitive",
            "primitive_shape": "box",
            "description": "Chrome napkin dispenser, rectangular, reflective",
        },
    ],
    "lights": [
        {
            "id": "pendant_01",
            "name": "Pendant Lamp",
            "light_type": "point",
            "position": {"x": 0.0, "y": 2.6, "z": 0.0},
            "direction": {"x": 0.0, "y": -1.0, "z": 0.0},
            "color": "#ffb347",
            "color_temperature_k": 2800,
            "intensity": 3.5,
            "range_meters": 5.0,
            "spot_angle_deg": 45.0,
            "cast_shadows": True,
        },
        {
            "id": "window_ambient",
            "name": "Window Ambient Light",
            "light_type": "directional",
            "position": {"x": 0.0, "y": 2.0, "z": 2.5},
            "direction": {"x": 0.0, "y": -0.3, "z": -0.7},
            "color": "#7ba3c4",
            "color_temperature_k": 7500,
            "intensity": 0.8,
            "range_meters": 10.0,
            "spot_angle_deg": 90.0,
            "cast_shadows": True,
        },
    ],
    "doors": [
        {
            "id": "kitchen_door",
            "position": {"x": -3.2, "y": 0.0, "z": -1.0},
            "wall": "west",
            "width": 0.9,
            "height": 2.1,
            "swing_direction": "inward",
        }
    ],
    "windows": [
        {
            "id": "storefront_window",
            "position": {"x": 0.0, "y": 0.0, "z": 2.5},
            "wall": "north",
            "width": 3.0,
            "height": 2.0,
            "sill_height": 0.3,
        }
    ],
    "ambient_color": "#1a1a2e",
    "ambient_energy": 0.15,
}


def _mock_floor_plan_v11() -> dict:
    """Return deterministic typed Plan intent without changing retained mock bytes."""
    payload = json.loads(json.dumps(MOCK_FLOOR_PLAN))
    payload["schema_version"] = "floor-plan/v11"
    for item in payload["items"]:
        item["mount"] = "ceiling" if item["id"].startswith("light_") else "floor"
    payload["relationships"] = [
        {
            "subject_id": "counter_1", "kind": "against_wall", "wall": "north",
            "parameters_m": {"along_offset_m": 0.0, "wall_gap_m": 0.05},
        },
        *[
            {
                "subject_id": f"stool_{index}", "kind": "south_of",
                "target_id": "counter_1", "parameters_m": {
                    "gap_m": 0.2, "distribution_index": float(index - 1),
                    "distribution_count": 4.0, "distribution_span_m": 3.0,
                },
            }
            for index in range(1, 5)
        ],
        *[
            {
                "subject_id": f"light_{index}", "kind": "above",
                "target_id": "counter_1", "parameters_m": {
                    "distribution_index": float(index - 1),
                    "distribution_count": 3.0, "distribution_span_m": 1.3,
                },
            }
            for index in range(1, 4)
        ],
    ]
    payload["opening_intents"] = [
        {
            "opening_id": "opening_1", "wall": "west",
            "placement": "near_corner", "corner": "northwest", "margin_m": 0.1,
        },
        {
            "opening_id": "opening_2", "wall": "south",
            "placement": "centered", "margin_m": 0.1,
        },
    ]
    payload["camera_intent"] = {
        "corner": "southeast", "target_id": "counter_1", "inset_m": 0.45,
        "eye_height_m": 1.6, "target_height_m": 1.2, "fov_deg": 55.0,
    }
    return payload


def mock_generate(system: str, user: str) -> str:
    """Produce mock responses based on what the system prompt is asking for."""
    lower = system.lower()
    if "v11 explicit-intent extension" in lower:
        return json.dumps(_mock_floor_plan_v11(), indent=2)
    if "llm director" in lower and "semantic world edits" in lower:
        return json.dumps({"commands": []})
    if "space planner" in lower:
        return json.dumps(MOCK_FLOOR_PLAN, indent=2)
    if "spatial planner" in lower or ("scene graph" in lower and "room" in lower):
        return json.dumps(MOCK_SCENE_GRAPH, indent=2)
    elif "creative director" in lower or ("scene concept" in lower and "image_prompt" in lower):
        return json.dumps(MOCK_SCENE_CONCEPT, indent=2)
    elif "image_prompt" in lower or "regeneration" in lower:
        return MOCK_SCENE_CONCEPT["image_prompt"]
    else:
        return json.dumps(MOCK_SCENE_CONCEPT, indent=2)
