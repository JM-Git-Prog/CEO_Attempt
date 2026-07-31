"""Metric Plan Generator — constrained template selection and parameterization.

Converts a Brief's spatial requirements into a validated MetricPlan using
template-based generation. The LLM selects a template + parameters (not
free-form coordinate emission).

Requirements: 5.1, 5.2, 5.5, 5.6
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from src.orchestrator.llm import generate_json, LLMError
from src.unified_pipeline.models import Brief, MetricPlan, PlanRevision


# ─── Room Templates ────────────────────────────────────────────────────────────

ROOM_TEMPLATES: dict[str, dict[str, Any]] = {
    "kitchen": {
        "base_dimensions": (4.0, 3.5, 2.7),  # width, depth, ceiling_height
        "min_dimensions": (3.0, 3.0, 2.4),
        "max_dimensions": (5.0, 5.0, 3.0),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ],
        "keywords": ["kitchen", "kitchenette", "cooking", "breakfast", "diner"],
    },
    "living_room": {
        "base_dimensions": (5.0, 4.5, 2.7),
        "min_dimensions": (4.0, 3.5, 2.4),
        "max_dimensions": (8.0, 7.0, 3.2),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.3, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "east", "parameter": 0.5, "width": 1.5, "height": 1.5},
        ],
        "keywords": ["living", "lounge", "sitting", "family"],
    },
    "bedroom": {
        "base_dimensions": (4.0, 4.0, 2.7),
        "min_dimensions": (3.0, 3.0, 2.4),
        "max_dimensions": (6.0, 5.5, 3.0),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.2, "width": 0.8, "height": 2.1},
            {"type": "window", "wall": "east", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ],
        "keywords": ["bedroom", "sleeping", "rest", "nursery"],
    },
    "studio": {
        "base_dimensions": (5.5, 4.5, 2.9),
        "min_dimensions": (4.0, 4.0, 2.7),
        "max_dimensions": (7.0, 5.0, 3.2),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.35, "width": 1.0, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 2.0, "height": 1.6},
        ],
        "keywords": ["studio", "loft", "open plan", "open-plan", "creative", "art"],
    },
    "generic": {
        "base_dimensions": (4.0, 4.0, 2.7),
        "min_dimensions": (2.0, 2.0, 2.4),
        "max_dimensions": (10.0, 10.0, 4.0),
        "default_openings": [
            {"type": "door", "wall": "south", "parameter": 0.5, "width": 0.9, "height": 2.1},
            {"type": "window", "wall": "north", "parameter": 0.5, "width": 1.2, "height": 1.2},
        ],
        "keywords": [],
    },
}


# ─── LLM Prompt ────────────────────────────────────────────────────────────────

PLAN_GENERATION_SYSTEM = """\
You are an interior space planner. Given a Brief describing a room, select the best
template and parameterize it. You do NOT emit raw coordinates — you select from
templates and set parameters.

Available templates: kitchen, living_room, bedroom, studio, generic.

Return JSON:
{
  "template_id": "kitchen",
  "dimensions": {
    "width": 4.0,
    "depth": 3.5,
    "ceiling_height": 2.7
  },
  "openings": [
    {"type": "door|window", "wall": "north|south|east|west", "parameter": 0.0-1.0, "width": 0.8-2.0, "height": 1.0-2.5}
  ],
  "object_placements": [
    {"name": "object name", "x": 0.0-1.0, "y": 0.0-1.0, "rotation_deg": 0, "width": 0.5, "depth": 0.5, "height": 0.8}
  ],
  "circulation_paths": [
    {"from": "door_0", "to": "center", "min_width": 0.6}
  ]
}

