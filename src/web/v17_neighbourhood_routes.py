"""V17 neighbourhood builder — "build a cul-de-sac with multiple homes" typed INTO the
Living Room chat builds a neighbourhood headlessly in UPBGE and shows it in the right pane.

John, 2026-09-02: "into the Living Room chat I already use v17".
John, 2026-09-03: "load this world into v17 … start building from there through the chat … take
advantage of all the local and cloud models available through Ollama".

The builder itself is the Neighbourhood Builder service on :8196
(E:\\Software Development\\Video Game Development\\03 Projects\\Cul-de-sac\\neighbourhood-service.py):
sentence -> brief (Ollama: cloud tag first by the house law, local nuextract fallback) -> UPBGE 0.50
--background -> a place (or the next VERSION of an existing place) in CEO-3D-World/worlds/. These
routes proxy it, the same way v17_pick_routes.py proxies the Pick Board:
  * The service stays the one job writer; V17 never writes into jobs/ or worlds/ itself.
  * Images proxy THROUGH here so the page keeps a single origin (the service is loopback-only).
  * If the service is down, V17 starts it (its own window, detached) — it used to die with UPBGE.

Additive: no V2-V16 route or behavior changes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from src.web import architect_card, jobsite
from src.web.candidate_labels import candidate_labels
from src.web.unified_routes import _references, _session_dir

router = APIRouter(prefix="/api/v17/neighbourhood", tags=["v17_neighbourhood"])

BUILDER = "http://127.0.0.1:8196"
SERVICE = r"E:\Software Development\Video Game Development\03 Projects\Cul-de-sac\neighbourhood-service.py"
_HINT = "start it with START-NEIGHBOURHOOD-BUILDER.bat (03 Projects\\Cul-de-sac)"

_JOB = re.compile(r"\d{8}-\d{6}")
_FILE = re.compile(r"[a-z0-9_\-]{1,40}\.png")
_SLUG = re.compile(r"[a-z0-9][a-z0-9\-]{0,40}")


def _builder_down(exc: Exception, url: str) -> JSONResponse:
    """Turn a failed call to the builder into a message that names what actually failed.

    httpx's own timeout exceptions (ConnectTimeout/ReadTimeout/...) very often stringify to ""
    — the underlying httpcore/anyio timeout is raised with no message and httpx just forwards
    that empty string along — so `str(exc)` alone can say nothing at all (this is what John saw:
    "unreachable: "). Always show the exception TYPE and the URL that was tried, and say plainly
    whether it timed out (no answer in time) or was refused (nothing listening / connection error)."""
    kind = type(exc).__name__
    if isinstance(exc, httpx.TimeoutException):
        reason = f"{kind} — {url} did not answer in time"
    else:
        reason = f"{kind} — could not reach {url}"
    detail = str(exc)
    if detail:
        reason = f"{reason} ({detail})"
    return JSONResponse({"error": f"Neighbourhood Builder unreachable: {reason}", "hint": _HINT}, status_code=502)


def _rewrite(status: dict) -> dict:
    """The service returns image paths on ITS origin (/jobs/<id>/<file>) — point them at our proxy."""
    status["images"] = ["/api/v17/neighbourhood" + u for u in status.get("images", [])]
    return status


async def _alive(timeout: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as cl:
            r = await cl.get(f"{BUILDER}/api/health")
        return r.status_code == 200
    except Exception:
        return False


def _python() -> str | None:
    for cand in (r"C:\Program Files\Python313\python.exe", r"C:\Program Files\Python312\python.exe"):
        if os.path.exists(cand):
            return cand
    return shutil.which("python") or shutil.which("py")


async def _ensure_builder() -> str:
    """Start the service if it is not answering. Detached with no window; its own log next to the script."""
    if await _alive():
        return "up"
    py = _python()
    if not py or not os.path.exists(SERVICE):
        return f"down (no launcher: python={py}, service exists={os.path.exists(SERVICE)})"
    log = open(os.path.join(os.path.dirname(SERVICE), "service-log.txt"), "a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen([py, SERVICE], stdout=log, stderr=subprocess.STDOUT, creationflags=flags, cwd=os.path.dirname(SERVICE))
    for _ in range(20):
        await asyncio.sleep(0.5)
        if await _alive(1.0):
            return "started"
    return "down (started but not answering after 10 s — see service-log.txt)"


# ─── Decision 22 (2026-09-03): nothing John asks is dropped. The builder keeps what its form cannot
# hold in the brief ("features" per house, "other_features" for the grounds), appends one line per
# phrase to tools/capability-gaps.jsonl and reports them as brief["gaps"]. When that list is not empty
# the gap router runs — detached, never awaited — and turns each line into work (a prop job on the
# board, or a permit). It reads the ledger, Ollama and the board itself; nothing is passed to it.
GAP_ROUTER = Path(r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World\tools\gap-router\gap-router.mjs")


def _route_gaps(gaps: list, where: str) -> None:
    if not gaps:
        return
    log = logging.getLogger("live_trace")
    node = shutil.which("node")
    if not node or not GAP_ROUTER.is_file():
        log.warning("  NB GAPS %s: %d gap(s) noted but the router did not start (node=%s, router exists=%s)", where, len(gaps), node, GAP_ROUTER.is_file())
        return
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with open(GAP_ROUTER.with_name("router-runs.log"), "a", encoding="utf-8") as out:   # the child keeps its own copy of the handle
            out.write(f"\n=== {time.strftime('%Y-%m-%dT%H:%M:%S')} {where}: {', '.join(gaps)}\n")
            out.flush()
            subprocess.Popen([node, str(GAP_ROUTER), "--live"], cwd=str(GAP_ROUTER.parents[2]), stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
    except Exception as exc:   # the build already started; a router that would not launch is a warning, not a failed order
        log.warning("  NB GAPS %s: gap router did not start: %s", where, exc)
        return
    log.info("  NB GAPS %s: gap router started (--live) for: %s", where, ", ".join(gaps))


@router.get("/health")
async def v17_nb_health():
    state = await _ensure_builder()
    try:
        async with httpx.AsyncClient(timeout=4.0) as cl:
            r = await cl.get(f"{BUILDER}/api/health")
        data = r.json()
    except Exception as exc:
        return JSONResponse({"up": False, "state": state, "error": str(exc), "hint": _HINT})
    data["up"] = True
    data["state"] = state
    return data


@router.get("/models")
async def v17_nb_models():
    """John's Ollama garage as the builder sees it, plus the lane it will use (cloud first, by the house law)."""
    await _ensure_builder()
    try:
        async with httpx.AsyncClient(timeout=8.0) as cl:
            r = await cl.get(f"{BUILDER}/api/models")
        return r.json()
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/api/models")


