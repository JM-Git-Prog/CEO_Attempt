"""
Lane ladder data models for cheapest-first model routing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LaneDef:
    """Immutable definition of a model lane in the escalation ladder."""

    model: str
    timeout_s: float
    local: bool
    priority: int = 0
