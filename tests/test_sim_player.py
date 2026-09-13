"""The Sam Loop (sim-player/): the state machine, the world seeding, the runner — each against fakes,
no model, no server, no file outside a temp dir — plus the one V17 guard the loop depends on.

Each module's --selftest is the spec (every route tripped on known-bad input); these tests run them
under pytest so the mechanic's gate and John's RUN bats see them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SIM = Path(__file__).resolve().parents[1] / "sim-player"
sys.path.insert(0, str(SIM))


def test_sam_state_machine_selftest():
    import sam
    assert sam.selftest() == 0


def test_seed_world_selftest():
    import seed_world
    assert seed_world.selftest() == 0


def test_loop_runner_selftest():
    import sam_loop
    assert sam_loop.selftest() == 0


def test_sim_sessions_never_wear_johns_name():
    """The nightly student trains only on by == "john" rows; a sim- session's confirm is stamped "sim"."""
    routes = pytest.importorskip("src.web.v17_say_routes")
    assert routes._by("sim-4f3a9c") == "sim"
    assert routes._by("29401d47-5542-487e-831e-1cccb2052307") == "john"
    assert routes._by("") == "john"


# ── the two laws the first real night taught us (2026-09-10), each tripped on known-bad input ──

def _fake_http(script):
    """Replace common.http_json with a scripted (status, body) per call; records the bodies sent."""
    sent = []

    def http_json(method, url, body=None, timeout=30.0):
        sent.append(dict(body or {}))          # a COPY: the caller mutates its body on the think-retry
        item = script.pop(0) if script else (200, {"message": {"content": "{}"}, "done_reason": "stop"})
        if isinstance(item, Exception):
            raise item
        return item

    return http_json, sent


def _reply(text, done="stop"):
    return (200, {"message": {"content": text}, "done_reason": done, "eval_count": 400})


def test_a_cut_off_answer_is_truncated_not_a_backend_verdict(monkeypatch):
    """The whole first night died here: eval_count == the cap, JSON cut mid-key, counted as a backend
    failure, three in a row ended the round. Truncated is its own thing, and the caller retries."""
    import common
    fake, _ = _fake_http([_reply('{\n  "i_see": "I see: version 1 neigh', done="length")])
    monkeypatch.setattr(common, "http_json", fake)
    with pytest.raises(common.Truncated):
        common.ollama_chat("m", "sys", [{"role": "user", "content": "hi"}], schema={"type": "object"}, num_predict=400)
    # a reasoning model that spends the whole budget thinking returns EMPTY at done_reason=length
    fake, _ = _fake_http([_reply("", done="length")])
    monkeypatch.setattr(common, "http_json", fake)
    with pytest.raises(common.Truncated):
        common.ollama_chat("m", "sys", [{"role": "user", "content": "hi"}], num_predict=400)
    # trips: an empty answer for any OTHER reason is a plain Backend, never a retry-bigger
    fake, _ = _fake_http([_reply("", done="stop")])
    monkeypatch.setattr(common, "http_json", fake)
    with pytest.raises(common.Backend) as e:
        common.ollama_chat("m", "sys", [{"role": "user", "content": "hi"}], num_predict=400)
    assert not isinstance(e.value, common.Truncated)


def test_thinking_is_off_and_a_model_that_refuses_gets_one_retry_without_it(monkeypatch):
    import common
    fake, sent = _fake_http([(400, {"error": "this model does not support think"}), _reply('{"ok": 1}')])
    monkeypatch.setattr(common, "http_json", fake)
    out = common.ollama_chat("m", "sys", [{"role": "user", "content": "hi"}], schema={"type": "object"})
    assert out["json"] == {"ok": 1}
    assert sent[0]["think"] is False and "think" not in sent[1]


def test_a_retired_tag_falls_through_to_the_next_rung_and_the_winner_is_recorded(monkeypatch, tmp_path):
    """qwen3-coder:480b-cloud answered HTTP 410 on all 36 mechanic calls on 2026-09-10 and the lane
    just died. The ladder now proves a rung live, skips the corpse, and remembers who answered."""
    import common
    common._lane_winner.clear(); common._lane_dead.clear()
    fake, _ = _fake_http([(410, {"error": "model retired at 2026-07-15"}), _reply('{"ok": 1}')])
    monkeypatch.setattr(common, "http_json", fake)
    ledger = tmp_path / "lane-ledger.jsonl"
    out = common.ask_lane("mechanic", "sys", [{"role": "user", "content": "hi"}], schema={"type": "object"}, ledger=ledger)
    ladder = common.LANES["mechanic"]
    assert out["model"] == ladder[1] and common._lane_winner["mechanic"] == ladder[1]
    assert ladder[0] in common._lane_dead
    rows = common.read_jsonl(ledger)
    assert [r["result"] for r in rows] == ["gone", "winner"]
    # the proven rung is asked FIRST next time — the ladder is never walked twice in a run
    fake2, _ = _fake_http([_reply('{"ok": 2}')])
    monkeypatch.setattr(common, "http_json", fake2)
    assert common.ask_lane("mechanic", "sys", [{"role": "user", "content": "hi"}], schema={"type": "object"})["model"] == ladder[1]
    common._lane_winner.clear(); common._lane_dead.clear()


def test_every_rung_dead_is_one_honest_failure(monkeypatch):
    import common
    common._lane_winner.clear(); common._lane_dead.clear()
    fake, _ = _fake_http([(410, {"error": "gone"})] * 8)
    monkeypatch.setattr(common, "http_json", fake)
    with pytest.raises(common.Backend) as e:
        common.ask_lane("sam", "sys", [{"role": "user", "content": "hi"}])
    assert "every rung is dead" in str(e.value)
    common._lane_winner.clear(); common._lane_dead.clear()


def test_sam_retries_a_cut_off_answer_once_at_double_the_budget(monkeypatch, tmp_path):
    import common, sam
    budgets = []

    def ask_lane(kind, system, messages, **kw):
        budgets.append(kw.get("num_predict"))
        if len(budgets) == 1:
            raise common.Truncated("cut off")
        return {"json": {"i_see": "grass", "i_type": "I want a red house", "pick": None, "card": None,
                          "done": False, "didnt_get": []}, "model": "m", "text": ""}

    monkeypatch.setattr(common, "ask_lane", ask_lane)
    r = sam.Round(tmp_path / "r", v17=sam.V17("http://127.0.0.1:1"), board=sam.Board("http://127.0.0.1:1"),
                  world=sam.World(tmp_path), model="m", session="sim-t")
    assert r.decide("look")["i_type"] == "I want a red house"
    assert budgets == [sam.Round.BUDGET, sam.Round.BUDGET * 2]
    # trips: cut off twice is a real failure, not an endless retry
    budgets.clear()
    monkeypatch.setattr(common, "ask_lane", lambda *a, **kw: (budgets.append(kw.get("num_predict")), (_ for _ in ()).throw(common.Truncated("cut off")))[1])
    with pytest.raises(common.Truncated):
        r.decide("look")
    assert budgets == [sam.Round.BUDGET, sam.Round.BUDGET * 2]