@router.post("/build")
async def v17_nb_build(body: dict):
    """Forward the sentence (and the place it edits, if any); the service writes the brief and starts headless UPBGE."""
    text = str((body or {}).get("text", "")).strip()
    base = str((body or {}).get("base") or "").strip()
    if not text:
        return JSONResponse({"error": "empty sentence"}, status_code=400)
    if base and not _SLUG.fullmatch(base):
        return JSONResponse({"error": "bad place name"}, status_code=400)
    await _ensure_builder()
    try:
        async with httpx.AsyncClient(timeout=120.0) as cl:  # the brief writer (Ollama) can take a while
            r = await cl.post(f"{BUILDER}/api/build", json={"text": text, "base": base or None})
        data = r.json()
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/api/build")
    if r.status_code == 200:
        _route_gaps((data.get("brief") or {}).get("gaps") or [], f"build {data.get('job')}")
    return JSONResponse(data, status_code=r.status_code)


# ─── A NEW HOUSE: pictures first, then John chooses (2026-09-03, decision 21 applied to homes) ───
# John: "Pictures first, then I choose." An order for a new house does not build; it asks the
# builder for candidate houses rendered as pictures (--preview, nothing written into the
# world), hangs them through the Pick Board (the station kit), and only the
# house he clicks is built — as the next version of Mr. John's Neighborhood. Right-click =
# new candidates. The page polls GET /order/<job> and follows the stage it reports.
# Decision 25 (John, 2026-09-10: "Four pictures of candidate houses stand on a signboard on the
# lot, I pick one you build it"): the order asks for FOUR takes, and the wall hangs on the next
# empty lot's signboard in the world instead of the garage — the world hangs any wall made by
# `v17-neighbourhood` whose id starts with `house-` on its manifest's `lots.next` sign (the same
# lot the jobsite uses), and the builder's answer carries that lot (`lot`) so the page can walk
# John to it. The Pick Board's station file is unchanged: the same record, a different stand.
# 2026-09-11, the sim's own board: the Sam Loop runs a SECOND Pick Board on :8294 with its own
# stations and its own preferences.jsonl, so a robot's picks never land in John's. Unset, this is
# exactly the address it always was - John's Living Room talks to John's board, unchanged.
PICKBOARD = os.getenv("PICKBOARD", "http://127.0.0.1:8194")
HOME = "mr-johns-neighborhood"
_orders: dict[str, dict] = {}   # preview job id -> {text, base, station, build_job, stage, image, factory, lot}
CANDIDATES = 4                  # decision 25: four pictures on the signboard (the garage wall hung three)
SIGN_QUESTION = "Which one is your favorite?"   # John's words, 2026-09-10


