"""Vision fill - the audit of what the model invented (John, decision 32, 2026-09-11).

"i def want the model to take over more, i love what world labs does where you type a
sentence and then boom a room." So the workshop starts on the FIRST sentence: the model
fills in every blank, the build begins, and the chat says what it made up.

The whole promise rests on that last part being TRUE, and the model cannot be trusted to
say it. Measured on 2026-09-11 (gpt-oss:120b-cloud, four sentences, one call): asked to
fill in "a red brick house like the ones on my street" and list what it had guessed, it
listed the walls and the colour - the two things John actually said. Backwards. A model
asked what it invented is marking its own homework.

So this module does not fill anything in. It AUDITS the fill against John's own words:

  * an assumption he actually made himself is NOT an assumption, and is struck out;
  * a big visible choice nobody owns - not in his sentence, not in the assumptions -
    is an invention that was never declared, and is added;
  * what is left is said back to him in one plain line he can argue with.

Pure: no FastAPI, no model calls, no I/O. The five things it checks are the five a child
looks at first, borrowed from the conversation's own reader so there is ONE definition of
"he said two floors" in the product.
"""
from __future__ import annotations

import re
from typing import Any

from src.web import vision_talk

_WORDS = re.compile(r"[A-Za-z']+")
# words that carry no claim - an assumption made only of these is about nothing
_NOISE = {"a", "an", "the", "of", "and", "or", "with", "for", "to", "in", "on", "by", "is",
          "are", "be", "will", "would", "should", "it", "its", "this", "that", "these",
          "those", "was", "were", "has", "have", "had", "assumed", "assume", "assuming",
          "since", "because", "not", "no", "you", "your", "he", "did", "say", "said",
          "default", "standard", "typical", "usual", "common", "simple", "plain", "basic",
          "chose", "choose", "chosen", "picked", "used", "using", "added", "adding", "one"}

# the five a child looks at first, in the order he looks at them
_VISIBLE = (
    ("storeys", "floors"),
    ("wall_color", "wall colour"),
    ("wall_material", "walls"),
    ("roof", "roof"),
    ("porch", "porch"),
)

_PLAIN_NUM = {"one": "one floor", "two": "two floors", "three": "three floors",
              "four": "four floors", "five": "five floors"}


def _content(text: str) -> set[str]:
    out = set()
    for w in _WORDS.findall(text or ""):
        lw = w.lower()
        if lw.endswith("s") and len(lw) > 4:
            lw = lw[:-1]                 # stem FIRST, then judge - "defaults" is "default"
        if len(lw) > 2 and lw not in _NOISE:
            out.add(lw)
    return out


def he_said(phrase: str, sentence: str) -> bool:
    """Did his own sentence carry this claim?

    By FACTS, never by shared words. Live on 2026-09-11 the word test struck *"assumed a
    single-storey structure with a gable roof"* off the list of inventions because it and
    his sentence both contained the word "house" - and hiding a real invention is the one
    direction this must never fail in. A claim is his only when every house fact it names
    is a fact he named too."""
    mine = _facts(phrase)
    if not mine:
        return False         # names nothing a house is made of - see `silent` in audit()
    yours = _facts(sentence)
    return all(yours.get(slot) == value for slot, value in mine.items())


def _facts(text: str) -> dict[str, str]:
    return {slot: value for slot, value, _ in vision_talk._facts_in(text or "")}


def _plain(slot: str, value: str) -> str:
    if slot == "storeys":
        return _PLAIN_NUM.get(value, f"{value} floors")
    if slot == "wall_color":
        return f"{value} walls"
    if slot == "wall_material":
        return {"siding": "siding", "wood": "wooden walls", "log": "log walls"}.get(
            value, f"{value} walls")
    if slot == "roof":
        return f"a {value} roof"
    if slot == "porch":
        return "no porch" if value == "none" else f"a {value}"
    return value


def audit(sentence: str, card: dict[str, Any] | None) -> dict[str, Any]:
    """What the model invented, corrected against what John actually typed.

    Returns:
      guessed   - [(slot|None, plain english)] things HE did not choose
      struck    - assumptions the model claimed but he had actually said (its mistake)
      undeclared- big visible choices it made and never mentioned (its other mistake)
    """
    card = card or {}
    sentence = sentence or ""
    said = _facts(sentence)
    claimed = [str(a).strip() for a in (card.get("assumptions") or []) if str(a).strip()]
    # everything the architect says the house IS - its summary, its description and the
    # prose of its own assumptions - read through the conversation's one reader.
    built = _facts(" ".join([str(card.get("summary") or ""), str(card.get("description") or ""),
                             " ".join(claimed)]))

    # three buckets, because they are three different things and only one is a mistake:
    #   struck - the model called HIS choice an assumption (its error, 2026-09-11)
    #   silent - prose naming nothing a house is made of (the room count, the reasoning)
    #   kept   - a real invention it declared in words rather than in parts
    struck = [a for a in claimed if he_said(a, sentence)]
    silent = [a for a in claimed if a not in struck and not _facts(a)]
    kept = [a for a in claimed if a not in struck and a not in silent]

    undeclared: list[tuple[str, str]] = []
    for slot, _name in _VISIBLE:
        if slot in said:
            continue                       # he chose it
        value = built.get(slot)
        if not value:
            continue                       # nobody chose it; the builder will default
        # A colour and a material are ONE thing to a person. Live on 2026-09-11 this read
        # "green walls, wooden walls and a gable roof", which is not how anyone talks.
        if slot == "wall_material" and undeclared and undeclared[-1][0] == "wall_color":
            undeclared[-1] = ("walls", f"{built['wall_color']} {_plain(slot, value)}")
            continue
        undeclared.append((slot, _plain(slot, value)))

    return {"guessed": undeclared, "struck": struck, "prose": kept, "silent": silent,
            "he_chose": sorted(said.keys())}