Rules:
- Dimensions must be within template min/max bounds
- Object x,y are normalized 0..1 (fraction of room width/depth)
- Every room needs at least one door and one window
- Leave 0.6m minimum circulation clearance between furniture
- Opening parameter is position along wall (0=left corner, 1=right corner)
- Keep openings at least 0.3m from corners (parameter 0.05-0.95)
"""


# ─── Template Selection ────────────────────────────────────────────────────────


def select_template(brief: Brief) -> str:
    """Select the best room template based on Brief content.

    Uses keyword matching on room_purpose and object names.
    Requirement 5.1: constrained template selection.
    """
    purpose_lower = brief.room_purpose.lower()
    object_names_lower = " ".join(
        obj.name.lower() for obj in brief.object_manifest
    )
    combined = f"{purpose_lower} {object_names_lower}"

    best_template = "generic"
    best_score = 0

    for template_id, template in ROOM_TEMPLATES.items():
        if template_id == "generic":
            continue
        score = sum(1 for kw in template["keywords"] if kw in combined)
        if score > best_score:
            best_score = score
            best_template = template_id

    return best_template


# ─── Plan Generation ───────────────────────────────────────────────────────────


def _compute_plan_hash(plan: MetricPlan) -> str:
    """Compute a deterministic hash of a plan for revision tracking."""
    data = json.dumps(plan.to_dict(), sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def _build_walls_from_dimensions(
    width: float, depth: float, ceiling_height: float
) -> tuple[dict[str, Any], ...]:
    """Build 4 walls from room dimensions."""
    return (
        {"id": "north", "start": (0, 0, 0), "end": (width, 0, 0), "height": ceiling_height},
        {"id": "east", "start": (width, 0, 0), "end": (width, depth, 0), "height": ceiling_height},
        {"id": "south", "start": (width, depth, 0), "end": (0, depth, 0), "height": ceiling_height},
        {"id": "west", "start": (0, depth, 0), "end": (0, 0, 0), "height": ceiling_height},
    )


def _denormalize_placements(
    placements: list[dict[str, Any]], width: float, depth: float
) -> tuple[dict[str, Any], ...]:
    """Convert normalized (0..1) placements to absolute coordinates."""
    result = []
    for p in placements:
        result.append({
            "id": p.get("id", p.get("object_id", "")),
            "name": p.get("name", "object"),
            "x": p.get("x", 0.5) * width,
            "y": p.get("y", 0.5) * depth,
            "rotation_deg": p.get("rotation_deg", 0),
            "width": p.get("width", 0.5),
            "depth": p.get("depth", 0.5),
            "height": p.get("height", 0.8),
        })
    return tuple(result)


def _deterministic_placements(
    brief: Brief, width: float, depth: float
) -> tuple[dict[str, Any], ...]:
    """Place non-architectural manifest instances on a bounded deterministic grid."""
    objects = [obj for obj in brief.object_manifest if not obj.is_architectural]
    total = sum(obj.count for obj in objects)
    if total == 0:
        return ()

    columns = min(4, total)
    rows = max(1, (total + columns - 1) // columns)
    placements: list[dict[str, Any]] = []
    index = 0
    for obj in objects:
        for instance_index in range(obj.count):
            column = index % columns
            row = index // columns
            instance_id = obj.id if obj.count == 1 else f"{obj.id}-{instance_index + 1}"
            placements.append({
                "id": instance_id,
                "name": obj.name,
                "x": (column + 1) * width / (columns + 1),
                "y": (row + 1) * depth / (rows + 1),
                "rotation_deg": 0,
                "width": 0.5,
                "depth": 0.5,
                "height": 0.8,
            })
            index += 1
    return tuple(placements)


def _normalize_openings(raw_openings: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Normalize openings from various LLM response formats into consistent format.

    Handles both our expected format and alternative formats (e.g., mock LLM).
    Each opening must have: type, wall, parameter (0..1), width, height.
    """
    result = []
    for o in raw_openings:
        if not isinstance(o, dict):
            continue
        # Determine type
        opening_type = o.get("type", o.get("kind", ""))
        if opening_type not in ("door", "window"):
            continue
        # Determine wall
        wall = o.get("wall", "south")
        if wall not in ("north", "south", "east", "west"):
            continue
        # Determine parameter (0..1 along wall)
        parameter = o.get("parameter", None)
        if parameter is None:
            # Try to derive from offset if available
            parameter = 0.5  # default center
        # Clamp parameter to 0..1
        parameter = max(0.0, min(1.0, float(parameter)))
        # Width and height
        width = float(o.get("width", 0.9))
        height = float(o.get("height", 2.1 if opening_type == "door" else 1.2))

        result.append({
            "type": opening_type,
            "wall": wall,
            "parameter": parameter,
            "width": width,
            "height": height,
        })
    return tuple(result) if result else ()


