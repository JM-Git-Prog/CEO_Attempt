"""Vision talk - the conversation before the build (John, 2026-09-10): "it needs to
understand and ask questions to collect the data needed to build what I want,
conversational... we discuss my vision, then when i click enter, my v17 backend
builds it." Pure module: no FastAPI, no model calls. Holds one running "vision" per
session and answers what v17_say_routes.py needs: is this sentence a build command,
a reset, or more vision; the running summary; the whole vision as one brief for the
builder; and the next question to ask.

2026-09-11 - John's ten cards (board 0h). Two of them land here.

  CARD 5, A CHANGE OF MIND REPLACES, OUT LOUD. Until today every sentence was
  APPENDED, so "a yellow house" followed by "actually blue" handed the builder BOTH
  and the finished house could match neither. His own sixty-turn batch caught the
  chat noticing ("...but now you want it blue") while the ORDER did not. Now every
  line is read for the few facts a house is made of; a new value for a fact he has
  already given REPLACES the old one AT THE PLACE HE FIRST SAID IT; and the swap is
  handed back to the caller so it can be said out loud in the same breath.
  The verbatim transcript is never rewritten (capture law): `lines` still holds every
  word he typed. `brief_lines` is the corrected rendering - the one that reaches the
  builder - and it is the only thing a correction touches.

  CARD 3, CONFIRM BEFORE BUILDING. The conversation no longer trails off with "say
  build it whenever you like". It reads the order back in one plain sentence and
  waits for a yes. The sentence it reads back IS `brief_text()`, the very words the
  builder is handed, because a confirmation that differs from the order is a lie.
"""
from __future__ import annotations

import re
import time
from typing import Any

Vision = dict[str, Any]
_visions: dict[str, Vision] = {}


# --------------------------------------------------------------------------- state

def open_vision(session: str, first_line: str) -> Vision:
    v: Vision = {
        "session": session,
        "lines": [],          # verbatim, never rewritten - the capture law
        "brief_lines": [],    # the same lines, corrected: what the builder is handed
        "facts": {},          # slot -> {value, phrase, line}
        "changes": [],        # every change of mind this session
        "last_changes": [],   # the ones from the most recent line, for the reply
        "asked": [],
        "topics_asked": [],   # card 1: his subjects, so none is chased twice
        "answers": [],
        "confirm_pending": False,
        "opened": time.time(),
    }
    _visions[session] = v
    _absorb(v, first_line)
    return v


def get(session: str) -> Vision | None:
    return _visions.get(session)


def add(session: str, line: str) -> Vision | None:
    v = _visions.get(session)
    if v is not None:
        _absorb(v, line)
    return v


def close(session: str) -> None:
    _visions.pop(session, None)


# ------------------------------------------------------------------- what he said

_NUM = r"(a|single|one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
_STOREY_RE = re.compile(rf"\b{_NUM}\b[\s-]{{0,2}}(storeys?|storys?|stories|floors?|levels?)\b", re.I)
_MATERIAL_RE = re.compile(r"\b(?:of\s+)?(brick|siding|plaster|stone|stucco|wood|log)\b", re.I)
_ROOF_CUE_RE = re.compile(r"\b(roofs?|shingles?|tiles?|tiled|gabled?|hipped)\b", re.I)
_ROOF_KIND_RE = re.compile(r"\b(shingles?|metal|tin|slate|thatch|flat|clay|tiles?|tiled|gabled?|hipped|hip)\b", re.I)
_PORCH_RE = re.compile(r"\b(?:a |an |the )?(porch|veranda|verandah|garage|carport)\b", re.I)
_NO_PORCH_RE = re.compile(r"\b(?:no|without(?: a| an)?|not?)\s+(?:\w+\s+){0,2}?(?:porch|veranda|garage|carport)\b|\bneither\b", re.I)
_COLORS = "red|white|black|blue|green|yellow|brown|grey|gray|beige|tan|cream|orange|purple|pink|gold|silver"
_COLOR_RE = re.compile(rf"\b({_COLORS})\b", re.I)
_COLOR_WORDS = set(_COLORS.split("|"))
# "flower" has no trailing boundary so it also catches John's own "flowerpot" (one word).
# He SAID he changed his mind, rather than it falling out of an answer.
_EXPLICIT_RE = re.compile(r"\b(actually|instead|rather|no|nope|not|change[d]?|scrap|forget|"
                          r"nevermind|never mind|wait|make it|switch|sorry)\b", re.I)
