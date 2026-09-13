"""jobsite.py — pure functions, no server. Pins the arrival/build ramps, the step math,
and the done/failed/zero-total edge cases the CONTRACT depends on."""
from __future__ import annotations

from src.web import jobsite


def test_facts_missing_assembly_returns_empty_parts():
    card = {"name": "Test House", "width_cm": 100, "depth_cm": 80, "height_cm": 50,
            "home": {"stories": 1}, "plan": ["do it"]}
    f = jobsite.facts(card)
    assert f == {"name": "Test House", "whole": {"width_cm": 100, "depth_cm": 80, "height_cm": 50, "stories": 1},
                 "plan": ["do it"], "parts": []}


def test_facts_reads_assembly_and_defaults_a_bad_part():
    card = {"name": "House", "assembly": [
        {"name": "Foundation", "count": 1, "width_cm": 1200, "depth_cm": 1000, "height_cm": 30, "material": "concrete", "connects_to": "ground"},
        {"count": 4},              # no name — dropped
        {"name": "Column"},        # no sizes/count — defaulted
    ]}
    f = jobsite.facts(card)
    assert len(f["parts"]) == 2
    assert f["parts"][0]["name"] == "Foundation" and f["parts"][0]["material"] == "concrete"
    assert f["parts"][1] == {"name": "Column", "count": 1, "width_cm": 0, "depth_cm": 0, "height_cm": 0, "material": "", "connects_to": ""}


def test_facts_on_non_dict_returns_none():
    assert jobsite.facts(None) is None
    assert jobsite.facts("nope") is None


def test_arrival_ramps_0_to_total_over_60s_then_holds():
    t0 = 1000.0
    for now, expect in ((t0, 0), (t0 + 15, 7), (t0 + 30, 15), (t0 + 60, 30), (t0 + 999, 30)):
        p = jobsite.progress("rendering", t0, None, now, 7, 30, [])
        assert p["parts_on_site"] == expect, (now, p)
        assert p["assembled"] == 0 and p["step"] == 0


def test_arrival_note_changes_once_all_parts_are_on_site():
    t0 = 1000.0
    mid = jobsite.progress("rendering", t0, None, t0 + 10, 7, 30, [])
    assert mid["note"] == "parts arriving"
    full = jobsite.progress("on the wall", t0, None, t0 + 60, 7, 30, [])
    assert full["note"] == "all parts on site — waiting for your pick in the garage"


def test_building_ramps_and_caps_at_total_minus_one_until_done():
    t0 = 2000.0
    total = 30
    plan = [f"Step number {i} of the plan, written out long enough to be cut" for i in range(7)]
    p0 = jobsite.progress("building", None, t0, t0, 7, total, plan)
    assert p0["parts_on_site"] == total and p0["assembled"] == 0
    p_half = jobsite.progress("building", None, t0, t0 + 37.5, 7, total, plan)
    assert 0 < p_half["assembled"] < total
    p_over = jobsite.progress("building", None, t0, t0 + 9999, 7, total, plan)
    assert p_over["assembled"] == total - 1     # never reaches total until stage flips to "done"


def test_step_math_and_note_lowercased_first_letter():
    t0 = 3000.0
    total = 30
    steps = 7
    plan = [f"Step {i} Does A Thing" for i in range(steps)]
    p = jobsite.progress("building", None, t0, t0 + 30, steps, total, plan)
    expected_step = 1 + int((p["assembled"] / total) * steps)
    assert p["step"] == min(steps, expected_step)
    assert p["note"] == plan[p["step"] - 1][:60][0].lower() + plan[p["step"] - 1][:60][1:]


def test_done_fills_every_number():
    d = jobsite.progress("done", None, 4000.0, 4999.0, 4, 10, ["a", "b", "c", "d"])
    assert d == {"step": 4, "steps": 4, "parts_on_site": 10, "parts_total": 10, "assembled": 10,
                 "note": "built — the house is on the block"}


def test_failed_during_building_freezes_short_of_done():
    t0 = 5000.0
    f = jobsite.progress("failed", None, t0, t0 + 9999, 7, 30, ["x"], error="the builder crashed")
    assert f["note"] == "the builder crashed"
    assert f["parts_on_site"] == 30
    assert f["assembled"] == 29                # capped, never the full total


def test_failed_before_building_started_reports_the_arrival_state():
    t0 = 6000.0
    f = jobsite.progress("failed", t0, None, t0 + 10, 7, 30, [], error="boom")
    assert f["note"] == "boom"
    assert f["assembled"] == 0 and f["step"] == 0
    assert 0 <= f["parts_on_site"] <= 30


def test_zero_parts_total_and_zero_steps_never_crash():
    p1 = jobsite.progress("building", None, 0.0, 5.0, 7, 0, [])
    assert p1 == {"step": 0, "steps": 7, "parts_on_site": 0, "parts_total": 0, "assembled": 0, "note": ""}
    p2 = jobsite.progress("rendering", 0.0, None, 5.0, 0, 30, [])
    assert p2["step"] == 0 and p2["steps"] == 0
    p3 = jobsite.progress("done", None, 0.0, 5.0, 0, 0, [])
    assert p3["assembled"] == 0 and p3["step"] == 0


def test_numbers_are_never_negative_or_over_total():
    t0 = 7000.0
    # now BEFORE t_order/t_building (clock skew) must not go negative
    p = jobsite.progress("building", None, t0, t0 - 500, 7, 30, [])
    assert p["assembled"] >= 0 and p["parts_on_site"] >= 0
    p2 = jobsite.progress("rendering", t0, None, t0 - 500, 7, 30, [])
    assert p2["parts_on_site"] >= 0


def test_unknown_stage_fails_soft():
    p = jobsite.progress("what", None, None, 0.0, 7, 30, [])
    assert p == {"step": 0, "steps": 7, "parts_on_site": 0, "parts_total": 30, "assembled": 0, "note": ""}