# ─── A PICTURE with the order (2026-09-03): the photo John pasted into the chat box ───
# unified_v17.js keeps the pasted picture under <session>/artifacts/references/<n>.png|.jpg
# (references.json lists them). When a new-house order carries one, two things happen:
#   (a) the builder gets it as "image" so the three candidates follow the photo, and
#   (b) the Pick Board's /api/intake copies it into the prop line as the RAW picture —
#       make-prop skips its render (the raw exists), cleans, meshes, shape-gates, and stops
#       at MESH CHECK in the garage. Its answer (the job number) rides along as `factory`.
_SUBJECT_STRIP = re.compile(r"[^A-Za-z0-9 ,'\-]+")


def _reference_png(session: str, n: int) -> Path:
    """Absolute PNG path of picture #n; a JPEG is converted once, next to it, create-only."""
    session_dir = _session_dir(Path(os.getenv("OUTPUT_DIR", "output")), session)   # the root app.py uses
    rec = next((r for r in _references(session_dir)["references"] if isinstance(r, dict) and r.get("id") == n), None)
    src = Path(str((rec or {}).get("file") or ""))
    if not rec or not src.is_file():
        raise FileNotFoundError(f"no reference picture #{n} in session {session[:8]}")
    if src.suffix.lower() == ".png":
        return src
    png = src.with_suffix(".png")
    if not png.exists():
        from PIL import Image
        with png.open("xb") as handle:
            Image.open(src).convert("RGB").save(handle, format="PNG")
    return png


def _subject(text: str) -> str:
    """The order's words as the board's SUBJECT_RE allows: letters, digits, spaces, commas, apostrophes, hyphens; 2-80 chars."""
    s = " ".join(_SUBJECT_STRIP.sub(" ", text).split()).lstrip(" ,'-")[:80].rstrip()
    return s if len(s) >= 2 else "house from a photo"


async def _intake(session: str, n: int, text: str, png: Path) -> dict:
    """Hand the picture to the prop line through the Pick Board (the one job writer)."""
    slug = "house-" + re.sub(r"[^a-z0-9]", "-", session[:8].lower()) + f"-{n}"
    body = {"id": slug, "subject": _subject(text), "image": str(png), "kind": "building"}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.post(f"{PICKBOARD}/api/intake", json=body)
    try:
        data = r.json()
    except ValueError:   # a board without this route answers plain-text "not found" (restart it)
        data = {"error": r.text[:160]}
    if r.status_code != 200:
        raise RuntimeError(f"the Pick Board would not take the picture ({r.status_code}): {data.get('error') or r.text[:160]}")
    return {"id": slug, "job": (data.get("job") or {}).get("n"), "raw": (data.get("intake") or {}).get("raw"), "image": str(png)}


