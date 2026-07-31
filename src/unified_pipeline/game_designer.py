"""Deterministic GAME overlay stub for the Unified World Pipeline.

The marathon scope suggests a theme and mechanics from the Brief's room purpose.
It deliberately emits no executable gameplay rules, scoring, win logic, or object
bindings; full AI game design remains post-MVP.

Requirements: 23.1, 23.2, 23.3, 23.4
"""

from __future__ import annotations

from .models import Brief, GameOverlay


_SUGGESTIONS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("kitchen", "kitchenette"), "Kitchen Challenge", "Sequence preparation tasks and use room objects as prompts."),
    (("diner", "dining", "restaurant"), "Service Rhythm", "Coordinate orders and timing in a room-themed service challenge."),
    (("office", "study", "workspace"), "Desk Investigation", "Explore clues and organize discoveries around the workspace."),
    (("workshop", "garage", "studio"), "Maker Challenge", "Discover parts and plan an assembly sequence."),
    (("bedroom", "lounge", "living room"), "Hidden Stories", "Explore the room and connect notable objects into a story."),
)
_DEFAULT_SUGGESTION = (
    "Room Discovery",
    "Explore the room and identify notable objects as potential challenge prompts.",
)


class GameDesigner:
    """Return a non-functional game concept tailored to ``Brief.room_purpose``."""

    def design(self, brief: Brief) -> GameOverlay:
        purpose = " ".join(brief.room_purpose.casefold().split())
        theme, mechanics = _DEFAULT_SUGGESTION
        for keywords, candidate_theme, candidate_mechanics in _SUGGESTIONS:
            if any(keyword in purpose for keyword in keywords):
                theme, mechanics = candidate_theme, candidate_mechanics
                break
        return GameOverlay(theme=theme, mechanics=mechanics)


def design_game(brief: Brief) -> GameOverlay:
    """Convenience entry point for the stateless stub designer."""
    return GameDesigner().design(brief)
