"""TaxonomyResolver — bind detected/generated objects to the master taxonomy.

Every object the pipeline generates or extracts is given a canonical identity
from data/master_taxonomy_engine.json: a Taxonomy_Path, a canonical Display_Name,
and the taxonomy Entity_ID. This is the "step 2 TaxonomyResolver" seam referenced
in vision_catalog.py.

Design notes
------------
- Resolution is ADDITIVE. The raw descriptive detection name (e.g. "cracked
  baseball bat") is preserved by callers for SAM3 prompting, placement matching,
  and provenance. The resolver only supplies the canonical taxonomy fields.
- Scoping: the vision catalog already emits a `category` drawn from the
  Consumer_Furnishings sub-category vocabulary (seating, tables_surfaces, ...).
  We use that to scope candidate entries to the matching sub-category, then pick
  the best Display_Name by token-aware name similarity. If the category is
  unknown/"other" we search the whole furnishings domain.
- Graceful fallback: if nothing clears the confidence floor we return an
  UNRESOLVED result (empty path/entity_id, title-cased detected name as display)
  so the pipeline never blocks on a miss.

The taxonomy JSON is loaded once and cached process-wide.
"""
from __future__ import annotations

import datetime as _dt
import json
import json as _json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

_TAXONOMY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "master_taxonomy_engine.json"
)

# Only interior/consumer furnishings are relevant to room objects. Restricting
# the search space keeps matches on-target (a "table" resolves to furniture,
# never to a "Tectonic Plate").
_FURNISHINGS_MARKER = "Consumer_Furnishings"

# Minimum similarity for a confident bind. Below this we return UNRESOLVED.
_CONFIDENCE_FLOOR = 0.34

# Common detection-name synonyms that map to a taxonomy leaf's own vocabulary.
# Applied as extra tokens on the DETECTED side before matching, so e.g. a
# "trophy case" gains the token "display"/"cabinet" and binds to Display Cabinet.
_SYNONYM_TOKENS: dict[str, tuple[str, ...]] = {
    "trophy": ("display", "cabinet"),
    "case": ("cabinet",),
    "couch": ("sofa",),
    "tv": ("television",),
    "crt": ("television",),
    "fridge": ("refrigerator",),
    "poster": ("wall", "art"),
    "painting": ("wall", "art"),
    "rug": ("area", "rug"),
    "chandelier": ("ceiling", "light"),
}

# Maps the vision-catalog category enum (Consumer_Furnishings sub-category,
# lowercased) back to the taxonomy's sub-category segment (CamelCase in path).
_CATEGORY_TO_SUBCATEGORY: dict[str, str] = {
    "seating": "Seating",
    "tables_surfaces": "Tables_Surfaces",
    "storage_casegoods": "Storage_Casegoods",
    "sleeping": "Sleeping",
    "lighting_fixtures": "Lighting_Fixtures",
    "soft_goods_textiles": "Soft_Goods_Textiles",
    "appliances_major": "Appliances_Major",
    "appliances_small": "Appliances_Small",
    "electronics_entertainment": "Electronics_Entertainment",
    "kitchen_tableware": "Kitchen_Tableware",
    "decor_accessories": "Decor_Accessories",
    "bathroom_fixtures": "Bathroom_Fixtures",
    "window_wall_treatments": "Window_Wall_Treatments",
    "outdoor_patio": "Outdoor_Patio",
    "kids_nursery": "Kids_Nursery",
    "office_workspace": "Office_Workspace",
    "fitness_recreation": "Fitness_Recreation",
    "pet": "Pet",
    "cleaning_utility": "Cleaning_Utility",
    "personal_everyday": "Personal_Everyday",
}


@dataclass(frozen=True)
class TaxonomyMatch:
    """Result of resolving a detection against the master taxonomy."""

    entity_id: str
    taxonomy_path: str
    display_name: str
    domain_class: str
    confidence: float
    resolved: bool

    @classmethod
    def unresolved(cls, detected_name: str) -> "TaxonomyMatch":
        title = _titlecase(detected_name) or "Unknown Object"
        return cls(
            entity_id="",
            taxonomy_path="",
            display_name=title,
            domain_class="",
            confidence=0.0,
            resolved=False,
        )


@dataclass(frozen=True)
class _Entry:
    entity_id: str
    taxonomy_path: str
    display_name: str
    domain_class: str
    subcategory: str  # third path segment when present, else ""
    tokens: frozenset[str]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", (text or "").lower()).strip()


# Descriptive adjectives the vision model loves that add no taxonomic signal.
# Stripped before matching so "dusty glass trophy case" reads as "trophy case".
_STOPWORDS: frozenset[str] = frozenset({
    "old", "dusty", "worn", "wornout", "cracked", "faded", "peeling", "tarnished",
    "stained", "dingy", "cluttered", "vintage", "antique", "broken", "dirty",
    "glowing", "heavy", "large", "small", "big", "little", "the", "a", "an",
    "brown", "black", "white", "grey", "gray", "beige", "dark", "light",
})


