"""The architect card (src/web/architect_card.py) — pure functions, no server, no model.

Rule E5/E6: the first tests v17's say router ever had. The model call is replaced by a fake bench
so the shape of what the chat receives, the builder clause, and the confirm lookup are pinned.
"""
from __future__ import annotations

import json
import types

import pytest

from src.web import architect_card as ac


def _fake_bench():
    """A stand-in for the Night Shift's architect lane: ask_architect returns a fixed card."""
    card = {
        "name": "Presidential Georgian", "level": "home", "catalog_path": "Buildings/Residential/Home",
        "summary": "A three-story red brick Georgian home with white columns.",
        "description": " ".join(["Red brick walls rise three stories behind eight white columns."] * 12),
        "style": "georgian", "material": "brick", "color": "red", "width_cm": 1400, "depth_cm": 1000, "height_cm": 960,
        "home": {"stories": 3, "bedrooms": 4, "bathrooms": 3, "wall": "brick", "wall_color": "red", "roof": "slate", "garage": "2-car", "porch": True, "features": ["white columns"]},
        "room": {"floor": "none", "features": []},
        "plan": ["Survey the lot and draft the plans.", "Pour the foundation.", "Raise the brick walls and set the columns.",
                 "Frame the floors and roof.", "Fit doors and windows.", "Finish the interior and inspect."],
        "replication": {"method": "boxes", "functions": ["open the front door"], "lod_notes": ""},
        "assembly": [{"name": "foundation slab", "count": 1, "width_cm": 1400, "depth_cm": 1000, "height_cm": 30, "material": "concrete", "connects_to": "ground", "moves": "none"},
                     {"name": "white column", "count": 8, "width_cm": 40, "depth_cm": 40, "height_cm": 900, "material": "wood", "connects_to": "porch", "moves": "none"}],
        "assumptions": ["A slate roof was assumed.", "Four bedrooms were assumed."],
        "questions": ["Slate or clay tile for the roof?"],
        "_chain": {"stories": 3},
    }
    calls = []
    W = types.SimpleNamespace(base_opts=lambda **kw: dict(kw))
    ns = types.SimpleNamespace(
        W=W, install=lambda: None,
        ask_architect=lambda tag, text, opts: (calls.append((tag, text)), (dict(card), "{}", 1.0, 100, 0))[1],
        schema_check=lambda c: [], plan_checks=lambda plan: (len(plan) >= 5, True), fits=lambda c: True,
    )
    ns.calls = calls
    return ns


@pytest.fixture(autouse=True)
def no_pattern_book(monkeypatch):
    """Hermetic by default: the real E: shelf is never read by a test. A test that wants the pattern
    book installs `_fake_book()` itself."""
    monkeypatch.setattr(ac, "_hbc", False)


def _fake_book(raise_on_find=False):
    """A stand-in for 13-home-builders-catalog/hbc_reference.py: two fixed designs."""
    matches = [
        {"id": "HBC-P0001-D01", "name": "Chatham", "type": "house", "page": 1, "output_page": 3, "plate": "plates/P0001.jpg",
         "line": "The Chatham · New England Colonial · 2 storeys · 7 Rooms, Bath, Nook and Sun Parlor · 45'6\" x 31'0\"",
         "blurb": "A superb example of the New England Colonial style.", "score": 5.5, "why": ["style new england colonial"],
         "notes": ["no 3-storey house in the catalogue; two-storey designs shown for proportion"]},
        {"id": "HBC-P0011-D01", "name": "Cronhardt", "type": "house", "page": 11, "output_page": 14, "plate": "plates/P0011.jpg",
         "line": "The Cronhardt · Colonial · 2 storeys · 7 Rooms and Bath · 42'0\" x 32'6\"", "blurb": "", "score": 5.0, "why": ["style colonial"], "notes": []},
    ]

    def find(brief, k=4):
        if raise_on_find:
            raise RuntimeError("index exploded")
        return list(matches[:k])

    return types.SimpleNamespace(find=find, prompt_block=lambda ms: "REFS: " + ", ".join(m["id"] for m in ms) if ms else "",
                                 record=lambda rid: {"record_id": rid, "derived": {"plate": "plates/P0001.jpg"}} if rid == "HBC-P0001-D01" else None)


@pytest.fixture
def bench(monkeypatch):
    fake = _fake_bench()
    monkeypatch.setattr(ac, "_bench", fake)
    ac._cards.clear()
    ac._shelf["mtime"] = None
    ac._shelf["index"] = []
    return fake


