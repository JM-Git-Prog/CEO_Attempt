"""sim-player/remember.py — what Sam carries from one round to the next.

John, 2026-09-11, choosing the sim its own Pick Board: *"(assuming he will get smarter as it loops)"*.

HE DID NOT. That assumption was false when he wrote it, and this file is the honest fix. Every round
started Sam from zero: same persona, same empty head, so he asked for a house with a big porch twelve
nights running and would have asked for the same couch every night forever. What was getting smarter
was the APP (the mechanic patches it), the SHELF (the factory builds what he asked for) and the
STUDENT (it trains nightly) — never Sam.

Now he remembers, and only what a ten-year-old would actually remember:
  * the things he asked for and GOT — he does not ask twice,
  * the things he asked for and NEVER got — he pushes on them, and gives up after three nights,
  * the rooms he has already filled — he starts in a new one,
  * what he thought of the last house he built — so his next order is not identical,
  * how many nights he has played.

It is deliberately small and forgetful. A memory that remembers everything makes an expert, and an
expert is no longer a first-time user — the whole value of Sam is that he is new. `GIVE_UP_AFTER`
nights of not getting a thing and he stops asking; `FORGET_ROOMS_AFTER` rounds and the house feels
new enough to walk through again.

Pure module (rule E2): one JSON file, read and written whole, no server, no model.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GIVE_UP_AFTER = 3          # nights of asking for the same thing and never getting it
FORGET_ROOMS_AFTER = 6     # rounds before a furnished room is worth walking through again
KEEP_WANTS = 60            # the head of a ten-year-old, not a database
_STOP = re.compile(r"^(a|an|the|some|my|our)\s+", re.I)


def _key(s: str) -> str:
    return _STOP.sub("", str(s or "").strip().lower()).rstrip("s")


def blank() -> dict:
    # `lessons` arrived 2026-09-14 with the 20-round batch. Everything else in this head is a LIST
    # OF THINGS - what he has, what he is chasing, what he gave up on - and a list of things cannot
    # explain why he keeps missing. A lesson is the one sentence consolidate.py boils twenty nights
    # down to, and it is the only part of his head that is about HOW he asks rather than WHAT he
    # wants. It must be listed here or load() drops it on the next read.
    return {"nights": 0, "wants": {}, "rooms": {}, "houses": [], "lessons": [], "version": 1}


def load(path: Path) -> dict:
    """Sam's head. A missing or corrupt file is an empty head, never an error — he is ten."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return blank()
    if not isinstance(d, dict):
        return blank()
    out = blank()
    out.update({k: v for k, v in d.items() if k in out and isinstance(v, type(out[k]))})
    return out


