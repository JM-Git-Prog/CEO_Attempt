"""The signboard's labels — DECISION 28 (John, 2026-09-11): "Four different houses."

The four pictures that stand on the lot are four genuinely different houses — the builder may ignore
some of what John asked for so they read as real alternatives — and each one says which parts it
changed.

WHY, with the evidence: the Sam Loop's simulated ten-year-old played the signboard four times on the
night of 2026-09-10 and reported, in three different colours, *"four identical white colonial house
pictures"*. The old candidates prompt allowed the model to vary only what the sentence left
unspecified, and a child specifies colour, walls, roof and floors long before he reaches the sign —
so decision 25's core loop ("four pictures stand on a signboard, I pick one") had nothing to choose
between. The builder's prompt now departs deliberately; this module reports the departure.

THE DISCLOSURE IS A DIFF, NEVER A SENTENCE A MODEL WROTE. Candidate 1 is exactly what John asked for;
every other label is computed here by comparing that candidate's summary against candidate 1's. A
model can write a wrong sentence about what it changed; a diff cannot.

Pure module (rule E2): no FastAPI, no I/O, no globals. The wall, the lot's signboard and the chat
line all read the one string this returns.
"""
from __future__ import annotations

# The attributes a candidate may depart in, and the plain word for each. Order is the reading order
# of the label — the big changes first, the trimmings last.
TELL = (("stories", "floors"), ("style", "style"), ("wall", "walls"), ("color", "colour"),
        ("roof", "roof"), ("porch", "porch"), ("garage", "garage"))
_FLOORS = {1: "one", 2: "two", 3: "three", 4: "four"}


def say(field: str, value) -> str:
    """One attribute in the words a ten-year-old would use."""
    if field == "stories":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{_FLOORS.get(n, n)} floor" + ("" if n == 1 else "s")
    if field == "porch":
        return "a porch" if value else "no porch"
    if field == "garage":
        return "no garage" if str(value) in ("none", "", "None") else f"garage on the {value}"
    return str(value)


def candidate_labels(cands: list[dict]) -> list[str]:
    """One label per picture: what it is, and — for every picture but the first — what it changed.

    `cands` is the builder's candidate list (`tag`, `image`, `summary`, `house`). A candidate with no
    summary, or one whose summary lacks a field, never produces an invented change: a difference is
    only reported when BOTH candidates state that field."""
    out: list[str] = []
    first = (cands[0].get("summary") or {}) if cands else {}
    for i, c in enumerate(cands):
        s = c.get("summary") or {}
        base = " ".join(str(s.get(k) or "") for k in ("color", "wall", "style")).strip() or str(c.get("tag") or "")
        if i == 0:
            out.append(f"{base} — what you asked for")
            continue
        changed = [f"{word} ({say(field, s.get(field))}, not {say(field, first.get(field))})"
                   for field, word in TELL
                   if field in s and field in first and s.get(field) != first.get(field)]
        out.append(f"{base} — changed: {', '.join(changed)}" if changed
                   else f"{base} — the same parts, drawn differently")
    return out
