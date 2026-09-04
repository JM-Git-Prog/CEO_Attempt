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
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.unified_pipeline import model_router, stations
from src.web.v17_neighbourhood_routes import _reference_png

router = APIRouter(prefix="/api/v17", tags=["v17_say"])

GAP_LEDGER = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World"
    r"\tools\capability-gaps.jsonl"
)

VISION_MODEL = "minicpm-v:latest"
ORDER_MODEL = "gemma4:cloud"
_KINDS = {"grounds", "house", "room", "check", "question", "command", "gap", "unknown"}
_CALL_TIMEOUT = 25.0

VISION_SYSTEM = (
    "You read a reference photo a user pasted into a home-building app. Describe "
    "ONLY what you can actually see in the image. Never invent details that are not "
    "visible. Reply in ENGLISH ONLY — every field and every list item must be plain "
    "English words. Never use any non-English characters. "
    # 2026-09-04: COUNT things. The builder reads a number straight out of these words,
    # so "four columns" builds four and "columns" builds a default of four by luck.
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

    if subject == "exterior_building":
        story_word = ""
        if isinstance(stories, (int, float)) and stories:
            story_word = _STORY_WORDS.get(int(stories), f"{int(stories)}-storey")
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
    if subject == "object":
        bits = [b for b in (style, wall) if b]
        return ("a " + " ".join(bits) + " object") if bits else "an object"
    bits = [b for b in (style, wall, *features[:3]) if b]
    return _join(bits) if bits else "an image whose subject isn't clear"


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


def _file_gaps(phrases: list[str], *, source: str, session: str, request: str, target: str) -> list[str]:
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


def _final(*, kind: str, confidence: float, reason: str, command: dict | None,
           picture: dict | None, order_hint: dict | None, gaps_filed: list[str],
           models: dict, receipt: dict) -> dict:
    return {
        "kind": kind, "confidence": confidence, "reason": reason,
        "command": command, "picture": picture, "order_hint": order_hint,
        "receipt": receipt, "gaps_filed": gaps_filed, "models": dict(models),
    }


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

    # a station rule ("which of these rooms do you like?") — the cheapest rung,
    # checked before the literal commands too: "show me the rooms" must never be
    # misread as a navigation command to a place named "rooms".
    rule = stations.parse_rule(message)
    if rule:
        return _final(
            kind="check", confidence=1.0, reason="matched a station check phrase",
            command=None, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("check", message, picture, []),
        )

    # the three literal commands — exact words, a model call would be waste
    command = _detect_command(message)
    if command:
        return _final(
            kind="command", confidence=1.0, reason="matched a literal command",
            command=command, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("command", message, picture, []),
        )

    # b) classify
    route_model = await model_router.pick("talk")
    models["route"] = route_model
    # Everything the two panes know about each other, handed to the classifier as
    # plain lines (2026-09-03, John: "nothing hard coded because the vision model in
    # the right pane and the chat model router in the left pane should be aware of
    # each other and what each other is doing"). Absent lines are simply absent —
    # nothing here invents a location or a subject.
    lines = []
    if standing:
        lines.append(f"Where he is standing right now, reported by the 3D pane: {standing}")
    if picture:
        lines.append(f"The photo he attached shows: {picture['summary']}")
    lines.append(f"John's sentence: {message}")
    user = "\n\n".join(lines)
    try:
        result = await _classify(route_model, user)
    except _Transport as exc:
        return _final(
            kind="unknown", confidence=0.0, reason=f"the Ollama backend failed after 3 tries: {exc}",
            command=None, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("unknown", message, picture, []),
        )
    except _BadAnswer as exc:
        return _final(
            kind="unknown", confidence=0.0, reason=f"the model's answer could not be understood: {exc}",
            command=None, picture=picture, order_hint=None, gaps_filed=[],
            models=models, receipt=_build_receipt("unknown", message, picture, []),
        )

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

    # c) order fields — only a house/grounds order that carries a picture
    order_hint: dict | None = None
    if kind in ("house", "grounds") and picture is not None and picture_png is not None:
        models["order"] = ORDER_MODEL
        order_hint, order_note = await _order_fields(picture_png, picture.get("fields") or {})
        models["order_note"] = order_note

    # d) file gaps — append-only, never fatal
    gaps_filed = _file_gaps(phrases, source="v17-chat", session=session, request=message, target=kind)

    return _final(
        kind=kind, confidence=confidence, reason=reason, command=None,
        picture=picture, order_hint=order_hint, gaps_filed=gaps_filed,
        models=models, receipt=_build_receipt(kind, message, picture, gaps_filed),
    )
