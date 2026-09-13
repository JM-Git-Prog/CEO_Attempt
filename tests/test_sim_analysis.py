"""Tests for sim-player/analysis.py — the Sam Loop's analysis pass.

Hermetic: no network, no Ollama. Every judge-touching test injects its own `ask` callable, and
every other test passes `no_judge=True` so the default judge path (which would call
common.ollama_chat) is never exercised.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sim-player"))
import common  # noqa: E402
import analysis  # noqa: E402


# ---------------------------------------------------------------------- helpers

def _write_round(base: Path, name: str, rows: list[dict]) -> Path:
    round_dir = base / name
    round_dir.mkdir(parents=True)
    with open(round_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return round_dir


def _req(session="sim-test-01"):
    return {"session": session}


# ---------------------------------------------------------------------- counts

def test_counts_on_hand_written_transcript(tmp_path):
    """10 turns, hand-computed expectations for every deterministic count."""
    rows = [
        {"turn": 1, "t": "2026-09-10T20:01:00Z", "wish": True, "i_type": "I want a house right here",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "response": {"kind": "vision", "reply": "I can see it!", "question": None}},
        {"turn": 2, "t": "2026-09-10T20:01:30Z", "wish": False, "i_type": "ok",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0,
         "card": {"id": "c1", "name": "Cottage", "decision": None},
         "response": {"kind": "house", "question": "Slate roof or shingles?",
                      "card": {"id": "c1", "name": "Cottage", "summary": "cute cottage", "plan": ["dig", "walls", "roof"]}}},
        {"turn": 3, "t": "2026-09-10T20:02:00Z", "wish": False, "i_type": "shingles",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "response": {"kind": "house", "question": None}},
        {"turn": 4, "t": "2026-09-10T20:02:30Z", "wish": True, "i_type": "build it with a big porch",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0,
         "card": {"id": "c1", "name": "Cottage", "decision": "build"},
         "response": {"kind": "house", "card": {"id": "c1", "name": "Cottage", "summary": "cute cottage", "plan": ["dig", "walls", "roof"]}}},
        {"turn": 5, "t": "2026-09-10T20:03:00Z", "wish": False, "i_type": "ok",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "order": {"id": "o1", "stage": "building"}, "response": {"kind": "command"}},
        {"turn": 6, "t": "2026-09-10T20:04:00Z", "wish": False, "i_type": "",
         "request": _req(), "world_version_before": 0, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 0, "order": {"id": "o1", "stage": "done"}, "response": {"kind": "command"}},
        {"turn": 7, "t": "2026-09-10T20:04:30Z", "wish": True, "i_type": "I want a pool in the yard",
         "request": _req(), "world_version_before": 1, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 0,
         "response": {"kind": "gap", "gaps_filed": ["a swimming pool"], "receipt": {"needs": ["a swimming pool"]}}},
        {"turn": 8, "t": "2026-09-10T20:05:00Z", "wish": False, "i_type": "okay",
         "request": _req(), "world_version_before": 1, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 1, "wall": {"station": "house-2026-09-10-st1", "picked": None, "why": None},
         "response": {"kind": "command"}},
        {"turn": 9, "t": "2026-09-10T20:05:30Z", "wish": False, "i_type": "what",
         "request": _req(), "world_version_before": 1, "world_version_after": 1, "http_status": 500,
         "error": "internal server error", "streak_nothing": 2, "response": None},
        {"turn": 10, "t": "2026-09-10T20:06:00Z", "wish": False, "i_type": "",
         "request": _req(), "world_version_before": 1, "world_version_after": 1, "http_status": None,
         "error": "TimeoutError: connection reset", "streak_nothing": 3, "response": None},
        {"final": True, "reason_ended": "turns", "turns": 10, "didnt_get": ["a pool"],
         "world_version_start": 0, "world_version_end": 1},
    ]
    round_dir = _write_round(tmp_path, "round-counts", rows)
    result = analysis.analyze(round_dir, no_judge=True, ledger=tmp_path / "ledger.jsonl")
    c = result["counts"]

    assert c["turns"] == 10
    assert c["wishes"] == 3
    assert c["changes_seen"] == 1
    assert c["nothing_streak_max"] == 3
    assert c["questions_asked"] == 1
    assert c["questions_answered"] == 1
    assert c["walls_posted"] == 1
    assert c["walls_picked"] == 0
    assert c["cards_shown"] == 1
    assert c["cards_built"] == 1
    assert c["http_errors"] == 2
    assert c["http_5xx"] == 1
    assert c["exceptions"] == 1
    assert c["seconds_build_to_house"] == [90.0]
    assert c["slow"] == 0
    assert c["reason_ended"] == "turns"
    assert c["world_versions"] == {"start": 0, "end": 1}


# ---------------------------------------------------------------------- deterministic verdicts

def _deterministic_round(base: Path) -> Path:
    rows = [
        {"turn": 1, "t": "2026-09-10T20:00:00Z", "wish": True, "i_type": "I want a house right here",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "response": {"kind": "vision", "reply": "I can see it!"}},
        {"turn": 2, "t": "2026-09-10T20:00:30Z", "wish": False, "i_type": "build",
         "request": _req(), "world_version_before": 0, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 0, "order": {"id": "o1", "stage": "done"}, "response": {"kind": "command"}},
        {"turn": 3, "t": "2026-09-10T20:01:00Z", "wish": True, "i_type": "I want a pool in the yard",
         "request": _req(), "world_version_before": 1, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 0, "response": {"kind": "gap", "gaps_filed": ["a pool"]}},
        {"turn": 4, "t": "2026-09-10T20:01:30Z", "wish": True, "i_type": "I want a trampoline",
         "request": _req(), "world_version_before": 1, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 1, "response": {"kind": "command"}},
        {"final": True, "reason_ended": "streak", "turns": 4, "didnt_get": ["a trampoline"],
         "world_version_start": 0, "world_version_end": 1},
    ]
    return _write_round(base, "round-deterministic", rows)


def test_deterministic_got_cant_yet_nothing(tmp_path):
    round_dir = _deterministic_round(tmp_path)
    result = analysis.analyze(round_dir, no_judge=True, ledger=tmp_path / "ledger.jsonl")
    by_turn = {w["turn"]: w for w in result["wishes"]}

    assert by_turn[1]["verdict"] == "got"
    assert "o1" in by_turn[1]["evidence"]
    assert by_turn[1]["judge"] == "deterministic"

    assert by_turn[3]["verdict"] == "cant_yet"
    assert by_turn[3]["judge"] == "deterministic"

    assert by_turn[4]["verdict"] == "nothing"
    assert by_turn[4]["judge"] == "deterministic"

    # none of these needed a judge call
    assert result["judge_status"] == "skipped"
    assert result["judge_model"] is None


# ---------------------------------------------------------------------- judge

def _undecided_round(base: Path, name="round-undecided") -> Path:
    rows = [
        {"turn": 1, "t": "2026-09-10T20:00:00Z", "wish": True, "i_type": "I want a rainbow in the sky",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "response": {"kind": "vision", "reply": "neat!"}},
        {"turn": 2, "t": "2026-09-10T20:00:30Z", "wish": False, "i_type": "ok",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "response": {"kind": "command"}},
        {"final": True, "reason_ended": "proud", "turns": 2, "didnt_get": [],
         "world_version_start": 0, "world_version_end": 0},
    ]
    return _write_round(base, name, rows)


def test_judge_verdict_labelled_draft(tmp_path):
    def fake_ask(system, messages, schema):
        assert schema is analysis.JUDGE_SCHEMA
        return {"json": {"verdicts": [{"turn": 1, "verdict": "got", "evidence": "Sam said neat!"}]}}

    round_dir = _undecided_round(tmp_path)
    result = analysis.analyze(round_dir, ask=fake_ask, ledger=tmp_path / "ledger.jsonl", judge_model="test-judge-1")
    w1 = {w["turn"]: w for w in result["wishes"]}[1]

    assert w1["verdict"] == "got"
    assert w1["judge"] == "draft:test-judge-1"
    assert result["judge_status"] == "ok"
    assert result["judge_model"] == "test-judge-1"


def test_judge_backend_failure_is_unjudged_not_a_default(tmp_path):
    calls = []

    def broken_ask(system, messages, schema):
        calls.append(1)
        raise common.Backend("simulated outage")

    round_dir = _undecided_round(tmp_path, "round-undecided-backend")
    result = analysis.analyze(round_dir, ask=broken_ask, ledger=tmp_path / "ledger.jsonl", judge_model="test-judge-2")
    w1 = {w["turn"]: w for w in result["wishes"]}[1]

    assert len(calls) == 3               # up to 3 tries, then abort
    assert w1["verdict"] == "unjudged"   # never a silent default like "other"
    assert w1["judge"] == "unjudged"
    assert result["judge_status"] == "backend"


def test_judge_unparseable_reply_is_unjudged(tmp_path):
    def junk_ask(system, messages, schema):
        return {"json": {"not_verdicts": []}}   # doesn't match the schema shape

    round_dir = _undecided_round(tmp_path, "round-undecided-junk")
    result = analysis.analyze(round_dir, ask=junk_ask, ledger=tmp_path / "ledger.jsonl", judge_model="test-judge-3")
    w1 = {w["turn"]: w for w in result["wishes"]}[1]

    assert w1["verdict"] == "unjudged"
    assert result["judge_status"] == "unparseable"


def test_no_judge_flag_skips_and_marks_unjudged(tmp_path):
    round_dir = _undecided_round(tmp_path, "round-no-judge")
    result = analysis.analyze(round_dir, no_judge=True, ledger=tmp_path / "ledger.jsonl")
    w1 = {w["turn"]: w for w in result["wishes"]}[1]

    assert w1["verdict"] == "unjudged"
    assert result["judge_status"] == "skipped"
    assert result["judge_model"] is None


# ---------------------------------------------------------------------- gap ledger

def test_gap_ledger_row_shape_and_append_only(tmp_path):
    round_dir = _deterministic_round(tmp_path)
    ledger = tmp_path / "ledger.jsonl"

    analysis.analyze(round_dir, no_judge=True, ledger=ledger)
    lines1 = common.read_jsonl(ledger)
    assert len(lines1) == 2   # the pool (cant_yet) + the trampoline (nothing)

    row = lines1[0]
    assert set(row.keys()) == {"id", "at", "source", "session", "request", "phrase",
                                "model", "context", "status"}
    assert re.fullmatch(r"[0-9a-f]{12}", row["id"])
    assert row["source"] == "sim-user"
    assert row["model"] is None
    assert row["status"] == "new"
    assert set(row["context"].keys()) == {"target", "world", "round", "loop", "verdict"}
    assert row["context"]["loop"] == "sam-loop"
    assert row["context"]["round"] == round_dir.name
    assert row["context"]["verdict"] in ("cant_yet", "nothing")

    pool_row = next(r for r in lines1 if "pool" in r["request"])
    assert pool_row["context"]["target"] == "grounds"
    assert pool_row["context"]["verdict"] == "cant_yet"

    # a second analyze() run on the same round appends again — never rewrites the ledger.
    analysis.analyze(round_dir, no_judge=True, ledger=ledger)
    lines2 = common.read_jsonl(ledger)
    assert len(lines2) == 4
    assert lines2[:2] == lines1   # the first two rows are untouched, not rewritten


# ---------------------------------------------------------------------- defects

def test_defects_5xx_no_card_plan_wall_unanswered_slow(tmp_path):
    rows = [
        {"turn": 1, "t": "2026-09-10T20:00:00Z", "wish": False, "i_type": "",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 500,
         "error": "boom", "streak_nothing": 0, "response": {"kind": "unknown"}},
        {"turn": 2, "t": "2026-09-10T20:00:30Z", "wish": False, "i_type": "let's build a shed",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "card": {"id": "c9", "name": "Shed", "decision": None},
         "response": {"kind": "house", "card": {"id": "c9", "name": "Shed", "summary": "", "plan": []}}},
        {"turn": 3, "t": "2026-09-10T20:01:00Z", "wish": False, "i_type": "put a fence there",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "wall": {"station": "grounds-2026-09-10-a1", "picked": None, "why": None},
         "response": {"kind": "command"}},
        {"turn": 4, "t": "2026-09-10T20:01:30Z", "wish": False, "i_type": "ok build the gazebo",
         "request": _req(), "world_version_before": 0, "world_version_after": 0, "http_status": 200,
         "error": None, "streak_nothing": 0, "card": {"id": "c10", "name": "Gazebo", "decision": "build"},
         "response": {"kind": "house"}},
        {"turn": 5, "t": "2026-09-10T20:06:30Z", "wish": False, "i_type": "",
         "request": _req(), "world_version_before": 0, "world_version_after": 1, "http_status": 200,
         "error": None, "streak_nothing": 0, "order": {"id": "o10", "stage": "done"}, "response": {"kind": "command"}},
        {"final": True, "reason_ended": "proud", "turns": 5, "didnt_get": [],
         "world_version_start": 0, "world_version_end": 1},
    ]
    round_dir = _write_round(tmp_path, "round-defects", rows)
    result = analysis.analyze(round_dir, no_judge=True, ledger=tmp_path / "ledger.jsonl")
    by_kind = {d["kind"]: d for d in result["defects"]}

    assert by_kind["http_5xx"]["turn"] == 1
    assert by_kind["no_card_plan"]["turn"] == 2
    assert by_kind["wall_unanswered"]["turn"] == 3
    assert by_kind["slow"]["turn"] == 4
    assert "300" in by_kind["slow"]["detail"]
    assert result["counts"]["slow"] == 1
    assert result["counts"]["seconds_build_to_house"] == [300.0]


# ---------------------------------------------------------------------- REPORT.md

def test_report_md_headline(tmp_path):
    round_dir = _deterministic_round(tmp_path)
    result = analysis.analyze(round_dir, no_judge=True, ledger=tmp_path / "ledger.jsonl")

    report = (round_dir / "REPORT.md").read_text(encoding="utf-8")
    expected = (f"Round {round_dir.name}: Sam made 3 wishes, got 1, the app said can't-yet to 1, "
                f"1 went nowhere; 0 defects.")
    assert report.splitlines()[0] == expected
    assert result["counts"]["wishes"] == 3   # sanity: headline math matches the counts block


# ---------------------------------------------------------------------- rolling report

def test_rolling_report_over_three_rounds(tmp_path):
    runs = tmp_path / "runs"

    def wish_row(turn, text, verdict_kind):
        base = {"turn": turn, "t": "2026-09-10T20:00:00Z", "wish": True, "i_type": text,
                "request": _req(), "streak_nothing": 0, "http_status": 200, "error": None}
        if verdict_kind == "nothing":
            base.update(world_version_before=0, world_version_after=0, response={"kind": "command"})
        elif verdict_kind == "cant_yet":
            base.update(world_version_before=0, world_version_after=0,
                        response={"kind": "gap", "gaps_filed": [text]})
        elif verdict_kind == "got":
            base.update(world_version_before=0, world_version_after=0, response={"kind": "vision"})
        return base

    def build_row(turn, wv_before, wv_after, stage="done"):
        return {"turn": turn, "t": "2026-09-10T20:01:00Z", "wish": False, "i_type": "build",
                "request": _req(), "streak_nothing": 0, "http_status": 200, "error": None,
                "world_version_before": wv_before, "world_version_after": wv_after,
                "order": {"id": "o1", "stage": stage}, "response": {"kind": "command"}}

    rows1 = [wish_row(1, "I want a trampoline", "nothing"),
             {"final": True, "reason_ended": "streak", "turns": 1, "didnt_get": ["a trampoline"],
              "world_version_start": 0, "world_version_end": 0}]
    rows2 = [wish_row(1, "I want a trampoline", "cant_yet"),
             {"final": True, "reason_ended": "proud", "turns": 1, "didnt_get": ["a trampoline"],
              "world_version_start": 0, "world_version_end": 0}]
    rows3 = [wish_row(1, "I want a pool", "got"), build_row(2, 0, 1),
             {"final": True, "reason_ended": "proud", "turns": 2, "didnt_get": [],
              "world_version_start": 0, "world_version_end": 1}]

    for name, rows in (("round-1", rows1), ("round-2", rows2), ("round-3", rows3)):
        round_dir = _write_round(runs, name, rows)
        analysis.analyze(round_dir, no_judge=True, ledger=tmp_path / "ledger.jsonl")

    rolling = (runs / "SAM-LOOP-REPORT.md").read_text(encoding="utf-8")
    assert rolling.count("Round round-") == 3
    assert "Round round-1:" in rolling
    assert "Round round-2:" in rolling
    assert "Round round-3:" in rolling
    # "I want a trampoline" went nothing in round-1 and cant_yet in round-2 -> tallied twice
    assert "i want a trampoline — 2" in rolling
    # the pool wish was got, so it must never show up in the "never got" tally
    assert "i want a pool" not in rolling
