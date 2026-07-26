"""
Lane ladder data models and cheapest-first model routing for MVP plan generation.

Implements the escalation strategy: attempt primary lane first, on structural rejection
retry with simplified prompts, then escalate to next lane. Cloud fallback only after
all local lanes exhaust.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from src.floor_plan.models import FloorPlan, PlanValidationReport
from src.models import SceneConcept

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LaneDef:
    """Immutable definition of a model lane in the escalation ladder."""

    model: str
    timeout_s: float
    local: bool
    priority: int = 0


# ---------------------------------------------------------------------------
# Lane definitions — cheapest-first, all local except cloud fallback
# ---------------------------------------------------------------------------

LANE_LADDER: list[LaneDef] = [
    LaneDef(model="planner-probe-v1:latest", timeout_s=20, local=True, priority=1),
    LaneDef(model="gpt-oss:20b", timeout_s=25, local=True, priority=2),
    LaneDef(model="qwen3.6:27b", timeout_s=30, local=True, priority=3),
]

CLOUD_FALLBACK: list[LaneDef] = [
    LaneDef(model="glm-5.2:cloud", timeout_s=30, local=False, priority=4),
    LaneDef(model="kimi-k2.6:cloud", timeout_s=30, local=False, priority=5),
]


# ---------------------------------------------------------------------------
# Prompt simplification helpers
# ---------------------------------------------------------------------------

# Markers in the system prompt that delineate removable constraint sections
_RELATIONSHIP_MARKER = "4. RELATIONSHIPS:"
_CLEARANCE_MARKER = "6. DOOR CLEARANCE:"
_WINDOW_CLEARANCE_MARKER = "7. WINDOW CLEARANCE:"


def _simplify_prompt(system_prompt: str, *, remove_relationships: bool = False, remove_clearance: bool = False) -> str:
    """Progressively simplify the system prompt by removing constraint sections.

    Attempt 1 (full): no simplification
    Attempt 2: remove relationship constraints (section 4)
    Attempt 3: remove relationship + clearance constraints (sections 4, 6, 7)
    """
    lines = system_prompt.split("\n")
    result_lines: list[str] = []
    skip_until_next_numbered = False

    for line in lines:
        stripped = line.strip()

        # Check if we should start skipping
        if remove_relationships and stripped.startswith(_RELATIONSHIP_MARKER):
            skip_until_next_numbered = True
            continue
        if remove_clearance and (
            stripped.startswith(_CLEARANCE_MARKER)
            or stripped.startswith(_WINDOW_CLEARANCE_MARKER)
        ):
            skip_until_next_numbered = True
            continue

        # Check if we hit the next numbered rule (stop skipping)
        if skip_until_next_numbered:
            # Next numbered rule pattern: "N. WORD:" where N is a digit
            if stripped and stripped[0].isdigit() and ". " in stripped and stripped.split(". ", 1)[1][0:1].isupper():
                skip_until_next_numbered = False
            else:
                continue

        result_lines.append(line)

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Main lane ladder generation function
# ---------------------------------------------------------------------------


async def generate_plan_with_ladder(
    description: str,
    concept: SceneConcept,
    *,
    tolerance: Literal["strict", "mvp"] = "mvp",
) -> tuple[FloorPlan, list[str], PlanValidationReport, str, int]:
    """Generate a floor plan using cheapest-first lane escalation with progressive simplification.

    Returns:
        tuple of (plan, warnings, validation_report, model_used, attempts_count)

    Strategy:
        - For each lane in LANE_LADDER (then CLOUD_FALLBACK if all local fail):
          - Attempt 1: full prompt
          - Attempt 2 (on structural failure): same model, remove relationship constraints
          - On structural failure after attempt 2: escalate to next lane with further simplification
    """
    import json

    from src.floor_plan.builder import PLAN_SYSTEM
    from src.floor_plan.models import FloorPlan as FloorPlanModel
    from src.floor_plan.validator import normalize_floor_plan, validate_floor_plan
    from src.orchestrator.llm import LLMError, generate_json

    all_lanes = LANE_LADDER + CLOUD_FALLBACK
    total_attempts = 0
    last_error: str | None = None

    # Build the user prompt context
    context = {
        "description": description,
        "concept": concept.model_dump(mode="json"),
    }
    instruction = "Create the first practical plan."
    user_prompt = f"{instruction}\n{json.dumps(context)}"

    for lane_index, lane in enumerate(all_lanes):
        # Determine simplification level based on lane position
        # First lane: attempt 1 = full, attempt 2 = remove relationships
        # Subsequent lanes: start with relationships removed, add clearance removal
        if lane_index == 0:
            # Primary lane gets two attempts: full prompt, then simplified
            attempts_for_lane = [
                {"remove_relationships": False, "remove_clearance": False},
                {"remove_relationships": True, "remove_clearance": False},
            ]
        else:
            # Escalated lanes get one attempt with progressive simplification
            attempts_for_lane = [
                {
                    "remove_relationships": True,
                    "remove_clearance": lane_index >= 2,  # Remove clearance from 3rd lane onward
                },
            ]

        for attempt_config in attempts_for_lane:
            total_attempts += 1
            simplified_prompt = _simplify_prompt(
                PLAN_SYSTEM,
                remove_relationships=attempt_config["remove_relationships"],
                remove_clearance=attempt_config["remove_clearance"],
            )

            simplification_desc = "full prompt"
            if attempt_config["remove_clearance"]:
                simplification_desc = "no relationships + no clearance"
            elif attempt_config["remove_relationships"]:
                simplification_desc = "no relationships"

            logger.info(
                "[LaneLadder] Attempt %d: model=%s, simplification=%s",
                total_attempts,
                lane.model,
                simplification_desc,
            )

            try:
                raw = await generate_json(
                    simplified_prompt,
                    user_prompt,
                    model=lane.model,
                    timeout_seconds=lane.timeout_s,
                )

                # Parse and normalize the plan
                plan = FloorPlanModel.model_validate(raw)
                plan, warnings, report = normalize_floor_plan(
                    plan, description, strict=False, infer_text_placement=True
                )

                # Validate with requested tolerance
                report = validate_floor_plan(plan, warnings, tolerance=tolerance)

                if report.valid:
                    logger.info(
                        "[LaneLadder] Plan accepted: model=%s, attempt=%d",
                        lane.model,
                        total_attempts,
                    )
                    return plan, warnings, report, lane.model, total_attempts

                # Plan rejected — try auto-repair before escalating
                if report.blockers:
                    from src.floor_plan.repair import repair_near_miss

                    repair_result = repair_near_miss(plan, report, max_nudge_m=0.3)
                    if repair_result.repaired:
                        plan = repair_result.plan
                        # Re-validate the repaired plan
                        report = validate_floor_plan(plan, warnings, tolerance=tolerance)
                        if report.valid:
                            logger.info(
                                "[LaneLadder] Plan auto-repaired and accepted: model=%s, attempt=%d, repairs=%s",
                                lane.model,
                                total_attempts,
                                repair_result.repairs_applied,
                            )
                            return plan, warnings, report, lane.model, total_attempts
                        # Still failing after repair — continue to next attempt/lane
                        logger.info(
                            "[LaneLadder] Auto-repair applied %d fixes but %d blockers remain",
                            len(repair_result.repairs_applied),
                            len(repair_result.remaining_blockers),
                        )

                # Plan rejected — log blockers and continue
                blocker_summary = ", ".join(b.code for b in report.blockers[:3])
                last_error = f"Structural rejection ({blocker_summary})"
                logger.warning(
                    "[LaneLadder] Plan rejected (attempt %d, model=%s): %s",
                    total_attempts,
                    lane.model,
                    last_error,
                )

            except (LLMError, Exception) as exc:
                # LLM error (timeout, parse failure, network) — escalate to next lane
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "[LaneLadder] LLM error (attempt %d, model=%s): %s",
                    total_attempts,
                    lane.model,
                    last_error,
                )
                # Break out of attempts for this lane and move to next lane
                break

    # All lanes exhausted — return the last attempt's result (even if invalid)
    # Re-run with the strongest available model to get a result for reporting
    logger.error(
        "[LaneLadder] All lanes exhausted after %d attempts. Last error: %s",
        total_attempts,
        last_error,
    )

    # Final fallback: use the last lane's result or raise
    # Try one more time with the strongest local model for a best-effort result
    strongest_lane = LANE_LADDER[-1]
    try:
        simplified_prompt = _simplify_prompt(
            PLAN_SYSTEM, remove_relationships=True, remove_clearance=True
        )
        total_attempts += 1
        raw = await generate_json(
            simplified_prompt,
            user_prompt,
            model=strongest_lane.model,
            timeout_seconds=strongest_lane.timeout_s + 10,
        )
        plan = FloorPlanModel.model_validate(raw)
        plan, warnings, report = normalize_floor_plan(
            plan, description, strict=False, infer_text_placement=True
        )
        report = validate_floor_plan(plan, warnings, tolerance=tolerance)
        logger.warning(
            "[LaneLadder] Final fallback result (valid=%s, model=%s, attempts=%d)",
            report.valid,
            strongest_lane.model,
            total_attempts,
        )
        return plan, warnings, report, strongest_lane.model, total_attempts
    except Exception as final_exc:
        raise RuntimeError(
            f"Lane ladder exhausted all {total_attempts} attempts. "
            f"Last error: {last_error}. Final fallback error: {final_exc}"
        ) from final_exc
