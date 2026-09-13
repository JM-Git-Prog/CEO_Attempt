"""V17 → the Home Builders Catalog (E:\\...\\05 Training\\13-home-builders-catalog), read-only.

The pattern book the architect card is drawn against (2026-09-10): 576 real 1920s designs with the
catalogue's own dimensions and colour plates. Three reads, nothing else:

  GET /api/v17/hbc/find?q=<sentence>&k=4    the designs the architect would be handed for that sentence
  GET /api/v17/hbc/plate/<HBC-Pnnnn-Dnn>    the design's original colour plate (JPEG) — what the chat shows
  GET /api/v17/hbc/record/<HBC-Pnnnn-Dnn>   the full catalogue record with its derived block

Additive — no V2–V17 route changes. Every answer names the shelf folder when it is absent, so a
missing E: drive reads as "not on this machine", never as a broken app. Ids are validated before
they touch a path; the plate route serves only files inside the shelf.
"""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse

from src.web import architect_card

router = APIRouter(prefix="/api/v17/hbc", tags=["v17_hbc"])

_ID = re.compile(r"^HBC-P\d{4}-D\d{2}$")
_PUBLIC = ("id", "name", "type", "page", "output_page", "line", "blurb", "score", "why", "notes",
           "storeys", "rooms", "rooms_line", "width_m", "depth_m", "width_ftin", "depth_ftin",
           "styles", "features", "materials")


def _absent() -> JSONResponse:
    return JSONResponse({"error": "the pattern book is not on this machine", "shelf": str(architect_card.HBC)}, status_code=404)


@router.get("/find")
async def find(q: str = Query("", max_length=600), k: int = Query(architect_card.REFERENCES, ge=1, le=12)):
    """The designs the architect would read for this sentence — the same call write_card() makes."""
    if architect_card.hbc() is None:
        return _absent()
    refs = await asyncio.to_thread(architect_card.references, q, k)
    matches = []
    for r in refs:
        row = {key: r.get(key) for key in _PUBLIC if key in r}
        row["plate"] = f"/api/v17/hbc/plate/{r['id']}"
        matches.append(row)
    return {"query": q, "matches": matches, "shelf": str(architect_card.HBC)}


@router.get("/record/{record_id}")
async def record(record_id: str):
    if not _ID.match(record_id):
        return JSONResponse({"error": "not a catalog id (HBC-Pnnnn-Dnn)"}, status_code=400)
    H = architect_card.hbc()
    if H is None:
        return _absent()
    rec = await asyncio.to_thread(H.record, record_id)
    if not rec:
        return JSONResponse({"error": f"no record {record_id} on the shelf"}, status_code=404)
    return rec


@router.get("/plate/{record_id}")
async def plate(record_id: str):
    """The original colour plate for one design. A JPEG the browser can only show."""
    if not _ID.match(record_id):
        return JSONResponse({"error": "not a catalog id (HBC-Pnnnn-Dnn)"}, status_code=400)
    H = architect_card.hbc()
    if H is None:
        return _absent()
    rec = await asyncio.to_thread(H.record, record_id)
    rel = ((rec or {}).get("derived") or {}).get("plate") if isinstance(rec, dict) else None
    if not rel:
        return JSONResponse({"error": f"no plate filed for {record_id}"}, status_code=404)
    shelf = architect_card.HBC.resolve()
    path = (shelf / rel).resolve()
    if shelf not in path.parents or not path.is_file():
        return JSONResponse({"error": f"plate for {record_id} is not on the shelf ({rel})"}, status_code=404)
    return FileResponse(str(path), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})
