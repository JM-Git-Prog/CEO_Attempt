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
  wall_gap_m is distance from wall surface to nearest item edge; ensure depth/2 + wall_gap_m < half_room_depth.
- RELATION SEMANTICS — these are geometric operations, not natural-language synonyms:
  * adjacent_to / east_of: places subject EAST of target (x increases). Never for a south row.
  * west_of: places subject WEST of target.
  * south_of: places subject SOUTH of target (z decreases). Use for seating rows along a counter's south face.
  * north_of: places subject NORTH of target.
  * above: places subject directly above target at ceiling. Use for pendant lights above a counter.
  * around: distributes subjects in a circle around target.
  * centered: places at room center with optional offsets.
- Repeated rows use a directional/above relation plus zero-based distribution_index,
  distribution_count, and distribution_span_m. Keep every repeated instance separate.
- Repeated rows must be compact rather than stretched across the complete target. Unless the user
  gives an exact spacing, use 0.5m center spacing for floor seating and 0.6m center spacing for
  ceiling pendants. distribution_span_m = (count - 1) * spacing (e.g. 1.5m for four stools, 1.2m for three pendants).
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
        schema_repair_used = False
        try:
            plan = FloorPlanV11.model_validate(raw)
        except ValidationError as exc:
            schema_repair_used = True
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

        # Bounded semantic repair: if schema was valid but deterministic validation
        # fails (e.g. wrong relation kinds placing items outside room), use the one
        # remaining repair budget to ask the model to fix typed relation semantics.
        if not report.valid and not schema_repair_used:
            semantic_repair_context = {
                "original_user_description": description,
                "instruction": (
                    "The Plan below is schema-valid but fails deterministic geometry validation. "
                    "Fix ONLY blocker-subject relationships to resolve all blockers while preserving "
                    "every explicit constraint in original_user_description. Do not change any "
                    "non-blocker relationship. For against_wall or near_corner anchors, preserve "
                    "kind, wall, and target; adjust only parameters_m. Do NOT change room "
                    "dimensions, item counts, item dimensions, openings, opening_intents, or "
                    "camera_intent. Return the complete repaired FloorPlanV11 JSON."
                ),
                "blockers": [
                    {"code": b.code, "message": b.message, "item_ids": b.item_ids}
                    for b in report.blockers
                ],
                "relation_semantics": {
                    "adjacent_to": "Places subject EAST of target (x + width/2 + gap). Do NOT use for a row south of a surface.",
                    "east_of": "Same as adjacent_to — places subject east of target.",
                    "west_of": "Places subject WEST of target.",
                    "south_of": "Places subject SOUTH of target (z - depth/2 - gap). Use for seating rows south of a counter.",
                    "north_of": "Places subject NORTH of target.",
                    "above": "Places subject directly above target (same x via distribution, z = target.z). Use for ceiling pendants above a counter.",
                    "against_wall": "Places subject flat against the named wall. wall_gap_m=0 means item edge touches wall — ensure rotated bounds still fit inside room.",
                    "around": "Distributes subjects in a circle around target at radius_m.",
                    "centered": "Places subject at room center with optional offsets.",
                },
                "compact_row_rules": (
                    "For repeated floor seating (stools/chairs): use distribution_span_m = (count-1) * 0.5. "
                    "For repeated ceiling pendants: use distribution_span_m = (count-1) * 0.6. "
                    "Never use target width as the span unless user explicitly specifies it."
                ),
                "wall_gap_rule": (
                    "wall_gap_m is the distance from the wall surface to the nearest item edge. "
                    "The item's full rotated depth must fit: item center z = half_room_depth - depth/2 - wall_gap_m. "
                    "If wall_gap_m=0, ensure depth/2 < half_room_depth."
                ),
                "previous_plan": plan.model_dump(mode="json"),
            }
            repaired_raw = await generate_json(
                V11_PLAN_SYSTEM,
                json.dumps(semantic_repair_context),
                model=V11_PLAN_MODEL,
                timeout_seconds=timeout_seconds,
            )
            try:
                model_repair = FloorPlanV11.model_validate(
                    _complete_v11_base_fields(repaired_raw, concept)
                )
                blocker_codes: dict[str, set[str]] = {}
                item_ids = {item.id for item in plan.items}
                for blocker in report.blockers:
                    for item_id in blocker.item_ids:
                        if item_id in item_ids:
                            blocker_codes.setdefault(item_id, set()).add(blocker.code)
                proposed_by_subject = {
                    relation.subject_id: relation
                    for relation in model_repair.relationships
                }
                authorized_relationships = []
                for original in plan.relationships:
                    proposed = proposed_by_subject.get(original.subject_id, original)
                    if original.subject_id not in blocker_codes:
                        authorized = original
                    elif original.kind in {"against_wall", "near_corner"}:
                        authorized = original.model_copy(update={
                            "parameters_m": proposed.parameters_m,
                        })
                    else:
                        authorized = proposed
                    authorized_relationships.append(authorized)
                repaired_plan = plan.model_copy(
                    deep=True,
                    update={"relationships": authorized_relationships},
                )
                solved2 = solve_explicit_plan(repaired_plan)
                normalized2, warnings2, _ = normalize_floor_plan(
                    solved2, "", strict=strict_validation, infer_text_placement=False
                )
                resolved2 = solve_explicit_plan(FloorPlanV11.model_validate(normalized2))
                report2 = validate_floor_plan(resolved2, warnings2)
                # Accept the repair only if it actually improved things
                if report2.valid or len(report2.blockers) < len(report.blockers):
                    return resolved2, warnings2, report2
            except (ValidationError, ValueError, KeyError, TypeError):
                pass  # Repair failed schema/solve — fall through with original

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
