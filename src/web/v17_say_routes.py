"""V17 unified chat router — ONE endpoint that decides what a sentence means.

John, 2026-09-03, Phase 1: the browser used to guess "grounds vs. house vs. room vs.
a check vs. a command" with eleven regexes, and a guess that missed always fell back
to the room brain — so a photo of a brick mansion produced a teal living room. This
router replaces all eleven: the page sends the raw sentence (plus which reference
picture, if any, it followed) and gets back one classified, receipted answer.

Three model calls, cheapest rung first:
  a) a picture glance (minicpm-v:latest) — only when a reference picture is attached;
     what is actually IN the photo, so the classifier and the room brain both stop
     being blind to it.
  b) the classifier (model_router.pick("talk"), cloud first by the house law) — the
     sentence's kind. Station-rule phrases and the three literal commands (open/
     leave/models) are caught by code first — a model call for those would be waste.
  c) the order fields (gemma4:cloud) — only for a house/grounds order that carries a
     picture; the same photo, read again for the structured fields an order needs.

FAIL CLOSED is the whole point of this file: a classifier that errors, times out, or
answers something unparseable returns kind="unknown" and says which layer failed
(the Ollama transport, or a bad answer) — never a silent default to "room".

Every unbuildable phrase the classifier names is appended to the capability-gaps
ledger (append-only; the ledger contract lives at
CEO-3D-World/tools/capability-gaps.CONTRACT.md) so nothing John asks for is dropped
without a trace. Additive: no V2-V17 route or behavior changes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.unified_pipeline import event_log, model_router, stations
from src.web.v17_neighbourhood_routes import _reference_png

router = APIRouter(prefix="/api/v17", tags=["v17_say"])

GAP_LEDGER = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World"
    r"\tools\capability-gaps.jsonl"
)

VISION_MODEL = "minicpm-v:latest"
ORDER_MODEL = "gemma4:cloud"
_KINDS = {"grounds", "house", "room", "check", "question", "command", "gap", "problem", "unknown"}
_CALL_TIMEOUT = 25.0

# ── ASK BEFORE ACTING (John's call, 2026-09-04) ───────────────────────────────
# "When it isn't sure what you meant, ask me one short question first."
# A confident classification acts as before. Anything below the floor, on a kind that
# BUILDS something, stops and asks — because the damage case was never a confused
# model saying "unknown", it was a mediocre guess acted on: "i cannot see the culdsac
# on the right" read as a grounds order, twice, each costing a render pass.
# The answer John gives comes back as `forced_kind` and is logged as a human
# correction — the sentence, the wrong guess, and the right answer in one row. Those
# are the most valuable training rows the system can produce, and they only exist
# because it asked.
CONFIDENCE_FLOOR = float(os.getenv("V17_CONFIDENCE_FLOOR", "0.75"))
_ACTING = {"house", "grounds", "room"}          # the kinds that make something appear
_SIBLING = {"house": "grounds", "grounds": "house", "room": "grounds"}
_LABEL = {
    "house": "build a house on the block",
    "grounds": "change something outside",
    "room": "change something in here",
    "problem": "nothing — something looks broken",
    "question": "nothing — I'm just asking",
}


def _clarify(kind: str) -> dict:
    """One short question, two or three concrete answers. Never free text."""
    options: list[dict] = []
    if kind in _ACTING:
        options.append({"kind": kind, "label": _LABEL[kind]})
        sib = _SIBLING.get(kind)
        if sib:
            options.append({"kind": sib, "label": _LABEL[sib]})
        question = "Before I build anything — which did you mean?"
    else:
        options.append({"kind": "room", "label": _LABEL["room"]})
        options.append({"kind": "grounds", "label": _LABEL["grounds"]})
        question = "I'm not sure what you meant — which is it?"
    options.append({"kind": "problem", "label": _LABEL["problem"]})
    options.append({"kind": "question", "label": _LABEL["question"]})
    return {"question": question, "options": options, "guessed": kind}

VISION_SYSTEM = (
    "You read a reference photo a user pasted into a home-building app. Describe "
    "ONLY what you can actually see in the image. Never invent details that are not "
    "visible. Reply in ENGLISH ONLY — every field and every list item must be plain "
    "English words. Never use any non-English characters. "
    # 2026-09-04: COUNT things. The builder reads a number straight out of these words,
    # so "four columns" builds four and "columns" builds a default of four by luck.
    # 2026-09-04, live: John's Georgian mansion came back as subject="object", so the
    # summary collapsed to "a colonial brick object" — no storeys, no columns, no roof.
    # The whole photo lane is worthless if this field is wrong, so it is spelled out.
    "SUBJECT FIRST, and get it right: a photograph of a house, a mansion, or any building "
    "seen from outside is 'exterior_building' — ALWAYS, even when it is grand or far away. "
    "'object' means ONE item like a chair, a lamp or a cash register. 'interior_room' means "
    "you are standing inside a room. Never call a house an object. "
    "COUNT what you can count: if there are columns, say how many in column_count and "
    "their colour in column_color. Keep material and colour APART — wall_material is "
    "'brick', wall_color is 'red'. Keep roof shape apart from roof material — roof_shape "
    "is 'hipped' or 'gable' or 'flat', roof is 'slate' or 'clay tile'. List every "
    "distinctive thing you see in notable_features, not just the first two — dormers, "
    "chimneys, a portico, a pediment, a fanlight over the door, sash windows, shutters — "
    "and say how many of each where you can count them."
)
# Known defect (2026-09-03): gemma4:cloud ignores a bare format=json and returns
# markdown. The fix that worked: say it in the system prompt AND put the literal
# shape in the user prompt (see _order_fields). Reused verbatim, appended only here.
ORDER_SYSTEM = VISION_SYSTEM + (
    " Output RAW JSON ONLY — no markdown, no headings, no bold, no prose before or "
    "after. Start your reply with { and end it with }."
)
VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "enum": ["exterior_building", "interior_room", "object", "other"]},
        "wall_material": {"type": "string"},
        # colour kept APART from material (2026-09-04): they were one free-text field, so
        # "red brick" arrived as one blob and the column-colour guess below had to sniff the
        # word "white" out of the wall string — which fails on every house that isn't white.
        "wall_color": {"type": "string"},
        "columns": {"type": "boolean"},
        # John asked for FOUR WHITE columns and the schema could only say yes/no. Count and
        # colour were structurally unrepresentable, so they could never reach the builder —
        # which reads a number straight out of the phrase and would have used it.
        "column_count": {"type": "integer"},
        "column_color": {"type": "string"},
        "stories": {"type": "integer"},
        # shape kept APART from material for the same reason: "hipped" had nowhere to live,
        # and the builder decides roof SHAPE from the house style, so it never heard the word.
        "roof_shape": {"type": "string"},
        "roof": {"type": "string"},
        "style": {"type": "string"},
        "notable_features": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "wall_material", "wall_color", "columns", "column_count", "column_color",
                 "stories", "roof_shape", "roof", "style", "notable_features"],
}

CLASSIFY_SYSTEM = """\
You classify one sentence John typed into a home-building chat app. Decide exactly one kind:

