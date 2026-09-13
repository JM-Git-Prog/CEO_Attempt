"""The signboard's labels (decision 28, John 2026-09-11): four DIFFERENT houses, each saying what it
changed from what he asked for.

The defect that forced this is the fixture: the Sam Loop's simulated ten-year-old read the signboard
four times on 2026-09-10 and reported "four identical white colonial house pictures". The label is a
DIFF computed here against candidate 1 — never a sentence a model wrote — so it cannot be wrong.
"""
from __future__ import annotations

import pytest

from src.web.candidate_labels import candidate_labels


def _c(tag, **summary):
    base = {"style": "colonial", "stories": 2, "wall": "siding", "color": "white",
            "roof": "shingle", "garage": "none", "porch": True}
    base.update(summary)
    return {"tag": tag, "image": f"/jobs/x/{tag}.png", "summary": base}


def test_the_first_picture_is_what_he_asked_for_and_says_so():
    labels = candidate_labels([_c("c1")])
    assert labels == ["white siding colonial — what you asked for"]


def test_every_other_picture_names_exactly_what_it_changed():
    labels = candidate_labels([
        _c("c1"),
        _c("c2", wall="brick", color="red"),
        _c("c3", roof="metal"),
        _c("c4", stories=1, porch=False),
    ])
    assert labels[1] == "red brick colonial — changed: walls (brick, not siding), colour (red, not white)"
    assert labels[2] == "white siding colonial — changed: roof (metal, not shingle)"
    assert labels[3] == "white siding colonial — changed: floors (one floor, not two floors), porch (no porch, not a porch)"


def test_a_style_or_garage_change_is_said_in_plain_words():
    labels = candidate_labels([_c("c1"), _c("c2", style="cottage"), _c("c3", garage="left")])
    assert labels[1] == "white siding cottage — changed: style (cottage, not colonial)"
    assert labels[2] == "white siding colonial — changed: garage (garage on the left, not no garage)"


def test_trips_a_candidate_identical_to_the_first_is_called_out_not_dressed_up():
    """The whole point: an identical picture must never read as a real alternative."""
    labels = candidate_labels([_c("c1"), _c("c2")])
    assert labels[1] == "white siding colonial — the same parts, drawn differently"
    assert "changed:" not in labels[1]


def test_trips_a_missing_or_empty_summary_never_raises_and_never_invents_a_change():
    assert candidate_labels([]) == []
    labels = candidate_labels([{"tag": "c1", "image": "x"}, {"tag": "c2", "image": "y"}])
    assert labels[0] == "c1 — what you asked for" and labels[1] == "c2 — the same parts, drawn differently"
    # a field BOTH state is a real change even when the rest of the summary is missing
    labels = candidate_labels([_c("c1"), {"tag": "c2", "summary": {"color": "red"}}])
    assert labels[1] == "red — changed: colour (red, not white)"
    # a field only ONE of them states is not a change we can prove — it is never reported
    labels = candidate_labels([{"tag": "c1", "summary": {"color": "white"}},
                                {"tag": "c2", "summary": {"color": "white", "roof": "metal"}}])
    assert labels[1] == "white — the same parts, drawn differently"


def test_the_label_is_one_plain_string_the_board_can_hang():
    labels = candidate_labels([_c("c1"), _c("c2", roof="clay tile")])
    assert all(isinstance(x, str) and "\n" not in x and len(x) < 200 for x in labels)
