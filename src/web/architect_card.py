"""The architect card — V17's elaboration step before a render (John, 2026-09-07):

    "when I type 'create a new house on the block, red bricks, white columns, 3 stories, very
     presidential' I want the model to respond with a much more planned-out, ornate, detailed
     version of what it thinks I want. Then from that detailed discussion we finalize the renders."

Law G1 at the sentence level: a confident house/grounds order no longer goes straight to the
builder. The architect (a local model, qwen3.8:27b by the bench's evidence — 92.5 % on the card
rubric, ahead of every cloud giant) writes the CARD — summary, description, the build plan, the
assembly of parts, what it assumed, what it would ask — nuextract reads the stated facts back out
of the prose as the cross-check, and the card is shown in the chat as a gate. "Build it as
planned" sends the ornate brief on to the builder, so the render is built from the planned-out
description, not the six-word sentence. "Change something first" hands the sentence back.

ONE source of truth for the card (rule G7): the Night Shift's architect lane —
E:\\...\\12-world-text-bench\\architect-text-bench.py — writes it, grades it, and trains on it. This
module only loads that file and shapes its output for the chat. If the bench is not on this
machine the step is skipped and the old flow runs, loudly logged.

Pure module (rule E2): no FastAPI, no globals that hold requests; the route calls
`write_card()` in a thread and `gate()` / `builder_clause()` are plain functions of the card.

The pattern book (2026-09-10): before the architect writes, the Home Builders Catalog —
E:\\...\\05 Training\\13-home-builders-catalog (576 real 1920s designs with the catalogue's own
dimensions, storeys, room lines and colour plates) — is asked for the four designs the brief most
resembles, and their reference paragraph is appended to the brief. The card is still written by the
bench (G7 untouched); it is drawn against real proportions instead of invented ones. The card carries
`_references` so the chat shows which designs it leaned on, with their plates. Absent or corrupt, the
shelf costs nothing: logged once, the card is written exactly as before.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

ENABLED = os.getenv("V17_ARCHITECT", "1") != "0"
MODEL = os.getenv("V17_ARCHITECT_MODEL", "qwen3.8:27b")
BENCH = Path(os.getenv(
    "V17_ARCHITECT_BENCH",
    r"E:\Software Development\Video Game Development\05 Training\12-world-text-bench\architect-text-bench.py",
))
CATALOG = Path(os.getenv(
    "V17_CATALOG",
    r"E:\Software Development\Video Game Development\05 Training\12-world-text-bench\catalog",
))
HBC = Path(os.getenv(
    "V17_HBC",
    r"E:\Software Development\Video Game Development\05 Training\13-home-builders-catalog",
))
TIMEOUT_S = int(os.getenv("V17_ARCHITECT_TIMEOUT", "240"))
CLAUSE_MAX = 900            # characters of the ornate brief handed to the builder's order-form step
REFERENCES = 4              # catalog designs handed to the architect — decision 25's four candidates
HOUSE_WORDS = {"house", "home"}

_log = logging.getLogger("live_trace")
_bench = None
_bench_lock = threading.Lock()
_hbc = None
_hbc_lock = threading.Lock()
_cards: dict[str, dict] = {}          # card id -> card, so a confirm can find what was shown (in-memory, like _orders)
_shelf = {"mtime": None, "index": []}


def _shelf_index() -> list[dict]:
    """catalog/index.json, cached until its mtime moves (step 0e — build-catalog.py owns the file)."""
    try: mtime = (CATALOG / "index.json").stat().st_mtime
    except OSError: return []
    if _shelf["mtime"] != mtime:
        try: _shelf["index"] = json.loads((CATALOG / "index.json").read_text(encoding="utf-8"))
        except Exception: _shelf["index"] = []
        _shelf["mtime"] = mtime
    return _shelf["index"]


def _shelf_match(brief: str) -> dict | None:
    """The longest approved node whose every word appears whole in the brief. A house/home mention
    in the brief rules out every node except a home-level one — a brief asking for a whole house
    must never be answered with a shelved sofa card just because it also says "sofa"."""
    words = set(re.findall(r"[a-z0-9]+", brief.lower()))
    mentions_house = bool(words & HOUSE_WORDS)
    best = None
    for row in _shelf_index():
        if not row.get("approved") or row.get("level") == "real":
            continue
        toks = re.findall(r"[a-z0-9]+", str(row.get("node") or "").lower())
        if not toks or not all(t in words for t in toks):
            continue
        if row.get("level") == "built":                       # John's own built sentence: only the SAME sentence again
            if set(toks) == words:
                return row
            continue
        if mentions_house and row.get("level") != "home":
            continue
        if best is None or len(toks) > len(re.findall(r"[a-z0-9]+", str(best.get("node") or ""))):
            best = row
    return best


def bench():
    """The architect lane, loaded once. None when it is not on this machine."""
    global _bench
    with _bench_lock:
        if _bench is not None:
            return _bench or None
        if not BENCH.exists():
            _log.warning("  ARCHITECT bench not found at %s — the card step is off", BENCH)
            _bench = False
            return None
        spec = importlib.util.spec_from_file_location("architect_text_bench", str(BENCH))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.install()
        _bench = mod
        return mod


def hbc():
    """The Home Builders Catalog retriever (13-home-builders-catalog/hbc_reference.py), loaded once
    by path like the bench. None when it is not on this machine — logged once, never an error."""
    global _hbc
    with _hbc_lock:
        if _hbc is not None:
            return _hbc or None
        path = HBC / "hbc_reference.py"
        if not path.exists():
            _log.warning("  ARCHITECT pattern book not found at %s — cards are written without catalog references", path)
            _hbc = False
            return None
        try:
            spec = importlib.util.spec_from_file_location("hbc_reference", str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            _log.warning("  ARCHITECT pattern book at %s failed to load (%s) — cards are written without it", path, e)
            _hbc = False
            return None
        _hbc = mod
        return mod


def references(brief: str, k: int = REFERENCES) -> list[dict]:
    """Up to k catalog designs the brief resembles, or [] — the shelf never costs a card (fail closed)."""
    H = hbc()
    if H is None:
        return []
    try:
        found = H.find(brief, k=k)
        return found if isinstance(found, list) else []
    except Exception as e:
        _log.warning("  ARCHITECT pattern book lookup failed (%s) — writing the card without it", e)
        return []


def reference_block(refs: list[dict]) -> str:
    """The paragraph the architect reads under the brief, "" when there is nothing to say."""
    H = hbc()
    if H is None or not refs:
        return ""
    try:
        return str(H.prompt_block(refs) or "")
    except Exception as e:
        _log.warning("  ARCHITECT pattern book paragraph failed (%s) — writing the card without it", e)
        return ""


def _for_chat(refs: list[dict]) -> list[dict]:
    """What rides on the card: id, name, one line, the plate route. Nothing the browser must trust."""
    out = []
    for r in refs:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        out.append({
            "id": str(r["id"]), "name": str(r.get("name") or r["id"]), "line": str(r.get("line") or ""),
            "plate": f"/api/v17/hbc/plate/{r['id']}", "page": r.get("output_page"),
            "why": [str(w) for w in (r.get("why") or [])][:4], "notes": [str(n) for n in (r.get("notes") or [])][:2],
        })
    return out


def write_card(brief: str, standing: str = "") -> dict | None:
    """Blocking: the architect writes the card, nuextract reads it back. Raises on a backend
    failure (the caller decides what a failed card costs); returns None when the bench is absent
    or the model returned no card.

    Step 0e: an approved catalog card is checked first — the shelf, not the model, answers a
    brief that matches an approved node in under a second. Any miss (no match, a missing or
    corrupt catalog) falls straight through to the model below, exactly as before.

    The pattern book: the model is handed the brief plus the four closest real catalog designs;
    the card records them under `_references`."""
    t0 = time.monotonic()
    row = _shelf_match(brief)
    if row is not None:
        try:
            data = json.loads((CATALOG / row["path"]).read_text(encoding="utf-8"))
            card = dict(data["card"])
            card["_id"] = uuid.uuid4().hex[:12]
            card["_model"] = f"catalog:{row['slug']}"
            card["_seconds"] = round(time.monotonic() - t0, 1)
            card["_gates"] = gates(card)
            _cards[card["_id"]] = card
            return card
        except Exception as e:
            _log.warning("  ARCHITECT shelf hit on %r failed to load (%s) — asking the model instead", row.get("slug"), e)

    A = bench()
    if A is None:
        return None
    opts = A.W.base_opts(timeout=TIMEOUT_S, num_ctx=8192, keep_alive="10m")
    text = brief if not standing else f"{brief}\n(He is standing: {standing}.)"
    refs = references(brief)
    block = reference_block(refs)
    if block:
        text = f"{text}\n\n{block}"
    t0 = time.monotonic()
    card, raw, latency, evals, dur = A.ask_architect(MODEL, text, opts)
    if not isinstance(card, dict):
        return None
    card["_id"] = uuid.uuid4().hex[:12]
    card["_model"] = MODEL
    card["_seconds"] = round(time.monotonic() - t0, 1)
    card["_gates"] = gates(card)
    card["_references"] = _for_chat(refs)
    _cards[card["_id"]] = card
    return card


def gates(card: dict) -> dict:
    """The deterministic checks the bench runs, as a small dict for the receipt."""
    A = bench()
    if A is None:
        return {}
    defects = A.schema_check(card)
    steps_ok, order_ok = A.plan_checks(card.get("plan") or [])
    return {
        "schema": "ok" if not defects else ", ".join(defects[:3]),
        "parts_fit": bool(A.fits(card)),
        "plan": bool(steps_ok and order_ok),
        "words": len(str(card.get("description") or "").split()),
        "parts": len(card.get("assembly") or []),
    }


def find(card_id: str) -> dict | None:
    return _cards.get(str(card_id or ""))


def gate(card: dict, brief: str) -> dict:
    """What the chat shows: the card in plain English plus two answers. Never free text."""
    parts = []
    for p in (card.get("assembly") or [])[:14]:
        if isinstance(p, dict) and p.get("name"):
            n = p.get("count") or 1
            parts.append(f"{p['name']}" + (f" ×{n}" if isinstance(n, int) and n > 1 else ""))
    questions = [str(q) for q in (card.get("questions") or []) if str(q).strip()][:3]
    return {
        "id": card["_id"],
        "question": "Here is the architect's plan. Build it as planned, or change something first?",
        "name": str(card.get("name") or ""),
        "summary": str(card.get("summary") or ""),
        "description": str(card.get("description") or ""),
        "plan": [str(s) for s in (card.get("plan") or [])][:10],
        "parts": parts,
        "part_count": len(card.get("assembly") or []),
        "assumptions": [str(a) for a in (card.get("assumptions") or [])][:6],
        "questions": questions,
        "gates": card.get("_gates") or {},
        "references": list(card.get("_references") or []),   # the catalog designs it was drawn against, with plates
        "model": card.get("_model"),
        "seconds": card.get("_seconds"),
        "options": [
            {"kind": "build", "label": "Build it as planned"},
            {"kind": "revise", "label": "Change something first"},
        ],
        "brief": brief,
    }


def builder_clause(card: dict) -> str:
    """The ornate brief as one clause for the builder's order-form step (nuextract on :8196
    reads the whole sentence). John's own words still lead; this follows them."""
    summary = str(card.get("summary") or "").strip()
    desc = str(card.get("description") or "").strip()
    text = f"{summary} {desc}".strip()
    if len(text) > CLAUSE_MAX:
        cut = text[:CLAUSE_MAX]
        text = cut[: cut.rfind(".") + 1] if "." in cut[CLAUSE_MAX // 2:] else cut
    return text
