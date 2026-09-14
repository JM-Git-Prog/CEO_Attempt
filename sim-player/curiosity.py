"""curiosity.py — Sam asks before he wishes.

2026-09-14. Sam is ten and he says "i want a crib". That is a complete sentence and a useless
brief: it does not say how big, what it is made of, what it stands on, or which room it belongs
in. The builder then guesses, and a guess is how a crib comes out the size of a bed.

A real ten-year-old does not stop at "i want a crib". He asks. He asks how big a baby is, whether
the sides go up and down, why the bars are close together. The answers are what turn a wish into
something buildable, and this is the piece of Sam that was missing.

So: Sam calls the models himself, through the lane ladder in common.py, and asks ONE question about
his own wish. The answer comes back as two things, both of which matter:

    question  what Sam wanted to know, in Sam's words. This is the honest record of the gap in
              his understanding, and it is the half worth training on.
    brief     the answer turned into millimetres, materials and parts. This is what gets appended
              to the gap so the builder is told what Sam meant rather than what Sam typed.

WHAT THIS IS NOT. It is not a second opinion on whether the wish is reasonable, and it must never
rewrite the wish. Sam asked for a crib; he still gets a crib. The brief adds detail underneath it.
If the model comes back wanting to build a wardrobe instead, that is a failure and is dropped
(see `_brief_is_about`).

NEVER RAISES. Every call is wrapped. A round that cannot reach a model files its gaps exactly as it
did before, unenriched. Curiosity is worth having and is never worth stopping the loop for.

SCHEMA LAW (2026-09-14, the bug that blinded the eyes for four days): no "minimum", "maximum",
"exclusiveMinimum", "exclusiveMaximum" or "multipleOf" anywhere in a schema handed to Ollama. A
local tag compiles the schema into a decoding grammar and numeric bounds stall it - 60 s and no
reply, against 2.3 s without. common.grammar_safe() strips them at the door as a second line of
defence; this file simply never writes them.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import common

# The ladder. Cheap and fast first: this runs once per unbuilt wish, several times a round, and it
# must never be the reason a round is slow. gpt-oss:20b is local and is the floor, not the ceiling.
LANES = {
    "curious": [
        os.getenv("SAM_CURIOUS_MODEL", "glm-5.2:cloud"),
        "kimi-k3:cloud",
        "qwen3.5:397b-cloud",
        "deepseek-v4-flash:cloud",
        "gpt-oss:120b-cloud",
        "gpt-oss:20b",
    ],
}

BRIEF_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "thing": {"type": "string"},
        "about_mm": {
            "type": "object",
            "properties": {"wide": {"type": "integer"}, "tall": {"type": "integer"}, "deep": {"type": "integer"}},
            "required": ["wide", "tall", "deep"],
        },
        "made_of": {"type": "array", "items": {"type": "string"}},
        "parts": {"type": "array", "items": {"type": "string"}},
        "where_it_goes": {"type": "string"},
        "how_you_know_its_right": {"type": "string"},
    },
    "required": ["question", "answer", "thing", "about_mm", "made_of", "parts",
                 "where_it_goes", "how_you_know_its_right"],
}

SYSTEM = """You are helping a curious ten-year-old called Sam who is building a house in a video game.

Sam has asked for something and does not yet know enough about it to describe it properly. Your job
is two things, in this order:

1. Write the ONE question Sam himself would ask about it — in Sam's voice, short, plain, the way a
   ten-year-old actually talks. Not a polite adult question. Not three questions. One.
2. Answer it in the detail a person BUILDING the thing needs: real millimetres, what it is made of,
   what parts it has, and where in a house it stands.

Rules that matter:
- Keep the thing Sam asked for. If he asked for a crib, the answer is about a crib. Never swap it
  for something you think is better.
- Millimetres, and real ones. A single bed is 900 x 1900. A worktop is 900 high. A doorway is 900
  wide and 2100 to the head. If you do not know, give the ordinary domestic size, not a guess with
  a zero on the end.
- `parts` is how the thing is actually put together, biggest first: "four corner posts", "a slatted
  base", "a mattress", "two drop-down side rails". Between three and eight of them.
- `how_you_know_its_right` is the one thing a person could measure to catch a mistake: "the gap
  between the bars is under 65 mm so a baby's head cannot fit through".
