"""The vision-talk module (src/web/vision_talk.py) — pure functions, no server, no model.

Pins the command detection, the running summary, the builder's brief, and the
next-question logic John's spec calls out by example.
"""
from __future__ import annotations

import uuid

import pytest

from src.web import vision_talk as vt


@pytest.fixture
def sid():
    session = "test-" + uuid.uuid4().hex[:8]
    yield session
    vt.close(session)


# ─── build / reset command detection ───────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "build it", "Build It!", "build.", "BUILD", "go", "Go!", "go build it",
    "that's it", "thats it", "do it", "make it", "ok build", "yes build it",
    "build it now", "let's build", "Let's build!",
])
def test_is_build_command_recognizes_the_phrase_alone(text):
    assert vt.is_build_command(text) is True


@pytest.mark.parametrize("text", [
    "build it with a red door", "let's build a porch too",
    "", "I want a red door", "build a house",
])
def test_is_build_command_rejects_extra_content(text):
    assert vt.is_build_command(text) is False


@pytest.mark.parametrize("text", [
    "start over", "Start Over.", "forget that", "new house", "scrap it", "Scrap It!",
])
def test_is_reset_command_recognizes_the_phrase(text):
    assert vt.is_reset_command(text) is True


@pytest.mark.parametrize("text", [
    "start over with a red door", "forget", "build it", "", "new house please",
])
def test_is_reset_command_rejects_unrelated_text(text):
    assert vt.is_reset_command(text) is False


# ─── summary / brief_text ───────────────────────────────────────────────────────

def test_summary_shape():
    vision = {"lines": ["A small red house.", "It has a flowerpot by the door"]}
    out = vt.summary(vision)
    assert out == "So far: a small red house · it has a flowerpot by the door"


def test_summary_is_capped_at_400_chars():
    vision = {"lines": ["x" * 500]}
    assert len(vt.summary(vision)) <= 400


def test_brief_text_keeps_every_word():
    vision = {"lines": ["A red house on the block", "red front door", "a flowerpot by the door"]}
    assert vt.brief_text(vision) == (
        "A red house on the block; also: red front door; a flowerpot by the door"
    )


def test_brief_text_single_line_is_unchanged():
    vision = {"lines": ["A red house on the block"]}
    assert vt.brief_text(vision) == "A red house on the block"


# ─── still_needed / next_question ───────────────────────────────────────────────

def test_still_needed_asks_storeys_first_when_nothing_else_is_known():
    vision = {"lines": ["a small white cottage with a red door"], "asked": []}
    needed = vt.still_needed(vision)
    assert needed[0] == "How many floors should it have — one, two, or three?"


def test_still_needed_leaves_only_the_yard_question():
    vision = {"lines": ["two storey brick house with shingle roof and a porch"], "asked": []}
    assert vt.still_needed(vision) == [
        "Anything in the yard or by the door — a flowerpot, a swing, a flag?"
    ]


def test_still_needed_is_empty_once_everything_is_mentioned():
    vision = {
        "lines": ["a three storey red brick house with a shingle roof, a porch, "
                  "and a flag by the mailbox"],
        "asked": [],
    }
    assert vt.still_needed(vision) == []


def test_still_needed_catches_flowerpot_as_one_word():
    vision = {
        "lines": ["a two storey brick house with a shingle roof and a porch, "
                  "with a flowerpot by the door"],
        "asked": [],
    }
    assert vt.still_needed(vision) == []


def test_still_needed_never_repeats_a_question_already_asked():
    vision = {"lines": ["a house"], "asked": ["How many floors should it have — one, two, or three?"]}
    assert "How many floors should it have — one, two, or three?" not in vt.still_needed(vision)


def test_next_question_returns_none_once_covered():
    vision = {
        "lines": ["a three storey red brick house with a shingle roof, a porch, "
                  "and a flag by the mailbox"],
        "asked": [],
    }
    assert vt.next_question(vision) is None


def test_next_question_stops_after_four_asked():
    vision = {"lines": ["a house"], "asked": ["q1", "q2", "q3", "q4"]}
    assert vt.next_question(vision) is None


def test_next_question_matches_still_needed_first_item():
    vision = {"lines": ["a small white cottage with a red door"], "asked": []}
    assert vt.next_question(vision) == vt.still_needed(vision)[0]


# ─── module-level vision lifecycle ──────────────────────────────────────────────

def test_open_get_add_close_lifecycle(sid):
    assert vt.get(sid) is None
    v = vt.open_vision(sid, "a red house on the block")
    assert vt.get(sid) is v
    assert v["lines"] == ["a red house on the block"]
    assert v["asked"] == [] and v["answers"] == []
    vt.add(sid, "with a red door")
    assert vt.get(sid)["lines"] == ["a red house on the block", "with a red door"]
    vt.close(sid)
    assert vt.get(sid) is None


def test_add_to_a_session_with_no_open_vision_returns_none(sid):
    assert vt.add(sid, "a house") is None