def _write_shelf(tmp_path, monkeypatch, node, approved, level="object", slug="sofa", score=0.95):
    monkeypatch.setattr(ac, "CATALOG", tmp_path)
    (tmp_path / level).mkdir(parents=True, exist_ok=True)
    card_body = {"name": node.title(), "level": level, "summary": f"The shelved {node}.", "plan": ["a"], "assembly": [], "questions": []}
    (tmp_path / level / f"{slug}.json").write_text(json.dumps({"card": card_body}), encoding="utf-8")
    index = [{"node": node, "level": level, "slug": slug, "path": f"{level}/{slug}.json", "score": score, "lane": "qwen3.8:27b", "approved": approved}]
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")


def test_shelf_serves_an_approved_node_without_calling_the_bench(bench, tmp_path, monkeypatch):
    _write_shelf(tmp_path, monkeypatch, "sofa", approved=True)
    card = ac.write_card("please add a sofa to the room")
    assert card["_model"] == "catalog:sofa" and card["name"] == "Sofa"
    assert card["_id"] and ac.find(card["_id"]) is card
    assert bench.calls == []           # the shelf answered — the model was never asked


def test_shelf_ignores_an_unapproved_node(bench, tmp_path, monkeypatch):
    _write_shelf(tmp_path, monkeypatch, "sofa", approved=False)
    card = ac.write_card("please add a sofa to the room")
    assert card["_model"] == ac.MODEL and len(bench.calls) == 1


def test_built_sentence_is_served_only_for_the_same_sentence(bench, tmp_path, monkeypatch):
    """John's rule (2026-09-10): a card he built in V17 is on the shelf for that sentence — and only that sentence."""
    _write_shelf(tmp_path, monkeypatch, "add a red brick house", approved=True, level="built", slug="add-a-red-brick-house")
    card = ac.write_card("Add a red brick house.")                       # same words, punctuation and case differ
    assert card["_model"] == "catalog:add-a-red-brick-house" and bench.calls == []
    card = ac.write_card("add a red brick house with white columns")     # a longer sentence: not the same ask
    assert card["_model"] == ac.MODEL and len(bench.calls) == 1


def test_missing_or_corrupt_index_falls_through_to_the_bench(bench, tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "CATALOG", tmp_path)   # empty dir: no index.json at all
    card = ac.write_card("please add a sofa to the room")
    assert card["_model"] == ac.MODEL and len(bench.calls) == 1
    ac._shelf["mtime"] = None
    (tmp_path / "index.json").write_text("{not valid json", encoding="utf-8")
    card = ac.write_card("please add a sofa to the room")
    assert card["_model"] == ac.MODEL and len(bench.calls) == 2


def test_write_card_returns_a_card_the_chat_can_show(bench):
    card = ac.write_card("create a new house on the block, red bricks, white columns, 3 stories, very presidential.")
    assert card is not None and card["_id"] and card["_model"] == ac.MODEL
    assert card["_gates"]["parts"] == 2 and card["_gates"]["schema"] == "ok"
    g = ac.gate(card, "create a new house on the block")
    assert g["id"] == card["_id"] and g["summary"].startswith("A three-story")
    assert len(g["plan"]) == 6 and g["parts"] == ["foundation slab", "white column ×8"]
    assert [o["kind"] for o in g["options"]] == ["build", "revise"]
    assert g["questions"] == ["Slate or clay tile for the roof?"]
    assert ac.find(card["_id"]) is card and ac.find("nope") is None


def test_builder_clause_is_the_ornate_brief_capped(bench):
    card = ac.write_card("a presidential house")
    clause = ac.builder_clause(card)
    assert clause.startswith("A three-story red brick Georgian home")
    assert len(clause) <= ac.CLAUSE_MAX and clause.endswith(".")


def test_no_bench_means_no_card_and_no_crash(monkeypatch):
    monkeypatch.setattr(ac, "_bench", False)
    assert ac.write_card("anything") is None
    assert ac.gates({"plan": []}) == {}


def test_gate_never_passes_model_html_through(bench):
    card = ac.write_card("x")
    card["summary"] = "<b>bold</b> summary"
    g = ac.gate(card, "x")
    assert g["summary"] == "<b>bold</b> summary"          # the browser sets textContent, never innerHTML — the string stays a string


# ── the pattern book (2026-09-10) ─────────────────────────────────────────────────────────────