# DECISION 28 (John, 2026-09-11): the four pictures are four DIFFERENT houses — the builder may
# ignore some of what he asked for so they read as real alternatives — and each label says which
# parts it changed, as a DIFF against candidate 1 (never a sentence a model wrote). The Sam Loop
# found the defect that forced this: see src/web/candidate_labels.py for the evidence.
async def _post_station(order_id: str, text: str, cands: list[dict]) -> str:
    """Hang the candidates as a station wall; the board serves the pictures from the builder's job folder.
    The world stands this wall on the next empty lot's signboard (decision 25) — see the section header."""
    station_id = f"house-{order_id}"
    items = []
    labels = candidate_labels(cands)
    for c, label in zip(cands, labels):
        items.append({"tag": c["tag"], "label": label, "image": c["image"]})
    body = {"id": station_id, "kind": "wall", "question": SIGN_QUESTION, "made_by": "v17-neighbourhood", "items": items, "actions": {"right": "more"}}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.post(f"{PICKBOARD}/api/stations", json=body)
    if r.status_code not in (200, 409):   # 409 = already hung (a repeated poll)
        raise RuntimeError(f"the Pick Board would not hang the wall ({r.status_code}): {r.text[:160]}")
    await _withdraw_superseded_house_walls(station_id)
    return station_id


