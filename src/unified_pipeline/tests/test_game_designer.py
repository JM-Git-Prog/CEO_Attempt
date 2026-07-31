"""Focused tests for the marathon-scope GAME designer stub."""

import pytest

from src.unified_pipeline.game_designer import GameDesigner, design_game
from src.unified_pipeline.models import Brief, GameOverlay


@pytest.mark.parametrize(
    ("purpose", "expected_theme"),
    [
        ("a warm KITCHENETTE for coffee", "Kitchen Challenge"),
        ("1950s diner", "Service Rhythm"),
        ("quiet home office", "Desk Investigation"),
        ("garage workshop", "Maker Challenge"),
        ("cozy living room", "Hidden Stories"),
        ("indoor observatory", "Room Discovery"),
    ],
)
def test_design_suggests_theme_and_mechanics_from_room_purpose(
    purpose: str, expected_theme: str
) -> None:
    overlay = GameDesigner().design(Brief(room_purpose=purpose))

    assert isinstance(overlay, GameOverlay)
    assert overlay.theme == expected_theme
    assert overlay.mechanics


def test_stub_contains_no_functional_gameplay_or_visual_mutations() -> None:
    overlay = design_game(Brief(room_purpose="kitchen"))

    assert overlay.rules == ""
    assert overlay.scoring == ""
    assert overlay.win_condition == ""
    assert overlay.object_role_bindings == {}
    assert set(overlay.to_dict()) == {
        "rules", "scoring", "win_condition", "object_role_bindings", "theme", "mechanics"
    }


def test_stub_design_is_deterministic() -> None:
    brief = Brief(room_purpose="small warm kitchen")

    assert design_game(brief) == design_game(brief)