class MetricPlanGenerator:
    """Generates a MetricPlan from a Brief using constrained template selection.

    The LLM selects template + parameters, NOT free-form coordinates.
    Includes revision tracking and auto-correction on validation failure.

    Requirements: 5.1, 5.2, 5.5, 5.6
    """

    def __init__(self, model: Optional[str] = None, timeout: float = 30.0):
        self._model = model
        self._timeout = timeout

    async def generate(self, brief: Brief) -> MetricPlan:
        """Generate a MetricPlan from a Brief.

        Requirement 5.1: constrained template selection and parameterization.
        Requirement 5.2: defines room dimensions, walls, openings, placements, circulation.
        Requirement 5.5: revision tracking with provenance.
        Requirement 5.6: relative parameterization (fixtures reference parent wall).
        """
        template_id = select_template(brief)
        template = ROOM_TEMPLATES[template_id]

        # Try LLM-based parameterization
        try:
            plan = await self._llm_generate(brief, template_id, template)
        except (LLMError, TimeoutError, Exception):
            # Fallback: use template defaults
            plan = self._fallback_generate(brief, template_id, template)

        return plan

    async def _llm_generate(
        self, brief: Brief, template_id: str, template: dict[str, Any]
    ) -> MetricPlan:
        """Use LLM to parameterize the template."""
        user_prompt = (
            f"Room purpose: {brief.room_purpose}\n"
            f"Template: {template_id}\n"
            f"Objects needed:\n"
            + "\n".join(
                f"  - {obj.name} (x{obj.count}, role={obj.role})"
                for obj in brief.object_manifest
            )
            + f"\n\nTemplate bounds:\n"
            f"  min: {template['min_dimensions']}\n"
            f"  max: {template['max_dimensions']}\n"
            f"  base: {template['base_dimensions']}\n"
            f"\nGenerate the plan parameters."
        )

        result = await generate_json(
            system=PLAN_GENERATION_SYSTEM,
            user=user_prompt,
            model=self._model,
            timeout_seconds=self._timeout,
        )

        # Parse LLM response into MetricPlan
        dims = result.get("dimensions", {})
        width = float(dims.get("width", template["base_dimensions"][0]))
        depth = float(dims.get("depth", template["base_dimensions"][1]))
        ceiling = float(dims.get("ceiling_height", template["base_dimensions"][2]))

        # Clamp to template bounds
        min_d = template["min_dimensions"]
        max_d = template["max_dimensions"]
        width = max(min_d[0], min(max_d[0], width))
        depth = max(min_d[1], min(max_d[1], depth))
        ceiling = max(min_d[2], min(max_d[2], ceiling))

        walls = _build_walls_from_dimensions(width, depth, ceiling)

        # Parse openings — validate they have the expected structure
        raw_openings = result.get("openings", None)
        if raw_openings and isinstance(raw_openings, list):
            openings = _normalize_openings(raw_openings)
            if not openings:
                openings = tuple(template["default_openings"])
        else:
            openings = tuple(template["default_openings"])

        # Ensure we have at least one opening (fallback to template)
        if not openings:
            openings = tuple(template["default_openings"])

        raw_placements = result.get("object_placements", [])
        placements = _denormalize_placements(raw_placements, width, depth)
        if not placements:
            placements = _deterministic_placements(brief, width, depth)
        circulation = tuple(result.get("circulation_paths", [])) or (
            {"from": "door_0", "to": "center", "min_width": 0.6},
        )

        plan = MetricPlan(
            room_dimensions=(width, depth, ceiling),
            walls=walls,
            openings=openings,
            object_placements=placements,
            circulation_paths=circulation,
            revisions=(),
            template_id=template_id,
        )

        # Compute and bind hash in revision
        plan_hash = _compute_plan_hash(plan)
        revision = PlanRevision(
            revision=1,
            changed="initial generation",
            reason=f"Generated from Brief using template '{template_id}'",
            plan_hash=plan_hash,
        )
        plan = MetricPlan(
            room_dimensions=plan.room_dimensions,
            walls=plan.walls,
            openings=plan.openings,
            object_placements=plan.object_placements,
            circulation_paths=plan.circulation_paths,
            revisions=(revision,),
            template_id=template_id,
        )

        return plan

    def _select_template(self, brief: Brief) -> dict[str, Any]:
        """Select the best template dict from the library.

        Returns the template dictionary from ROOM_TEMPLATES.
        """
        template_id = select_template(brief)
        return ROOM_TEMPLATES[template_id]

    def _parameterize(
        self, brief: Brief, template: dict[str, Any]
    ) -> MetricPlan:
        """Parameterize a template into a MetricPlan using defaults.

        This is the synchronous path used when LLM is not available.
        """
        template_id = next(
            (k for k, v in ROOM_TEMPLATES.items() if v is template), "generic"
        )
        return self._fallback_generate(brief, template_id, template)

    def revise(
        self,
        plan: MetricPlan,
        changed: str,
        reason: str,
        **updates: Any,
    ) -> MetricPlan:
        """Create a new revision of an existing plan.

        Requirement 5.5: Every Plan revision SHALL be traceable — revision number,
        what changed, why.

        Args:
            plan: The current MetricPlan to revise.
            changed: Description of what changed.
            reason: Why it was changed (e.g., "validation failure: wall gap").
            **updates: Fields to override on the plan.

        Returns:
            A new MetricPlan with incremented revision number and provenance.
        """
        current_rev = max(
            (r.revision for r in plan.revisions), default=0
        )
        new_rev_num = current_rev + 1

        # Apply updates
        new_dims = updates.get("room_dimensions", plan.room_dimensions)
        new_walls = updates.get("walls", plan.walls)
        new_openings = updates.get("openings", plan.openings)
        new_placements = updates.get(
            "object_placements", plan.object_placements
        )
        new_circulation = updates.get(
            "circulation_paths", plan.circulation_paths
        )

        # Build updated plan (without revision yet to compute hash)
        updated = MetricPlan(
            room_dimensions=tuple(new_dims),
            walls=tuple(new_walls),
            openings=tuple(new_openings),
            object_placements=tuple(new_placements),
            circulation_paths=tuple(new_circulation),
            revisions=(),
            template_id=plan.template_id,
        )
        plan_hash = _compute_plan_hash(updated)

        # Create revision record
        new_revision = PlanRevision(
            revision=new_rev_num,
            changed=changed,
            reason=reason,
            plan_hash=plan_hash,
        )

        return MetricPlan(
            room_dimensions=tuple(new_dims),
            walls=tuple(new_walls),
            openings=tuple(new_openings),
            object_placements=tuple(new_placements),
            circulation_paths=tuple(new_circulation),
            revisions=plan.revisions + (new_revision,),
            template_id=plan.template_id,
        )

    def _fallback_generate(
        self, brief: Brief, template_id: str, template: dict[str, Any]
    ) -> MetricPlan:
        """Generate a plan from template defaults when LLM fails.

        Uses template base dimensions and default openings, placing objects
        in a simple grid layout.
        """
        width, depth, ceiling = template["base_dimensions"]
        walls = _build_walls_from_dimensions(width, depth, ceiling)
        openings = tuple(template["default_openings"])

        # Deterministic placement preserves manifest identity and excludes architecture.
        placements = _deterministic_placements(brief, width, depth)

        circulation = (
            {"from": "door_0", "to": "center", "min_width": 0.6},
        )

        plan = MetricPlan(
            room_dimensions=(width, depth, ceiling),
            walls=walls,
            openings=openings,
            object_placements=tuple(placements),
            circulation_paths=circulation,
            revisions=(),
            template_id=template_id,
        )

        plan_hash = _compute_plan_hash(plan)
        revision = PlanRevision(
            revision=1,
            changed="initial generation (fallback)",
            reason=f"Fallback generation using template '{template_id}' defaults",
            plan_hash=plan_hash,
        )
        plan = MetricPlan(
            room_dimensions=plan.room_dimensions,
            walls=plan.walls,
            openings=plan.openings,
            object_placements=plan.object_placements,
            circulation_paths=plan.circulation_paths,
            revisions=(revision,),
            template_id=template_id,
        )

        return plan