- house: a new home on the block ("add a red brick house with white columns")
- grounds: anything else OUTSIDE — a colour, a roof, the sky, trees, the street, a
  fence, an existing house's exterior
- room: the inside of a space — furniture, walls, lighting, a room's purpose
- check: asking to be shown options and choose ("which of these do you like?")
- question: asking about the state of things, not ordering ("what is your design
  prompt?", "how would you describe the photo")
- command: open/load/show/go to <place>, leave/home, models
- gap: asking for something the world plainly cannot make yet
- problem: reporting that the APP is broken — the right-hand pane is black or empty,
  something did not load, a button does nothing, he cannot see the world. This is a
  complaint, NOT an order. "I cannot see the cul-de-sac on the right", "the world is
  blank", "nothing is happening", "it's frozen". NEVER build anything from one of these.
- unknown: you genuinely cannot tell

A sentence that follows an exterior photo is about the OUTSIDE unless it clearly
names something indoors. If you are told where he is standing, that is where he means
unless his words say otherwise — a man standing outdoors who says "on the block" or
"a house" means the grounds, not a room. Never guess "room" as a fallback when you are
unsure of the kind — "unknown" is the honest answer.

List, verbatim, every phrase in the sentence that asks for something the world
plainly cannot build yet (a named real building, anything physically impossible) in
unbuildable_phrases. Leave it empty when nothing in the sentence is unbuildable.
The builder DOES handle: one, two or three storeys; columns, a portico, a pediment,
dormers, chimneys, a balcony, shutters; brick, plaster, concrete, siding and stone
walls; and a porch. Never call any of those unbuildable. (2026-09-04: this prompt used
to name "an exact count of storeys" as unbuildable while the order form has held 1-3
storeys all along — it was flagging a request the builder can actually satisfy.)

Reply with RAW JSON ONLY — no markdown, no prose. Start with { and end with }. Use
EXACTLY these four key names, spelled exactly like this, and no others:
{"kind": "...", "confidence": 0.0, "reason": "...", "unbuildable_phrases": []}
The key is "kind" — not "classification", not "category", not "type". confidence is 0.0-1.0.
(2026-09-04: the cloud lane ignores the schema it is handed and invents key names, so the
names are spelled out here where it will actually read them.)
"""
CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": sorted(_KINDS)},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
        "unbuildable_phrases": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "confidence", "reason", "unbuildable_phrases"],
}

# the three literal commands — exact words, never worth a model call
_CMD_SLUG = r"[a-z0-9][a-z0-9\-]{0,40}"  # same convention as v17_pick_routes / v17_neighbourhood_routes
_CMD_OPEN = re.compile(rf"^\s*(?:open|load|show|go\s+to)\s+(?:me\s+)?(?:the\s+)?({_CMD_SLUG})\s*$", re.I)
_CMD_LEAVE = re.compile(r"^\s*(?:leave|home|go\s+home)\s*$", re.I)


class _Transport(Exception):
    """Ollama itself did not answer — connection, timeout, non-200, or an empty body."""


class _BadAnswer(Exception):
    """Ollama answered 200 but the content was not the JSON the schema asked for."""


# Cloud tags IGNORE Ollama's `format` schema and name the fields whatever they like.
# Seen live: gemma4:cloud returned markdown instead of JSON (2026-09-03), and
# gpt-oss:120b-cloud answered {"classification":"house","confidence":0.97} — a perfectly
# correct classification thrown away because the key was not called "kind" (2026-09-04).
# A right answer under a different label is still a right answer. Same family as the
# missing-"reason" bug: a deterministic gate failing on valid model output.
_ALIASES = {
    "classification": "kind", "category": "kind", "type": "kind", "label": "kind", "intent": "kind",
    "wall": "wall_material", "material": "wall_material",
    "colour": "wall_color", "color": "wall_color", "wall_colour": "wall_color",
    "storeys": "stories", "floors": "stories", "num_stories": "stories", "story_count": "stories",
    "features": "notable_features", "details": "notable_features",
    "column_colour": "column_color", "num_columns": "column_count", "columns_count": "column_count",
    "roofshape": "roof_shape", "roof_type": "roof_shape",
}


def _blank(prop: dict):
    """An empty value of the right type, for a field the model simply left out."""
    kind = prop.get("type")
    if kind == "array":
        return []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    if kind == "object":
        return {}
    return ""


async def _ollama_chat(model: str, system: str, user: str, schema: dict, *,
                        images: list[str] | None = None, essential: list[str] | None = None,
                        timeout: float = _CALL_TIMEOUT) -> dict:
    """POST /api/chat constrained to `schema`. Raises _Transport vs _BadAnswer —
    the two are never conflated; that distinction is the whole point of this router."""
    user_turn: dict = {"role": "user", "content": user}
    if images:
        user_turn["images"] = images
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, user_turn],
        "stream": False,
        "format": schema,
        "options": {"temperature": 0.15},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as cl:
            r = await cl.post(f"{model_router.OLLAMA_URL}/api/chat", json=payload)
    except Exception as exc:
        raise _Transport(f"{type(exc).__name__}: {exc}") from exc
    if r.status_code != 200:
        raise _Transport(f"HTTP {r.status_code}: {r.text[:200]}")
    try:
        body = r.json()
    except Exception as exc:
        raise _Transport(f"non-JSON response: {exc}") from exc
    content = str((body.get("message") or {}).get("content") or "").strip()
    if not content:
        raise _Transport(f"empty message (done_reason={body.get('done_reason')!r})")
    if content.startswith("```"):
        content = content.strip("`")
        if content[:4].lower() == "json":
            content = content[4:]
        content = content.strip()
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        raise _BadAnswer(f"no JSON object in the reply: {content[:200]}")
    try:
        parsed = json.loads(content[start:end + 1])
    except json.JSONDecodeError as exc:
        raise _BadAnswer(f"{exc}: {content[:200]}") from exc
    if not isinstance(parsed, dict):
        raise _BadAnswer(f"reply was not a JSON object: {content[:200]}")
    # A missing COSMETIC field must never bin a correct answer. 2026-09-03, live:
    # the classifier returned {"kind":"house","confidence":0.99} three times in a
    # row and this check threw all three away because "reason" was absent — a
    # deterministic gate failing on valid model output, which is the one thing a
    # gate must never do. Only `essential` is load-bearing now; anything else the
    # model left out is filled with an empty value of its declared type.
    props = schema.get("properties") or {}
    # a right answer under the wrong key name is still a right answer — see _ALIASES
    for wrong, right in _ALIASES.items():
        if right in props and right not in parsed and wrong in parsed:
            parsed[right] = parsed.pop(wrong)
    for key, prop in props.items():
        if key not in parsed:
            parsed[key] = _blank(prop)
    for key in (essential or []):
        value = parsed.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise _BadAnswer(f"no usable {key!r} in the reply: {content[:200]}")
    return parsed


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


_STORY_WORDS = {1: "one-storey", 2: "two-storey", 3: "three-storey", 4: "four-storey", 5: "five-storey"}


def _summarize_picture(fields: dict) -> str:
    """One plain-English line — this is what the room brain reads (picture_summary)
    and what the receipt quotes back to John."""
    subject = str(fields.get("subject") or "").strip()
    wall = str(fields.get("wall_material") or "").strip()
    roof = str(fields.get("roof") or "").strip()
    style = str(fields.get("style") or "").strip()
    columns = bool(fields.get("columns"))
    stories = fields.get("stories")
    features = [str(f).strip() for f in (fields.get("notable_features") or []) if str(f).strip()]
    wall_color = str(fields.get("wall_color") or "").strip()
    column_color = str(fields.get("column_color") or "").strip()
    roof_shape = str(fields.get("roof_shape") or "").strip()
    try:
        column_count = int(fields.get("column_count") or 0)
    except (TypeError, ValueError):
        column_count = 0
    # computed ONCE, for every branch — a mislabelled subject must not cost John the storeys
    story_word = ""
    if isinstance(stories, (int, float)) and stories:
        story_word = _STORY_WORDS.get(int(stories), f"{int(stories)}-storey")

    if subject == "exterior_building":
        head = "a " + " ".join(b for b in (story_word, wall_color, wall, "exterior") if b)
        extras = []
        if columns:
            # the count and the colour, spelled out. This used to read the word "white"
            # out of the WALL string, so a red-brick house with white columns lost the
            # word "white" entirely (2026-09-04) — and the count had nowhere to live.
            count_word = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}.get(column_count)
            extras.append(" ".join(b for b in (count_word, column_color, "columns") if b))
        if roof_shape or roof:
            roof_words = " ".join(b for b in (roof_shape, roof) if b)
            extras.append(roof_words if "roof" in roof_words.lower() else f"a {roof_words} roof")
        # NO truncation. The old [:2] threw away half of an eight-feature house before
        # any builder logic ran, and this sentence is the only thing the classifier, the
        # room brain and John himself ever see of the photo.
        extras.extend(features)
        return head + (f" with {_join(extras)}" if extras else "")
    if subject == "interior_room":
        head = ("a " + " ".join(b for b in (style, wall) if b) + " room") if (style or wall) else "a room"
        return head + (f" with {_join(features[:3])}" if features else "")
    # object / other / anything unrecognised: SAY WHAT WAS SEEN ANYWAY.
    # 2026-09-04, live: the model mislabelled John's three-storey Georgian mansion as
    # "object", and this branch reported "a colonial brick object" — dropping the storeys,
    # the four white columns, the hipped roof, both chimneys and both dormers, all of which
    # the model HAD returned. A wrong subject must degrade the wording, never the content.
    head = " ".join(b for b in (story_word, wall_color, wall, style) if b).strip()
    extras = []
    if columns:
        count_word = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}.get(column_count)
        extras.append(" ".join(b for b in (count_word, column_color, "columns") if b))
    roof_words = " ".join(b for b in (roof_shape, roof) if b)
    if roof_words:
        extras.append(roof_words if "roof" in roof_words.lower() else f"a {roof_words} roof")
    extras.extend(features)
    if not head and not extras:
        return "an image whose subject isn't clear"
    lead = f"a {head}" if head else "something"
    return lead + (f" with {_join(extras)}" if extras else "")


async def _picture_glance(png: Path) -> dict | None:
    """minicpm-v's read of the photo, or None on any failure (logged, never fatal —
    this is supplementary context, not the classification)."""
    log = logging.getLogger("live_trace")
    try:
        image_b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    except OSError as exc:
        log.info("  SAY picture glance: could not read %s: %s", png, exc)
        return None
    try:
        fields = await _ollama_chat(VISION_MODEL, VISION_SYSTEM, "Describe this photo.",
                                     VISION_SCHEMA, images=[image_b64], essential=["subject"])
    except (_Transport, _BadAnswer) as exc:
        log.info("  SAY picture glance failed (%s): %s", type(exc).__name__, exc)
        return None
    return {"subject": fields.get("subject"), "summary": _summarize_picture(fields), "fields": fields}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def _detect_command(message: str) -> dict | None:
    if model_router.is_models_command(message):
        return {"name": "models", "arg": None}
    if _CMD_LEAVE.match(message):
        return {"name": "leave", "arg": None}
    m = _CMD_OPEN.match(message)
    if m:
        slug = _slugify(m.group(1))
        if slug:
            return {"name": "open", "arg": slug}
    return None


async def _classify(model: str, user: str) -> dict:
    """Up to 3 consecutive backend (transport) attempts, per the house law on
    deterministic-vs-backend failures. A bad answer is not retried — the model
    already answered, just not usably."""
    last: _Transport | None = None
    for _ in range(3):
        try:
            # only `kind` is load-bearing — reason/confidence are commentary
            return await _ollama_chat(model, CLASSIFY_SYSTEM, user, CLASSIFY_SCHEMA, essential=["kind"])
        except _Transport as exc:
            last = exc
            continue
    raise last  # type: ignore[misc]  # loop runs >=1 time, so last is always set here


async def _order_fields(png: Path, fallback_fields: dict) -> tuple[dict | None, str | None]:
    """gemma4:cloud's read of the same photo, for the order fields. Returns
    (fields, note) — note is set only when we fell back to the picture glance."""
    log = logging.getLogger("live_trace")
    try:
        image_b64 = base64.b64encode(png.read_bytes()).decode("ascii")
    except OSError as exc:
        return (fallback_fields or None), f"could not re-read the photo ({exc}); used the picture-glance fields"
    shape_hint = json.dumps({k: "..." for k in VISION_SCHEMA["properties"]})
    user = f"Describe this photo. Reply with RAW JSON only, exactly this shape: {shape_hint}"
    try:
        fields = await _ollama_chat(ORDER_MODEL, ORDER_SYSTEM, user, VISION_SCHEMA,
                                     images=[image_b64], essential=["subject"])
        return fields, None
    except (_Transport, _BadAnswer) as exc:
        note = f"{ORDER_MODEL} did not answer cleanly ({type(exc).__name__}); used the picture-glance fields instead"
        log.warning("  SAY order fields: %s — %s", note, exc)
        return (fallback_fields or None), note


def _file_gaps(phrases: list[str], *, source: str, session: str, request: str, target: str,
               model: str | None = None) -> list[str]:
    """Append-only write to the capability-gaps ledger (CONTRACT.md §1). Never
    read-modify-write, never fatal to the caller."""
    if not phrases:
        return []
    log = logging.getLogger("live_trace")
    context_target = target if target in ("house", "room", "grounds") else "unknown"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    lines = []
    for phrase in phrases:
        gap_id = hashlib.sha1(f"{source}{request}{phrase}".encode("utf-8")).hexdigest()[:12]
        lines.append(json.dumps({
            "id": gap_id, "at": now, "source": source, "session": session,
            "request": request, "phrase": phrase,
            # which model called this phrase unbuildable. Was recoverable only by
            # joining on session+request against events.jsonl; inline now so the row
            # stands on its own (2026-09-04).
            "model": model,
            "context": {"target": context_target},
            "status": "new",
        }))
    try:
        GAP_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with GAP_LEDGER.open("a", encoding="utf-8") as fh:
            for line in lines:
                fh.write(line + "\n")
        return list(phrases)
    except OSError as exc:
        log.warning("  SAY gap ledger write failed (%d phrase(s) lost): %s", len(phrases), exc)
        return []


def _build_receipt(kind: str, message: str, picture: dict | None, gaps_filed: list[str]) -> dict:
    """CONTRACT §4's three lines, in plain English, aimed at John."""
    got = f'the photo ({picture["summary"]}) and "{message}"' if picture else f'"{message}"'
    if kind in ("house", "grounds", "room"):
        making = f"working on the {kind} you described"
    elif kind == "check":
        making = "hanging the choices on the garage wall for you to pick"
    else:
        making = None
    needs = f"{_join(gaps_filed)} — noted for the workshop, it can't build that yet" if gaps_filed else None
    return {"got": got, "making": making, "needs": needs}