_YARD_RE = re.compile(r"\bflower|\b(pot|swing|flag|bench|tree|fence|mailbox|path|slide|sandbox|pond)\b", re.I)

_WALL_NOUNS = {"house", "houses", "home", "homes", "wall", "walls", "siding", "brick", "bricks",
               "stone", "stucco", "plaster", "exterior", "outside", "place", "building", "cottage"}
# A colour hung on one of these names nothing: what it means depends entirely on what was
# just asked. "a red one" after "what colour should the swing be?" is a red SWING.
_PRONOUNS = {"it", "one", "ones", "thing", "them", "those", "that", "this"}
_ROOF_NOUNS = {"roof", "roofs", "shingle", "shingles", "tile", "tiles"}
_DOOR_NOUNS = {"door", "doors", "doorway"}
# words a colour may sit in front of without them being the thing that is coloured
_PASSTHRU = {"and", "with", "the", "a", "an", "or", "of", "in", "on", "by", "to", "is", "are", "be",
             "for", "that", "this", "very", "really", "like", "please", "also", "some", "its",
             "would", "want", "make", "made", "paint", "painted", "colour", "color", "coloured",
             "colored", "big", "small", "little", "nice", "new", "old", "tall", "wide", "huge",
             "pretty", "bright", "dark", "light", "kind", "sort", "metal", "tin", "slate", "clay",
             "thatch", "wood", "wooden", "flat", "storey", "storeys", "story", "stories", "floor",
             "floors", "level", "levels", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine", "ten", "put", "add", "give", "build", "use", "need", "have",
             "get", "keep", "do", "go", "having", "adding"}
_FILLER = {"actually", "no", "not", "nope", "make", "made", "it", "the", "a", "an", "change",
           "changed", "to", "instead", "lets", "let", "i", "id", "want", "wanted", "please",
           "rather", "wait", "sorry", "and", "but", "now", "be", "should", "could", "would",
           "house", "home", "place", "one", "on", "its", "we", "you", "my", "mine", "yeah",
           "yep", "ok", "okay", "um", "hmm", "think", "second", "thought", "thoughts", "better",
           "prefer", "like", "them", "then", "of", "is", "are", "with", "in", "for", "that",
           "this", "kind", "sort", "colour", "color", "paint", "painted", "do", "just", "really"}

_WORDS = re.compile(r"[A-Za-z']+")
_CLAUSE_BREAK = re.compile(r"[,.;:!?]|\b(?:and|but|then|plus|also|with|while|so|because)\b", re.I)
_DIGIT_WORD = {"1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
               "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
               "single": "one", "a": "one"}


def _num_word(tok: str) -> str:
    t = (tok or "").strip().lower()
    return _DIGIT_WORD.get(t, t)


def _fold(value: str) -> str:
    """Same meaning, one spelling - so "grey"/"gray" and "shingle"/"shingles" never
    look like a change of mind."""
    v = (value or "").strip().lower()
    if v == "gray":
        return "grey"
    if v in ("tiled", "tiles"):
        return "tile"
    if v in ("gabled",):
        return "gable"
    if v in ("hip",):
        return "hipped"
    if v.endswith("s") and len(v) > 3 and not v.endswith("ss"):
        v = v[:-1]
    return v