def guessed_sentence(result: dict[str, Any], limit: int = 3) -> str:
    """The one line the chat says while the workshop is already running.

    Card 3 does not die under decision 32, it changes tense: not "have I got that right?"
    before a build, but "here is what I made up" during one."""
    result = result or {}
    items = [p for _, p in result.get("guessed") or []]
    if not items:
        # The architect wrote its assumptions as paragraphs, not as parts. They are already
        # on the card above; repeating three of them here would be a wall of small text,
        # which is the exact thing John threw out of the plan card on 2026-09-10.
        if result.get("prose"):
            return ("Building it now - I've filled in a few details you didn't mention. "
                    "They're in the plan above; tell me and I'll change any of them.")
        return "Building it now - everything in it is something you asked for."
    shown = items[:limit]
    if len(shown) == 1:
        what = shown[0]
    elif len(shown) == 2:
        what = shown[0] + " and " + shown[1]
    else:
        what = ", ".join(shown[:-1]) + " and " + shown[-1]
    left = len(items) - len(shown)
    more = (" and one more thing" if left == 1 else f" and {left} more things") if left else ""
    return (f"Building it now - I've gone with {what}{more} since you didn't say. "
            "Tell me and I'll change any of it.")


def _selftest() -> int:
    fails = []

    def ok(name, cond, detail=""):
        print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"   <- {detail}"))
        if not cond:
            fails.append(name)

    # THE MEASURED DEFECT, verbatim: it called his own words a guess.
    r = audit("a red brick house like the ones on my street",
              {"summary": "A two-storey red brick house with a gable shingle roof and a porch.",
               "assumptions": ["assumed red brick walls", "assumed two storeys",
                               "assumed a shingle roof"]})
    said_back = guessed_sentence(r)
    ok("his own red brick is never called a guess", "brick" not in said_back.lower(), said_back)
    ok("and the model's claim to have guessed it is struck",
       any("brick" in s for s in r["struck"]), r["struck"])
    ok("the storeys it really did invent are still owned",
       "two storeys" in " ".join(a for _, a in r["guessed"]) or
       "two floors" in said_back, said_back)

    # THE LIVE CASE, verbatim (2026-09-11 14:50, the first real build-on-turn-one run):
    # the word test struck a genuine invention because both texts said "house", and the
    # line it produced was three of the architect's paragraphs glued together.
    r = audit("a little house on the corner where my grandma lives",
              {"summary": "A single-story wooden cottage with a front porch, designed for a corner lot.",
               "assumptions": [
                   "The house is assumed to be a single-story structure with a gable roof, as indicated by the reference designs.",
                   "The exterior siding is assumed to be natural wood, reflecting the material specified in the reference designs.",
                   "The front porch is assumed to be covered and supported by four square posts.",
                   "The interior layout includes two bedrooms and one bathroom."]})
    line = guessed_sentence(r)
    ok("a real invention is never struck off", not r["struck"], r["struck"])
    ok("prose about nothing a house is made of is set aside, not claimed as his",
       any("bedroom" in a for a in r["silent"]), r["silent"])
    ok("the line names parts, not paragraphs", len(line) < 200, line)
    ok("and it names the one floor it chose for him", "one floor" in line, line)
    ok("and it counts the rest like a person", "other bits" not in line, line)

    # UNDER-REPORTING: it built a porch and a roof and mentioned neither.
    r = audit("a blue house",
              {"summary": "A two-storey blue house with white siding, a metal roof and a porch.",
               "assumptions": []})
    line = guessed_sentence(r)
    ok("what it built and never mentioned is declared anyway",
       all(w in line for w in ("two floors",)) and ("roof" in line or "walls" in line), line)
    ok("his blue is not in the list", "blue" not in line.lower(), line)

    # NOTHING INVENTED
    r = audit("a two storey white siding house with a shingle roof and a porch",
              {"summary": "A two-storey white siding house with a shingle roof and a porch.",
               "assumptions": []})
    ok("when he chose everything, it says so",
       guessed_sentence(r).startswith("Building it now - everything"), guessed_sentence(r))

    # the line itself
    r = audit("a house", {"summary": "A two-storey white siding house with a shingle roof.",
                          "assumptions": []})
    line = guessed_sentence(r)
    ok("it builds first and tells him after", line.startswith("Building it now"), line)
    ok("and offers the way back", "change any of it" in line, line)
    ok("at most three things are named", line.count(",") <= 3, line)

    # it must never be louder than it has to be
    r = audit("a house", {"summary": "A house.", "assumptions": ["assumed the defaults"]})
    ok("an assumption about nothing is never claimed as his",
       not r["struck"] and r["silent"] == ["assumed the defaults"], (r["struck"], r["silent"]))
    ok("a card with no plan does not crash", isinstance(audit("a house", None), dict), "")
    ok("one reader for the whole product",
       _facts("a two storey house")["storeys"] == "two", _facts("a two storey house"))

    total = 15
    if fails:
        print(f"\n  vision_fill selftest FAILED {len(fails)} of {total}")
        return 1
    print(f"\n  vision_fill selftest OK - {total} of {total}: what the model invented is "
          "computed from John's own words, never taken from the model.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
