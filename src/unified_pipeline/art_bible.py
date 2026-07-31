"""Art Bible Deriver — extracts structured style rules from Brief + Dream_Preview.

Derives era_rules, material_palette, lighting_direction, color_palette,
prop_style, and era_exclusions using Ollama. The resulting ArtBible is
frozen (immutable) once created — it conditions Canon generation, material
estimation, and architectural finishing. Changes require returning to
conversation.

Requirements: 4.1, 4.2, 4.3, 4.4
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

import httpx

from src.unified_pipeline.models import ArtBible, Brief


# ─── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
ART_BIBLE_MODEL = os.getenv("ART_BIBLE_MODEL", os.getenv("LLM_MODEL", "llama3.1:latest"))
ART_BIBLE_TIMEOUT = float(os.getenv("ART_BIBLE_TIMEOUT", "30"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "24576"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "12288"))


# ─── Prompts ───────────────────────────────────────────────────────────────────

ART_BIBLE_SYSTEM_PROMPT = """\
You are a production designer creating a definitive Art Bible for a 3D room.
Given a Brief (structured intent) and optional Dream Preview metadata (mood image details),
extract precise, actionable style rules that will guide ALL visual generation downstream.

Return ONLY valid JSON with these exact fields:

{
  "era_rules": {
    "belongs": ["list of era-defining elements that BELONG in this space"],
    "excludes": ["list of elements that are EXCLUDED as anachronistic"]
  },
  "material_palette": [
    "specific material with PBR hint (e.g. chrome (metallic=0.95, roughness=0.1))",
    "..."
  ],
  "lighting_direction": {
    "key": {"direction": "primary light direction", "color_temperature_k": 3200},
    "fill": {"direction": "secondary light source", "color_temperature_k": 5600},
    "accent": {"direction": "highlight/mood light", "color_temperature_k": 2800}
  },
  "color_palette": ["#hexcolor1", "#hexcolor2", "#hexcolor3", "#hexcolor4", "#hexcolor5"],
  "prop_style": {
    "silhouette_language": "rounded/angular/organic/geometric/mixed",
    "detail_level": "minimal/medium/ornate",
    "wear_patina": "description of aging and wear characteristics"
  },
  "era_exclusions": [
    "specific anachronistic element that MUST NOT appear (e.g. no smart thermostats in a 1950s diner)",
    "..."
  ]
}