def _color_slot(text: str, m: re.Match) -> tuple[str, bool]:
    """WHICH thing is this colour about. A colour with no owner is about the walls;
    a colour sitting in front of a flowerpot is about the flowerpot and must never
    overwrite the colour of the house - that was the bug that would have made every
    "red flowerpot" repaint a blue house."""
    # A clause break ends the colour's reach: in "actually blue, and put a swing in the
    # yard" the blue belongs to the house he was talking about, not to the swing.
    tail = _CLAUSE_BREAK.split(text[m.end():], 1)[0]
    for w in _WORDS.findall(tail)[:5]:
        lw = w.lower()
        if lw in _WALL_NOUNS:
            return "wall_color", True
        if lw in _ROOF_NOUNS:
            return "roof_color", True
        if lw in _DOOR_NOUNS:
            return "door_color", True
        if lw in _PRONOUNS:
            return "wall_color", False        # he named nothing - the caller decides
        if lw in _PASSTHRU or lw in _COLOR_WORDS:
            continue
        if len(lw) > 2:
            return "color:" + _fold(lw), True
    for w in reversed(_WORDS.findall(text[:m.start()])[-5:]):
        lw = w.lower()
        if lw in _WALL_NOUNS:
            return "wall_color", True
        if lw in _ROOF_NOUNS:
            return "roof_color", True
        if lw in _DOOR_NOUNS:
            return "door_color", True
    return "wall_color", False


def _facts_in(text: str, default_color_slot: str = "wall_color") -> list[tuple[str, str, str]]:
    """(slot, value, the exact words he used) for every house fact in one line.
    Yard things are deliberately absent: a swing and a flag both belong in a yard, so
    they are additive and can never be a change of mind."""
    out: list[tuple[str, str, str]] = []
    m = _STOREY_RE.search(text)
    if m:
        out.append(("storeys", _num_word(m.group(1)), m.group(0)))
    m = _MATERIAL_RE.search(text)
    if m:
        out.append(("wall_material", _fold(m.group(1)), m.group(1)))
    if _ROOF_CUE_RE.search(text):
        m = _ROOF_KIND_RE.search(text)
        if m:
            out.append(("roof", _fold(m.group(1)), m.group(1)))
    m = _NO_PORCH_RE.search(text)
    if m:
        out.append(("porch", "none", m.group(0)))
    else:
        m = _PORCH_RE.search(text)
        if m:
            out.append(("porch", _fold(m.group(1)), m.group(0)))
    for m in _COLOR_RE.finditer(text):
        slot, sure = _color_slot(text, m)
        out.append((slot if sure else default_color_slot, _fold(m.group(1)), m.group(0)))
    return out


def _swap(line: str, old_phrase: str, new_phrase: str) -> str:
    if not old_phrase:
        return line
    i = line.lower().find(old_phrase.lower())
    if i < 0:
        return line
    return line[:i] + new_phrase + line[i + len(old_phrase):]


def _strip_once(line: str, phrase: str) -> str:
    if not phrase:
        return line
    i = line.lower().find(phrase.lower())
    if i < 0:
        return line
    return line[:i] + " " + line[i + len(phrase):]


def _substantive(text: str) -> bool:
    return any(w.lower() not in _FILLER and len(w) > 1 for w in _WORDS.findall(text))


def _absorb(v: Vision, line: str) -> None:
    text = (line or "").strip()
    v["lines"].append(text)
    v["brief_lines"].append(text)
    idx = len(v["lines"]) - 1
    v["confirm_pending"] = False      # a new sentence always re-opens the order
    # CARD 1's payoff: if the last thing asked was about his swing, then "a red one" is a
    # red SWING, not red siding. The question he is answering disambiguates the answer.
    topic = v.pop("open_topic", None)
    # Kept for the reply: the model must be told WHAT he is answering about, or it will
    # repeat "a red one" back to him as a red HOUSE while the order says a red swing.
    v["answering_topic"] = topic
    default_color = ("color:" + _fold(topic)) if topic else "wall_color"
    changes: list[dict] = []
    added: list[str] = []
    landed_on_new = False

    for slot, value, phrase in _facts_in(text, default_color):
        if slot not in v["facts"]:
            added.append(slot)
        old = v["facts"].get(slot)
        if old is None or _fold(old["value"]) == _fold(value):
            v["facts"][slot] = {"value": value, "phrase": phrase, "line": idx}
            continue
        # A CHANGE OF MIND. Correct the order where he first said it, so the builder
        # is handed one answer and not two.
        oi = int(old.get("line", idx))
        if 0 <= oi < len(v["brief_lines"]) and v["brief_lines"][oi].strip() and oi != idx:
            v["brief_lines"][oi] = _swap(v["brief_lines"][oi], old["phrase"], phrase)
            target = oi
        else:
            target = idx
            landed_on_new = True
        changes.append({"slot": slot, "from": old["value"], "to": value,
                        "from_phrase": old["phrase"], "to_phrase": phrase})
        v["facts"][slot] = {"value": value, "phrase": phrase, "line": target}

    if changes and not landed_on_new:
        remainder = text
        for c in changes:
            remainder = _strip_once(remainder, c["to_phrase"])
        if not _substantive(remainder):
            # "actually blue" carried nothing but the correction, and the correction has
            # already been made where he first said it. Keeping it would hand the builder
            # the word twice.
            v["brief_lines"][idx] = ""

    v["last_added"] = added
    v["last_changes"] = changes
    v["last_change_explicit"] = bool(changes) and bool(_EXPLICIT_RE.search(text))
    v["changes"].extend(changes)