"""


def _prompt(wish: str, context: dict | None) -> str:
    where = ""
    if context:
        bits = [f"{k}: {v}" for k, v in context.items() if k in ("target", "world", "room") and v]
        if bits:
            where = "\nWhere Sam is standing: " + ", ".join(bits)
    return (f"Sam asked for this, and the game could not build it:\n\n  {wish.strip()}\n" + where
            + "\n\nAsk his question and answer it." + common.JSON_ONLY)


def _brief_is_about(wish: str, brief: dict) -> bool:
    """Did it answer about the thing Sam asked for, or about something it preferred?

    A cheap word-overlap check, on purpose. The failure this catches is the model quietly deciding
    that what Sam REALLY wants is a wardrobe, and that failure is obvious in the nouns. Anything
    subtler than that is not worth a second model call to detect.
    """
    thing = str(brief.get("thing", "")).lower()
    if not thing:
        return False
    stop = {"a", "an", "the", "for", "in", "on", "my", "some", "want", "i", "can", "have",
            "is", "it", "to", "and", "of", "with", "please", "room", "baby"}
    words = {w.strip(".,!?'\"") for w in wish.lower().split()} - stop
    return any(w and (w in thing or thing in w) for w in words)


def _sane(brief: dict) -> list[str]:
    """Arithmetic, not opinion. The same tape measure architect_card.py uses on build cards."""
    bad = []
    mm = brief.get("about_mm") or {}
    for axis in ("wide", "tall", "deep"):
        v = mm.get(axis)
        if not isinstance(v, int):
            bad.append(f"{axis} is not a whole number of millimetres ({v!r})")
        elif v < 20:
            bad.append(f"{axis} is {v} mm — smaller than a thumbnail, so the units are wrong")
        elif v > 6000:
            bad.append(f"{axis} is {v} mm — over six metres, so the units are wrong")
    parts = brief.get("parts") or []
    if not (3 <= len(parts) <= 8):
        bad.append(f"{len(parts)} parts — a thing is made of three to eight of them, not {len(parts)}")
    if not (brief.get("made_of") or []):
        bad.append("made_of is empty — everything is made of something")
    return bad


def wonder(wish: str, *, context: dict | None = None, round_dir: Path | None = None,
           ledger: Path | None = None, timeout: float = 90.0) -> dict | None:
    """One curious question about `wish`, and the answer as a buildable brief. None if it could not.

    Writes the raw model call to the round's calls.jsonl (so the corpus collector picks it up for
    free) and the accepted result to the round's curiosity.jsonl.
    """
    wish = (wish or "").strip()
    if len(wish) < 3:
        return None
    t0 = time.time()
    try:
        out = common.ask_lane(
            "curious", SYSTEM, [{"role": "user", "content": _prompt(wish, context)}],
            schema=BRIEF_SCHEMA, lanes=LANES["curious"], ledger=ledger,
            num_predict=1400, temperature=0.5, timeout=timeout,
            capture_to=(round_dir / "calls.jsonl") if round_dir else None,
            purpose="curiosity",
        )
    except Exception as e:                      # noqa: BLE001 — curiosity never stops a round
        common.capture(round_dir / "curiosity.jsonl" if round_dir else Path("curiosity.jsonl"),
                       {"at": common.now_iso(), "wish": wish, "ok": False, "why": f"{type(e).__name__}: {e}"})
        return None

    brief = out.get("json") or common.extract_json(out.get("text", "")) or {}
    row = {"at": common.now_iso(), "wish": wish, "model": out.get("model"),
           "latency_s": round(time.time() - t0, 2), "brief": brief}

    if not brief:
        row.update(ok=False, why="no JSON in the reply")
    elif not _brief_is_about(wish, brief):
        # Kept as a labelled fault rather than dropped: "answered about something else" is exactly
        # the row that teaches a model not to do it.
        row.update(ok=False, why=f"answered about {brief.get('thing')!r}, which is not what Sam asked for")
    else:
        bad = _sane(brief)
        row.update(ok=not bad, **({"why": "; ".join(bad)} if bad else {}))

    if round_dir:
        common.capture(round_dir / "curiosity.jsonl", row)
    return brief if row.get("ok") else None


def as_note(brief: dict) -> str:
    """The brief as one line the builder can read, to append to a gap's `request`."""
    if not brief:
        return ""
    mm = brief.get("about_mm") or {}
    size = f"{mm.get('wide')}x{mm.get('tall')}x{mm.get('deep')}mm"
    made = ", ".join(brief.get("made_of") or [])
    parts = "; ".join(brief.get("parts") or [])
    return (f"[Sam asked: {brief.get('question','').strip()}] "
            f"{brief.get('thing')} — about {size}, made of {made}. Parts: {parts}. "
            f"Goes in the {brief.get('where_it_goes')}. "
            f"Right when: {brief.get('how_you_know_its_right')}")