Rules:
- Be SPECIFIC: "worn oak with visible grain" not "wood"
- Era exclusions must be explicit and practical for filtering
- Color palette must use real hex codes (#RRGGBB format)
- Material palette should have 3-8 entries with PBR hints
- Era exclusions should have 3-10 entries covering common anachronisms
- era_rules.belongs lists what IS appropriate; era_rules.excludes lists what IS NOT
- If Dream Preview metadata is provided, weight its aesthetic direction heavily

Return compact JSON only. No markdown, no explanation.
"""


# ─── Error Types ───────────────────────────────────────────────────────────────


class ArtBibleError(Exception):
    """Raised when Art Bible derivation fails irrecoverably."""


class ArtBibleLockedError(Exception):
    """Raised when attempting to modify a locked Art Bible.

    Req 4.4: Art Bible is immutable once Canon generation begins.
    """


# ─── Ollama Client ─────────────────────────────────────────────────────────────


async def _call_ollama_json(
    system: str,
    user: str,
    *,
    timeout: float = ART_BIBLE_TIMEOUT,
) -> str:
    """Call Ollama /api/chat requesting JSON output."""
    url = os.getenv("OLLAMA_URL", OLLAMA_URL)
    payload: dict[str, Any] = {
        "model": ART_BIBLE_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.15,
            "num_predict": OLLAMA_NUM_PREDICT,
            "num_ctx": OLLAMA_NUM_CTX,
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{url}/api/chat", json=payload)
        if response.status_code != 200:
            raise ArtBibleError(
                f"Ollama returned {response.status_code}: {response.text[:300]}"
            )
        body = response.json()
        content = (body.get("message") or {}).get("content") or ""
        if not content.strip():
            raise ArtBibleError(
                f"Ollama returned empty content. "
                f"done_reason={body.get('done_reason')!r} "
                f"error={body.get('error')!r}"
            )
        return content


# ─── JSON Parsing ──────────────────────────────────────────────────────────────


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Parse JSON from LLM output, handling markdown fences."""
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ArtBibleError(f"Could not parse Art Bible JSON from LLM: {raw[:200]}")


# ─── Fallback Art Bible ────────────────────────────────────────────────────────


def _fallback_art_bible(brief: Brief) -> ArtBible:
    """Schema-correct fallback when Ollama is unavailable.

    Derives reasonable defaults from Brief fields. This ensures the pipeline
    can proceed even when the LLM is down, though the results will be generic.

    The returned ArtBible has immutable=False since it was not LLM-derived;
    downstream can still lock it via the ArtBibleDeriver.lock() call.
    """
    # Derive era exclusions from the Brief's style_exclusions
    exclusions = list(brief.era.style_exclusions)

    period = brief.era.period.lower() if brief.era.period else "contemporary"

    # Add common anachronism exclusions based on era
    if any(decade in period for decade in ("1920", "1930", "1940", "1950", "1960")):
        exclusions.extend([
            "no LED strip lighting",
            "no smart home devices",
            "no USB outlets",
            "no flat-screen displays",
        ])
    elif any(decade in period for decade in ("1970", "1980")):
        exclusions.extend([
            "no smart home devices",
            "no wireless charging pads",
            "no USB-C ports",
        ])
    elif "victorian" in period or "edwardian" in period:
        exclusions.extend([
            "no electrical outlets visible",
            "no modern light switches",
            "no plastic materials",
            "no stainless steel appliances",
        ])

    if not exclusions:
        exclusions = ["no anachronistic technology"]

    # Build belongs list from era
    belongs: list[str] = []
    if brief.era.period:
        belongs.append(f"furnishings typical of {brief.era.period}")
        belongs.append(f"materials common in {brief.era.period}")
    if brief.object_manifest:
        for obj in brief.object_manifest:
            if obj.material_hint:
                belongs.append(f"{obj.material_hint} {obj.name}")

    # Build material palette from Brief palette
    materials = list(brief.palette.material_finishes)
    if not materials:
        materials = ["natural wood", "brushed metal", "woven textile"]

    # Derive color palette (hex codes)
    colors: tuple[str, ...] = (
        "#F5F0E8",
        "#8B7355",
        "#D4A574",
        "#4A4A4A",
        "#E8DCC8",
    )

    # Build lighting direction from Brief atmosphere
    lighting_dir = brief.atmosphere.lighting_direction or "overhead diffuse"
    time_of_day = brief.atmosphere.time_of_day or "afternoon"

    # Estimate color temperature from time of day
    temp_k = 4000
    if "morning" in time_of_day:
        temp_k = 3500
    elif "evening" in time_of_day or "night" in time_of_day:
        temp_k = 2800
    elif "afternoon" in time_of_day:
        temp_k = 4500

    return ArtBible(
        era_rules={
            "belongs": belongs,
            "excludes": list(brief.era.style_exclusions),
        },
        material_palette=tuple(materials),
        lighting_direction={
            "key": {"direction": lighting_dir, "color_temperature_k": temp_k},
            "fill": {"direction": "ambient bounce", "color_temperature_k": 5000},
            "accent": {"direction": "none", "color_temperature_k": 2800},
        },
        color_palette=colors,
        prop_style={
            "silhouette_language": "mixed",
            "detail_level": "medium",
            "wear_patina": "light surface wear appropriate to era",
        },
        era_exclusions=tuple(exclusions),
        immutable=False,
    )


# ─── Brief Context Builder ────────────────────────────────────────────────────


def _build_brief_context(
    brief: Brief,
    dream_preview_path: Optional[str],
) -> str:
    """Build the user prompt from Brief + optional Dream Preview path.

    Formats the Brief fields into a text prompt for the LLM, and optionally
    references the Dream Preview image the user preferred.
    """
    parts: list[str] = []

    parts.append("=== BRIEF ===")
    parts.append(f"Room Purpose: {brief.room_purpose}")
    parts.append(f"Mood: {brief.atmosphere.mood}")
    parts.append(f"Lighting Direction: {brief.atmosphere.lighting_direction}")
    parts.append(f"Time of Day: {brief.atmosphere.time_of_day}")
    parts.append(f"Era/Period: {brief.era.period}")

    if brief.era.style_exclusions:
        parts.append(f"Known Exclusions: {', '.join(brief.era.style_exclusions)}")

    parts.append(f"Primary Palette: {brief.palette.primary}")
    parts.append(f"Accent Palette: {brief.palette.accent}")

    if brief.palette.material_finishes:
        parts.append(f"Material Finishes: {', '.join(brief.palette.material_finishes)}")

    if brief.object_manifest:
        parts.append("\nKey Objects:")
        for obj in brief.object_manifest:
            parts.append(
                f"  - {obj.name} ({obj.role}, material: {obj.material_hint or 'unspecified'})"
            )

    if dream_preview_path:
        parts.append(f"\n=== Dream_Preview (preferred mood image) ===")
        parts.append(f"  path: {dream_preview_path}")
        parts.append("  (Weight this image's aesthetic direction heavily)")

    parts.append(
        "\nDerive the complete Art Bible from this information. "
        "Be specific about materials, colors (hex), and era exclusions."
    )

    return "\n".join(parts)


# ─── Art Bible Construction from LLM Output ───────────────────────────────────


def _art_bible_from_dict(data: dict[str, Any]) -> ArtBible:
    """Build an ArtBible from extracted JSON dict.

    Normalizes the LLM output into the frozen ArtBible dataclass structure.
    The resulting object is immutable (frozen dataclass).

    Req 4.1: Structured style reference with all required fields.
    Req 4.4: Immutable once created (frozen dataclass).
    """
    # Normalize era_rules — must have "belongs" and "excludes" lists
    era_rules = data.get("era_rules", {})
    if not isinstance(era_rules, dict):
        era_rules = {"belongs": [], "excludes": []}
    else:
        if "belongs" not in era_rules:
            era_rules["belongs"] = []
        if "excludes" not in era_rules:
            era_rules["excludes"] = []

    material_palette = data.get("material_palette", [])
    if not isinstance(material_palette, (list, tuple)):
        material_palette = [str(material_palette)] if material_palette else []

    lighting_direction = data.get("lighting_direction", {})
    if not isinstance(lighting_direction, dict):
        lighting_direction = {}

    color_palette = data.get("color_palette", [])
    if not isinstance(color_palette, (list, tuple)):
        color_palette = [str(color_palette)] if color_palette else []

    prop_style = data.get("prop_style", {})
    if not isinstance(prop_style, dict):
        prop_style = {}

    era_exclusions = data.get("era_exclusions", [])
    if not isinstance(era_exclusions, (list, tuple)):
        era_exclusions = [str(era_exclusions)] if era_exclusions else []

    return ArtBible(
        era_rules=dict(era_rules),
        material_palette=tuple(str(m) for m in material_palette),
        lighting_direction=dict(lighting_direction),
        color_palette=tuple(str(c) for c in color_palette),
        prop_style=dict(prop_style),
        era_exclusions=tuple(str(e) for e in era_exclusions),
        immutable=True,
    )


# ─── ArtBibleDeriver ──────────────────────────────────────────────────────────


class ArtBibleDeriver:
    """Derives a structured Art Bible from Brief + preferred Dream_Preview.

    The Art Bible is the single style authority for all downstream generation:
    Canon images, material estimation, and architectural finishing all reference it.

    Once locked (when Canon generation begins), the Art Bible cannot be re-derived.
    The frozen dataclass enforces structural immutability; the lock() method
    enforces lifecycle immutability (no new derivation after Canon begins).

    Req 4.1: Produces era_rules, material_palette, lighting_direction,
             color_palette, prop_style from Brief + Dream_Preview.
    Req 4.2: Explicitly lists era exclusions.
    Req 4.3: Conditions Canon generation, material estimation, finishing.
    Req 4.4: Immutable once Canon generation begins.

    Usage:
        deriver = ArtBibleDeriver()
        art_bible = await deriver.derive(brief, dream_preview_path)
        deriver.lock()  # Called when Canon generation begins
        # Further derive() calls will raise ArtBibleLockedError
    """

    def __init__(
        self,
        model: str = ART_BIBLE_MODEL,
        timeout: float = ART_BIBLE_TIMEOUT,
    ):
        self._model = model
        self._timeout = timeout
        self._locked: bool = False
        self._art_bible: Optional[ArtBible] = None

    @property
    def art_bible(self) -> Optional[ArtBible]:
        """The derived Art Bible, or None if not yet derived."""
        return self._art_bible

    def is_locked(self) -> bool:
        """Whether the Art Bible is locked (Canon has begun).

        Req 4.4: Immutable once Canon generation begins.
        """
        return self._locked

    def lock(self) -> None:
        """Lock the Art Bible — called when Canon generation begins.

        After locking, derive() will raise ArtBibleLockedError.
        This enforces Req 4.4: changes require returning to conversation.
        """
        self._locked = True

    async def derive(
        self,
        brief: Brief,
        dream_preview_path: Optional[str] = None,
    ) -> ArtBible:
        """Derive the Art Bible from Brief + optional Dream Preview path.

        Req 4.1: Extract era_rules, material_palette, lighting_direction,
                 color_palette, prop_style.
        Req 4.2: Explicitly list era exclusions.
        Req 4.4: Raises if already locked (Canon has begun).

        Args:
            brief: The structured Brief from conversation.
            dream_preview_path: Optional file path to the user's preferred
                Dream Preview image (for style conditioning reference).

        Returns:
            A frozen ArtBible instance ready for downstream conditioning.

        Raises:
            ArtBibleLockedError: If called after lock().
            ArtBibleError: If derivation fails irrecoverably (after fallback).
        """
        if self._locked:
            raise ArtBibleLockedError(
                "Art Bible is locked — Canon generation has begun. "
                "Changes require returning to conversation. (Req 4.4)"
            )

        user_prompt = _build_brief_context(brief, dream_preview_path)

        try:
            raw = await asyncio.wait_for(
                _call_ollama_json(
                    ART_BIBLE_SYSTEM_PROMPT,
                    user_prompt,
                    timeout=self._timeout,
                ),
                timeout=self._timeout,
            )
            data = _parse_json_response(raw)
            art_bible = _art_bible_from_dict(data)
        except (
            asyncio.TimeoutError,
            ArtBibleError,
            httpx.HTTPError,
            json.JSONDecodeError,
            OSError,
        ):
            # Fallback: derive from Brief fields directly
            art_bible = _fallback_art_bible(brief)

        self._art_bible = art_bible
        return art_bible

    def derive_sync(
        self,
        brief: Brief,
        dream_preview_path: Optional[str] = None,
    ) -> ArtBible:
        """Synchronous wrapper for derive(). For use in non-async contexts."""
        return asyncio.run(self.derive(brief, dream_preview_path))


# ─── Module-Level Convenience ──────────────────────────────────────────────────


async def derive_art_bible(
    brief: Brief,
    dream_preview_path: Optional[str] = None,
    *,
    model: str = ART_BIBLE_MODEL,
    timeout: float = ART_BIBLE_TIMEOUT,
) -> ArtBible:
    """One-shot Art Bible derivation from Brief + Dream Preview.

    Convenience function when you don't need the stateful ArtBibleDeriver
    (lock/unlock lifecycle). Returns a frozen ArtBible.

    Req 4.1, 4.2: Full Art Bible with era exclusions.
    """
    deriver = ArtBibleDeriver(model=model, timeout=timeout)
    return await deriver.derive(brief, dream_preview_path)