# ------------------------------------------------------------------ what he meant

def _normalize(text: str) -> str:
    """"Build it!" and "build it." both become "build it" - case/punctuation-insensitive."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", (text or "").lower())).strip()


_BUILD_PHRASES = {
    "build it", "build", "go", "go build it", "thats it", "do it", "make it",
    "ok build", "yes build it", "build it now", "lets build",
}
_RESET_PHRASES = {"start over", "forget that", "new house", "scrap it"}
# Card 3: after the order has been read back, a plain yes IS the go-ahead. Only ever
# consulted while a confirmation is on the table, so a stray "yes" mid-conversation is
# still just another thing he said.
_YES_PHRASES = {
    "yes", "yep", "yeah", "yup", "y", "sure", "ok", "okay", "okey", "yes please",
    "please", "please do", "go ahead", "go for it", "thats right", "that is right",
    "correct", "right", "perfect", "sounds good", "looks good", "great", "lets go",
    "do it please", "yes do it", "yes go", "uh huh", "mhm", "mm hm", "aye",
}


def is_build_command(text: str) -> bool:
    """The phrase ALONE - "build it with a red door" is more vision, not a command."""
    return _normalize(text) in _BUILD_PHRASES


def is_reset_command(text: str) -> bool:
    return _normalize(text) in _RESET_PHRASES


def is_yes(text: str) -> bool:
    return _normalize(text) in _YES_PHRASES


# ------------------------------------------------------------------ what he is told

def _clause(line: str) -> str:
    s = line.strip()
    if s.endswith("."):
        s = s[:-1]
    return (s[0].lower() + s[1:]) if s else s


def summary(vision: Vision) -> str:
    """The running summary shows the CORRECTED order, not the transcript - otherwise a
    change of mind would still be shown to him as two answers."""
    src = vision.get("brief_lines") or vision.get("lines", [])
    clauses = [c for c in (_clause(l) for l in src) if c]
    return ("So far: " + " - ".join(clauses))[:400]


def brief_text(vision: Vision) -> str:
    """Every word he still means, as one sentence - nothing summarised away, and
    nothing he changed his mind about left in."""
    src = vision.get("brief_lines") or vision.get("lines", [])
    lines = [l.strip() for l in src if l and l.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    return lines[0] + "; also: " + "; ".join(lines[1:])


_SLOT_NAMES = {"wall_color": "the walls", "wall_material": "the walls", "roof": "the roof",
               "roof_color": "the roof", "door_color": "the door", "storeys": "the floors",
               "porch": "the porch"}


def slot_name(slot: str) -> str:
    if slot in _SLOT_NAMES:
        return _SLOT_NAMES[slot]
    if slot.startswith("color:"):
        return "the " + slot.split(":", 1)[1]
    return "that"


def change_text(changes: list[dict] | None, explicit: bool = True) -> str:
    """Card 5's "out loud" half, said by the code rather than hoped for from the model,
    because the whole point is that he can trust it happened.

    Two voices, because they are two different events. When he SAYS he has changed his
    mind ("actually blue"), that is a decision and it is confirmed as one. When the
    change only falls out of answering a question - asked what colour the walls are, he
    says "white siding" over an earlier "yellow house" - he may not realise he has
    overwritten anything, so he is told plainly and given the way back. Live on
    2026-09-11 the second case was being announced in the first voice, which reads like
    being told you said something you never said."""
    if not changes:
        return ""
    bits = [f"{c['to']} instead of {c['from']}" for c in changes]
    if len(bits) == 1:
        swap = bits[0]
    elif len(bits) == 2:
        swap = bits[0] + " and " + bits[1]
    else:
        swap = ", ".join(bits[:-1]) + ", and " + bits[-1]
    if explicit:
        return f"Right - {swap}; I've changed it in the plan, so the old one is gone."
    where = slot_name(changes[0]["slot"]) if len(changes) == 1 else "the plan"
    olds = changes[0]["from"] if len(changes) == 1 else "what was there"
    return (f"I've put {swap} down for {where} - say the word if you'd rather keep "
            f"the {olds}.")


def worth_rebuilding(vision: Vision) -> bool:
    """DECISION 32: once a house exists, a sentence that changes or adds something is a
    CHANGE ORDER and goes straight back to the workshop. A sentence that adds nothing -
    "nice", "thanks", "what do you think" - is just talk, and must never cost a rebuild."""
    return bool(vision.get("last_changes") or vision.get("last_added"))


def confirm_text(vision: Vision) -> str:
    """Card 3. The read-back IS the order: these are the exact words the builder gets."""
    b = brief_text(vision).strip().rstrip(".")
    if not b:
        return "Tell me about the place you want and I'll read it back to you before I build it."
    return f"So - {b}. Have I got that right? Say yes and I'll build it."


# --------------------------------------------------------------- what to ask next

# CARD 1 (John, 2026-09-11): "follow him first". The five below are a BACKSTOP, not the
# driver. His own sixty-turn batch asked "How many floors?" on 44 of 60 turns - after a
# swing, after a flag, after "the house should be blue" - because the code walked this
# list and the model was only ever allowed to reword whichever item was next. It could
# not ask about the swing. Now the model asks about the thing he just mentioned, and the
# code's only job is to GUARANTEE that the builder still ends up with what it needs:
# a free follow-up is allowed only while there is still room in the budget for every
# required answer afterwards.
_QUESTION_BUDGET = 6

_QUESTIONS = (  # the backstop, in priority order - the first uncovered, unasked one
    ("storeys", "How many floors should it have - one, two, or three?"),
    ("wall", "What are the outside walls made of, and what colour - like white siding or red brick?"),
    ("roof", "What kind of roof - shingles, metal, or flat?"),
    ("porch", "Should it have a porch or a garage? Or neither?"),
    ("yard", "Anything in the yard or by the door - a flowerpot, a swing, a flag?"),
)


def _mentioned(key: str, text: str) -> bool:
    """Kept for callers that only have the raw text. `_covered` is the accurate one."""
    if key == "storeys":
        return bool(_STOREY_RE.search(text))
    if key == "wall":
        return bool(_MATERIAL_RE.search(text) or _COLOR_RE.search(text))
    if key == "roof":
        return bool(_ROOF_CUE_RE.search(text))
    if key == "porch":
        return bool(_PORCH_RE.search(text) or _NO_PORCH_RE.search(text))
    return bool(_YARD_RE.search(text))


def _covered(key: str, vision: Vision) -> bool:
    f = vision.get("facts") or {}
    if key == "storeys":
        return "storeys" in f
    if key == "wall":
        return "wall_color" in f or "wall_material" in f
    if key == "roof":
        return "roof" in f or "roof_color" in f
    if key == "porch":
        return "porch" in f
    return bool(_YARD_RE.search(" ".join(vision.get("lines", []))))


def still_needed(vision: Vision) -> list[str]:
    """Uncovered, unasked fields, in priority order - the same question never repeats."""
    asked = set(vision.get("asked", []))
    return [q for key, q in _QUESTIONS if not _covered(key, vision) and q not in asked]


def next_question(vision: Vision) -> str | None:
    """The next REQUIRED thing to ask, or None once covered or the budget is spent -
    None is the signal to read the order back (card 3), never to trail off."""
    if len(vision.get("asked", [])) >= _QUESTION_BUDGET:
        return None
    needed = still_needed(vision)
    return needed[0] if needed else None


# ---------------------------------------------------------- card 1: follow him first

_KNOWN = (_WALL_NOUNS | _ROOF_NOUNS | _DOOR_NOUNS | _PASSTHRU | _FILLER | _COLOR_WORDS | {
    "storeys", "storey", "story", "stories", "floors", "floor", "levels", "level",
    "porch", "porches", "veranda", "verandah", "garage", "garages", "carport",
    "shingle", "shingles", "roof", "roofs", "yard", "yards", "garden", "front", "back",
    "side", "left", "right", "corner", "street", "there", "here", "want", "like", "look",
    "looks", "make", "build", "please", "maybe", "something", "anything", "everything",
    "nothing", "yes", "yeah", "sure", "actually", "really", "quite", "about", "around",
    "over", "under", "near", "next", "outside", "inside", "upstairs", "downstairs",
    "windows", "window", "walls", "wall", "colour", "color", "material", "materials",
})


def follow_topic(vision: Vision) -> str | None:
    """The thing he JUST brought up that nobody has asked him about yet.

    A yard thing he named ("a swing", "a flag") first, because those are the ones the
    old code was deaf to; then any word the product simply does not know - "a treehouse",
    "a basketball hoop" - which is exactly where he felt ignored. Never the same topic
    twice, and never something already answered."""
    lines = vision.get("lines") or []
    if not lines:
        return None
    last = lines[-1]
    done = {t.lower() for t in vision.get("topics_asked", [])}

    m = _YARD_RE.search(last)
    if m:
        word = (m.group(0) or "").strip().lower()
        # "\bflower" matches the front of John's own one-word "flowerpot"
        if word == "flower":
            tail = last[m.start():].split()[0].strip(".,!?;:").lower()
            word = tail or word
        if word and word not in done:
            return word

    toks = [w for w in _WORDS.findall(last)]
    run: list[str] = []
    for w in toks:
        lw = w.lower()
        if len(lw) >= 4 and lw not in _KNOWN:
            run.append(lw)
            if len(run) == 2:
                break
        elif run:
            break
    if run:
        phrase = " ".join(run)
        if phrase not in done and run[0] not in done:
            return phrase
    return None


def should_follow(vision: Vision) -> bool:
    """May this turn be spent on HIS subject instead of the next required field?

    Only while the budget still has room for every required answer afterwards - that is
    the guarantee. Spend one on the swing and there must still be enough turns left to
    ask about the floors, the walls, the roof and the porch."""
    remaining = _QUESTION_BUDGET - len(vision.get("asked", []))
    return remaining > 0 and len(still_needed(vision)) < remaining


def note_asked(vision: Vision, question: str, topic: str | None = None) -> None:
    """Record a question the MODEL wrote, so it is never asked twice and the budget is
    honest about what has been spent."""
    q = (question or "").strip()
    if q:
        vision.setdefault("asked", []).append(q)
    if topic:
        vision.setdefault("topics_asked", []).append(topic)
        vision["open_topic"] = topic     # his next line is an answer ABOUT this


def fallback_follow_question(topic: str) -> str:
    """What to ask about his thing when the model is slow or down - so a failed call
    still follows him instead of snapping back to "How many floors?"."""
    return f"Tell me more about the {topic} - what does it look like, and where should it go?"


def question_in(reply: str) -> str | None:
    """The one question the model actually asked, pulled back out of its own words."""
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+", (reply or "").strip()) if p.strip()]
    for p in reversed(parts):
        if p.endswith("?"):
            return p
    return None


# ------------------------------------------------------------------------ its proof

def still_needed_at_start(vision: Vision) -> list[str]:
    """Which backstop questions this vision ever OWED, ignoring what has been asked -
    used by the proof that following him never costs the builder an answer."""
    return [q for key, q in _QUESTIONS if not _covered(key, vision)]


def _selftest() -> int:
    """Cards 5 and 3, proven on the real code before either is allowed near John."""
    fails: list[str] = []

    def ok(name, cond, detail=""):
        if not cond:
            fails.append(f"{name}: {detail}")

    def fresh(*lines):
        close("t")
        v = open_vision("t", lines[0])
        for l in lines[1:]:
            add("t", l)
        return v

    # CARD 5 - the defect John's own batch caught live
    v = fresh("I want a yellow house", "actually blue")
    ok("5.colour-replaces", "yellow" not in brief_text(v).lower(), brief_text(v))
    ok("5.colour-lands", "blue" in brief_text(v).lower(), brief_text(v))
    ok("5.one-change", len(v["changes"]) == 1, v["changes"])
    ok("5.said-out-loud", "blue instead of yellow" in change_text(v["last_changes"]),
       change_text(v["last_changes"]))
    ok("5.he-said-so-so-it-is-confirmed", v["last_change_explicit"], "")
    v2 = fresh("I want a yellow house", "white siding")
    ok("5.answering-a-question-is-not-a-decision", not v2["last_change_explicit"], "")
    soft = change_text(v2["last_changes"], explicit=False)
    ok("5.and-he-is-given-the-way-back", "rather keep" in soft and "the walls" in soft, soft)
    ok("5.transcript-kept", v["lines"] == ["I want a yellow house", "actually blue"], v["lines"])

    v = fresh("make it two floors", "no, three floors")
    ok("5.storeys-replaced", brief_text(v).strip() == "make it three floors", brief_text(v))

    v = fresh("a house with white siding", "actually red brick")
    b = brief_text(v).lower()
    ok("5.material+colour", "red" in b and "brick" in b and "white" not in b and "siding" not in b, b)

    v = fresh("a metal roof", "actually shingles")
    ok("5.roof-replaced", "metal" not in brief_text(v).lower(), brief_text(v))

    # ... and the things that must NOT be treated as a change of mind
    v = fresh("a blue house", "a red flowerpot by the door")
    ok("5.item-colour-is-not-wall", not v["changes"], v["changes"])
    ok("5.both-survive", "blue" in brief_text(v).lower() and "flowerpot" in brief_text(v).lower(),
       brief_text(v))
    v = fresh("a blue house with a red door")
    ok("5.door-colour-apart", not v["changes"] and v["facts"].get("door_color", {}).get("value") == "red",
       v["facts"])
    v = fresh("put a swing in the yard", "and a flag by the path")
    ok("5.yard-is-additive", not v["changes"] and "swing" in brief_text(v) and "flag" in brief_text(v),
       brief_text(v))
    v = fresh("a grey house", "make it gray")
    ok("5.same-word-no-change", not v["changes"], v["changes"])
    v = fresh("a yellow house", "actually blue, and put a swing in the yard")
    ok("5.correction-plus-new", "yellow" not in brief_text(v).lower() and "swing" in brief_text(v),
       brief_text(v))

    v = fresh("a house with a swing in the yard")
    note_asked(v, "What colour should the swing be?", topic="swing")
    add("t", "a red one")
    ok("1.a-red-one-paints-the-swing", v["facts"].get("color:swing", {}).get("value") == "red",
       v["facts"])
    ok("1.and-does-not-repaint-the-house", "wall_color" not in v["facts"], v["facts"])
    ok("1.knows-what-he-is-answering-about", v.get("answering_topic") == "swing",
       v.get("answering_topic"))
    v = fresh("a blue house")
    add("t", "make it red")
    ok("1.with-nothing-asked-it-is-still-the-house",
       v["facts"].get("wall_color", {}).get("value") == "red", v["facts"])

    v = fresh("a blue house")
    ok("32.the-first-sentence-is-worth-building", worth_rebuilding(v), v.get("last_added"))
    add("t", "make it red")
    ok("32.a-change-is-worth-rebuilding", worth_rebuilding(v), v.get("last_changes"))
    add("t", "nice, thanks")
    ok("32.small-talk-is-not", not worth_rebuilding(v), (v.get("last_changes"), v.get("last_added")))

    # CARD 3 - the read-back IS the order
    v = fresh("a blue two storey house with metal roof and a porch and a flowerpot")
    c = confirm_text(v)
    ok("3.reads-back-the-order", brief_text(v).rstrip(".") in c, c)
    ok("3.asks-for-a-yes", c.rstrip().endswith("I'll build it."), c)
    ok("3.no-question-left", next_question(v) is None, still_needed(v))
    ok("3.yes-means-go", is_yes("Yes!") and is_yes("yep") and is_yes("sounds good"), "")
    ok("3.more-vision-is-not-yes", not is_yes("make it blue"), "")
    ok("3.new-line-reopens", fresh("a blue house", "and a porch")["confirm_pending"] is False, "")

    # the contract the rest of the product depends on
    v = fresh("a house on the corner")
    ok("Q.storeys-first", next_question(v) == _QUESTIONS[0][1], next_question(v))
    v = fresh("a house")
    v["asked"] = ["q%d" % i for i in range(_QUESTION_BUDGET)]
    ok("Q.budget-then-stop", next_question(v) is None, next_question(v))
    ok("Q.five-backstops", len(_QUESTIONS) == 5, len(_QUESTIONS))

    # CARD 1 - follow him first, without ever losing what the builder needs
    v = fresh("I want a house with a swing in the yard")
    ok("1.hears-the-swing", follow_topic(v) == "swing", follow_topic(v))
    v = fresh("a house with a treehouse out back")
    ok("1.hears-a-word-we-dont-know", follow_topic(v) == "treehouse", follow_topic(v))
    v = fresh("a house with a basketball hoop over the garage")
    ok("1.hears-two-words", follow_topic(v) == "basketball hoop", follow_topic(v))
    v = fresh("a two storey house")
    ok("1.nothing-new-nothing-to-chase", follow_topic(v) is None, follow_topic(v))
    v = fresh("a house with a swing")
    note_asked(v, "What colour is the swing?", topic="swing")
    ok("1.never-chases-the-same-thing-twice", follow_topic(v) is None, follow_topic(v))
    ok("1.the-model-s-question-is-recorded", v["asked"] == ["What colour is the swing?"], v["asked"])
    ok("1.pulls-the-question-back-out",
       question_in("That swing sounds great. What colour should it be?") == "What colour should it be?",
       question_in("That swing sounds great. What colour should it be?"))
    ok("1.a-failed-call-still-follows-him", "swing" in fallback_follow_question("swing"), "")

    # the guarantee: a follow-up is only ever allowed while every required answer still fits
    v = fresh("a house with a swing in the yard")
    ok("1.room-early-so-follow-him", should_follow(v), (len(still_needed(v)), _QUESTION_BUDGET))
    v = fresh("a house")
    v["asked"] = ["q1", "q2"]
    ok("1.no-room-so-the-backstop-takes-over", not should_follow(v),
       (len(still_needed(v)), _QUESTION_BUDGET - 2))
    # played out: whatever it chases, the required fields still all get asked
    v = fresh("a house with a swing in the yard")
    chased = 0
    while True:
        if should_follow(v) and follow_topic(v):
            note_asked(v, "made-up follow-up?", topic=follow_topic(v))
            chased += 1
            continue
        q = next_question(v)
        if q is None:
            break
        v["asked"].append(q)
    asked_backstops = [q for _, q in _QUESTIONS if q in v["asked"]]
    ok("1.coverage-is-still-guaranteed", len(asked_backstops) == len(still_needed_at_start(v)),
       (len(asked_backstops), chased, v["asked"]))
    ok("Q.build-phrase-alone", is_build_command("build it") and not is_build_command("build it with a red door"), "")
    close("t")

    total = 45
    if fails:
        print(f"  vision_talk selftest FAILED {len(fails)} of {total}:")
        for f in fails:
            print("    - " + f)
        return 1
    print(f"  vision_talk selftest OK - {total} of {total}: a change of mind replaces (card 5)"
          " and the order is read back before anything is built (card 3).")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
