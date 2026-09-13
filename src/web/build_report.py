"""Build report - nothing is silently dropped (John, decision 33, 2026-09-11).

"i dont care if its slow, i care if its complete."

Two different things go missing between what John types and what he can walk up to, and
before today only one of them was ever mentioned.

  1. WHAT THE WORKSHOP TRIED AND COULD NOT MAKE. The builder already knows this: its swap
     ledger plus status.json's `unbuilt_features` become `couldnt_sentence()`, which the
     page printed as "Couldn't use: you asked for 'a big porch' - the porch is 'porch'
     instead; could not build: red flowerpot." True, and written machine-to-machine, which
     is the defect John filed as card 9. `in_his_voice()` re-says it as the builder.

  2. WHAT THE PLAN PROMISED THAT THE WORKSHOP NEVER ATTEMPTS - and this one was invisible
     to every ledger in the product. On the first real build-on-turn-one run the architect
     planned three bedrooms, one bathroom, a covered porch on four square posts and a
     chimney; the workshop raises an OUTSIDE: storeys, walls, roof, and the small feature
     table it owns. The bedrooms were never tried, so they were never in `unbuilt_features`
     either. A thing nothing attempts cannot report its own absence - it has to be caught
     up front, from what the PLAN says, which is what `not_yet()` does.

Pure: no FastAPI, no model calls, no I/O.
"""
from __future__ import annotations

import re

# What the workshop raises today: an OUTSIDE. Everything here is something a plan happily
# describes and the builder has no helper for - so it must be declared, not quietly missed.
# Grouped because a person hears "the rooms inside" as one thing, not as six words.
_INSIDE = {
    "the rooms inside": r"\b(bedrooms?|bathrooms?|washrooms?|kitchens?|living\s+rooms?|dining\s+rooms?"
                        r"|hallways?|landings?|studys?|studies|offices?|nurser(y|ies)|interiors?"
                        r"|floor\s+plans?|layouts?|rooms?\s+inside)\b",
    "stairs": r"\b(stairs?|staircases?|stairways?|steps\s+inside)\b",
    "a basement": r"\b(basements?|cellars?|crawl\s*spaces?)\b",
    "an attic": r"\b(attics?|lofts?)\b",
    "furniture": r"\b(furniture|furnished|beds?|sofas?|couches?|tables?|chairs?|cupboards?|wardrobes?)\b",
    "a garden laid out": r"\b(flower\s*beds?|hedges?|lawns?\s+laid|landscap(ing|ed)|driveways?|patios?|decks?)\b",
    "the inside of the garage": r"\b(garage\s+interior|inside\s+the\s+garage)\b",
}
_INSIDE_RE = {name: re.compile(pat, re.I) for name, pat in _INSIDE.items()}


def not_yet(card: dict | None) -> list[str]:
    """Everything this plan promises that the workshop does not build at all, in the words
    a person would use. Read from the plan, because nothing downstream can ever report it."""
    card = card or {}
    text = " ".join(str(x) for x in [
        card.get("summary") or "", card.get("description") or "",
        " ".join(str(a) for a in (card.get("assumptions") or [])),
        " ".join(str(p) for p in (card.get("parts") or [])),
    ])
    return [name for name, rx in _INSIDE_RE.items() if rx.search(text)]


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return items[0] + " and " + items[1]
    return ", ".join(items[:-1]) + " and " + items[-1]


def not_yet_line(items: list[str]) -> str:
    """Said while the build is starting, never after - he should know before he walks up."""
    if not items:
        return ""
    return (f"One thing up front: {_join(items)} won't be real - I only build the outside so "
            "far, so that part of the plan is a drawing, not a place yet.")


_COULDNT_SWAP = re.compile(r"you asked for \"(.+?)\" - (.+?) is \"(.+?)\" instead", re.I)
_COULDNT_UNBUILT = re.compile(r"could not build: (.+?)(?:;|\.|$)", re.I)


def in_his_voice(couldnt: str | None) -> str:
    """The workshop's factual line, re-said by the builder John actually talks to.

    Card 9: not "Couldn't use: could not build: prominent front porch", but "I got
    everything except the front porch - the workshop is still learning that one." Nothing
    is softened away: every phrase in the original survives into the new sentence."""
    line = str(couldnt or "").strip()
    if not line:
        return ""
    swaps = _COULDNT_SWAP.findall(line)
    m = _COULDNT_UNBUILT.search(line)
    missing = [p.strip() for p in (m.group(1).split(",") if m else []) if p.strip()]
    bits = []
    if missing:
        bits.append(f"I got everything except {_join(missing)} - the workshop is still "
                    "learning those" if len(missing) > 1 else
                    f"I got everything except {missing[0]} - the workshop is still learning that one")
    for asked, place, used in swaps:
        bits.append(f"you asked for {asked} and I used {used} for {place} instead")
    if not bits:
        return ""
    out = ". ".join(b[0].upper() + b[1:] for b in bits)
    return out + ". It's on the list, so ask me again another day."