async def _withdraw_superseded_house_walls(keep_id: str) -> None:
    """A new house order takes down its own earlier unanswered walls (John, 2026-09-05).

    Every order hung a wall and nothing ever expired, so four orders for the SAME colonial in one
    morning left four walls waiting - and with three older ones already up, seven competed for the
    three slots the garage displays, with nothing on a wall to say which order it came from. John
    could walk in and not find the set worth choosing from. He was never going to pick an earlier
    attempt at the same house, so the older wall comes down by itself.

    Withdraw, not choose: 'choose' would BUILD the house on that picture. Best-effort by design -
    a board that cannot withdraw (older build, or down) must never stop the new wall being hung,
    which is why this runs AFTER the post and swallows everything.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as cl:
            r = await cl.get(f"{PICKBOARD}/api/stations")
            if r.status_code != 200:
                return
            for s in r.json().get("stations", []):
                sid = s.get("id") or ""
                if sid == keep_id or s.get("answer") or not sid.startswith("house-"):
                    continue
                if (s.get("made_by") or "") != "v17-neighbourhood":
                    continue          # somebody else's wall is not ours to take down
                await cl.post(f"{PICKBOARD}/api/stations/{sid}/answer",
                              json={"action": "withdraw", "reason": f"superseded by {keep_id}"})
    except Exception:
        return                        # never let tidying break an order


async def _station_answer(station_id: str) -> dict | None:
    async with httpx.AsyncClient(timeout=8.0) as cl:
        r = await cl.get(f"{PICKBOARD}/api/stations")
    for s in r.json().get("stations", []):
        if s.get("id") == station_id:
            return s.get("answer") or None
    return None


def _photo_clause(hint: object) -> str:
    """Gemma's read of the pasted photo, as words the builder's order-form step can use.

    2026-09-03: /api/v17/say already asks gemma4:cloud to read the photo into fields, and
    V17 showed John that reading and then threw it away — the builder only ever got his
    typed sentence, so "very presidential" had to carry the whole house. This turns the
    fields into a plain clause appended to the order. Additive: the builder still gets the
    picture itself, and John's own words still lead.
    """
    if not isinstance(hint, dict):
        return ""
    bits: list[str] = []
    stories = hint.get("stories")
    if isinstance(stories, (int, float)) and 0 < int(stories) < 10:
        bits.append(f"{int(stories)} storeys")
    wall = " ".join(b for b in (str(hint.get("wall_color") or "").strip(),
                                str(hint.get("wall_material") or "").strip()) if b)
    if wall:
        bits.append(f"{wall} walls")
    if hint.get("columns"):
        # SAY THE NUMBER. build-neighbourhood.py's count() reads a number word straight
        # out of this phrase (2 to 8, default 4) — so "four white columns" builds four,
        # while the old fixed wording "columns across the front" could never say how many
        # no matter what John asked for or what the photo showed (2026-09-04).
        try:
            n = int(hint.get("column_count") or 0)
        except (TypeError, ValueError):
            n = 0
        count_word = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}.get(n)
        colour = str(hint.get("column_color") or "").strip()
        bits.append(" ".join(b for b in (count_word, colour, "columns across the front") if b))
    roof = " ".join(b for b in (str(hint.get("roof_shape") or "").strip(),
                                str(hint.get("roof") or "").strip()) if b)
    if roof:
        bits.append(roof if "roof" in roof.lower() else f"{roof} roof")
    style = str(hint.get("style") or "").strip()
    if style:
        bits.append(f"{style} style")
    # every feature, not the first four — the summary the classifier sees is already
    # capped downstream by leftovers() (12 phrases); truncating twice, at different
    # limits, dropped roughly half of an eight-feature house before anything ran.
    for feature in (hint.get("notable_features") or []):
        feature = str(feature).replace("_", " ").strip()
        if feature and feature not in bits:
            bits.append(feature)
    return ", ".join(bits)


@router.post("/order")
async def v17_nb_order(body: dict):
    """A new-house order → a candidates preview job on the builder (three houses, pictures only)."""
    text = str((body or {}).get("text", "")).strip()
    base = str((body or {}).get("base") or HOME).strip()
    if not text:
        return JSONResponse({"error": "empty sentence"}, status_code=400)
    if not _SLUG.fullmatch(base):
        return JSONResponse({"error": "bad place name"}, status_code=400)
    # the pasted picture, if the page sent one: {"reference": <n>, "session": "<V17 session id>"}
    log = logging.getLogger("live_trace")
    session = str((body or {}).get("session") or "").strip()
    try:
        ref_n = int((body or {}).get("reference") or 0)
    except (TypeError, ValueError):
        ref_n = 0
    image: Path | None = None
    factory: dict | None = None
    if ref_n > 0 and session:
        try:
            image = _reference_png(session, ref_n)
        except Exception as exc:
            log.warning("  NB ORDER picture #%s [%s] unusable: %s", ref_n, session[:8], exc)
            factory = {"error": f"reference picture #{ref_n}: {exc}"}
    # Gemma already read the photo in /api/v17/say — spend that reading here instead of
    # dropping it. John's typed words lead; the photo clause follows them.
    builder_text = text
    clause = _photo_clause((body or {}).get("order_hint"))
    if clause:
        builder_text = f"{text}. From the photo: {clause}"
        log.info("  NB ORDER photo clause: %s", clause[:160])
    # The architect's confirmed plan (2026-09-10): the ornate brief John said "build it as
    # planned" to, appended so the builder's order form is read from the planned-out
    # description, not the six-word sentence. His words still lead.
    card_clause = str((body or {}).get("card_clause") or "").strip()
    if card_clause:
        builder_text = f"{builder_text}. Architect's brief: {card_clause[:1200]}"
        log.info("  NB ORDER architect clause: %s", card_clause[:160])
    # THE JOBSITE (2026-09-10): the confirmed card's id rides with the order so the world can
    # show its own parts arriving and assembling — best-effort, never fatal to the order.
    card_id = str((body or {}).get("card_id") or "")
    card = architect_card.find(card_id) if card_id else None
    await _ensure_builder()
    try:
        async with httpx.AsyncClient(timeout=120.0) as cl:
            r = await cl.post(f"{BUILDER}/api/candidates", json={"text": builder_text, "base": base, "count": CANDIDATES, **({"image": str(image)} if image else {})})
        data = r.json()
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/api/candidates")
    if r.status_code != 200:
        return JSONResponse(data, status_code=r.status_code)
    lot = data.get("lot") if isinstance(data.get("lot"), dict) else None   # the next empty lot (decision 25); None on a place without a plat
    if image:
        try:
            factory = await _intake(session, ref_n, text, image)
        except Exception as exc:
            log.warning("  NB ORDER %s intake failed: %s", data["job"], exc)
            factory = {"error": str(exc)}
    _orders[data["job"]] = {"text": text, "base": base, "station": None, "build_job": None, "stage": "rendering",
                             "image": str(image) if image else None, "factory": factory, "lot": lot,
                             "jobsite": jobsite.facts(card) if card else None, "t_order": time.time(), "t_building": None}
    _route_gaps((data.get("brief") or {}).get("gaps") or [], f"order {data['job']}")
    return {"order": data["job"], "brief": data.get("brief"), "stage": "rendering", "factory": factory, "lot": lot, "count": CANDIDATES}


@router.get("/order/{order_id}")
async def v17_nb_order_status(order_id: str):
    """Where the order stands: rendering → on the wall → (John clicks) → building <job> | more (new preview).
    Every answer carries `factory` — the pasted picture's prop-line job, or null."""
    if not _JOB.fullmatch(order_id):
        return JSONResponse({"error": "bad order id"}, status_code=400)
    o = _orders.get(order_id)
    if o is None:
        return JSONResponse({"error": "unknown order (V17 restarted?) — say it again"}, status_code=404)
    resp = await _order_stage(order_id, o)
    if isinstance(resp, dict):
        resp["factory"] = o.get("factory")
        resp["lot"] = o.get("lot")
        block = _jobsite_block(order_id, o, resp.get("stage"), error=resp.get("error"))
        if block:
            resp["jobsite"] = block
    return resp


