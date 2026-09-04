"""The warehouse gap check — does this room need anything we don't own yet?

2026-09-02. `00-Vision-Product.md` §6 has described this loop since June:

    The AI checks the warehouse:
      OK  Conference table - built for a prior scene, extendable to 10
      OK  Office chairs - 12 in inventory
      NO  Whiteboard - not in warehouse; AI builds it, then files it

It had never been wired. Nothing in the pipeline had ever looked at the shelf,
so every room was rendered from scratch and nothing compounded — the opposite of
"every room you finish makes the next one faster".

This module is only the LOOKUP half: given a brief's objects, say which ones the
warehouse already holds and which are missing. Starting the factory for the
missing ones is the caller's job (the board owns the job queue and the GPU lock),
and John's pick gate still governs everything that gets made.

Read-only. It never writes to the warehouse and never deletes anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

# The warehouse lives in the OTHER repo (the 3D world), not this one. An env var
# wins so nothing is hard-coded to one machine; the default is John's layout, and
# a missing folder degrades to "own nothing" rather than raising — a gap check is
# never worth failing a build over.
_DEFAULT_WAREHOUSE = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc"
    r"\CEO-3D-World\worlds\warehouse\output"
)

_STOPWORDS = {
    "a", "an", "one", "single", "lone", "the", "of", "with", "and",
    "plain", "simple", "small", "large", "big", "little", "old", "new",
}


def warehouse_root() -> Path:
    raw = os.getenv("WAREHOUSE_DIR", "").strip()
    return Path(raw) if raw else _DEFAULT_WAREHOUSE


def _tokens(name: str) -> set[str]:
    words = re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower()).split()
    out = set()
    for w in words:
        if w in _STOPWORDS or len(w) < 3:
            continue
        out.add(w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    return out


def _head_noun(name: str) -> str:
    """The last meaningful word — what the thing actually IS.

    "executive desk" -> desk · "desk clock" -> clock · "caged ceiling light" -> light
    """
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", str(name or "").lower()).split() if w not in _STOPWORDS]
    if not words:
        return ""
    w = words[-1]
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


@lru_cache(maxsize=1)
def _unusable(entry) -> bool:
    """True when the board's shape gate failed this mesh, or it is a remake try
    that did not pass. Unreadable stamps count as absent (fail-open here is the
    same behaviour as no stamp; the GATE itself fails closed on the board)."""
    def _read(name):
        try:
            doc = json.loads((entry / name).read_text(encoding="utf-8"))
            return doc if isinstance(doc, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    gate = _read("shape-gate.json")
    if gate is not None and gate.get("ok") is False:
        return True
    remake = _read("remake.json")
    if remake is not None and remake.get("status") != "passed":
        return True
    return False


def _shelf() -> tuple[dict, ...]:
    """Every catalogued asset on disk, WITH its taxonomy.

    2026-09-02, John: "it's not just the asset, it's the art style and all of the
    metadata in the deep taxonomy we built." The first version of this matcher
    tokenised folder names and read none of it — which was the wrong instinct in
    a repo that already has `app/src/warehouse/schema.ts` defining a real
    vocabulary (function, spaceTypes, style, era, materials).

    Honest limits of that taxonomy today, measured: type/function on 105 of 128,
    spaceTypes 58, materials 21, style 20 — and `confirmed` on ZERO, so by the
    schema's own design every value is an unconfirmed regex guess. So tags are
    used to ENRICH and RANK, never as the sole gate; folder/display tokens stay
    the floor. A tag that isn't there must never make an owned asset invisible.
    """
    root = warehouse_root()
    items: list[dict] = []
    if not root.is_dir():
        return ()
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        # An asset counts as OWNED only if a real mesh exists — a folder alone is
        # not proof a step finished (constitution, 2026-07-16).
        if not any(entry.glob("*.glb")):
            continue
        # 2026-09-03, the shape gate (CEO-3D-World/tools/run-ledger.mjs): a mesh
        # standing on a floor sheet is NOT a usable asset, whatever its tags say.
        # The Pick Board stamps its verdict at output/<id>/shape-gate.json, and
        # remake-prop.mjs marks every remake try at remake.json. A failed verdict
        # or a non-passed try is skipped here, so a room never receives the plate
        # John pulled out of the world. No stamp = not yet measured = still owned
        # (the legacy batch shelf), exactly as before.
        if _unusable(entry):
            continue
        name, tags = entry.name, {}
        try:
            doc = json.loads((entry / "object.json").read_text(encoding="utf-8"))
            name = str(doc.get("object", {}).get("name") or entry.name)
            tags = doc.get("tags") or {}
            if not isinstance(tags, dict):
                tags = {}
        except (OSError, ValueError, TypeError):
            pass
        style = {}
        try:
            card = json.loads((entry / "source.json").read_text(encoding="utf-8"))
            raw = card.get("style")
            style = raw if isinstance(raw, dict) else {}
        except (OSError, ValueError, TypeError):
            pass

        def _listed(key):
            v = tags.get(key)
            return [str(x).lower() for x in v] if isinstance(v, list) else ([str(v).lower()] if v else [])

        # "surface/desk" carries the real noun in its tail — worth as much as the
        # folder name, and written by the derive rules rather than guessed here.
        type_tag = str(tags.get("type", "") or "")
        tag_tokens = set()
        for part in type_tag.replace("/", " ").split():
            tag_tokens |= _tokens(part)
        for key in ("function", "style", "era"):
            tag_tokens |= _tokens(str(tags.get(key, "") or ""))
        for material in _listed("materials"):
            tag_tokens |= _tokens(material)

        items.append({
            "id": entry.name,
            "name": name,
            "tokens": frozenset(_tokens(entry.name) | _tokens(name) | tag_tokens),
            "name_tokens": frozenset(_tokens(entry.name) | _tokens(name)),
            "type": type_tag.lower(),
            "function": str(tags.get("function", "") or "").lower(),
            "space_types": _listed("spaceTypes"),
            "materials": _listed("materials"),
            "style_tag": str(tags.get("style", "") or "").lower(),
            "era": str(tags.get("era", "") or "").lower(),
            # The style that actually PRODUCED the asset (make-prop.mjs writes
            # this from 2026-09-02). Absent on everything made before today —
            # 125 of 128 — which is exactly why it is recorded now.
            "style_sha": str(style.get("sha256", "") or ""),
            "style_file": str(style.get("file", "") or ""),
        })
    return tuple(items)


def refresh() -> None:
    """Forget the cached shelf — call after the factory files something new."""
    _shelf.cache_clear()


def house_style_sha() -> str:
    """The 16-char hash of the CURRENT house style (art/PROP-STYLE.txt).

    Matches what make-prop.mjs stamps onto every new asset card, so "is this prop
    in today's style?" is one comparison rather than diffing prose.
    """
    path = warehouse_root().parent.parent.parent / "art" / "PROP-STYLE.txt"
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


def find(name: str, space_type: str = "") -> dict | None:
    """Best warehouse match for one object name, or None.

    Deliberately conservative: every meaningful word of the request must appear
    in the asset, so "caged ceiling light" never silently matches "desk lamp".
    Claiming to own something we don't is worse than making one extra prop.
    """
    wanted = _tokens(name)
    if not wanted:
        return None
    head = _head_noun(name)
    # Two tiers, because neither rule alone is right:
    #   * head-noun only  -> "desk" wrongly matched "desk-clock"
    #   * tokens only     -> "vase" found nothing, because the asset folder is
    #     the truncated slug "ceramic-jug-vase-smooth-glazed-rounded-b" whose
    #     last word is "b". Same for "filing cabinet" vs "filing-cabinet-short".
    # So: a head-noun agreement WINS, but when no asset in the whole warehouse
    # agrees on the head, fall back to a plain token match rather than claiming
    # we own nothing.
    # Three tiers, because the taxonomy is derived and sometimes wrong: the
    # asset's own NAME outranks its tag. Live example — `desk-clock` is tagged
    # `surface/desk`, so trusting the tag equally made "desk" match the clock
    # again, a case folder names had got right. Name head first, tag head
    # second, bare tokens last.
    name_hits: list[tuple[tuple, dict]] = []
    tag_hits: list[tuple[tuple, dict]] = []
    token_hits: list[tuple[tuple, dict]] = []
    space = str(space_type or "").lower().strip()
    for asset in _shelf():
        if not wanted <= asset["tokens"]:
            continue
        hit = {
            "asset_id": f"warehouse/{asset['id']}/0",
            "id": asset["id"],
            "matched": asset["name"],
            "type": asset["type"] or None,
            "function": asset["function"] or None,
            "materials": asset["materials"] or None,
            "space_types": asset["space_types"] or None,
            "in_house_style": bool(asset["style_sha"] and asset["style_sha"] == house_style_sha()),
            "style_known": bool(asset["style_sha"]),
        }
        # Ranking, cheapest signal first. Every term is a PREFERENCE — an asset
        # with no tags can still win, because 107 of 128 are barely labelled and
        # a missing tag must never hide something John already owns.
        space_miss = 1 if (space and asset["space_types"] and space not in asset["space_types"]) else 0
        style_miss = 0 if hit["in_house_style"] else (1 if asset["style_sha"] else 2)
        clutter = len(asset["tokens"] - wanted)
        rank = (space_miss, style_miss, clutter)
        if head and head in {_head_noun(asset["id"]), _head_noun(asset["name"])}:
            name_hits.append((rank, hit))
        elif head and asset["type"] and head == _head_noun(asset["type"].split("/")[-1]):
            tag_hits.append((rank, hit))
        else:
            token_hits.append((rank, hit))
    pool = name_hits or tag_hits or token_hits
    return min(pool, key=lambda pair: pair[0])[1] if pool else None


def check(objects, space_type: str = "") -> dict:
    """Split a brief's objects into what the warehouse owns and what it lacks.

    `space_type` is the room kind (office, diner, garage…), matched against each
    asset's `spaceTypes` so a diner stool is not offered for an office.
    """
    owned, missing = [], []
    for item in objects or []:
        if isinstance(item, dict):
            name = str(item.get("name", "")).strip()
            count = int(item.get("count", 1) or 1)
        else:
            name, count = str(item).strip(), 1
        if not name:
            continue
        hit = find(name, space_type)
        # Keep John's word for the thing AND the asset it matched — the earlier
        # version let the asset name overwrite the request, so the chat reported
        # owning "ceramic-jug-vase-smooth-glazed-rounded-b" instead of "vase".
        if hit:
            owned.append({"name": name, "count": count, **hit})
        else:
            missing.append({"name": name, "count": count})
    return {
        "warehouse": str(warehouse_root()),
        "shelf_size": len(_shelf()),
        "owned": owned,
        "missing": missing,
    }


def sentence(result: dict) -> str:
    """One line for the chat — what we own, what has to be made."""
    owned, missing = result.get("owned", []), result.get("missing", [])
    if not owned and not missing:
        return ""
    if not missing:
        return f"All {len(owned)} objects are already in the warehouse — nothing to make."
    made = ", ".join(item["name"] for item in missing[:4])
    more = f" (+{len(missing) - 4} more)" if len(missing) > 4 else ""
    have = f"{len(owned)} of {len(owned) + len(missing)} already in the warehouse. " if owned else ""
    return f"{have}Not on the shelf yet: {made}{more}. I'll make them and file them."