def promise_line(phrases: list[str] | None, message: str, filed: bool = True) -> str:
    """DECISION 34 / card 2/7 (John): "say, we need to build that for you, come back later.
    then go build it, label it, add it to the warehouse."

    A wish the world cannot grant is an ORDER placed with the factory, not a refusal and
    not a substitution. Found live on 2026-09-11: John typed "a little red car" and was
    answered "We can begin a room design whenever you describe the interior space you'd
    like to create." The order had ALREADY been filed - it was simply never said to him,
    which is the whole defect. This is the sentence that says it.

    `filed` is the truth of whether the order really reached the ledger; a promise that
    was not actually written down must never claim it was."""
    want = [str(p).strip() for p in (phrases or []) if str(p).strip()]
    what = _join(want) if want else str(message or "").strip().rstrip(".")
    if not what:
        return ""
    kept = ("I've put the order in, and it should be in the warehouse next time you ask."
            if filed else "I've written it down so it doesn't get lost.")
    return f"I can't make {what} yet - but I will. {kept}"


def _selftest() -> int:
    fails = []

    def ok(name, cond, detail=""):
        print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"   <- {detail}"))
        if not cond:
            fails.append(name)

    # THE LIVE CASE, verbatim (2026-09-11, the first build-on-turn-one run): the plan
    # promised rooms nothing ever tried to build, and no ledger in the product knew.
    card = {"summary": "A single-storey colonial bungalow of 671 x 1219 cm with three bedrooms, "
                       "one bathroom, a front porch, and classic wood clapboard siding.",
            "assumptions": ["The house will contain three bedrooms to accommodate a small family.",
                            "One full bathroom is deemed sufficient.",
                            "No attached garage is provided."]}
    items = not_yet(card)
    ok("the rooms nobody builds are caught", "the rooms inside" in items, items)
    line = not_yet_line(items)
    ok("and he is told before he walks up", line.startswith("One thing up front"), line)
    ok("in plain words", "a drawing, not a place yet" in line, line)
    ok("and it names them once, not six times", line.count("room") <= 2, line)

    ok("an outside-only plan says nothing", not_yet_line(not_yet(
        {"summary": "A two-storey white siding house with a shingle roof and a porch."})) == "", "")
    ok("furniture counts too", "furniture" in not_yet({"summary": "A furnished cottage with beds."}), "")
    ok("stairs count too", "stairs" in not_yet({"summary": "A house with a staircase to the loft."}), "")
    ok("no plan does not crash", not_yet(None) == [], "")

    # CARD 9 - the same facts, said by the builder instead of by the machine
    v = in_his_voice('you asked for "a big porch" - the porch is "porch" instead; '
                     'could not build: red flowerpot.')
    ok("the missing thing is named", "red flowerpot" in v, v)
    ok("the swap is named", "a big porch" in v and "porch" in v, v)
    ok("it does not sound like an error log", "Couldn't use" not in v and "could not build" not in v, v)
    ok("and it leaves the door open", "ask me again" in v, v)
    v2 = in_his_voice("could not build: red flowerpot, weather vane.")
    ok("two missing things read like a sentence", "red flowerpot and weather vane" in v2, v2)
    ok("nothing missing says nothing", in_his_voice(None) == "" and in_his_voice("") == "", "")

    # CARD 2/7 - the live case, verbatim
    v = promise_line([], "a little red car")
    ok("it names what he asked for", "a little red car" in v, v)
    ok("it promises rather than refusing", "but I will" in v, v)
    ok("and says where to find it", "warehouse" in v, v)
    ok("it never says the order is in when it is not",
       "warehouse" not in promise_line([], "a little red car", filed=False), "")
    ok("the router's own words are preferred when it has them",
       "weather vane" in promise_line(["weather vane"], "a house with a weather vane"), "")
    ok("two things read like a sentence",
       "a rocket and a trampoline" in promise_line(["a rocket", "a trampoline"], "x"), "")
    ok("nothing asked, nothing promised", promise_line([], "") == "", "")

    total = 21
    if fails:
        print(f"\n  build_report selftest FAILED {len(fails)} of {total}")
        return 1
    print(f"\n  build_report selftest OK - {total} of {total}: what the workshop never tries is "
          "declared up front, and what it tried and missed is said in the builder's own voice.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