def _capture(out: dict, ctx: dict) -> None:
    """One event-log row per turn, on EVERY path — the station rule, the literal
    commands, a transport failure, an unusable answer, and the classified answer.

    John's 2026-09-04 decision is capture everything including the misses: the rows
    where the classifier failed are the only evidence of what failure looks like, and
    a log of successes alone can train nothing to avoid one. Never fatal — see
    event_log.append_event."""
    picture = out.get("picture") or None
    router_decision = ctx.get("router") or {}
    models = out.get("models") or {}
    event_log.append_event(
        stage="say",
        session=ctx.get("session"),
        input={
            "message": ctx.get("message"),
            # the EXACT string the classifier saw — assembled from the standing line,
            # the picture summary and the sentence. That template drifts, so the
            # sentence alone will not reproduce this call later.
            "prompt_rendered": ctx.get("prompt_rendered"),
            "prompt_sha": event_log.sha(ctx.get("prompt_rendered") or ctx.get("message") or ""),
            "standing": ctx.get("standing") or "",
            "standing_reported": bool(ctx.get("standing")),
            "reference": ctx.get("reference") or 0,
        },
        router=router_decision,
        model={
            "route": models.get("route"),
            "digest": router_decision.get("digest", ""),
            "cloud": router_decision.get("cloud"),
            "picture": models.get("picture"),
            "order": models.get("order"),
            "order_note": models.get("order_note"),
        },
        outcome={
            "ok": bool(ctx.get("ok", True)),
            # transport vs bad_answer stay APART: a backend outage must never be
            # scored as a wrong answer (house law).
            "error": ctx.get("error"),
            "ms": ctx.get("ms"),
            "path": ctx.get("path"),
        },
        result={
            "kind": out.get("kind"),
            "confidence": out.get("confidence"),
            "reason": out.get("reason"),
            "command": out.get("command"),
            "gaps_filed": out.get("gaps_filed") or [],
            "order_hint": out.get("order_hint"),
            "clarify": out.get("clarify"),
        },
        # THE GOLD ROW. Set only when John answered the question himself: the sentence,
        # what the model guessed, and what he said it actually was. A supervised example
        # produced by the disagreement, which no amount of unlabelled traffic can replace.
        correction=ctx.get("correction"),
        picture={
            "subject": picture.get("subject"),
            "summary": picture.get("summary"),
            "fields": picture.get("fields"),
        } if picture else None,
        # John typed the sentence; every model-authored field is named above. Keeps the
        # provenance filter enforceable when these rows become a training set.
        origin={"message": "human", "classification": models.get("route") or None},
    )


