"""Generate a metric floor plan with the existing local orchestration LLM."""

from __future__ import annotations

import json
import os

from pydantic import ValidationError

from src.floor_plan.models import FloorPlan, FloorPlanV11, PlanValidationReport
from src.floor_plan.validator import normalize_floor_plan, validate_floor_plan
from src.models import SceneConcept
from src.orchestrator.llm import generate_json

V11_PLAN_MODEL = os.getenv("V11_PLAN_MODEL", "gpt-oss:20b")

PLAN_SYSTEM = """You are an expert interior space planner creating a practical, buildable floor plan.

DESIGN THINKING — apply these principles before placing anything:
1. ZONES: Identify functional zones (seating, work, circulation, display). Place primary furniture first, then support pieces relative to it.
2. WALLS FIRST: Large furniture belongs against walls. Only focal-point pieces (tables, islands) go in the center. Never cluster everything at 0,0.
3. CIRCULATION: Maintain at least 0.8m clear paths between the door and all zones. A person must walk from the door to any seat without squeezing past furniture.
4. RELATIONSHIPS: Chairs face tables. Stools line up along counters/bars. Pendant lights hang above the surface they illuminate. Side tables flank beds/sofas.
5. SPACING: Repeated items (stools, chairs, cabinets) distribute evenly along their parent surface with equal gaps. Never stack them on top of each other.
6. DOOR CLEARANCE: Nothing within 1.0m inward of a door. The door swing arc must be completely unobstructed.
7. WINDOW CLEARANCE: Keep furniture at least 0.3m from exterior window walls so light enters freely.
8. PROPORTIONS: Item dimensions must be realistic. A stool is ~0.4m wide. A pendant light is ~0.3m tall. An arcade cabinet is ~0.7m wide × 0.8m deep. A bed is ~2.0m × 1.6m.
9. CAMERA: Place the camera in a corner with a clear diagonal view across the room showing the maximum number of objects. Never place the camera behind or inside furniture.

COORDINATE SYSTEM:
- Room center is (0, 0). North is +Z, East is +X.
- x,z are the item's CENTER position in meters.
- width is the X-axis span, depth is the Z-axis span.
- elevation is bottom of the item (0 for floor items, room_height - item_height for ceiling items).
- rotation_deg rotates the item around its center (0 = front faces south).

RULES:
- Return one valid JSON object only. No commentary.
- One item per physical instance: four stools = stool_1, stool_2, stool_3, stool_4.
- Items = furniture, built-ins, freestanding fixtures only. Never put floor/wall/ceiling/door/window in items.
- Doors and windows go in "openings" only.
- Ceiling fixtures: set mount="ceiling", height = realistic hanging size (0.1-0.5m typical), elevation = room_height - height.
- fixed=true only for large built-in surfaces (counters, islands, built-in shelving). Everything else is fixed=false.

Schema: {"name":string,"room":{"width":number,"depth":number,"height":number},
"items":[{"id":string,"name":string,"category":"furniture|fixture|architectural|decor",
"mount":"floor|wall|ceiling",
"x":number,"z":number,"width":number,"depth":number,"height":number,"elevation":number,
"rotation_deg":number,"fixed":boolean,"clearance_m":number,"description":string}],
"openings":[{"id":string,"kind":"door|window","wall":"north|south|east|west",
"offset":number,"width":number,"height":number,"sill_height":number}],
"camera":{"x":number,"y":number,"z":number,"target_x":number,"target_y":number,
"target_z":number,"fov_deg":number},"circulation_notes":[string],"design_notes":[string]}"""

V11_PLAN_SYSTEM = PLAN_SYSTEM + """

V11 EXPLICIT-INTENT EXTENSION — augment the complete base schema above; do not replace it:
- Every base field remains mandatory, including name, room, items, openings, camera,
  circulation_notes, and design_notes.
- Add schema_version="floor-plan/v11".
- Add relationships with EXACTLY one typed placement for every item. Each entry has subject_id,
  kind, optional target_id/wall, and parameters_m. Never encode placement intent only in names.
- Use against_wall + wall="north" + along_offset_m=0 + wall_gap_m for a centered north counter.
- Repeated rows use a directional/above relation plus zero-based distribution_index,
  distribution_count, and distribution_span_m. Keep every repeated instance separate.
- Repeated rows must be compact rather than stretched across the complete target. Unless the user
  gives an exact spacing, use 0.5m center spacing for floor seating and 0.6m center spacing for
  ceiling pendants (for example spans 1.5m for four stools and 1.2m for three pendants).
- Ceiling fixtures MUST declare mount="ceiling" and use above with distribution parameters.
- Add opening_intents with exactly one entry per opening. placement is centered or near_corner;
  near_corner also declares northwest/northeast/southwest/southeast.
- Add camera_intent with corner, target_id, inset_m, eye_height_m, target_height_m, and fov_deg.
- Initial x/z/offset/camera values are placeholders only; the deterministic solver owns final values.
Return JSON only and conform exactly to the supplied FloorPlanV11 JSON schema.
"""


