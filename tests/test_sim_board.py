"""tests/test_sim_board.py — the sim's own Pick Board, Sam's eyes, and Sam's memory.

John, 2026-09-11: *"Give the sim its own Pick Board (assuming he will get smarter as it loops)"*.

These tests exist for one reason above all others: to prove that nothing Sam decides can reach John.
The board he answers is his; the taste file he writes is his; the port is not John's; and if any of
that is misconfigured the loop REFUSES to start rather than quietly poisoning the style model's
training set. Every other check here is about the second half of his sentence — the assumption that
he gets smarter, which was false until `remember.py` and is tested here as behaviour, not hope.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[1] / "sim-player"
sys.path.insert(0, str(SIM))

import eyes  # noqa: E402
import remember  # noqa: E402
import sim_board  # noqa: E402
import sam  # noqa: E402


# ── the guard rails: nothing Sam does can reach John ─────────────────────────────────────────
@pytest.fixture
def fake_tools(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tmp_path / "art").mkdir()
    server = tools / "pick-server.mjs"
    server.write_text('const STATIONS_DIR = process.env.PICK_STATIONS || join(HERE, "stations");', encoding="utf-8")
    return tools, server


def test_every_writable_path_moves_to_the_sims_own_folder(tmp_path):
    home = tmp_path / "sim-board"
    e = sim_board.env({}, home, 8294)
    assert e["PICK_PORT"] == "8294"
    for key in ("PICK_STATIONS", "PICK_PREFS", "PICK_REROLL", "PICK_FLAGS"):
        assert str(home) in e[key], f"{key} still points outside the sim's folder: {e[key]}"


def test_a_clean_config_is_allowed(tmp_path, fake_tools):
    _, server = fake_tools
    assert sim_board.check(tmp_path / "sim-board", 8294, server) == []


def test_johns_port_is_refused(tmp_path, fake_tools):
    _, server = fake_tools
    bad = sim_board.check(tmp_path / "sim-board", 8194, server)
    assert any("John's own board" in b for b in bad)


def test_johns_taste_ledger_is_refused(tmp_path, fake_tools):
    tools, server = fake_tools
    bad = sim_board.check(tools.parent / "art", 8294, server)
    assert any("taste ledger" in b for b in bad)


def test_johns_tools_folder_is_refused(tmp_path, fake_tools):
    tools, server = fake_tools
    bad = sim_board.check(tools / "stations", 8294, server)
    assert any("inside John's tools" in b for b in bad)


def test_an_unpatched_board_is_refused(tmp_path, fake_tools):
    _, server = fake_tools
    server.write_text('const STATIONS_DIR = join(HERE, "stations");', encoding="utf-8")
    bad = sim_board.check(tmp_path / "sim-board", 8294, server)
    assert any("no PICK_STATIONS" in b for b in bad)


def test_the_board_refuses_to_start_when_a_guard_rail_trips(tmp_path, fake_tools):
    _, server = fake_tools
    b = sim_board.SimBoard(port=8194, home=tmp_path / "sim-board", server=server)
    assert b.start(wait_s=1) is False


def test_clear_stations_can_keep_the_answered_ones(tmp_path):
    d = tmp_path / "stations"
    d.mkdir(parents=True)
    (d / "open.json").write_text(json.dumps({"id": "open", "items": [], "answer": None}), encoding="utf-8")
    (d / "done.json").write_text(json.dumps({"id": "done", "items": [], "answer": {"action": "choose"}}), encoding="utf-8")
    assert sim_board.clear_stations(tmp_path, keep_answered=True) == 1
    assert (d / "done.json").exists()
    assert sim_board.clear_stations(tmp_path) == 1


# ── eyes: a pick is a judgement or it is nothing ─────────────────────────────────────────────
def _png(path: Path) -> Path:
    import struct
    import zlib

    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
                     + chunk(b"IEND", b""))
    return path


def _scorer(scores):
    calls = []

    def ask(system, messages, schema):
        calls.append(messages)
        return {"json": {"score": scores[len(calls) - 1], "why": "a reason"}, "model": "fake-vl"}

    ask.calls = calls
    return ask


def test_the_highest_score_wins_and_the_picture_is_actually_sent(tmp_path):
    p = _png(tmp_path / "v.png")
    ask = _scorer([3, 5, 4])
    out = eyes.look(ask, "a couch", [{"tag": t, "png": p} for t in ("v1", "v2", "v3")])
    assert out["winner"] == "v2"
    assert all("images" in m[0] for m in ask.calls), "Sam must actually be shown the picture"


def test_a_bad_take_is_denied_but_a_loser_is_only_not_picked(tmp_path):
    p = _png(tmp_path / "v.png")
    out = eyes.look(_scorer([1, 5, 4]), "a couch", [{"tag": t, "png": p} for t in ("v1", "v2", "v3")])
    assert out["denied"] == ["v1"]
    assert "v3" not in out["denied"]


def test_when_every_take_is_wrong_nobody_wins(tmp_path):
    p = _png(tmp_path / "v.png")
    out = eyes.look(_scorer([2, 1, 2]), "a couch", [{"tag": t, "png": p} for t in ("v1", "v2", "v3")])
    assert out["winner"] is None
    assert sorted(out["denied"]) == ["v1", "v2", "v3"]


def test_no_eyes_means_no_opinion_never_a_guess(tmp_path):
    p = _png(tmp_path / "v.png")

    def blind(system, messages, schema):
        raise RuntimeError("no vision model in the garage")

    assert eyes.look(blind, "a couch", [{"tag": "v1", "png": p}]) is None
    assert eyes.look(None, "a couch", [{"tag": "v1", "png": p}]) is None


def test_a_reply_that_is_not_a_score_is_no_opinion(tmp_path):
    p = _png(tmp_path / "v.png")

    def rubbish(system, messages, schema):
        return {"json": {"score": "lovely", "why": "x"}, "model": "fake-vl"}

    assert eyes.look(rubbish, "a couch", [{"tag": "v1", "png": p}]) is None


def test_an_unreadable_picture_is_skipped_not_scored(tmp_path):
    bad = tmp_path / "v.png"
    bad.write_bytes(b"this is not a png")
    assert eyes.look(_scorer([5]), "a couch", [{"tag": "v1", "png": bad}]) is None


# ── the prop wall, end to end, on a board that is not John's ─────────────────────────────────
class FakeBoard(sam.Board):
    """Stands in for the sim Pick Board: remembers what was posted so the test can check it."""

    def __init__(self, pending):
        super().__init__("http://127.0.0.1:8294")
        self.pending, self.posted = pending, []

    def picks(self, slug):
        return [p for p in self.pending if p["slug"] == slug]

    def pick(self, slug, pick_id, winner, notes=None, denied=None):
        self.posted.append({"slug": slug, "id": pick_id, "winner": winner, "notes": notes, "denied": denied})
        return 200, {"ok": True}


def _round(tmp_path, board, ask_eyes, worlds):
    r = sam.Round(tmp_path / "round", v17=sam.V17("http://127.0.0.1:1"), board=board,
                  world=sam.World(worlds), ask=lambda *a, **k: {}, model="fake",
                  slug="sim-neighborhood", session="sim-test", judge_props=True)
    return r


def test_sam_answers_a_prop_wall_on_his_own_board(tmp_path):
    worlds = tmp_path / "worlds"
    d = worlds / "sim-neighborhood" / "source" / "cutouts" / "picks" / "a-big-couch"
    d.mkdir(parents=True)
    for t in ("v1", "v2"):
        _png(d / f"{t}.png")
    board = FakeBoard([{"slug": "sim-neighborhood", "id": "a-big-couch", "subject": "a big couch",
                        "prompt": "a big couch", "variants": [{"tag": "v1"}, {"tag": "v2"}]}])
    r = _round(tmp_path, board, None, worlds)
    r.eyes_ask = _scorer([2, 5])
    props = r.look_at_props()
    assert props and props[0]["winner"] == "v2" and props[0]["posted"] is True
    assert board.posted[0]["slug"] == "sim-neighborhood"
    assert board.posted[0]["denied"] == ["v1"], "a take Sam thought was wrong must be recorded as denied"


def test_sam_never_answers_a_pick_in_another_world(tmp_path):
    worlds = tmp_path / "worlds"
    (worlds / "mr-johns-neighborhood").mkdir(parents=True)
    board = FakeBoard([{"slug": "mr-johns-neighborhood", "id": "a-lamp", "subject": "a lamp",
                        "variants": [{"tag": "v1"}]}])
    r = _round(tmp_path, board, None, worlds)
    r.eyes_ask = _scorer([5])
    assert r.look_at_props() == []
    assert board.posted == []


def test_a_prop_wall_sam_cannot_see_is_left_for_john(tmp_path):
    worlds = tmp_path / "worlds"
    d = worlds / "sim-neighborhood" / "source" / "cutouts" / "picks" / "a-rug"
    d.mkdir(parents=True)
    (d / "v1.png").write_bytes(b"not a png")
    board = FakeBoard([{"slug": "sim-neighborhood", "id": "a-rug", "subject": "a rug",
                        "variants": [{"tag": "v1"}]}])
    r = _round(tmp_path, board, None, worlds)
    r.eyes_ask = _scorer([5])
    props = r.look_at_props()
    assert props[0]["winner"] is None and props[0]["posted"] is False
    assert board.posted == [], "no opinion must never become a pick"


def test_a_board_that_is_down_never_ends_the_round(tmp_path):
    worlds = tmp_path / "worlds"
    (worlds / "sim-neighborhood").mkdir(parents=True)

    class Dead(sam.Board):
        def picks(self, slug):
            raise RuntimeError("board is down")

    r = _round(tmp_path, Dead("http://127.0.0.1:8294"), None, worlds)
    assert r.look_at_props() == []


# ── the memory: the half of John's sentence that was not true until now ──────────────────────
def test_the_first_night_he_knows_nothing():
    assert remember.opening_line(remember.blank()) == ""


def test_he_stops_asking_for_what_he_already_has():
    m = remember.remember_round(remember.blank(),
                                things=[{"room": "living room", "thing": "a big couch"}],
                                got=["a big couch"], rooms=["living room"])
    assert remember.already_have(m) == ["a big couch"]
    assert "a big couch" in remember.opening_line(m)


def test_he_pushes_on_what_he_never_got_then_gives_up():
    m = remember.blank()
    for _ in range(remember.GIVE_UP_AFTER - 1):
        m = remember.remember_round(m, things=[{"room": "living room", "thing": "a TV"}], got=[], rooms=[])
    assert remember.still_chasing(m) == ["a TV"]
    m = remember.remember_round(m, things=[{"room": "living room", "thing": "a TV"}], got=[], rooms=[])
    assert remember.gave_up_on(m) == ["a TV"]
    assert remember.still_chasing(m) == []
    assert "Do not ask for those again" in remember.opening_line(m)


def test_what_he_gave_up_on_is_the_list_that_matters():
    """The point of the give-up list: it is the app's failures, in a kid's words, ranked by persistence."""
    m = remember.blank()
    for _ in range(remember.GIVE_UP_AFTER):
        m = remember.remember_round(m, things=[{"room": "garage", "thing": "a trampoline"}], got=[], rooms=[])
    assert remember.gave_up_on(m) == ["a trampoline"]


def test_a_filled_room_is_skipped_until_it_goes_stale():
    m = remember.remember_round(remember.blank(), things=[], got=[], rooms=["kitchen"])
    assert remember.rooms_to_skip(m) == ["kitchen"]
    for _ in range(remember.FORGET_ROOMS_AFTER):
        m = remember.remember_round(m, things=[], got=[], rooms=[])
    assert remember.rooms_to_skip(m) == []


def test_the_head_stays_a_kids_head():
    m = remember.remember_round(remember.blank(),
                                things=[{"room": "patio", "thing": f"a thing {i}"}
                                        for i in range(remember.KEEP_WANTS + 25)],
                                got=[], rooms=[])
    assert len(m["wants"]) == remember.KEEP_WANTS


def test_a_corrupt_head_is_an_empty_head_never_a_crash(tmp_path):
    p = tmp_path / "sam-head.json"
    p.write_text("{ not json at all", encoding="utf-8")
    assert remember.load(p) == remember.blank()


def test_the_head_survives_a_round_trip(tmp_path):
    p = tmp_path / "sam-head.json"
    m = remember.remember_round(remember.blank(), things=[{"room": "kitchen", "thing": "a fridge"}],
                                got=["a fridge"], rooms=["kitchen"], house="a colonial with a big porch")
    remember.save(p, m)
    back = remember.load(p)
    assert back["nights"] == 1 and remember.already_have(back) == ["a fridge"]
    assert "big porch" in remember.opening_line(back)


def test_sam_is_told_what_he_remembers_on_his_first_turn(tmp_path):
    m = remember.remember_round(remember.blank(), things=[{"room": "living room", "thing": "a big couch"}],
                                got=["a big couch"], rooms=["living room"])
    r = sam.Round(tmp_path / "round", v17=sam.V17("http://127.0.0.1:1"), board=sam.Board("http://127.0.0.1:8294"),
                  world=sam.World(tmp_path / "worlds"), ask=lambda *a, **k: {}, model="fake",
                  slug="sim-neighborhood", session="sim-test", mem=m)
    r.turn = 1
    seen = r.observe()
    assert "WHAT YOU REMEMBER" in seen and "a big couch" in seen
    r.turn = 4
    assert "WHAT YOU REMEMBER" not in r.observe(), "he is told once, at the start — not every turn"
