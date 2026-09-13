"""Sam furnishes the house, room by room, talking to a friend (decision 29, John 2026-09-11).

Maya is a conversation, not a list — these pin that what Sam ends up asking the app for comes out of
what the two of them actually said, that a silent friend never stops the round, and that nothing
vague or impossible ever reaches the app as a wish.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sim-player"))

import furnish  # noqa: E402


def _ask(replies):
    """A scripted Maya: each call returns the next reply. Records what she was asked."""
    calls = []

    def ask(system, messages, schema):
        calls.append({"system": system, "messages": list(messages), "schema": schema})
        r = replies.pop(0) if replies else ""
        if isinstance(r, Exception):
            raise r
        return r

    ask.calls = calls
    return ask


def test_the_friend_is_a_conversation_that_deepens_not_a_list():
    ask = _ask([{"text": "You need a bunk bed so your cousin can sleep over. Do you want a slide on it?",
                 "model": "qwen3.8:27b"},
                {"text": "A slide is way better. And a beanbag to land on!", "model": "qwen3.8:27b"}])
    maya = furnish.Friend(ask=ask, room="primary bedroom")
    assert maya.opener() == "I'm in the primary bedroom. What should I put in here?"
    first = maya.say(maya.opener())
    second = maya.say("yes a slide!")
    assert "bunk bed" in first and "beanbag" in second
    assert maya.model == "qwen3.8:27b"
    # the SECOND call carries the whole conversation, which is what makes it deepen
    sent = [m["content"] for m in ask.calls[1]["messages"]]
    assert sent[0].startswith("I'm in the primary bedroom") and sent[1] == first and sent[2] == "yes a slide!"
    assert "primary bedroom" in ask.calls[1]["system"] and "ten years old" in ask.calls[1]["system"]


def test_what_sam_asks_for_comes_out_of_what_they_said():
    ask = _ask([{"text": "You need a bunk bed with a slide!", "model": "m"},
                {"json": {"things": ["a bunk bed with a slide", "a beanbag"]}, "model": "m"}])
    maya = furnish.Friend(ask=ask, room="primary bedroom")
    maya.say(maya.opener())
    things = maya.ideas()
    assert things[0] == "a bunk bed with a slide" and "a beanbag" in things
    assert furnish.wish_for(things[0], "primary bedroom", 0) == "can I have a bunk bed with a slide in the primary bedroom?"


def test_a_quiet_friend_never_stops_the_round():
    """A kid does not need to be told a bedroom has a bed."""
    maya = furnish.Friend(ask=None, room="kitchen")
    assert maya.say("hello?") == "" and maya.model == "quiet"
    assert "a fridge" in maya.ideas()
    # and a friend who errors is just as quiet
    boom = furnish.Friend(ask=_ask([RuntimeError("model down")]), room="kitchen")
    assert boom.say("hi") == "" and "a stove" in boom.ideas()


def test_nothing_vague_impossible_or_repeated_ever_reaches_the_app():
    ask = _ask([{"text": "hmm", "model": "m"},
                {"json": {"things": ["a bunk bed", "A Bunk Beds", "something cool", "the kitchen",
                                      "a really enormous extremely tall wizard tower thing", "a beanbag", "ideas"]}}])
    maya = furnish.Friend(ask=ask, room="primary bedroom")
    maya.say("hi")
    things = maya.ideas(already=["a beanbag"])
    assert things[0] == "a bunk bed"
    assert not any("something" in t or "ideas" == t or "kitchen" == t for t in things)   # vague + room names out
    assert sum(1 for t in things if "bunk bed" in t.lower()) == 1                        # deduped, case/plural
    assert "a beanbag" not in things                                                      # already asked for
    assert all(len(t.split()) <= furnish.MAX_WORDS for t in things)                       # the wizard tower is out


def test_the_house_is_furnished_a_little_at_a_time_room_by_room():
    assert furnish.next_room() == "living room"
    assert furnish.next_room(done=["living room"]) == "primary bedroom"
    assert furnish.next_room(done=furnish.ROOMS) is None
    assert len(furnish.ROOMS) == 11                    # the catalogue's own eleven rooms
    assert not furnish.room_done(["a couch"], ["a couch", "a tv", "a rug", "a lamp", "a shelf"])
    assert furnish.room_done(["a couch", "a tv", "a rug", "a lamp"], ["a couch", "a tv", "a rug", "a lamp", "a shelf"])
    assert furnish.room_done(["a couch"], ["a couch"])  # a short list finishes early, never loops


def test_entering_a_room_keeps_the_friend_but_drops_the_old_rooms_chatter():
    ask = _ask([{"text": "a couch!", "model": "m"}, {"text": "a fridge!", "model": "m"}])
    maya = furnish.Friend(ask=ask, room="living room")
    maya.say("hi")
    maya.enters("kitchen")
    assert maya.room == "kitchen" and maya.history == []
    maya.say(maya.opener())
    assert "kitchen" in ask.calls[1]["system"] and len(ask.calls[1]["messages"]) == 1
