"""jobsite.py — pure logic for the V17→world jobsite (2026-09-10).

After John confirms the architect's card ("build it as planned"), the world shows a
fenced jobsite: the plan's parts arrive as labelled blocks, then assemble in plan
order until the real house replaces them. This module computes the numbers V17
posts to the world on every poll tick — no FastAPI, no globals, no clock of its
own (the caller passes `now`). See the CONTRACT in the jobsite build brief for the
exact message shape and semantics; this implements them.

Rule E2 (pure module): stdlib only.
"""
from __future__ import annotations

ARRIVE_S = 60   # parts ramp 0 -> total over this many seconds from the order, then hold
BUILD_S = 75    # once building starts, parts assemble 0 -> total-1 over this many seconds


def facts(card: dict) -> dict | None:
    """The card's shape the world needs: name, whole, plan, parts. None for a bad card."""
    if not isinstance(card, dict):
        return None

    def _int(src: dict, key: str) -> int:
        try:
            return int(src.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    whole = {
        "width_cm": _int(card, "width_cm"), "depth_cm": _int(card, "depth_cm"),
        "height_cm": _int(card, "height_cm"), "stories": _int(card.get("home") or {}, "stories"),
    }
    parts = []
    for p in (card.get("assembly") or []):
        if not isinstance(p, dict) or not str(p.get("name") or "").strip():
            continue
        try:
            count = int(p.get("count") or 1)
        except (TypeError, ValueError):
            count = 1
        parts.append({
            "name": str(p["name"]), "count": max(1, count),
            "width_cm": _int(p, "width_cm"), "depth_cm": _int(p, "depth_cm"), "height_cm": _int(p, "height_cm"),
            "material": str(p.get("material") or ""), "connects_to": str(p.get("connects_to") or ""),
        })
    return {"name": str(card.get("name") or ""), "whole": whole,
            "plan": [str(s) for s in (card.get("plan") or [])], "parts": parts}


def _ramp(start: float | None, now: float, span: float, total: int, cap: int) -> int:
    """0 -> cap over `span` seconds from `start`, holding at `cap` after. Fails soft."""
    if total <= 0 or start is None or span <= 0:
        return 0
    elapsed = max(0.0, (now or 0.0) - start)
    return max(0, min(cap, int(min(1.0, elapsed / span) * total)))


def _note(plan: list, step: int) -> str:
    idx = step - 1
    if not plan or idx < 0 or idx >= len(plan):
        return ""
    raw = str(plan[idx])[:60]
    return raw[0].lower() + raw[1:] if raw else ""


def progress(stage: str, t_order: float | None, t_building: float | None, now: float,
             steps: int, parts_total: int, plan: list, error: str | None = None) -> dict:
    """The `progress` block of the jobsite.update message, per the CONTRACT semantics."""
    steps = max(0, int(steps or 0))
    parts_total = max(0, int(parts_total or 0))

    if stage in ("rendering", "on the wall") or (stage == "failed" and t_building is None):
        on_site = _ramp(t_order, now, ARRIVE_S, parts_total, parts_total)
        assembled, step = 0, 0
        note = "all parts on site — waiting for your pick in the garage" if on_site >= parts_total > 0 else "parts arriving"
    elif stage in ("building", "failed"):
        on_site = parts_total
        assembled = _ramp(t_building, now, BUILD_S, parts_total, max(0, parts_total - 1))
        step = max(1, min(steps, 1 + int((assembled / parts_total) * steps))) if parts_total and steps else 0
        note = _note(plan, step)
    elif stage == "done":
        on_site, assembled, step = parts_total, parts_total, steps
        note = "built — the house is on the block"
    else:
        on_site, assembled, step, note = 0, 0, 0, ""

    if stage == "failed":
        note = str(error or "")

    return {"step": step, "steps": steps, "parts_on_site": on_site,
            "parts_total": parts_total, "assembled": assembled, "note": note}
