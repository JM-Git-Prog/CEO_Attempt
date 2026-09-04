"""Stations — a check John asks for in the chat becomes a wall in the garage.

John, 2026-09-03 (decision 21 and its kit): "when anything needs my eye, build it
into a mini game in the cul-de-sac" and, asked what should happen when a new kind
of check is needed, "I say it in chat and the garage grows a new station."

The kit has three parts and this module is V17's side of it:

  1. A SENTENCE becomes a RULE for the session ("which of these rooms do you
     like?" -> at the room-picture step, render three and let me choose). Rules
     live in <session>/artifacts/stations.json — durable, append-only.
  2. When the stage the rule names runs, it renders `count` candidates instead of
     one and POSTs a station to the Pick Board (:8194, the ONE writer of review
     state) — `post_wall`. The garage hangs it; nothing here touches the world.
  3. The board records John's answer in the station file; `wall_answer` reads it
     back so the pipeline can continue from the picture he chose.

MATERIALS is the list of things the chat can put on a wall today. A new material
is a row here plus the stage that renders it — never a new minigame in TypeScript.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

PICKBOARD = "http://127.0.0.1:8194"
STATIONS_FILE = "stations.json"

# what the chat can hang on a wall: the material, the stage that makes it, the
# words that name it, and the question the wall asks
MATERIALS: list[dict[str, Any]] = [
    {
        "material": "room-picture",
        "stage": "canon_generation",
        "words": r"\b(rooms?|places?|pictures?|renders?|versions?|options?|looks?|designs?)\b",
        "default_count": 3,
        "max_count": 4,
        "question": "Which of these rooms do you like?",
    },
]

# the shapes of a check request — kept deliberately plain; the rung above this
# (a model with a schema) is not needed until a sentence this misses shows up
_CHECK = re.compile(
    r"\b(which (one|of these|of them)|let me (choose|pick|decide)|"
    r"(show|give|render|make) me (a few|some|\w+) (\w+ )?(versions|options|choices|pictures|renders|looks|designs|rooms)|"
    r"(two|three|four|2|3|4) (versions|options|choices|pictures|renders|looks|designs|rooms))\b",
    re.I,
)
_COUNT = {"two": 2, "three": 3, "four": 4, "2": 2, "3": 3, "4": 4, "a couple of": 2, "a few": 3, "some": 3}


def parse_rule(text: str) -> dict[str, Any] | None:
    """The sentence -> a rule, or None when it is not asking for a check.

    >>> parse_rule("which of these rooms do you like?")["count"]
    3
    >>> parse_rule("show me four versions of the room and let me pick")["count"]
    4
    >>> parse_rule("make the walls green") is None
    True
    """
    said = " ".join(str(text or "").split())
    if not said or not _CHECK.search(said):
        return None
    low = said.lower()
    for m in MATERIALS:
        if not re.search(m["words"], low):
            continue
        count = m["default_count"]
        for word, n in _COUNT.items():
            if re.search(r"\b" + re.escape(word) + r"\b", low):
                count = n
                break
        count = max(1, min(int(m["max_count"]), count))
        return {
            "material": m["material"],
            "stage": m["stage"],
            "count": count,
            "question": m["question"],
            "said": said[:200],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    return None


def rule_sentence(rule: dict[str, Any], already_rendered: bool = False) -> str:
    """What the chat says back — the end user's words, not the machine's."""
    n = int(rule.get("count", 3))
    word = {1: "one", 2: "two", 3: "three", 4: "four"}.get(n, str(n))
    when = "next time the room's picture is rendered" if already_rendered else "when the room's picture is ready"
    return (
        f"Got it — {when}, I'll hang {word} on the garage wall and you choose there. "
        "Left-click the one you like; right-click if none of them is right."
    )


# ─── the session's stations.json ───────────────────────────────────────────

def _path(session_dir: Path) -> Path:
    return Path(session_dir) / "artifacts" / STATIONS_FILE


def load(session_dir: Path) -> dict[str, Any]:
    try:
        doc = json.loads(_path(session_dir).read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("rules"), list) and isinstance(doc.get("walls"), list):
            return doc
    except (OSError, ValueError, TypeError):
        pass
    return {"rules": [], "walls": []}


def save(session_dir: Path, doc: dict[str, Any]) -> None:
    p = _path(session_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(p)


def add_rule(session_dir: Path, rule: dict[str, Any]) -> dict[str, Any]:
    doc = load(session_dir)
    # one rule per material: the newest count wins, the history stays
    doc["rules"] = [r for r in doc["rules"] if r.get("material") != rule.get("material")] + [rule]
    save(session_dir, doc)
    return doc


def rule_for(session_dir: Path, stage: str) -> dict[str, Any] | None:
    for r in load(session_dir)["rules"]:
        if r.get("stage") == stage:
            return r
    return None


def open_wall(session_dir: Path) -> dict[str, Any] | None:
    """The wall whose answer has not been applied yet, if any."""
    for w in reversed(load(session_dir)["walls"]):
        if not w.get("applied_at"):
            return w
    return None


# ─── the board ─────────────────────────────────────────────────────────────

_LABELS = ["the first", "the second", "the third", "the fourth", "the fifth", "the sixth", "the seventh", "the eighth"]


async def post_wall(session_dir: Path, session_id: str, stage: str, question: str, candidates: list[Path]) -> dict[str, Any]:
    """Hang `candidates` on the garage wall: one station on the board, one wall record here.

    The board serves the pictures from where they are (read-only); nothing is copied.
    Raises on a board that will not take it — a wall that silently failed to hang
    would leave the pipeline parked with nothing for John to see.
    """
    doc = load(session_dir)
    n = sum(1 for w in doc["walls"] if w.get("stage") == stage) + 1
    station_id = f"{session_id[:8].lower()}-{stage.replace('_', '-')}-{n}"
    items = [
        {"tag": f"c{i + 1}", "label": _LABELS[i] if i < len(_LABELS) else f"number {i + 1}", "image": str(Path(p).resolve())}
        for i, p in enumerate(candidates)
    ]
    body = {"id": station_id, "kind": "wall", "question": question, "made_by": "v17", "items": items, "actions": {"right": "more"}}
    async with httpx.AsyncClient(timeout=10.0) as cl:
        r = await cl.post(f"{PICKBOARD}/api/stations", json=body)
    if r.status_code != 200:
        raise RuntimeError(f"the Pick Board would not hang the wall ({r.status_code}): {r.text[:200]}")
    wall = {
        "id": station_id,
        "stage": stage,
        "question": question,
        "candidates": [it["image"] for it in items],
        "tags": [it["tag"] for it in items],
        "posted_at": datetime.now(timezone.utc).isoformat(),
        "answer": None,
        "applied_at": None,
    }
    doc["walls"].append(wall)
    save(session_dir, doc)
    return wall


async def wall_answer(station_id: str) -> dict[str, Any] | None:
    """The board's answer for a station, or None while John has not been to the garage."""
    async with httpx.AsyncClient(timeout=8.0) as cl:
        r = await cl.get(f"{PICKBOARD}/api/stations")
    if r.status_code != 200:
        return None
    for s in r.json().get("stations", []):
        if s.get("id") == station_id:
            return s.get("answer") or None
    return None


def apply_choice(session_dir: Path, wall: dict[str, Any], tag: str, target_name: str = "canon.png") -> Path:
    """The chosen candidate becomes the stage's picture (a copy — candidates stay as evidence)."""
    tags = list(wall.get("tags", []))
    if tag not in tags:
        raise ValueError(f"no picture {tag} on wall {wall.get('id')}")
    src = Path(wall["candidates"][tags.index(tag)])
    if not src.exists():
        raise FileNotFoundError(str(src))
    dst = Path(session_dir) / "artifacts" / target_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def mark_applied(session_dir: Path, station_id: str, answer: dict[str, Any]) -> None:
    doc = load(session_dir)
    for w in doc["walls"]:
        if w.get("id") == station_id:
            w["answer"] = answer
            w["applied_at"] = datetime.now(timezone.utc).isoformat()
    save(session_dir, doc)