def _final(*, kind: str, confidence: float, reason: str, command: dict | None,
           picture: dict | None, order_hint: dict | None, gaps_filed: list[str],
           models: dict, receipt: dict, capture: dict | None = None,
           clarify: dict | None = None) -> dict:
    out = {
        "kind": kind, "confidence": confidence, "reason": reason,
        "command": command, "picture": picture, "order_hint": order_hint,
        "receipt": receipt, "gaps_filed": gaps_filed, "models": dict(models),
        "clarify": clarify,
    }
    _capture(out, capture or {})
    return out


@router.post("/say")
async def v17_say(body: dict):
    """The one router that replaces the browser's eleven regexes. See module docstring."""
    body = body or {}
    session = str(body.get("session") or "").strip()
    message = str(body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "empty message"}, status_code=400)
    if not session:
        return JSONResponse({"error": "session is required"}, status_code=400)
    try:
        ref_n = int(body.get("reference") or 0)
    except (TypeError, ValueError):
        ref_n = 0

    log = logging.getLogger("live_trace")

    # Where the 3D pane says he is standing, if it has reported. One plain sentence,
    # e.g. "outdoors on the street in mr-johns-neighborhood". Never assumed.
    world = body.get("world")
    standing = str((world or {}).get("standing") or "").strip() if isinstance(world, dict) else ""

    # Everything this turn will tell the event log. Filled in as the turn proceeds and
    # handed to _final on EVERY path, so a turn that fails is recorded exactly as
    # faithfully as one that succeeds.
    turn: dict = {
        "session": session, "message": message, "standing": standing, "reference": ref_n,
        "path": None, "ok": True, "error": None, "prompt_rendered": None,
        "router": None, "ms": None,
    }

    # a) the picture glance — best-effort, never fatal to the request
    picture: dict | None = None
    picture_png: Path | None = None
    if ref_n > 0:
        try:
            picture_png = _reference_png(session, ref_n)
        except Exception as exc:
            log.info("  SAY picture #%s [%s] unusable: %s", ref_n, session[:8], exc)
            picture_png = None
        if picture_png is not None:
            picture = await _picture_glance(picture_png)

    models: dict[str, object] = {
        "picture": VISION_MODEL if picture is not None else None,
        "route": None,
        "order": None,
        "order_note": None,
    }

    # John answered the question the pane asked him. His word is final: no model call,
    # and the disagreement is written down as a correction — the sentence, the wrong
    # guess, and the right answer, which is the best training row this system makes.
    forced_kind = str(body.get("forced_kind") or "").strip().lower()
    if forced_kind in _KINDS:
        turn["path"] = "human-correction"
        turn["correction"] = {
            "guessed": str(body.get("guessed_kind") or "").strip().lower() or None,
            "chose": forced_kind,
            "by": "john",
        }
        # a confirmed house/grounds order still deserves the good photo read, or
        # answering the question would quietly cost him the order fields
        forced_hint = None
        if forced_kind in ("house", "grounds") and picture is not None and picture_png is not None:
            models["order"] = ORDER_MODEL
            forced_hint, note = await _order_fields(picture_png, picture.get("fields") or {})
            models["order_note"] = note
        return _final(
            kind=forced_kind, confidence=1.0,
            reason="John was asked which he meant, and chose this himself",
            command=None, picture=picture, order_hint=forced_hint, gaps_filed=[],
            models=models, receipt=_build_receipt(forced_kind, message, picture, []),
            capture=turn,
        )

    # a station rule ("which of these rooms do you like?") — the cheapest rung,
    # checked before the literal commands too: "show me the rooms" must never be
    # misread as a navigation command to a place named "rooms".
    rule = stations.parse_rule(message)
    if rule:
        turn["path"] = "station-rule"
        return _final(
            kind="check", confidence=1.0, reason="matched a station check phrase",
            command=None, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("check", message, picture, []),
            capture=turn,
        )

    # the three literal commands — exact words, a model call would be waste
    command = _detect_command(message)
    if command:
        turn["path"] = "literal-command"
        return _final(
            kind="command", confidence=1.0, reason="matched a literal command",
            command=command, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("command", message, picture, []),
            capture=turn,
        )

    # b) classify
    decision = await model_router.pick_verbose("talk")
    route_model = decision["chosen"]
    turn["router"] = decision
    turn["path"] = "classifier"
    models["route"] = route_model
    # Everything the two panes know about each other, handed to the classifier as
    # plain lines (2026-09-03, John: "nothing hard coded because the vision model in
    # the right pane and the chat model router in the left pane should be aware of
    # each other and what each other is doing"). Absent lines are simply absent —
    # nothing here invents a location or a subject.
    lines = []
    if standing:
        lines.append(f"Where he is standing right now, reported by the 3D pane: {standing}")
    else:
        # SILENCE IS NOT AGREEMENT (2026-09-04). The world only speaks when it is alive,
        # so a blank pane reported nothing and the classifier could not tell that from a
        # healthy world — which is how "i cannot see the culdsac on the right" became a
        # grounds order and built John a house he never asked for. Twice.
        lines.append(
            "The 3D pane has NOT reported where he is. It may be blank, still loading, or not "
            "running at all. If his sentence sounds like he cannot see the world, that is a "
            "'problem' report about the app — never an order to build."
        )
    if picture:
        lines.append(f"The photo he attached shows: {picture['summary']}")
    lines.append(f"John's sentence: {message}")
    user = "\n\n".join(lines)
    turn["prompt_rendered"] = user
    started = time.monotonic()
    try:
        result = await _classify(route_model, user)
    except _Transport as exc:
        turn["ok"] = False
        turn["ms"] = int((time.monotonic() - started) * 1000)
        turn["error"] = {"kind": "transport", "msg": str(exc)[:300]}
        return _final(
            kind="unknown", confidence=0.0, reason=f"the Ollama backend failed after 3 tries: {exc}",
            command=None, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("unknown", message, picture, []),
            capture=turn,
        )
    except _BadAnswer as exc:
        turn["ok"] = False
        turn["ms"] = int((time.monotonic() - started) * 1000)
        turn["error"] = {"kind": "bad_answer", "msg": str(exc)[:300]}
        return _final(
            kind="unknown", confidence=0.0, reason=f"the model's answer could not be understood: {exc}",
            command=None, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("unknown", message, picture, []),
            capture=turn,
        )
    turn["ms"] = int((time.monotonic() - started) * 1000)

    kind = str(result.get("kind") or "").strip()
    if kind not in _KINDS:
        kind = "unknown"
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(result.get("reason") or "")
    phrases = [str(p).strip() for p in (result.get("unbuildable_phrases") or []) if str(p).strip()]

    if kind == "command":
        # only the literal regex above may declare a command — it already ran and
        # found nothing, so a model claiming "command" here has no structured
        # {name, arg} to back it up. Honest is "unknown", not a half-built contract.
        kind = "unknown"
        reason = f"model said command but no literal command matched (model reason: {reason})"

    # ASK BEFORE ACTING. An unsure guess on a kind that BUILDS something stops here and
    # asks one short question rather than spending a render pass on a coin flip. The
    # unbuildable phrases are still filed first — a question must never cost data — but
    # the second vision call is skipped, because there is nothing to order yet.
    if kind == "unknown" or (kind in _ACTING and confidence < CONFIDENCE_FLOOR):
        turn["path"] = "clarify"
        gaps_filed = _file_gaps(phrases, source="v17-chat", session=session,
                                request=message, target=kind, model=route_model)
        return _final(
            kind="unknown", confidence=confidence,
            reason=reason or "not sure enough to act on that",
            command=None, picture=picture, order_hint=None, gaps_filed=gaps_filed,
            models=models, receipt=_build_receipt("unknown", message, picture, gaps_filed),
            capture=turn, clarify=_clarify(kind),
        )

    # c) order fields — only a house/grounds order that carries a picture
    order_hint: dict | None = None
    if kind in ("house", "grounds") and picture is not None and picture_png is not None:
        models["order"] = ORDER_MODEL
        order_hint, order_note = await _order_fields(picture_png, picture.get("fields") or {})
        models["order_note"] = order_note

    # d) file gaps — append-only, never fatal
    gaps_filed = _file_gaps(phrases, source="v17-chat", session=session, request=message,
                            target=kind, model=route_model)

    return _final(
        kind=kind, confidence=confidence, reason=reason, command=None,
        picture=picture, order_hint=order_hint, gaps_filed=gaps_filed,
        models=models, receipt=_build_receipt(kind, message, picture, gaps_filed),
        capture=turn,
    )