def save(path: Path, mem: dict) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(mem, indent=1, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def remember_round(mem: dict, *, things: list[dict], got: list[str], rooms: list[str], house: str | None = None) -> dict:
    """Fold one round into the head. `things` are what he asked for ({room, thing}); `got` are the ones
    that actually appeared. Returns the same dict, updated."""
    mem = dict(mem or blank())
    mem["nights"] = int(mem.get("nights") or 0) + 1
    night = mem["nights"]
    got_keys = {_key(g) for g in got or []}
    wants = dict(mem.get("wants") or {})
    for t in things or []:
        thing = str((t or {}).get("thing") or "").strip()
        if not thing:
            continue
        k = _key(thing)
        w = wants.get(k) or {"thing": thing, "room": (t or {}).get("room"), "asked": 0, "missed": 0, "got": False}
        w["asked"] = int(w.get("asked") or 0) + 1
        if k in got_keys:
            w["got"] = True
            w["missed"] = 0
        elif not w.get("got"):
            w["missed"] = int(w.get("missed") or 0) + 1
        w["last_night"] = night
        wants[k] = w
    # a ten-year-old's head, not a database: keep what he got and what he is still chasing, newest first
    keep = sorted(wants.values(), key=lambda w: (-(w.get("last_night") or 0), w.get("thing") or ""))[:KEEP_WANTS]
    mem["wants"] = {_key(w["thing"]): w for w in keep}
    rm = dict(mem.get("rooms") or {})
    for r in rooms or []:
        if r:
            rm[str(r)] = night
    mem["rooms"] = rm
    if house:
        mem["houses"] = ([*mem.get("houses", []), str(house)])[-5:]
    return mem


def already_have(mem: dict) -> list[str]:
    """Things he asked for and got — he does not ask for them again."""
    return [w["thing"] for w in (mem.get("wants") or {}).values() if w.get("got")]


def still_chasing(mem: dict) -> list[str]:
    """Things he asked for and never got, and has not given up on. These are what he pushes on."""
    return [w["thing"] for w in (mem.get("wants") or {}).values()
            if not w.get("got") and 0 < int(w.get("missed") or 0) < GIVE_UP_AFTER]


def gave_up_on(mem: dict) -> list[str]:
    """What he stopped asking for. The most valuable list on the board: it is what the app never made."""
    return [w["thing"] for w in (mem.get("wants") or {}).values()
            if not w.get("got") and int(w.get("missed") or 0) >= GIVE_UP_AFTER]


def rooms_to_skip(mem: dict) -> list[str]:
    """Rooms he filled recently enough that he would start somewhere else tonight."""
    night = int(mem.get("nights") or 0)
    return [r for r, n in (mem.get("rooms") or {}).items() if night - int(n or 0) < FORGET_ROOMS_AFTER]


def opening_line(mem: dict) -> str:
    """What Sam knows when he sits down. "" on his first night — he is new, and that matters."""
    if not int(mem.get("nights") or 0):
        return ""
    bits = [f"You have played this {mem['nights']} time" + ("s" if mem["nights"] > 1 else "") + " before."]
    have = already_have(mem)
    if have:
        bits.append("You already have: " + ", ".join(have[:8]) + ".")
    chasing = still_chasing(mem)
    if chasing:
        bits.append("You asked for these before and never got them: " + ", ".join(chasing[:5]) +
                    ". Ask again — you still want them.")
    gone = gave_up_on(mem)
    if gone:
        bits.append("You gave up on: " + ", ".join(gone[:5]) + ". Do not ask for those again.")
    if mem.get("houses"):
        bits.append(f"Last time you built: {mem['houses'][-1]}. Build something different this time.")
    # The last lesson, last — it is the thing he should be holding as he starts, and the closest
    # line to the top of his head is the one he reads first.
    lessons = mem.get("lessons") or []
    if lessons and str(lessons[-1].get("lesson") or "").strip():
        bits.append("Last time you worked something out: " + str(lessons[-1]["lesson"]).strip())
    return " ".join(bits)


def selftest() -> int:
    import tempfile
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (("  — " + detail) if detail and not ok else ""))
        if not ok:
            fails.append(name)

    print("remember self-test")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "sam-head.json"
        check("a missing head is an empty head", load(p) == blank())
        p.write_text("{not json", encoding="utf-8")
        check("a corrupt head is an empty head", load(p) == blank())
        p.write_text('["a list"]', encoding="utf-8")
        check("a head of the wrong shape is an empty head", load(p) == blank())

        check("night one has nothing to say", opening_line(blank()) == "")

        m = blank()
        m = remember_round(m, things=[{"room": "living room", "thing": "a big couch"},
                                      {"room": "living room", "thing": "a TV"}],
                           got=["a big couch"], rooms=["living room"], house="a house with a big porch")
        check("one night played", m["nights"] == 1, str(m["nights"]))
        check("what he got is remembered", already_have(m) == ["a big couch"], str(already_have(m)))
        check("what he missed is still chased", still_chasing(m) == ["a TV"], str(still_chasing(m)))
        check("the room he filled is skipped", rooms_to_skip(m) == ["living room"], str(rooms_to_skip(m)))

        save(p, m)
        check("a saved head loads back", load(p)["nights"] == 1)

        while m["wants"][_key("a TV")]["missed"] < GIVE_UP_AFTER - 1:      # one short of giving up
            m = remember_round(m, things=[{"room": "living room", "thing": "a TV"}], got=[], rooms=[])
        check("still chasing right up to the limit", "a TV" in still_chasing(m), str(still_chasing(m)))
        m = remember_round(m, things=[{"room": "living room", "thing": "a TV"}], got=[], rooms=[])
        check("he gives up after three misses", gave_up_on(m) == ["a TV"], str(gave_up_on(m)))
        check("what he gave up on is no longer chased", still_chasing(m) == [], str(still_chasing(m)))

        line = opening_line(m)
        check("the opening line says what he has", "a big couch" in line, line)
        check("the opening line says what to stop asking for", "a TV" in line and "not ask" in line, line)
        check("the opening line names the last house", "big porch" in line, line)

        m2 = remember_round(blank(), things=[{"room": "kitchen", "thing": "the fridge"}],
                            got=["A Fridge"], rooms=["kitchen"])
        check("'the fridge' and 'A Fridge' are the same thing", already_have(m2) == ["the fridge"], str(already_have(m2)))

        m3 = blank()
        for i in range(FORGET_ROOMS_AFTER + 1):
            m3 = remember_round(m3, things=[], got=[], rooms=["kitchen"] if i == 0 else [])
        check("a room goes stale and is worth walking again", rooms_to_skip(m3) == [], str(rooms_to_skip(m3)))

        m4 = blank()
        m4 = remember_round(m4, things=[{"room": "patio", "thing": f"thing {i}"} for i in range(KEEP_WANTS + 20)],
                            got=[], rooms=[])
        check("the head stays a kid's head, not a database", len(m4["wants"]) == KEEP_WANTS, str(len(m4["wants"])))

        save(Path(td) / "nope" / "deep" / "head.json", m)
        check("saving into a new folder works", (Path(td) / "nope" / "deep" / "head.json").exists())

    print("ALL GREEN" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