def _singular(token: str) -> str:
    """Cheap singularization so plurals match singular taxonomy leaves."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("es") and token[-3] not in "aeiou":
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(text: str, *, drop_stopwords: bool = True) -> frozenset[str]:
    out = set()
    for t in _normalize(text).split():
        if not t:
            continue
        if drop_stopwords and t in _STOPWORDS:
            continue
        out.add(_singular(t))
    return frozenset(out)


def _titlecase(text: str) -> str:
    return " ".join(w.capitalize() for w in _normalize(text).split())


def _similarity(detected: str, entry: _Entry) -> float:
    """Token-aware similarity between a detected name and a taxonomy entry.

    Combines Jaccard token overlap with a sequence ratio on the display name so
    both "media console" -> "TV Media Console" (token overlap) and
    "sofa" -> "Sofa Couch" (substring/sequence) score well.
    """
    d_tokens = set(_tokens(detected))
    for tok in list(d_tokens):
        for extra in _SYNONYM_TOKENS.get(tok, ()):  # augment with synonyms
            d_tokens.add(extra)
    d_tokens = frozenset(d_tokens)
    if not d_tokens:
        return 0.0
    inter = d_tokens & entry.tokens
    union = d_tokens | entry.tokens
    jaccard = len(inter) / len(union) if union else 0.0
    seq = SequenceMatcher(None, _normalize(detected), _normalize(entry.display_name)).ratio()
    # A full token containment (every detected token appears in the entry) is a
    # strong signal even when the entry adds words (e.g. "chair" in "Accent Chair").
    containment = 1.0 if d_tokens <= entry.tokens else len(inter) / len(d_tokens)
    return max(0.55 * jaccard + 0.45 * seq, 0.6 * containment)


@lru_cache(maxsize=1)
def _load_entries(path_str: str) -> tuple[_Entry, ...]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[_Entry] = []
    for raw in data.get("entries", []):
        tax_path = raw.get("Taxonomy_Path", "")
        if _FURNISHINGS_MARKER not in tax_path:
            continue
        segments = tax_path.split("/")
        subcat = segments[2] if len(segments) > 2 else ""
        display = raw.get("Display_Name", "")
        entries.append(
            _Entry(
                entity_id=raw.get("Entity_ID", ""),
                taxonomy_path=tax_path,
                display_name=display,
                domain_class=raw.get("Domain_Class", ""),
                subcategory=subcat,
                tokens=_tokens(display),
            )
        )
    return tuple(entries)


# ── THE RETURN PATH (2026-09-04) ────────────────────────────────────────────
# John: "I thought we were building a self-learning (but prepopulated)
# master_taxonomy_engine.json that would handle all of this."
#
# It nearly is. It is prepopulated, it binds free text to a path with a score, it
# refuses to guess below the floor, and its hydrators grow it idempotently. The one
# missing part was this: when the world met something it could not name, the miss was
# DISCARDED — unresolved() handed back confidence 0.0, the caller wrote an empty path,
# and the lesson evaporated. A dictionary forgets; an engine writes it down.
#
# Every resolve() now appends one line here — hits AND misses, with the score and the
# candidate it nearly matched. Capture everything, curate later: capture is
# irreversible and curation is only a query (John's capture law, 2026-09-04). The gap
# router already turns a ledger like this into proposals; this gives it a second feed.
#
# Never throws, never blocks: a ledger that breaks a render is worse than no ledger.
_MISS_LEDGER = Path(
    r"C:\Users\JohnM\Artificial Intelligence\Projects\CEO-of-My-Life-Inc\CEO-3D-World"
    r"\tools\taxonomy-misses.jsonl"
)


def _note(detected_name: str, category: str, score: float, best, resolved: bool) -> None:
    try:
        row = {
            "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "asked": detected_name,
            "category": category or "",
            "resolved": resolved,
            "score": round(float(score), 3),
            "floor": _CONFIDENCE_FLOOR,
            # what it ALMOST was — the single most useful field for proposing a new leaf
            "nearest": getattr(best, "taxonomy_path", "") if best is not None else "",
            "nearest_name": getattr(best, "display_name", "") if best is not None else "",
            "status": "new",
        }
        _MISS_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with _MISS_LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(_json.dumps(row) + "\n")
    except Exception:   # noqa: BLE001 — a broken ledger must never break a build
        pass


class TaxonomyResolver:
    """Resolves detected/generated object names to canonical taxonomy identities."""

    def __init__(self, taxonomy_path: Path | None = None) -> None:
        self._path = str(taxonomy_path or _TAXONOMY_PATH)
        # Warm the cache eagerly so a bad path fails fast at construction.
        self._entries = _load_entries(self._path)

    def resolve(self, detected_name: str, category: str = "") -> TaxonomyMatch:
        """Bind (detected_name, category) to the best taxonomy entry.

        Args:
            detected_name: raw descriptive name from the vision model.
            category: vision-catalog category enum value (optional but improves
                precision by scoping to the matching sub-category).

        Returns:
            A TaxonomyMatch. resolved=False (with a title-cased display name) when
            no candidate clears the confidence floor.
        """
        if not detected_name:
            return TaxonomyMatch.unresolved(detected_name)

        subcat = _CATEGORY_TO_SUBCATEGORY.get((category or "").lower(), "")
        scoped = [e for e in self._entries if e.subcategory == subcat] if subcat else []
        # Always also consider the full furnishings set so a mis-categorized
        # detection can still find its true home; scoped candidates get a small
        # prior boost so an equally-good in-category match wins ties.
        best: _Entry | None = None
        best_score = 0.0
        for pool, prior in ((scoped, 0.05), (self._entries, 0.0)):
            for entry in pool:
                score = min(1.0, _similarity(detected_name, entry) + prior)
                if score > best_score:
                    best_score = score
                    best = entry

        if best is None or best_score < _CONFIDENCE_FLOOR:
            _note(detected_name, category, best_score, best, resolved=False)
            return TaxonomyMatch.unresolved(detected_name)

        _note(detected_name, category, best_score, best, resolved=True)
        return TaxonomyMatch(
            entity_id=best.entity_id,
            taxonomy_path=best.taxonomy_path,
            display_name=best.display_name,
            domain_class=best.domain_class,
            confidence=round(best_score, 3),
            resolved=True,
        )


@lru_cache(maxsize=1)
def get_resolver() -> TaxonomyResolver:
    """Process-wide singleton resolver."""
    return TaxonomyResolver()