def _complete_v11_base_fields(raw: dict, concept: SceneConcept) -> dict:
    """Fill redundant base fields from typed V11 intent without inventing geometry."""
    payload = dict(raw)
    if not payload.get("name"):
        payload["name"] = str(payload.get("description") or concept.era or "Untitled plan")
    openings = {
        opening.get("id"): opening
        for opening in payload.get("openings", [])
        if isinstance(opening, dict) and opening.get("id")
    }
    normalized_intents = []
    for source in payload.get("opening_intents", []):
        if not isinstance(source, dict):
            normalized_intents.append(source)
            continue
        intent = dict(source)
        if "opening_id" not in intent and intent.get("id"):
            intent["opening_id"] = intent.pop("id")
        opening = openings.get(intent.get("opening_id"))
        if "wall" not in intent and opening is not None:
            intent["wall"] = opening.get("wall")
        normalized_intents.append(intent)
    if "opening_intents" in payload:
        payload["opening_intents"] = normalized_intents

    room = payload.get("room")
    intent = payload.get("camera_intent")
    if "camera" not in payload and isinstance(room, dict) and isinstance(intent, dict):
        corner = intent.get("corner")
        inset = float(intent.get("inset_m", 0.45))
        half_width = float(room.get("width", 0.0)) / 2.0
        half_depth = float(room.get("depth", 0.0)) / 2.0
        payload["camera"] = {
            "x": half_width - inset if corner in {"northeast", "southeast"} else -half_width + inset,
            "y": float(intent.get("eye_height_m", 1.6)),
            "z": half_depth - inset if corner in {"northwest", "northeast"} else -half_depth + inset,
            "target_x": 0.0,
            "target_y": float(intent.get("target_height_m", 1.2)),
            "target_z": 0.0,
            "fov_deg": float(intent.get("fov_deg", 55.0)),
        }
    return payload


async def build_floor_plan(
    description: str,
    concept: SceneConcept,
    current: FloorPlan | None = None,
    feedback: str = "",
    *,
    timeout_seconds: float | None = None,
    strict_validation: bool = False,
    placement_policy: str = "retained-keyword-v1",
) -> tuple[FloorPlan, list[str], PlanValidationReport]:
    """Create or revise a plan, preserving retained or explicit placement policy."""
    from src.floor_plan.solver import solve_plan

    if placement_policy not in {
        "retained-keyword-v1",
        "explicit-relations-v1",
        "explicit-semantic-relations/v1",
    }:
        raise ValueError(f"Unsupported placement policy: {placement_policy}")

    context = {
        "description": description,
        "concept": concept.model_dump(mode="json"),
    }
    if current:
        context["current_plan"] = current.model_dump(mode="json")
        context["revision_requirement"] = feedback
    instruction = "Revise the current plan while preserving unaffected IDs." if current else "Create the first practical plan."
    explicit_v11 = placement_policy == "explicit-semantic-relations/v1"
    if explicit_v11:
        context["floor_plan_v11_json_schema"] = FloorPlanV11.model_json_schema()
    system_prompt = V11_PLAN_SYSTEM if explicit_v11 else PLAN_SYSTEM
    raw = await generate_json(
        system_prompt,
        f"{instruction}\n{json.dumps(context)}",
        model=V11_PLAN_MODEL if explicit_v11 else None,
        timeout_seconds=timeout_seconds,
    )
    if explicit_v11:
        from src.floor_plan.solver import solve_explicit_plan

        raw = _complete_v11_base_fields(raw, concept)
        try:
            plan = FloorPlanV11.model_validate(raw)
        except ValidationError as exc:
            repair_context = {
                "instruction": (
                    "Repair the previous response into one complete FloorPlanV11 object. "
                    "Preserve valid semantic intent and return JSON only."
                ),
                "validation_errors": json.loads(exc.json(include_url=False)),
                "previous_response": raw,
                "required_fields": [
                    "name", "room", "items", "openings", "camera",
                    "schema_version", "relationships", "opening_intents", "camera_intent",
                ],
            }
            repaired = await generate_json(
                V11_PLAN_SYSTEM,
                json.dumps(repair_context),
                model=V11_PLAN_MODEL,
                timeout_seconds=timeout_seconds,
            )
            plan = FloorPlanV11.model_validate(
                _complete_v11_base_fields(repaired, concept)
            )
        solved = solve_explicit_plan(plan)
        normalized, warnings, _ = normalize_floor_plan(
            solved, "", strict=strict_validation, infer_text_placement=False
        )
        resolved = solve_explicit_plan(FloorPlanV11.model_validate(normalized))
        report = validate_floor_plan(resolved, warnings)
        return resolved, warnings, report

    plan = FloorPlan.model_validate(raw)
    if placement_policy == "retained-keyword-v1":
        # Historical profiles retain the broad text-keyword solver byte-for-byte.
        plan = solve_plan(plan)
        return normalize_floor_plan(
            plan, description, strict=strict_validation, infer_text_placement=True
        )
    # New profiles preserve typed coordinates until WorldContract relations are solved.
    return normalize_floor_plan(
        plan, "", strict=strict_validation, infer_text_placement=False
    )
