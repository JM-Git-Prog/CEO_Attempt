"""sim-player/furnish.py — Sam furnishes the house he built, room by room, talking it over with a friend.

John, 2026-09-11: *"He furnishes it, room by room. creating new objects, judging them, placing them,
talking to his friends (subagents or ollama cloud models) about good things to build."*
And: *"ideally the local model would be capable of having deeper conversations with Sam."*

THE POINT is not that Sam owns a sofa. A ten-year-old naming the things a real house needs, one at a
time, is the demand signal the factory has never had: every ask the shelf cannot answer becomes a
`capability-gaps` row, the gap router turns it into a prop job, and the catalogue's 210 object names
start becoming 210 things John has actually seen. Decision 24's always-on factory gets a customer.

THE FRIEND IS A CONVERSATION, NOT A LIST. Maya is another ten-year-old, played by JOHN'S OWN LOCAL
MODEL, and Sam actually talks to her — she answers in a sentence or two, suggests specific things,
and asks him questions back. What Sam then asks the app for comes OUT of that conversation, which is
why he ends up wanting a bunk bed with a slide instead of "bedroom furniture". `ideas()` reads the
buildable things back out of what was said; it never invents a want Sam and Maya did not talk about.

WHY LOCAL, against the usual cloud-first law: John asked for it, the loop already waits for a free
4090 before a round starts, and — the real argument — V17's architect (`qwen3.8:27b`) is already
resident with a 10-minute keep-alive while Sam plays, so the friend on that same tag costs no extra
VRAM at all. That makes local genuinely the cheapest rung here, not an exception to the law.

A friend who does not answer never stops the round: Sam falls back to what a kid already knows
(`KID_KNOWS`), because a ten-year-old does not need to be told a bedroom has a bed.

Pure module (rule E2): no I/O, no globals, no server — the caller injects `ask`.
The eleven rooms are the ones the Night Shift's catalogue carries
(E:\\...\\12-world-text-bench\\catalog\\room\\), so what Sam wants lands on the shelf's own taxonomy.
"""
from __future__ import annotations

import re

ROOMS = ["living room", "primary bedroom", "kitchen", "bathroom", "home office",
         "dining room", "garage", "nursery", "entry foyer", "laundry room", "patio"]

KID_KNOWS = {
    "living room": ["a big couch", "a TV", "a coffee table", "a lamp", "a rug", "a bookshelf"],
    "primary bedroom": ["a bed", "a dresser", "a nightstand", "a lamp", "a mirror", "a beanbag"],
    "kitchen": ["a fridge", "a stove", "a sink", "a kitchen table", "cupboards", "a microwave"],
    "bathroom": ["a bathtub", "a toilet", "a sink", "a mirror", "a towel rack", "a bath mat"],
    "home office": ["a desk", "a chair", "a computer", "a lamp", "a bookshelf", "a trash can"],
    "dining room": ["a dining table", "six chairs", "a big light", "a rug", "a cabinet"],
    "garage": ["a workbench", "a toolbox", "a bike", "shelves", "a garbage can"],
    "nursery": ["a crib", "a rocking chair", "a changing table", "a toy box", "a nightlight"],
    "entry foyer": ["a coat rack", "a bench", "a mirror", "a little table", "a door mat"],
    "laundry room": ["a washing machine", "a dryer", "a laundry basket", "a shelf", "an ironing board"],
    "patio": ["a picnic table", "chairs", "an umbrella", "a grill", "a plant pot"],
}

MAX_WORDS = 6
IDEAS_SCHEMA = {"type": "object", "properties": {"things": {"type": "array", "items": {"type": "string"}}},
                "required": ["things"]}
_WAYS = ("can I have {thing} in the {room}?", "put {thing} in the {room}", "the {room} needs {thing}",
         "I want {thing} in there", "add {thing}")
_STOP = re.compile(r"^(a|an|the|some|my|our)\s+", re.I)
_BAD = re.compile(r"\b(ideas?|maybe|think|cool|nice|awesome|something|stuff|anything|everything|things?)\b", re.I)


def _key(s: str) -> str:
    return _STOP.sub("", str(s or "").strip().lower()).rstrip("s")


_ROOM_KEYS = frozenset(_key(r) for r in ROOMS)


def clean(things, already=(), limit: int = 10) -> list[str]:
    """A list of buildable things, safe to hand a ten-year-old: short, concrete, deduped (against what
    was already asked for), no room names, no vague words."""
    seen = {_key(a) for a in already}
    out: list[str] = []
    for t in things or []:
        s = re.sub(r"\s+", " ", str(t or "")).strip().strip(".!,")
        if not s or len(s.split()) > MAX_WORDS or len(s) > 40 or _BAD.search(s):
            continue
        if _key(s) in _ROOM_KEYS or _key(s) in seen:          # "the kitchen" is a room, not a thing
            continue
        seen.add(_key(s))
        out.append(s)
        if len(out) >= limit:
            break
    return out