# ─────────────────────────────────────────────────────────────── proof

def selftest() -> int:
    fails = 0

    def check(name, ok, detail=""):
        nonlocal fails
        print(("PASS  " if ok else "FAIL  ") + name + (("  — " + detail) if not ok and detail else ""))
        if not ok:
            fails += 1

    good = {"question": "how big is a crib, like as big as me?",
            "answer": "about half your height long",
            "thing": "crib", "about_mm": {"wide": 700, "tall": 950, "deep": 1300},
            "made_of": ["pine", "paint"],
            "parts": ["four corner posts", "two drop side rails", "a slatted base", "a mattress"],
            "where_it_goes": "nursery",
            "how_you_know_its_right": "the gap between bars is under 65mm"}

    check("a good brief passes the tape", _sane(good) == [], str(_sane(good)))
    check("a good brief is about what Sam asked for", _brief_is_about("i want a crib for the baby room.", good))
    check("a brief about the wrong thing is caught",
          not _brief_is_about("i want a crib", {**good, "thing": "wardrobe"}))
    check("metres pretending to be millimetres are caught",
          any("units are wrong" in b for b in _sane({**good, "about_mm": {"wide": 1, "tall": 1, "deep": 1}})))
    check("a ten-metre crib is caught",
          any("units are wrong" in b for b in _sane({**good, "about_mm": {"wide": 700, "tall": 950, "deep": 13000}})))
    check("a float where millimetres belong is caught",
          any("whole number" in b for b in _sane({**good, "about_mm": {"wide": 700.5, "tall": 950, "deep": 1300}})))
    check("two parts is not a thing", any("parts" in b for b in _sane({**good, "parts": ["a box", "a lid"]})))
    check("nine parts is not a thing", any("parts" in b for b in _sane({**good, "parts": ["p"] * 9})))
    check("made of nothing is caught", any("made_of" in b for b in _sane({**good, "made_of": []})))

    # THE SCHEMA LAW. This is the check that would have caught the bug that blinded the eyes.
    def bounds(node):
        if isinstance(node, dict):
            return (any(k in node for k in ("minimum", "maximum", "exclusiveMinimum",
                                            "exclusiveMaximum", "multipleOf"))
                    or any(bounds(v) for v in node.values()))
        if isinstance(node, list):
            return any(bounds(v) for v in node)
        return False
    check("the schema carries no numeric bounds, at any depth", not bounds(BRIEF_SCHEMA))

    # THE BUG OF 2026-09-14, in the one place it can be caught for free. `lanes=LANES` handed
    # ask_lane the whole {lane: [tags]} table; iterating a dict yields its keys, so the string
    # "curious" went to Ollama as a model name and every rung 404'd. Sam played ten nights and
    # asked not one question. A lane NAME never has a colon in it; a model tag always does.
    me = Path(__file__).read_text(encoding="utf-8")
    call = me.split("common.ask_lane(", 1)[1].split("purpose=", 1)[0]
    check("ask_lane is handed a ladder of tags, not the lane table",
          "lanes=LANES[" in call and "lanes=LANES," not in call, call.strip()[:150])
    check("every rung of the curious lane is a model tag, not a lane name",
          all(isinstance(t, str) and ":" in t for t in LANES["curious"]), str(LANES["curious"]))

    note = as_note(good)
    check("the note names the size in millimetres", "700x950x1300mm" in note, note)
    check("the note carries Sam's own question", "how big is a crib" in note)
    check("an empty brief makes an empty note", as_note({}) == "")
    check("a short wish is not worth a model call", wonder("hi") is None)

    print("\n" + ("ALL PASS" if fails == 0 else f"{fails} FAILED"))
    return fails


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(1 if selftest() else 0)
    if len(sys.argv) > 1:
        b = wonder(" ".join(a for a in sys.argv[1:] if not a.startswith("--")))
        print(json.dumps(b, indent=2) if b else "no brief")
    else:
        print(__doc__.strip().splitlines()[0])
        print("\n  python curiosity.py --selftest")
        print('  python curiosity.py "i want a crib for the baby room."')
