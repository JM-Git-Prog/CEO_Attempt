"""Generate a metric floor plan with the existing local orchestration LLM."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import ValidationError

from src.floor_plan.models import FloorPlan, FloorPlanV11, PlanValidationReport
from src.floor_plan.validator import normalize_floor_plan, validate_floor_plan
from src.models import SceneConcept
from src.orchestrator.llm import generate_json

def _v11_plan_model() -> str:
    """Model for the v11 explicit-relations planning path.

    Read fresh on every call - NOT frozen at import. A frozen module-level
    constant here used to silently defeat every bench/exam lane switch:
    plan_bench.py sets os.environ["LLM_MODEL"] = lane per lane, but this
    path always passed a literal model= string into generate_json(), so
    generate()'s own "model or LLM_MODEL" fallback never ran - every lane
    (llama3.1, planner-probe-v1, cloud lanes, whatever) silently queried
    the same frozen default instead of the one actually being tested.
    LLM_MODEL (what plan_bench.py sets) wins when present; V11_PLAN_MODEL
    remains available as an independent pin for callers outside the bench
    harness that want v11 planning on one fixed model regardless of lane;
    "gpt-oss:20b" is the unchanged default when neither is set.
    """
    return os.getenv("LLM_MODEL") or os.getenv("V11_PLAN_MODEL", "gpt-oss:20b")


def _v11_plan_system() -> str:
    """System prompt for the v11 planning call - production text unless a
    Stage A prompt-variant experiment (bench/prompt_experiment.py) points
    V11_PLAN_SYSTEM_FILE at an alternate file. Unset by default, so this is
    a no-op for every normal caller. Repair calls deliberately keep using
    V11_PLAN_SYSTEM directly (not this override) so an experiment only
    changes the ONE variable it's testing - the initial planning prompt.
    """
    override = os.getenv("V11_PLAN_SYSTEM_FILE")
    if override:
        try:
            return Path(override).read_text(encoding="utf-8")
        except OSError:
            pass
    return V11_PLAN_SYSTEM

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


def _reconcile_v11_relations(raw: dict) -> tuple[dict, dict]:
    """Make relationships and items agree before validation.

    FloorPlanV11 demands exactly one placement relation per item. Models miss
    that constantly, and by a hair: a relation naming an item that isn't in
    the list, two relations for one item, or an item nobody placed. Measured
    2026-07-26: 385 of 558 generations died on this single rule - more than
    every geometry fault combined - and the model-retry below usually failed
    on it too, so the cost was two LLM calls to produce nothing.

    Dropping an orphan or a duplicate relation invents nothing: an orphan
    references an item that does not exist, and a second relation for the
    same subject is unusable either way. Synthesizing a relation for an
    unplaced item DOES guess, so those are counted and surfaced as a warning
    so the row can be kept out of training if the guess proves harmful.
    """
    payload = dict(raw)
    items = payload.get("items")
    relations = payload.get("relationships")
    if not isinstance(items, list) or not isinstance(relations, list):
        return payload, {}

    item_ids = [i.get("id") for i in items if isinstance(i, dict) and i.get("id")]
    known = set(item_ids)
    kept: list[dict] = []
    placed: set = set()
    dropped_orphan = dropped_duplicate = synthesized = 0

    for relation in relations:
        if not isinstance(relation, dict):
            continue
        subject = relation.get("subject_id")
        if subject not in known:
            dropped_orphan += 1
            continue
        if subject in placed:
            dropped_duplicate += 1
            continue
        placed.add(subject)
        kept.append(relation)

    # Distribute unplaced items along available wall space rather than stacking
    # them all at "centered" (0,0). This was the single largest overlap source:
    # 430 synthesized centered relations with 64% overlapping (TRAINING-REAIM).
    unplaced = [item_id for item_id in item_ids if item_id not in placed]
    if unplaced:
        # Assign each unplaced item to a wall slot, cycling through walls
        # with offsets so they don't land on the same spot.
        walls = ["south", "east", "north", "west"]
        for index, item_id in enumerate(unplaced):
            wall = walls[index % len(walls)]
            # Spread items along the wall using fractional offsets
            slot = (index // len(walls)) + 1
            offset = slot * 0.8  # 0.8m spacing between synthesized placements
            # Alternate left/right of center
            sign = 1.0 if (slot % 2 == 1) else -1.0
            along_offset = sign * offset
            kept.append({
                "subject_id": item_id, "kind": "against_wall",
                "wall": wall,
                "parameters_m": {"along_offset_m": along_offset, "wall_gap_m": 0.05},
                "relaxable": True,
            })
            synthesized += 1

    payload["relationships"] = kept
    stats = {}
    if dropped_orphan:
        stats["dropped_orphan_relations"] = dropped_orphan
    if dropped_duplicate:
        stats["dropped_duplicate_relations"] = dropped_duplicate
    if synthesized:
        stats["synthesized_relations"] = synthesized
    return payload, stats


def _remap_relations_after_normalize(pre_items: list, payload: dict) -> tuple[dict, dict]:
    """Follow items through normalization so their relations follow too.

    normalize_floor_plan() rewrites the item list before the plan is validated
    again: it DROPS items that look like surfaces or openings (floor, wall,
    door, window...) and RENAMES ids via _safe_id plus a de-duplicating
    suffix. Relations still name the old ids, so a plan the model got
    perfectly right fails "exactly one typed placement relation per item" on
    the second validate - and reconciling before normalization cannot help,
    because the damage happens after it. Measured 2026-07-26: this, not the
    model, was the source of most of those failures.

    Item names survive normalization, and the surviving items stay in their
    original order, so the post-list is an ordered subsequence of the
    pre-list. Walking both in order recovers old id -> new id. Relations
    whose subject or target did not survive are dropped, and the caller's
    reconcile pass then fills any resulting gap.
    """
    items = payload.get("items")
    relations = payload.get("relationships")
    if not isinstance(items, list) or not isinstance(relations, list):
        return payload, {}

    mapping: dict[str, str] = {}
    cursor = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        while cursor < len(pre_items) and pre_items[cursor][1] != name:
            cursor += 1
        if cursor < len(pre_items):
            mapping[pre_items[cursor][0]] = item.get("id")
            cursor += 1

    surviving = {i.get("id") for i in items if isinstance(i, dict)}
    remapped: list[dict] = []
    renamed = dropped = 0
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        new = dict(relation)
        subject = new.get("subject_id")
        if subject not in surviving and subject in mapping:
            new["subject_id"] = mapping[subject]
            renamed += 1
        target = new.get("target_id")
        if target and target not in surviving and target in mapping:
            new["target_id"] = mapping[target]
        if new.get("subject_id") not in surviving:
            dropped += 1
            continue
        if new.get("target_id") and new["target_id"] not in surviving:
            # its anchor was normalized away; the reconcile pass will replace
            # this with a placeholder rather than leave a dangling reference
            dropped += 1
            continue
        remapped.append(new)

    payload = dict(payload)
    payload["relationships"] = remapped

    # The camera points at an item too, and the schema rejects the whole plan
    # if that item was renamed or dropped ("camera intent has dangling
    # target"). Follow the rename; if the subject is gone entirely, aim at the
    # first surviving item so the plan stays valid rather than being discarded.
    camera_retargeted = 0
    intent = payload.get("camera_intent")
    if isinstance(intent, dict):
        intent = dict(intent)
        target = intent.get("target_id")
        if target not in surviving:
            replacement = mapping.get(target)
            if replacement not in surviving:
                replacement = next((i.get("id") for i in items
                                    if isinstance(i, dict) and i.get("id") in surviving), None)
            if replacement:
                intent["target_id"] = replacement
                camera_retargeted = 1
                payload["camera_intent"] = intent

    stats = {}
    if renamed:
        stats["relations_followed_rename"] = renamed
    if dropped:
        stats["relations_lost_to_normalize"] = dropped
    if camera_retargeted:
        stats["camera_retargeted"] = camera_retargeted
    return payload, stats


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
    system_prompt = _v11_plan_system() if explicit_v11 else PLAN_SYSTEM
    raw = await generate_json(
        system_prompt,
        f"{instruction}\n{json.dumps(context)}",
        model=_v11_plan_model() if explicit_v11 else None,
        timeout_seconds=timeout_seconds,
    )
    if explicit_v11:
        from src.floor_plan.solver import solve_explicit_plan

        raw = _complete_v11_base_fields(raw, concept)
        raw, relation_fixes = _reconcile_v11_relations(raw)
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
                model=_v11_plan_model(),
                timeout_seconds=timeout_seconds,
            )
            repaired_payload, repair_relation_fixes = _reconcile_v11_relations(
                _complete_v11_base_fields(repaired, concept)
            )
            for key, count in repair_relation_fixes.items():
                relation_fixes[key] = relation_fixes.get(key, 0) + count
            plan = FloorPlanV11.model_validate(repaired_payload)
        solved = solve_explicit_plan(plan)
        pre_normalize_items = [(i.id, i.name) for i in solved.items]
        normalized, warnings, _ = normalize_floor_plan(
            solved, "", strict=strict_validation, infer_text_placement=False
        )
        # Normalization drops and renames items, which orphans the relations
        # pointing at them. Follow them across, then reconcile whatever is
        # left, BEFORE the validate below - this is where most of the
        # "one relation per item" deaths actually happened.
        normalized_payload = normalized.model_dump(mode="json")
        normalized_payload, remap_stats = _remap_relations_after_normalize(
            pre_normalize_items, normalized_payload)
        normalized_payload, post_fixes = _reconcile_v11_relations(normalized_payload)
        for key, count in list(remap_stats.items()) + list(post_fixes.items()):
            relation_fixes[key] = relation_fixes.get(key, 0) + count

        # Surfaced through the existing warnings channel so callers (and the
        # bench corpus) can see a plan only validated because we reconciled
        # its relations - no schema change needed to carry the fact.
        warnings = list(warnings or [])
        for key, count in relation_fixes.items():
            warnings.append(f"{key}:{count}")
        resolved = solve_explicit_plan(FloorPlanV11.model_validate(normalized_payload))
        report = validate_floor_plan(resolved, warnings, tolerance="strict")

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
                model=_v11_plan_model(),
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
                pre_normalize_items2 = [(i.id, i.name) for i in solved2.items]
                normalized2, warnings2, _ = normalize_floor_plan(
                    solved2, "", strict=strict_validation, infer_text_placement=False
                )
                payload2, _remap2 = _remap_relations_after_normalize(
                    pre_normalize_items2, normalized2.model_dump(mode="json"))
                payload2, _fix2 = _reconcile_v11_relations(payload2)
                resolved2 = solve_explicit_plan(FloorPlanV11.model_validate(payload2))
                report2 = validate_floor_plan(resolved2, warnings2, tolerance="strict")
                # Accept the repair only if it actually improved things
                if report2.valid or len(report2.blockers) < len(report.blockers):
                    warnings2 = list(warnings2 or [])
                    for key, count in relation_fixes.items():
                        warnings2.append(f"{key}:{count}")
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