_JOBSITE_STAGE = {"more": "rendering"}   # a re-roll is still parts arriving, from the world's point of view


def _jobsite_block(order_id: str, o: dict, stage: str | None, *, error: str | None = None) -> dict | None:
    """The `jobsite` block of an /order or /job answer, or None when this order carries no card.
    Fails soft (house law): a bad card or a math error must never break the order flow."""
    js = o.get("jobsite")
    if not js:
        return None
    try:
        stage = _JOBSITE_STAGE.get(stage or o.get("stage") or "rendering", stage or o.get("stage") or "rendering")
        plan = js.get("plan") or []
        parts_total = sum(int(p.get("count") or 1) for p in js.get("parts") or [])
        progress = jobsite.progress(stage, o.get("t_order"), o.get("t_building"), time.time(),
                                     len(plan), parts_total, plan, error=error)
        return {**js, "order": order_id, "stage": stage, "progress": progress}
    except Exception as exc:
        logging.getLogger("live_trace").warning("  NB JOBSITE %s: %s", order_id, exc)
        return None


async def _order_stage(order_id: str, o: dict):
    if o["stage"] in ("building", "more", "failed"):
        return {"order": order_id, **{k: o[k] for k in ("stage", "build_job", "station")}, "next_order": o.get("next_order")}
    try:
        async with httpx.AsyncClient(timeout=8.0) as cl:
            r = await cl.get(f"{BUILDER}/api/job/{order_id}")
        st = r.json()
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/api/job/{order_id}")
    if st.get("status") == "failed":
        o["stage"] = "failed"
        return {"order": order_id, "stage": "failed", "error": (st.get("error") or st.get("stage") or "")[-600:]}
    if st.get("status") != "done" or not st.get("candidates"):
        return {"order": order_id, "stage": "rendering", "detail": st.get("stage", "")}
    if not o["station"]:
        try:
            o["station"] = await _post_station(order_id, o["text"], st["candidates"])
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        o["stage"] = "on the wall"
        o["candidates"] = st["candidates"]
    try:
        answer = await _station_answer(o["station"])
    except Exception as exc:
        return {"order": order_id, "stage": "on the wall", "station": o["station"], "board": f"unreachable: {exc}"}
    if not answer:
        return {"order": order_id, "stage": "on the wall", "station": o["station"], "count": len(o.get("candidates") or [])}
    if answer.get("action") == "choose":
        chosen = next((c for c in o.get("candidates") or [] if c.get("tag") == answer.get("tag")), None)
        if not chosen:
            o["stage"] = "failed"
            return {"order": order_id, "stage": "failed", "error": f"no candidate {answer.get('tag')}"}
        try:
            async with httpx.AsyncClient(timeout=120.0) as cl:
                r = await cl.post(f"{BUILDER}/api/build", json={"text": o["text"], "base": o["base"], "house": chosen.get("house") or {}})
            data = r.json()
        except Exception as exc:
            return _builder_down(exc, f"{BUILDER}/api/build")
        if r.status_code != 200:
            return JSONResponse(data, status_code=r.status_code)
        o["stage"] = "building"; o["build_job"] = data["job"]; o["t_building"] = time.time()
        return {"order": order_id, "stage": "building", "build_job": data["job"], "station": o["station"], "chosen": chosen.get("summary")}
    # more: new candidates, same words (and the same picture, if there was one)
    try:
        async with httpx.AsyncClient(timeout=120.0) as cl:
            r = await cl.post(f"{BUILDER}/api/candidates", json={"text": o["text"], "base": o["base"], "count": CANDIDATES, **({"image": o["image"]} if o.get("image") else {})})
        data = r.json()
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/api/candidates")
    if r.status_code != 200:
        return JSONResponse(data, status_code=r.status_code)
    _orders[data["job"]] = {"text": o["text"], "base": o["base"], "station": None, "build_job": None, "stage": "rendering",
                             "image": o.get("image"), "factory": o.get("factory"),
                             "lot": data.get("lot") if isinstance(data.get("lot"), dict) else o.get("lot"),
                             "jobsite": o.get("jobsite"), "t_order": time.time(), "t_building": None}
    o["stage"] = "more"; o["next_order"] = data["job"]
    return {"order": order_id, "stage": "more", "next_order": data["job"], "station": o["station"]}