def friend_system(name: str = "Maya", room: str = "house") -> str:
    """Maya's whole character. She is a PERSON to talk to, not a list-returner."""
    return (f"You are {name}, ten years old, talking to your friend Sam. He is building a house in a game "
            f"and you are helping him decide what goes in the {room}. Talk like a real kid: one or two short "
            "sentences, never a list, never bullet points. Say ONE specific thing you think the room should "
            "have and why you like it — 'you need a bunk bed so your cousin can sleep over' — and sometimes "
            "ask Sam a question back about what he wants. Only real things that could actually be in a house; "
            "no magic, no dragons. Never explain the game, never talk like a grown-up or an assistant.")


IDEAS_SYSTEM = ("Read this conversation between two ten-year-olds about a room in a house. List ONLY the "
                "real, physical things they said should be in that room — the objects a builder could make. "
                "Use their own words, shortest form, under six words each, no room names, no feelings, no "
                'verbs. Reply as JSON only: {"things": ["a bunk bed", "a beanbag"]}.')


class Friend:
    """A second ten-year-old Sam actually talks to, on John's own local model.

    Holds the running conversation so it deepens instead of restarting each turn. Every method fails
    soft: a friend who goes quiet is a quiet friend, never a failed round."""

    def __init__(self, ask=None, name: str = "Maya", room: str = "house", remember: int = 10):
        self.ask, self.name, self.room, self.remember = ask, name, room, remember
        self.history: list[dict] = []
        self.model = "quiet"

    def enters(self, room: str) -> None:
        """A new room: keep the friendship, drop the old room's chatter."""
        self.room, self.history = room, []

    def say(self, sam_line: str) -> str:
        """Sam says something; Maya answers. "" when she has nothing to say (and Sam carries on)."""
        if self.ask is None or not str(sam_line or "").strip():
            return ""
        self.history.append({"role": "user", "content": str(sam_line).strip()})
        try:
            out = self.ask(friend_system(self.name, self.room), self.history[-self.remember:], None)
        except Exception:
            return ""
        text = str((out or {}).get("text") or "").strip() if isinstance(out, dict) else str(out or "").strip()
        text = re.sub(r"\s+", " ", text)[:300]
        if not text:
            return ""
        self.model = str((out or {}).get("model") or self.model) if isinstance(out, dict) else self.model
        self.history.append({"role": "assistant", "content": text})
        return text

    def ideas(self, already=()) -> list[str]:
        """The buildable things this conversation has actually named. Falls back to what a kid knows —
        never to nothing, so Sam always has something to ask for next."""
        floor = clean(KID_KNOWS.get(self.room, []), already)
        if self.ask is None or not self.history:
            return floor
        talk = "\n".join(f"{'Sam' if m['role'] == 'user' else self.name}: {m['content']}" for m in self.history)
        try:
            out = self.ask(IDEAS_SYSTEM, [{"role": "user", "content": f"The room is the {self.room}.\n{talk}"}], IDEAS_SCHEMA)
        except Exception:
            return floor
        js = (out or {}).get("json") if isinstance(out, dict) else None
        things = clean((js or {}).get("things") if isinstance(js, dict) else None, already)
        for t in floor:                                   # a short conversation is filled out, never replaced
            if len(things) >= 4:
                break
            if _key(t) not in {_key(x) for x in things}:
                things.append(t)
        return things

    def opener(self) -> str:
        """What Sam says to start talking about a room he has just walked into."""
        return f"I'm in the {self.room}. What should I put in here?"


def wish_for(thing: str, room: str, n: int = 0) -> str:
    """One thing, asked the way a ten-year-old asks the app for it."""
    return _WAYS[n % len(_WAYS)].format(thing=re.sub(r"\s+", " ", str(thing or "")).strip(), room=room)


def next_room(done=(), rooms=None) -> str | None:
    seen = {str(d).lower() for d in done}
    for r in (rooms or ROOMS):
        if r.lower() not in seen:
            return r
    return None


def room_done(asked, things, per_room: int = 4) -> bool:
    """One round furnishes a little of each room rather than all of one: a kid who asks for nine things
    in the kitchen never sees the bedroom, and the round is time-boxed."""
    return len(asked) >= min(per_room, max(1, len(things or [])))
