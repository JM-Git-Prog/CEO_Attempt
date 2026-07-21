"""
Scene Interpreter - Takes user description, produces SceneConcept.
"""

from __future__ import annotations

from src.models import SceneConcept
from src.orchestrator.llm import generate_json
from src.orchestrator.prompts import SCENE_INTERPRETER_SYSTEM


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