_JOB_STATUS_TO_JOBSITE = {"building": "building", "done": "done", "failed": "failed"}


@router.get("/job/{job_id}")
async def v17_nb_job(job_id: str):
    if not _JOB.fullmatch(job_id):
        return JSONResponse({"error": "bad job id"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=8.0) as cl:
            r = await cl.get(f"{BUILDER}/api/job/{job_id}")
        data = r.json()
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/api/job/{job_id}")
    data = _rewrite(data)
    try:
        found = next(((oid, o) for oid, o in _orders.items() if o.get("build_job") == job_id), None)
        if found:
            oid, o = found
            stage = _JOB_STATUS_TO_JOBSITE.get(data.get("status"), "building")
            block = _jobsite_block(oid, o, stage, error=data.get("error") if stage == "failed" else None)
            if block:
                data["jobsite"] = block
    except Exception as exc:
        logging.getLogger("live_trace").warning("  NB JOBSITE job %s: %s", job_id, exc)
    return data


@router.get("/jobs/{job_id}/{file}")
async def v17_nb_image(job_id: str, file: str):
    """Stream one rendered PNG from the service so the browser stays on this origin."""
    if not (_JOB.fullmatch(job_id) and _FILE.fullmatch(file)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=15.0) as cl:
            r = await cl.get(f"{BUILDER}/jobs/{job_id}/{file}")
    except Exception as exc:
        return _builder_down(exc, f"{BUILDER}/jobs/{job_id}/{file}")
    if r.status_code != 200:
        return JSONResponse({"error": "no such picture"}, status_code=404)
    return Response(content=r.content, media_type="image/png", headers={"Cache-Control": "no-store"})
