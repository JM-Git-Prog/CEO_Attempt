"""V17 hero-pick gate — the pick happens INSIDE the split screen.

John, 2026-08-31: "I don't want the user to have to leave screens at all."

MAKE-PROP renders 4 candidates and then parks, waiting for a human to choose the
hero before it meshes and paints. That choice used to mean opening the Pick Board
on :8194 — a second window. These routes proxy the board instead, so V17's left
pane shows the candidates and V17 records the click.

Two laws carried over from the v15_fable line (src/v15_fable.py:1171):
  * The Pick Board stays the ONE approval writer. V17 never writes decision.json
    itself; it forwards to :8194 so there is exactly one place picks are recorded
    (and one style-learning log — the board appends every pick to preferences.jsonl).
  * Images proxy THROUGH here. The browser never opens a :8194 URL, so the page
    has no second origin in it and works even though the board is loopback-only.

Additive: no V2-V16 route or behavior changes.
"""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

router = APIRouter(prefix="/api/v17", tags=["v17_pick"])

PICKBOARD = "http://127.0.0.1:8194"

_SLUG = re.compile(r"[a-z0-9\-]{2,40}")
_TAG = re.compile(r"v\d{1,3}")


def _board_down(exc: Exception) -> JSONResponse:
    return JSONResponse(
        {"error": f"Pick Board unreachable: {exc}", "hint": "the board is the pick recorder — START-PICK-BOARD.bat"},
        status_code=502,
    )


@router.get("/picks")
async def v17_picks():
    """Candidates waiting on a human choice, with image URLs rewritten to this origin."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as cl:
            r = await cl.get(f"{PICKBOARD}/api/picks")
        data = r.json()
    except Exception as exc:
        return _board_down(exc)

    for item in data.get("pending", []):
        for v in item.get("variants", []):
            # /img/<slug>/picks/<id>/<tag>.png  ->  our own proxy path
            v["url"] = f"/api/v17/pick-img/{item['slug']}/{item['id']}/{v['tag']}"
    return data


@router.get("/pick-img/{slug}/{pick_id}/{tag}")
async def v17_pick_img(slug: str, pick_id: str, tag: str):
    """Stream one candidate PNG from the board so the browser stays on this origin."""
    if not (_SLUG.fullmatch(slug) and _SLUG.fullmatch(pick_id) and _TAG.fullmatch(tag)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    url = f"{PICKBOARD}/img/{slug}/picks/{pick_id}/{tag}.png"
    try:
        async with httpx.AsyncClient(timeout=15.0) as cl:
            r = await cl.get(url)
    except Exception as exc:
        return _board_down(exc)
    if r.status_code != 200:
        return JSONResponse({"error": "no such candidate"}, status_code=404)
    return Response(content=r.content, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.post("/pick")
async def v17_pick(body: dict):
    """Forward John's hero choice to the board — it owns decision.json and the style log."""
    slug = str((body or {}).get("slug", ""))
    pick_id = str((body or {}).get("id", ""))
    winner = str((body or {}).get("winner", ""))
    if not (_SLUG.fullmatch(slug) and _SLUG.fullmatch(pick_id) and _TAG.fullmatch(winner)):
        return JSONResponse({"error": "need slug, id and winner like v2"}, status_code=400)
    try:
        async with httpx.AsyncClient(timeout=10.0) as cl:
            r = await cl.post(f"{PICKBOARD}/api/pick",
                              json={"slug": slug, "id": pick_id, "winner": winner})
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return _board_down(exc)


@router.post("/make")
async def v17_make(body: dict):
    """Start the prop factory for one subject, through the board's job bay.

    Deliberately NOT a local subprocess. The board owns the job queue, the
    duplicate check and the GPU lock (the 4090 is a one-person workshop). A
    second spawner here would start work the board's queue could not see, and
    the two could collide on the card.
    """
    subject = " ".join(str((body or {}).get("subject", "")).split())[:80]
    if not re.fullmatch(r"[A-Za-z0-9 ]{2,80}", subject):
        return JSONResponse(
            {"error": "letters, numbers and spaces only (2-80 characters)"},
            status_code=400,
        )
    try:
        async with httpx.AsyncClient(timeout=15.0) as cl:
            r = await cl.post(f"{PICKBOARD}/api/make",
                              json={"subject": subject, "seeds": 4})
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return _board_down(exc)


# --- The rest of the line, proxied so every gate lives inside V17 ---------------
# John, 2026-08-31: "I want to interact with everything as an end user operating
# inside V17." Picking was only the first gate; MESH CHECK and PAINT CHECK were
# still stranded on :8194. These forward the remaining board contracts. The board
# stays the only writer of approvals, flags and decisions.


async def _get(path: str, timeout: float = 10.0):
    async with httpx.AsyncClient(timeout=timeout) as cl:
        return await cl.get(f"{PICKBOARD}{path}")


@router.get("/station-words")
async def v17_station_words():
    """The sentence shapes that mean "let me choose" — from stations.py, the one source.

    The page's place editor (neighbourhood_v17.js) reads these so a check request is
    never mistaken for a place edit (2026-09-03: "which of these rooms do you like?"
    built a cul-de-sac named after itself).
    """
    from src.unified_pipeline import stations
    return {"check": stations._CHECK.pattern, "materials": [m["material"] for m in stations.MATERIALS]}