def test_pattern_book_paragraph_rides_under_the_brief_and_the_card_names_its_references(bench, monkeypatch):
    monkeypatch.setattr(ac, "_hbc", _fake_book())
    card = ac.write_card("a colonial house with a sun parlor", standing="the front gate")
    tag, text = bench.calls[0]
    assert text.startswith("a colonial house with a sun parlor\n(He is standing: the front gate.)")   # John's words still lead
    assert text.endswith("\n\nREFS: HBC-P0001-D01, HBC-P0011-D01")                               # the paragraph rides underneath
    refs = card["_references"]
    assert [r["id"] for r in refs] == ["HBC-P0001-D01", "HBC-P0011-D01"]
    assert refs[0]["name"] == "Chatham" and refs[0]["plate"] == "/api/v17/hbc/plate/HBC-P0001-D01" and refs[0]["page"] == 3
    assert refs[0]["notes"] == ["no 3-storey house in the catalogue; two-storey designs shown for proportion"]
    g = ac.gate(card, "a colonial house with a sun parlor")
    assert g["references"] == refs                                                               # the chat gets exactly what the card holds


def test_pattern_book_absent_or_broken_never_costs_a_card(bench, monkeypatch):
    # not on this machine (the default in tests): the brief goes to the model untouched
    card = ac.write_card("a colonial house")
    assert bench.calls[-1][1] == "a colonial house" and card["_references"] == []
    assert ac.gate(card, "a colonial house")["references"] == []
    # on the machine but exploding on lookup: same — logged, never raised
    monkeypatch.setattr(ac, "_hbc", _fake_book(raise_on_find=True))
    card = ac.write_card("a colonial house")
    assert bench.calls[-1][1] == "a colonial house" and card["_references"] == []
    # a path with no hbc_reference.py in it loads as "absent", once, and stays absent
    monkeypatch.setattr(ac, "_hbc", None)
    monkeypatch.setattr(ac, "HBC", ac.Path("Z:/nowhere/13-home-builders-catalog"))
    assert ac.hbc() is None and ac._hbc is False and ac.references("a colonial house") == []


def test_shelf_hit_skips_the_pattern_book(bench, tmp_path, monkeypatch):
    """An approved shelf card is John's own answer — it is served as-is, no references bolted on."""
    monkeypatch.setattr(ac, "_hbc", _fake_book())
    _write_shelf(tmp_path, monkeypatch, "sofa", approved=True)
    card = ac.write_card("please add a sofa to the room")
    assert card["_model"] == "catalog:sofa" and "_references" not in card and bench.calls == []
    assert ac.gate(card, "please add a sofa to the room")["references"] == []


def test_hbc_routes_validate_ids_and_say_when_the_shelf_is_absent(monkeypatch):
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from src.web import hbc_routes
    app = fastapi.FastAPI()
    app.include_router(hbc_routes.router)
    c = TestClient(app)
    assert c.get("/api/v17/hbc/plate/../etc/passwd").status_code in (400, 404)
    assert c.get("/api/v17/hbc/plate/not-an-id").status_code == 400
    r = c.get("/api/v17/hbc/plate/HBC-P0001-D01")                    # the autouse fixture: shelf absent
    assert r.status_code == 404 and "not on this machine" in r.json()["error"] and "13-home-builders-catalog" in r.json()["shelf"]
    assert c.get("/api/v17/hbc/find?q=a+colonial+house").status_code == 404
    monkeypatch.setattr(ac, "_hbc", _fake_book())
    r = c.get("/api/v17/hbc/find?q=a+colonial+house&k=1")
    assert r.status_code == 200 and [m["id"] for m in r.json()["matches"]] == ["HBC-P0001-D01"]
    assert r.json()["matches"][0]["plate"] == "/api/v17/hbc/plate/HBC-P0001-D01" and "line" in r.json()["matches"][0]
    assert c.get("/api/v17/hbc/record/HBC-P0001-D01").json()["record_id"] == "HBC-P0001-D01"
    assert c.get("/api/v17/hbc/record/HBC-P9999-D01").status_code == 404
    # a plate whose file is not on the shelf: 404 with the reason, never a traceback
    monkeypatch.setattr(ac, "HBC", ac.Path(str(pytest.importorskip("tempfile").gettempdir())) / "no-such-shelf")
    r = c.get("/api/v17/hbc/plate/HBC-P0001-D01")
    assert r.status_code == 404 and "not on the shelf" in r.json()["error"]
