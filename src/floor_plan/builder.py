"""Generate a metric floor plan with the existing local orchestration LLM."""

from __future__ import annotations

import json

from src.floor_plan.models import FloorPlan
from src.floor_plan.validator import normalize_floor_plan
from src.models import SceneConcept
from src.orchestrator.llm import generate_json

PLAN_SYSTEM = """You are an expert interior space planner. Return one valid JSON object only.
The plan is authoritative geometry for a single rectangular room. Coordinates use X/Z in
meters with room center at 0,0; north is +Z. Include significant furniture, built-ins, doors,
windows, and a deliberate eye-level camera. Keep at least 0.8m circulation where practical.
Every item ID must be stable snake_case. Create one item per physical instance: four stools
means stool_1 through stool_4, never one combined stool footprint. Items contain furniture,
built-ins, and freestanding fixtures only. Put doors/windows only in openings; never put floors,
walls, ceilings, doors, or windows in items. Compact rooms should normally be 4-8m wide and
3-6m deep unless the user requests larger. The camera and target must be different points;
camera eye height should be about 1.6m. Ceiling fixtures use elevation = room height - item height.
Schema: {"name":string,"room":{"width":number,"depth":number,"height":number},
"items":[{"id":string,"name":string,"category":"furniture|fixture|architectural|decor",
"x":number,"z":number,"width":number,"depth":number,"height":number,"elevation":number,
"rotation_deg":number,"fixed":boolean,"clearance_m":number,"description":string}],
"openings":[{"id":string,"kind":"door|window","wall":"north|south|east|west",
"offset":number,"width":number,"height":number,"sill_height":number}],
"camera":{"x":number,"y":number,"z":number,"target_x":number,"target_y":number,
"target_z":number,"fov_deg":number},"circulation_notes":[string],"design_notes":[string]}"""


async def build_floor_plan(
    description: str,
    concept: SceneConcept,
    current: FloorPlan | None = None,
    feedback: str = "",
    *,
    timeout_seconds: float | None = None,
) -> tuple[FloorPlan, list[str]]:
    """Create or revise a plan, then normalize all authored geometry."""
    context = {
        "description": description,
        "concept": concept.model_dump(mode="json"),
    }
    if current:
        context["current_plan"] = current.model_dump(mode="json")
        context["revision_requirement"] = feedback
    instruction = "Revise the current plan while preserving unaffected IDs." if current else "Create the first practical plan."
    raw = await generate_json(
        PLAN_SYSTEM,
        f"{instruction}\n{json.dumps(context)}",
        timeout_seconds=timeout_seconds,
    )
    plan = FloorPlan.model_validate(raw)
    return normalize_floor_plan(plan, description)