@router.get("/pipeline")
async def v17_pipeline():
    """The whole kanban (pick / mesh_check / painting / paint_check / shelf).

    Image and model URLs are rewritten onto this origin so the page never has to
    reach :8194 itself.
    """
    try:
        r = await _get("/api/pipeline")
        data = r.json()
    except Exception as exc:
        return _board_down(exc)

    for col in ("pick", "mesh_check", "painting", "paint_check", "shelf"):
        for item in data.get(col, []) or []:
            slug, pid = item.get("slug"), item.get("id")
            if not (slug and pid):
                continue
            if item.get("cutout"):
                item["cutout"] = f"/api/v17/cutout/{slug}/{pid}"
            item["glb"] = f"/api/v17/glb/{slug}/{pid}"
            for v in item.get("variants", []) or []:
                v["url"] = f"/api/v17/pick-img/{slug}/{pid}/{v['tag']}"
    return data


@router.get("/jobs")
async def v17_jobs():
    """What the factory is doing right now, and what is waiting behind it."""
    try:
        r = await _get("/api/jobs")
        return r.json()
    except Exception as exc:
        return _board_down(exc)


@router.get("/cutout/{slug}/{pid}")
async def v17_cutout(slug: str, pid: str):
    if not (_SLUG.fullmatch(slug) and _SLUG.fullmatch(pid)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    try:
        r = await _get(f"/img/{slug}/{pid}.png", timeout=15.0)
    except Exception as exc:
        return _board_down(exc)
    if r.status_code != 200:
        return JSONResponse({"error": "no cutout"}, status_code=404)
    return Response(content=r.content, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/glb/{slug}/{pid}")
async def v17_glb(slug: str, pid: str):
    """Stream the newest GLB (painted > clean > raw — the board decides which)."""
    if not (_SLUG.fullmatch(slug) and _SLUG.fullmatch(pid)):
        return JSONResponse({"error": "bad request"}, status_code=400)
    try:
        r = await _get(f"/glb/{slug}/{pid}", timeout=60.0)
    except Exception as exc:
        return _board_down(exc)
    if r.status_code != 200:
        return JSONResponse({"error": "no GLB yet"}, status_code=404)
    return Response(
        content=r.content, media_type="model/gltf-binary",
        headers={"Cache-Control": "no-store",
                 "X-Glb-Name": r.headers.get("x-glb-name", "")},
    )


@router.get("/world-health")
async def v17_world_health():
    """Is THE world (:5173) actually up? Asked from the SERVER, not the browser.

    2026-09-02. The pane first asked with a cross-origin fetch from the page,
    which some browsers block outright — so it reported John's world dead while
    it was serving. The second version just mounted the iframe and trusted its
    `load` event: Chrome fires `load` for its own "frame failed" error page too,
    so a dead world looked like a live one.

    Both failures share a cause: the browser is the wrong place to ask. This
    server is on the same machine as the world, with no CORS and nothing to
    block it, so it can simply answer.
    """
    url = "http://127.0.0.1:5173/"
    try:
        async with httpx.AsyncClient(timeout=4.0) as cl:
            r = await cl.get(url)
        return {"up": r.status_code < 400, "status": r.status_code, "url": url}
    except Exception as exc:
        return {
            "up": False,
            "url": url,
            "error": str(exc)[:200],
            "hint": "Start it from your own console with RESTART-MY-OFFICE.bat — "
                    "a world started by a tool that later times out gets killed with it.",
        }


@router.get("/model-viewer.js")
async def v17_model_viewer():
    """The board ships model-viewer locally so 3D works offline. Reuse that copy."""
    try:
        r = await _get("/model-viewer.min.js", timeout=60.0)
    except Exception as exc:
        return _board_down(exc)
    if r.status_code != 200:
        return JSONResponse({"error": "3D engine not installed on the board"}, status_code=404)
    return Response(content=r.content, media_type="text/javascript",
                    headers={"Cache-Control": "max-age=86400"})


@router.post("/verdict")
async def v17_verdict(body: dict):
    """Approve or flag one gate. Forwarded to the board — the one approval writer.

    A flag also files a routed fix request on the board side (re-render / re-mesh
    / repaint), so rejecting something here queues its remake rather than just
    recording an opinion.
    """
    slug = str((body or {}).get("slug", ""))
    pid = str((body or {}).get("id", ""))
    stage = str((body or {}).get("stage", ""))
    ok = bool((body or {}).get("ok", False))
    if not (_SLUG.fullmatch(slug) and _SLUG.fullmatch(pid)):
        return JSONResponse({"error": "bad slug/id"}, status_code=400)
    if stage not in ("render", "mesh", "paint"):
        return JSONResponse({"error": "stage must be render, mesh or paint"}, status_code=400)
    if ok and stage == "render":
        return JSONResponse({"error": "the render gate is flag-only"}, status_code=400)

    payload = {"slug": slug, "id": pid, "stage": stage}
    try:
        async with httpx.AsyncClient(timeout=10.0) as cl:
            if ok:
                r = await cl.post(f"{PICKBOARD}/api/approve", json=payload)
            else:
                reason = str((body or {}).get("reason", "")).strip()[:120]
                if not reason:
                    return JSONResponse({"error": "give a reason — it's what gets researched"},
                                        status_code=400)
                payload["reason"] = reason
                payload["note"] = str((body or {}).get("note", ""))[:500]
                r = await cl.post(f"{PICKBOARD}/api/flag", json=payload)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as exc:
        return _board_down(exc)
