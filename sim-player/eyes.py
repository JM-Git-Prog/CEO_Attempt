"""sim-player/eyes.py — Sam looks at a picture and says what he thinks of it.

John, 2026-09-11, on the sim's own Pick Board. A board is two halves: the garage wall (which of four
houses to build) and the PROP wall (which of four takes of a couch gets meshed and painted). Sam
could always answer the garage wall, because V17 tells him in words what each house is. The prop wall
is four PNGs and nothing else — and a chooser who cannot see them is not choosing, he is rolling a
die. A die's answer appended to a preferences file is worse than no answer: it teaches a style model
that taste is random.

So Sam gets eyes: a small local vision model looks at ONE picture at a time and scores it 1–5 against
what was asked for. One at a time, not four in a grid, for three reasons — every vision model in the
garage handles a single image (several handle a grid badly and say so quietly), the scores are
comparable because each was given the same question, and a per-picture score is exactly the shape the
board already wants: the winner is the top score, and anything scoring 1–2 is DENIED — a real
rejection — while a 3 or 4 that simply lost is only "not picked". That difference is the whole value
of the losing half of a preference pair, and until now only John could draw it.

FAIL SOFT, ALWAYS TOWARDS SILENCE. No vision model, an unreadable PNG, a reply that is not a number:
Sam says nothing and the pick stays open for John. A missing opinion costs one night. A fabricated
one costs a training set.

The ladder is local and small on purpose (route-a-job: cheapest rung that passes the gate). John's
garage held qwen2.5vl:7b, minicpm-v and granite3.3-vision:2b as of the last listing, and he pulled a
qwen3-vl since; `ask_lane` proves each rung live and falls through the dead ones, because the listing
is always stale.

Pure-ish module (rule E2): no server, no globals; the caller injects `ask`.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

MAX_BYTES = 6 * 1024 * 1024          # a prop variant is ~1 MB; anything this big is not a variant
DENY_AT = 2                          # 1–2 is "no, that is wrong", 3+ is "fine, just not my favourite"
MIN_WIN = 3                          # Sam never picks a winner he would have denied

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "why": {"type": "string"},
    },
    "required": ["score", "why"],
}

SYSTEM = (
    "You are ten years old and you are looking at a picture of one object that a computer drew for "
    "your house. Score how well the picture matches what was asked for, and whether it looks like a "
    "real solid thing you could put in a room:\n"
    "  5 = exactly that thing, looks real and solid\n"
    "  4 = that thing, something small is off\n"
    "  3 = close enough\n"
    "  2 = wrong thing, or flat and papery, or broken looking\n"
    "  1 = not that thing at all, or a mess\n"
    'Answer as JSON only: {"score": 4, "why": "it is a couch but the legs are melted"}. '
    "The reason must be under fifteen words and must say what you actually SEE."
)


def _clean(s: str, n: int = 120) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def read_png(path) -> str | None:
    """A PNG as base64, or None if it is missing, empty, too big, or not a PNG."""
    try:
        p = Path(path)
        data = p.read_bytes()
    except OSError:
        return None
    if not data or len(data) > MAX_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    return base64.b64encode(data).decode("ascii")


def score_one(ask, subject: str, png, *, asked_for: str = "") -> dict | None:
    """One picture, one score. None means Sam could not see it — never a low score."""
    b64 = read_png(png)
    if b64 is None or ask is None:
        return None
    want = _clean(asked_for or subject, 200)
    try:
        out = ask(SYSTEM, [{"role": "user",
                            "content": f"This is supposed to be: {want}. What do you think of it?",
                            "images": [b64]}], SCORE_SCHEMA)
    except Exception:
        return None
    js = (out or {}).get("json") if isinstance(out, dict) else None
    if not isinstance(js, dict):
        return None
    try:
        score = int(js.get("score"))
    except (TypeError, ValueError):
        return None
    if not 1 <= score <= 5:
        return None
    return {"score": score, "why": _clean(js.get("why")), "model": (out or {}).get("model")}


def look(ask, subject: str, pictures: list[dict], *, asked_for: str = "") -> dict | None:
    """Score every picture, then turn the scores into a decision the Pick Board understands.

    `pictures`: [{"tag": "v1", "png": <path>}, ...]
    Returns None when Sam saw nothing, or nothing he would keep. Otherwise:
        {"winner": "v2", "why": ..., "notes": {tag: why}, "denied": [tags], "scores": {tag: n}, "seen": n}
    """
    scores, notes, denied, seen = {}, {}, [], 0
    for pic in pictures or []:
        tag = str((pic or {}).get("tag") or "")
        if not tag:
            continue
        got = score_one(ask, subject, (pic or {}).get("png"), asked_for=asked_for)
        if got is None:
            continue
        seen += 1
        scores[tag] = got["score"]
        if got["why"]:
            notes[tag] = got["why"]
        if got["score"] <= DENY_AT:
            denied.append(tag)
    if not scores:
        return None
    winner = max(scores, key=lambda t: (scores[t], -list(scores).index(t)))
    if scores[winner] < MIN_WIN:
        # every take was wrong. Picking the least-wrong one puts a bad prop in the house AND teaches
        # the style model that it was the good one. Sam denies them all and asks for different ones.
        return {"winner": None, "why": "none of them look right", "notes": notes,
                "denied": sorted(scores), "scores": scores, "seen": seen}
    return {"winner": winner, "why": notes.get(winner) or "it looks the most like a real one",
            "notes": notes, "denied": denied, "scores": scores, "seen": seen}


def selftest() -> int:
    import struct
    import zlib
    fails = []

    def check(name, ok, detail=""):
        print(("  ok   " if ok else "  FAIL ") + name + (("  — " + detail) if detail and not ok else ""))
        if not ok:
            fails.append(name)

    def png_bytes() -> bytes:
        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        idat = zlib.compress(b"\x00\xff\xff\xff")
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

    import tempfile
    print("eyes self-test")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        good = tmp / "v1.png"; good.write_bytes(png_bytes())
        notpng = tmp / "v2.png"; notpng.write_bytes(b"hello, not a png")
        missing = tmp / "nope.png"
        huge = tmp / "v3.png"; huge.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * (MAX_BYTES + 1))

        check("a real png reads", read_png(good) is not None)
        check("a non-png is refused", read_png(notpng) is None)
        check("a missing file is refused", read_png(missing) is None)
        check("an oversized file is refused", read_png(huge) is None)

        seen = []

        def ask_scores(scores):
            def ask(system, messages, schema):
                seen.append(messages[0])
                return {"json": {"score": scores[len(seen) - 1], "why": "because"}, "model": "fake-vl"}
            return ask

        seen.clear()
        out = look(ask_scores([2, 5, 3]), "a couch",
                   [{"tag": "v1", "png": good}, {"tag": "v2", "png": good}, {"tag": "v3", "png": good}])
        check("the best score wins", out and out["winner"] == "v2", str(out))
        check("a 2 is denied", out and out["denied"] == ["v1"], str(out and out["denied"]))
        check("a 3 that lost is NOT denied", out and "v3" not in out["denied"], str(out and out["denied"]))
        check("the picture actually went to the model", seen and "images" in seen[0], str(seen[:1]))
        check("every picture was seen", out and out["seen"] == 3, str(out))

        seen.clear()
        out = look(ask_scores([1, 2, 2]), "a couch",
                   [{"tag": "v1", "png": good}, {"tag": "v2", "png": good}, {"tag": "v3", "png": good}])
        check("all-bad picks nobody", out and out["winner"] is None, str(out))
        check("all-bad denies everything", out and sorted(out["denied"]) == ["v1", "v2", "v3"], str(out))

        def blind(system, messages, schema):
            raise RuntimeError("no vision model")
        check("no eyes means no opinion", look(blind, "a couch", [{"tag": "v1", "png": good}]) is None)
        check("no ask means no opinion", look(None, "a couch", [{"tag": "v1", "png": good}]) is None)

        def rubbish(system, messages, schema):
            return {"json": {"score": "very good", "why": "x"}, "model": "fake-vl"}
        check("a non-numeric score is no opinion", look(rubbish, "a couch", [{"tag": "v1", "png": good}]) is None)

        def out_of_range(system, messages, schema):
            return {"json": {"score": 9, "why": "x"}, "model": "fake-vl"}
        check("an out-of-range score is no opinion", look(out_of_range, "a couch", [{"tag": "v1", "png": good}]) is None)

        check("an unreadable picture is skipped, not scored",
              look(ask_scores([4]), "a couch", [{"tag": "v1", "png": notpng}]) is None)

    print("ALL GREEN" if not fails else f"{len(fails)} FAILED: " + ", ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
