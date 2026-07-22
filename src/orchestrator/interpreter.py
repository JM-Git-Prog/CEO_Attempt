"""
Scene Interpreter - Takes user description, produces SceneConcept.
"""

from __future__ import annotations

from src.models import SceneConcept
from src.orchestrator.llm import generate_json
from src.orchestrator.prompts import (
    SCENE_INTERPRETER_SYSTEM,
    SEMANTIC_COMMAND_PLANNER_SYSTEM,
    semantic_command_planning_prompt,
)
from src.semantic_commands import SemanticCommand, parse_semantic_command
from src.world_contract import WorldContract


async def interpret_description(
    user_description: str, *, timeout_seconds: float | None = None
) -> SceneConcept:
    """Take a plain-language description and return a structured SceneConcept."""
    data = await generate_json(
        system=SCENE_INTERPRETER_SYSTEM,
        user=user_description,
        timeout_seconds=timeout_seconds,
    )
    return SceneConcept(**data)


async def plan_semantic_commands(
    world_contract: WorldContract,
    instruction: str,
    *,
    timeout_seconds: float | None = None,
) -> tuple[SemanticCommand, ...]:
    """Ask the LLM for data-only semantic commands; validation remains deterministic."""
    data = await generate_json(
        system=SEMANTIC_COMMAND_PLANNER_SYSTEM,
        user=semantic_command_planning_prompt(world_contract, instruction),
        timeout_seconds=timeout_seconds,
    )
    if set(data) != {"commands"} or not isinstance(data["commands"], list):
        raise ValueError("semantic planner must return exactly one commands array")
    return tuple(parse_semantic_command(command) for command in data["commands"])
